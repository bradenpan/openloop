"""Permission enforcement system for agent tool calls.

Intercepts tool calls via SDK PreToolUse hooks, checks agent permissions
against the DB, and blocks/allows/requests-approval as configured.
Uses its own DB sessions (not request-scoped) because hooks run in the
SDK's async context.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from fnmatch import fnmatch

from contract.enums import GrantLevel, NotificationType, Operation, PermissionRequestStatus
from sqlalchemy.orm import Session

from backend.openloop.db.models import AgentPermission, PermissionRequest

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Approval timeout — how long to wait before auto-denying a pending request
# ---------------------------------------------------------------------------

APPROVAL_TIMEOUT_SECONDS: int = 1800  # 30 minutes

# ---------------------------------------------------------------------------
# System guardrails — always blocked, cannot be overridden by permissions
# ---------------------------------------------------------------------------

BLOCKED_PATTERNS: list[str] = [
    "*.env",
    "*.env.*",
    "credentials.json",
    "*/credentials.json",
    "*/.ssh/*",
    "*/.aws/*",
    "*/.claude/*",
    "*/openloop.db",
    "openloop.db",
]


def is_system_blocked(resource: str) -> bool:
    """Check if a resource matches system guardrails.

    Returns True if the resource must always be blocked.
    """
    normalized = resource.replace("\\", "/").lower()
    for pattern in BLOCKED_PATTERNS:
        if fnmatch(normalized, pattern.lower()):
            return True
    return False


# Keys whose values should be fully redacted in audit input summaries
_SECRET_KEYS = frozenset({
    "password", "secret", "token", "api_key", "apikey", "api-key",
    "authorization", "auth", "credential", "credentials",
})

# Maximum length for any single value in the redacted summary
_MAX_VALUE_LEN = 200


def _redact_tool_input(tool_input: dict) -> str:
    """Build a redacted string summary of tool inputs for audit logging.

    Truncates long values and masks keys that look like secrets.
    """
    if not tool_input:
        return "{}"
    parts: list[str] = []
    for key, value in tool_input.items():
        if key.lower() in _SECRET_KEYS:
            parts.append(f"{key}: [REDACTED]")
        else:
            val_str = str(value)
            if len(val_str) > _MAX_VALUE_LEN:
                val_str = val_str[:_MAX_VALUE_LEN] + "..."
            parts.append(f"{key}: {val_str}")
    return ", ".join(parts)


# ---------------------------------------------------------------------------
# Permission narrowing for multi-agent delegation (Phase 10.1)
# ---------------------------------------------------------------------------


@dataclass
class PermissionSet:
    """Represents a set of permissions for an agent.

    Each entry is (resource_pattern, operation, grant_level).
    Used for narrowed permission sets passed to delegated sub-agents.
    """

    entries: list[tuple[str, str, str]] = field(default_factory=list)

    def has_permission(self, resource: str, operation: str) -> str:
        """Check grant level for a resource+operation pair.

        Returns the GrantLevel string, or "never" if no match.
        """
        normalized = resource.replace("\\", "/")
        for res_pattern, op, grant in self.entries:
            if op != "*" and op != operation:
                continue
            if fnmatch(normalized, res_pattern) or res_pattern == resource:
                return grant
        return GrantLevel.NEVER


# Tools considered management-level (removed at depth 1+)
_MANAGEMENT_TOOLS: frozenset[str] = frozenset({
    "register_agent",
    "test_agent",
    "open_conversation",
    "list_agents",
    "list_spaces",
    "navigate_to_space",
    "get_attention_items",
    "get_cross_space_tasks",
    "update_task_list",
    "queue_approval",
})

def narrow_permissions(
    db: Session,
    parent_agent_id: str,
    delegation_depth: int,
) -> PermissionSet:
    """Build a permission set for a child agent by inheriting the parent's permissions.

    Sub-agents get the same permissions as their parent by default. The only
    hard rule is that permissions can never widen beyond the parent's scope
    (enforced by validate_narrowing()). max_spawn_depth limits recursion depth.
    delegation_depth is accepted for tracking but does not restrict permissions.
    """
    parent_permissions: list[AgentPermission] = (
        db.query(AgentPermission).filter(AgentPermission.agent_id == parent_agent_id).all()
    )

    entries: list[tuple[str, str, str]] = []
    for perm in parent_permissions:
        entries.append((perm.resource_pattern, perm.operation, perm.grant_level))

    return PermissionSet(entries=entries)


def validate_narrowing(
    parent_permissions: PermissionSet,
    child_permissions: PermissionSet,
) -> bool:
    """Verify that child permissions are strictly a subset of parent permissions.

    Every child permission entry must have a matching parent entry with equal
    or broader scope. Returns True if valid, False if child exceeds parent.
    """
    for res, op, grant in child_permissions.entries:
        parent_grant = parent_permissions.has_permission(res, op)
        if parent_grant == GrantLevel.NEVER:
            # Parent has no permission for this resource+operation
            return False
        # Child cannot escalate: e.g., child "always" but parent "approval"
        # is escalation. Grant hierarchy: always > approval > never.
        _grant_rank = {GrantLevel.NEVER: 0, GrantLevel.APPROVAL: 1, GrantLevel.ALWAYS: 2}
        child_rank = _grant_rank.get(grant, 0)
        parent_rank = _grant_rank.get(parent_grant, 0)
        if child_rank > parent_rank:
            return False
    return True


# ---------------------------------------------------------------------------
# Tool-to-resource mapping
# ---------------------------------------------------------------------------

# SDK file tools and their operations
_FILE_READ_TOOLS = frozenset({"Read", "Glob", "Grep"})
_FILE_WRITE_TOOLS = frozenset({"Write", "Edit"})

# Bare MCP tool name -> (resource, operation).  The SDK prefixes tool names
# with ``mcp__<server_name>__``, where the server name is dynamic (e.g.
# ``openloop_RecruitingAgent``).  We strip the prefix in map_tool_to_resource
# and look up the bare name here.
_MCP_TOOL_MAP: dict[str, tuple[str, str]] = {
    # Task / item tools (1-12)
    "create_task": ("openloop-board", Operation.CREATE),
    "complete_task": ("openloop-board", Operation.EDIT),
    "list_tasks": ("openloop-board", Operation.READ),
    "create_item": ("openloop-board", Operation.CREATE),
    "update_item": ("openloop-board", Operation.EDIT),
    "move_item": ("openloop-board", Operation.EDIT),
    "get_item": ("openloop-board", Operation.READ),
    "list_items": ("openloop-board", Operation.READ),
    "link_items": ("openloop-board", Operation.CREATE),
    "unlink_items": ("openloop-board", Operation.DELETE),
    "get_linked_items": ("openloop-board", Operation.READ),
    "archive_item": ("openloop-board", Operation.EDIT),
    # Memory tools (9-10, legacy)
    "read_memory": ("openloop-memory", Operation.READ),
    "write_memory": ("openloop-memory", Operation.CREATE),
    # Memory tools (Phase 3b: enhanced)
    "save_fact": ("openloop-memory", Operation.CREATE),
    "update_fact": ("openloop-memory", Operation.EDIT),
    "recall_facts": ("openloop-memory", Operation.READ),
    "delete_fact": ("openloop-memory", Operation.DELETE),
    # Behavioral rule tools (Phase 3b)
    "save_rule": ("openloop-memory", Operation.CREATE),
    "confirm_rule": ("openloop-memory", Operation.EDIT),
    "override_rule": ("openloop-memory", Operation.EDIT),
    "list_rules": ("openloop-memory", Operation.READ),
    # Document tools (11-13)
    "read_document": ("openloop-docs", Operation.READ),
    "list_documents": ("openloop-docs", Operation.READ),
    "create_document": ("openloop-docs", Operation.CREATE),
    # State / read-only views (14-18)
    "get_board_state": ("openloop-board", Operation.READ),
    "get_task_state": ("openloop-board", Operation.READ),
    "get_conversation_summaries": ("openloop-conversations", Operation.READ),
    "search_conversations": ("openloop-conversations", Operation.READ),
    "search_summaries": ("openloop-conversations", Operation.READ),
    "get_conversation_messages": ("openloop-conversations", Operation.READ),
    # Delegation (19)
    "delegate_task": ("openloop-delegation", Operation.EXECUTE),
    "update_task_progress": ("openloop-delegation", Operation.EDIT),
    "check_delegated_tasks": ("openloop-delegation", Operation.READ),
    "cancel_delegated_task": ("openloop-delegation", Operation.DELETE),
    # Agent Builder tools
    "register_agent": ("openloop-agents", Operation.CREATE),
    "test_agent": ("openloop-delegation", Operation.EXECUTE),
    # Approval queue tool
    "queue_approval": ("openloop-approvals", Operation.CREATE),
    # Autonomous task list management
    "update_task_list": ("openloop-delegation", Operation.EDIT),
    # Odin-only tools (20-25)
    "list_spaces": ("openloop-spaces", Operation.READ),
    "list_agents": ("openloop-agents", Operation.READ),
    "open_conversation": ("openloop-conversations", Operation.CREATE),
    "navigate_to_space": ("openloop-spaces", Operation.READ),
    "get_attention_items": ("openloop-attention", Operation.READ),
    "get_cross_space_tasks": ("openloop-board", Operation.READ),
    # Calendar tools
    "list_calendar_events": ("google_calendar", Operation.READ),
    "get_calendar_event": ("google_calendar", Operation.READ),
    "find_free_time": ("google_calendar", Operation.READ),
    "list_calendars": ("google_calendar", Operation.READ),
    "create_calendar_event": ("google_calendar", Operation.CREATE),
    "update_calendar_event": ("google_calendar", Operation.EDIT),
    "delete_calendar_event": ("google_calendar", Operation.DELETE),
    # Email tools
    "list_emails": ("gmail", Operation.READ),
    "get_email": ("gmail", Operation.READ),
    "get_email_headers": ("gmail", Operation.READ),
    "get_inbox_stats": ("gmail", Operation.READ),
    "label_email": ("gmail", Operation.EDIT),
    "archive_email": ("gmail", Operation.EDIT),
    "mark_email_read": ("gmail", Operation.EDIT),
    "draft_email": ("gmail", Operation.CREATE),
    "send_email": ("gmail", Operation.EXECUTE),
    "send_reply": ("gmail", Operation.EXECUTE),
    # Integration Builder tools (Phase 14)
    "create_api_data_source": ("openloop-integrations", Operation.CREATE),
    "test_api_connection": ("openloop-integrations", Operation.EXECUTE),
    "create_sync_automation": ("openloop-integrations", Operation.CREATE),
    # Drive tools
    "read_drive_file": ("google_drive", Operation.READ),
    "list_drive_files": ("google_drive", Operation.READ),
    "create_drive_file": ("google_drive", Operation.CREATE),
    # Layout tools
    "get_space_layout": ("openloop-spaces", Operation.READ),
    "add_widget": ("openloop-spaces", Operation.CREATE),
    "update_widget": ("openloop-spaces", Operation.EDIT),
    "remove_widget": ("openloop-spaces", Operation.DELETE),
    "set_space_layout": ("openloop-spaces", Operation.EDIT),
    # Search tools
    "search": ("openloop-content", Operation.READ),
    "search_items": ("openloop-board", Operation.READ),
}


def map_tool_to_resource(tool_name: str, tool_input: dict) -> tuple[str, str]:
    """Map a tool call to a (resource, operation) pair.

    Returns:
        Tuple of (resource_identifier, operation_string).
        For file tools, the resource is the file path.
        For named tools, the resource is a logical name.
    """
    # File read tools
    if tool_name in _FILE_READ_TOOLS:
        path = tool_input.get("file_path") or tool_input.get("path") or "unknown"
        return (str(path), Operation.READ)

    # File write tools
    if tool_name in _FILE_WRITE_TOOLS:
        path = tool_input.get("file_path") or tool_input.get("path") or "unknown"
        return (str(path), Operation.EDIT)

    # Bash
    if tool_name == "Bash":
        return ("bash", Operation.EXECUTE)

    # Web tools
    if tool_name in ("WebSearch", "WebFetch"):
        return ("web", Operation.EXECUTE)

    # OpenLoop MCP tools — server name is dynamic (e.g. mcp__openloop_AgentName__*)
    if tool_name.startswith("mcp__openloop"):
        # Extract the bare tool name: everything after the last "__"
        bare_name = tool_name.rsplit("__", 1)[-1]
        if bare_name in _MCP_TOOL_MAP:
            return _MCP_TOOL_MAP[bare_name]

    # Gmail MCP tools — any mcp__gmail__* tool
    if tool_name.startswith("mcp__gmail__"):
        # Determine operation from tool name suffix
        suffix = tool_name.removeprefix("mcp__gmail__")
        if suffix.startswith(("send", "create", "compose")):
            return ("gmail", Operation.CREATE)
        if suffix.startswith(("delete", "trash")):
            return ("gmail", Operation.DELETE)
        return ("gmail", Operation.READ)

    # Unknown tools
    return ("unknown", Operation.EXECUTE)


# ---------------------------------------------------------------------------
# Permission matching
# ---------------------------------------------------------------------------


def match_permission(
    resource: str,
    permissions: list[AgentPermission],
    operation: str,
) -> str:
    """Find the grant level for a resource+operation combination.

    Checks permissions in order. For file paths, uses fnmatch against
    resource_pattern. For named resources, uses exact string match.

    Returns the GrantLevel value string, or "never" if no match found
    (deny by default).
    """
    normalized = resource.replace("\\", "/")
    for perm in permissions:
        # Operation must match (or permission covers all with "*")
        if perm.operation != "*" and perm.operation != operation:
            continue
        # Try fnmatch for file-path-like patterns, exact match for named resources
        pattern = perm.resource_pattern
        if fnmatch(normalized, pattern) or pattern == resource:
            return perm.grant_level
    return GrantLevel.NEVER


# ---------------------------------------------------------------------------
# Core permission check
# ---------------------------------------------------------------------------


async def check_permission(
    db: Session,
    *,
    agent_id: str,
    conversation_id: str | None,
    tool_name: str,
    tool_input: dict,
) -> str:
    """Check whether an agent can execute a tool call.

    Returns:
        "allow"   - tool call is permitted
        "deny"    - tool call is blocked
        "pending" - approval was requested (then resolved); returns final status
    """
    # 1. Map tool to (resource, operation)
    resource, operation = map_tool_to_resource(tool_name, tool_input)

    # 2. Check system guardrails
    if is_system_blocked(resource):
        logger.info(
            "System guardrail blocked %s on %s for agent %s",
            tool_name,
            resource,
            agent_id,
        )
        return "deny"

    # 3. Load agent permissions from DB
    permissions: list[AgentPermission] = (
        db.query(AgentPermission).filter(AgentPermission.agent_id == agent_id).all()
    )

    # 4. Match against permission matrix
    grant = match_permission(resource, permissions, operation)

    # 5. "always" -> allow
    if grant == GrantLevel.ALWAYS:
        return "allow"

    # 6. "never" -> deny
    if grant == GrantLevel.NEVER:
        return "deny"

    # 7. "approval" -> create request, publish event, poll for resolution
    if grant == GrantLevel.APPROVAL:
        request = PermissionRequest(
            agent_id=agent_id,
            conversation_id=conversation_id,
            tool_name=tool_name,
            resource=resource,
            operation=operation,
            tool_input=tool_input,
            status=PermissionRequestStatus.PENDING,
        )
        db.add(request)
        db.commit()
        db.refresh(request)

        request_id = request.id

        # Publish SSE event (event_bus may not exist yet)
        try:
            from backend.openloop.agents.event_bus import event_bus

            await event_bus.publish(
                {
                    "type": "approval_request",
                    "data": {
                        "request_id": request_id,
                        "agent_id": agent_id,
                        "conversation_id": conversation_id,
                        "tool_name": tool_name,
                        "resource": resource,
                        "operation": operation,
                    },
                }
            )
        except Exception:
            logger.debug("Could not publish approval_request event", exc_info=True)

        # Poll for resolution — uses the same db session
        result = await _poll_for_approval(db, request_id)
        return "allow" if result == PermissionRequestStatus.APPROVED else "deny"

    # Fallback — deny
    return "deny"


# ---------------------------------------------------------------------------
# Autonomous-mode permission check
# ---------------------------------------------------------------------------


async def _check_permission_autonomous(
    db: Session,
    *,
    agent_id: str,
    conversation_id: str | None,
    background_task_id: str | None,
    tool_name: str,
    tool_input: dict,
) -> str:
    """Check permissions in autonomous mode.

    Behaves identically to check_permission for allow/deny grants.
    For "approval" grants, instead of blocking and polling, creates an
    ApprovalQueue entry and returns "approval_queued" immediately.
    """
    # 1. Map tool to (resource, operation)
    resource, operation = map_tool_to_resource(tool_name, tool_input)

    # 2. Check system guardrails
    if is_system_blocked(resource):
        logger.info(
            "System guardrail blocked %s on %s for agent %s",
            tool_name,
            resource,
            agent_id,
        )
        return "deny"

    # 3. Load agent permissions from DB
    permissions: list[AgentPermission] = (
        db.query(AgentPermission).filter(AgentPermission.agent_id == agent_id).all()
    )

    # 4. Match against permission matrix
    grant = match_permission(resource, permissions, operation)

    # 5. "always" -> allow
    if grant == GrantLevel.ALWAYS:
        return "allow"

    # 6. "never" -> deny
    if grant == GrantLevel.NEVER:
        return "deny"

    # 7. "approval" -> queue instead of blocking
    if grant == GrantLevel.APPROVAL:
        if not background_task_id:
            logger.warning(
                "Autonomous mode approval requested but no background_task_id — denying %s",
                tool_name,
            )
            return "deny"

        try:
            from backend.openloop.services import approval_service

            approval_service.create_approval(
                db,
                background_task_id=background_task_id,
                agent_id=agent_id,
                action_type=f"{operation}:{resource}",
                action_detail={
                    "tool_name": tool_name,
                    "tool_input": tool_input,
                },
                reason=f"Agent requested {operation} on {resource} via {tool_name}",
            )
        except Exception:
            logger.error(
                "Failed to create approval queue entry for %s — denying",
                tool_name,
                exc_info=True,
            )
            return "deny"

        return "approval_queued"

    # Fallback — deny
    return "deny"


# ---------------------------------------------------------------------------
# Approval polling
# ---------------------------------------------------------------------------


async def _poll_for_approval(db: Session, request_id: str) -> str:
    """Poll DB every 2 seconds until the permission request is resolved.

    Returns the resolved status string ("approved" or "denied").
    Times out after APPROVAL_TIMEOUT_SECONDS, auto-denying the request.
    If the request row is deleted, treats as denied.
    """
    from backend.openloop.services import notification_service

    poll_interval = 2.0
    start = time.monotonic()
    while True:
        db.expire_all()
        req = db.query(PermissionRequest).filter(PermissionRequest.id == request_id).first()
        if req is None:
            logger.warning("Permission request %s was deleted during polling — denying", request_id)
            return PermissionRequestStatus.DENIED
        if req.status != PermissionRequestStatus.PENDING:
            return req.status

        # Check timeout
        elapsed = time.monotonic() - start
        if elapsed >= APPROVAL_TIMEOUT_SECONDS:
            logger.warning(
                "Permission request %s timed out after %d seconds — auto-denying",
                request_id,
                int(elapsed),
            )
            req.status = PermissionRequestStatus.DENIED
            req.resolved_by = "system"
            req.resolved_at = datetime.now(UTC).replace(tzinfo=None)
            db.commit()

            notification_service.create_notification(
                db,
                type=NotificationType.SYSTEM,
                title="Approval request expired",
                body=(
                    f"Approval for tool '{req.tool_name}' on '{req.resource}' "
                    f"expired after {APPROVAL_TIMEOUT_SECONDS // 60} minutes "
                    f"with no response."
                ),
                conversation_id=req.conversation_id,
            )

            return PermissionRequestStatus.DENIED

        await asyncio.sleep(poll_interval)


# ---------------------------------------------------------------------------
# SDK hook builder
# ---------------------------------------------------------------------------


def _check_narrowed_permission(
    narrowed: PermissionSet,
    tool_name: str,
    tool_input: dict,
) -> str:
    """Check a tool call against a narrowed permission set.

    Returns "allow" or "deny". Narrowed sets do not support "approval" —
    delegated sub-agents get allow/deny only.
    """
    resource, operation = map_tool_to_resource(tool_name, tool_input)

    # System guardrails still apply
    if is_system_blocked(resource):
        return "deny"

    grant = narrowed.has_permission(resource, operation)
    if grant == GrantLevel.ALWAYS:
        return "allow"
    # For narrowed sets, treat "approval" as "deny" — sub-agents cannot
    # initiate approval flows
    return "deny"


def build_permission_hook(
    agent_id: str,
    conversation_id: str | None,
    background_task_id: str | None = None,
    autonomous_mode: bool = False,
    narrowed_permissions: PermissionSet | None = None,
):
    """Build a PreToolUse hook for SDK session registration.

    Returns a tuple of (HookMatcher, hook_function) compatible with the
    claude_agent_sdk hook registration pattern.

    The hook intercepts every tool call, checks permissions, and returns
    PermissionResultAllow or PermissionResultDeny.

    When autonomous_mode=True and a tool requires approval, instead of
    blocking and polling, the action is queued in the approval_queue table
    and the tool call is denied with a message telling the agent to continue
    with other work.

    When narrowed_permissions is provided (for delegated sub-agents), the
    hook checks against the narrowed set instead of querying the agent's
    full permissions from the DB. This enforces permission narrowing.

    Each invocation creates its own short-lived DB session via SessionLocal()
    so it is safe to call from async SDK context (not request-scoped).
    """
    from claude_agent_sdk import HookMatcher, PreToolUseHookInput

    from backend.openloop.database import SessionLocal

    async def hook(
        input: PreToolUseHookInput,
        session_name: str | None = None,
        context=None,
    ) -> dict:
        tool_name = input["tool_name"]
        tool_input = input.get("tool_input", {})

        # If narrowed permissions are provided, use them instead of DB lookup
        if narrowed_permissions is not None:
            result = _check_narrowed_permission(narrowed_permissions, tool_name, tool_input)
        else:
            db = SessionLocal()
            try:
                if autonomous_mode:
                    result = await _check_permission_autonomous(
                        db,
                        agent_id=agent_id,
                        conversation_id=conversation_id,
                        background_task_id=background_task_id,
                        tool_name=tool_name,
                        tool_input=tool_input,
                    )
                else:
                    result = await check_permission(
                        db,
                        agent_id=agent_id,
                        conversation_id=conversation_id,
                        tool_name=tool_name,
                        tool_input=tool_input,
                    )
            finally:
                db.close()

        # Audit log the permission decision
        resource, operation = map_tool_to_resource(tool_name, tool_input)
        audit_action = result  # "allow", "deny", "approval_queued"
        # Build a redacted summary of tool inputs (strip long values, mask secrets)
        input_summary = _redact_tool_input(tool_input)

        audit_db = SessionLocal()
        try:
            from backend.openloop.services import audit_service

            audit_service.log_tool_call(
                audit_db,
                agent_id=agent_id,
                conversation_id=conversation_id,
                background_task_id=background_task_id,
                tool_name=tool_name,
                action=audit_action,
                resource_id=resource,
                input_summary=input_summary,
            )
        except Exception:
            logger.debug("Failed to write audit log for %s", tool_name, exc_info=True)
        finally:
            audit_db.close()

        if result == "allow":
            # Empty dict = allow the tool call to proceed
            return {}
        elif result == "approval_queued":
            return {
                "decision": "block",
                "reason": "Action queued for approval. Continue with other work.",
            }
        else:
            return {
                "decision": "block",
                "reason": f"Permission denied: {operation} on {resource} for agent {agent_id}",
            }

    matcher = HookMatcher(matcher="*")
    return matcher, hook
