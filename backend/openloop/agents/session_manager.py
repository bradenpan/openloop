"""Session Manager — bridges OpenLoop conversations with Claude SDK sessions.

Manages the lifecycle of agent sessions: starting new sessions with assembled
context, sending messages with streaming, and closing sessions with summaries.
Tracks active sessions in-memory for fast lookup.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.openloop.agents import context_assembler
from backend.openloop.agents.mcp_tools import build_agent_tools, build_odin_tools
from backend.openloop.agents.permission_enforcer import build_permission_hook
from backend.openloop.services import (
    agent_service,
    background_task_service,
    conversation_service,
    memory_service,
    notification_service,
)

# ---------------------------------------------------------------------------
# Windows encoding fix (from spike/results.md)
# ---------------------------------------------------------------------------
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Model name mapping — short names to full SDK model IDs
# ---------------------------------------------------------------------------
MODEL_MAP: dict[str, str] = {
    "haiku": "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-4-6",
    "opus": "claude-opus-4-6",
}

CLOSE_SESSION_PROMPT = (
    "Please summarize this conversation: key decisions, outcomes, and any "
    "open questions. Format as a brief structured summary."
)

CHECKPOINT_PROMPT = (
    "Please provide a comprehensive summary of this conversation so far: "
    "key topics discussed, decisions made, current status of tasks, and any "
    "open questions. This will be used as a checkpoint for context management."
)

FLUSH_MEMORY_PROMPT = (
    "Review this conversation for any important facts, decisions, or user "
    "preferences that haven't been saved to memory yet. Save them now using "
    "your memory tools (save_fact, save_rule). This is mandatory before "
    "context compression."
)

# Observation masking: keep this many recent user+assistant exchange pairs verbatim
RECENT_TURNS_VERBATIM = 7

# ---------------------------------------------------------------------------
# Concurrency limits
# ---------------------------------------------------------------------------
MAX_INTERACTIVE_SESSIONS = 5
MAX_AUTOMATION_SESSIONS = 2

# Context window estimation (all models treated as 200K for now)
CONTEXT_WINDOW_TOKENS = 200_000
CHECKPOINT_THRESHOLD = 0.70  # 70% — trigger auto-checkpoint
CLOSE_THRESHOLD = 0.90  # 90% — suggest closing


def resolve_model(model_name: str) -> str:
    """Resolve a short model name to a full SDK model ID.

    If the name is already a full ID (contains a hyphen and digits), returns as-is.
    """
    return MODEL_MAP.get(model_name, model_name)


def _build_hooks_dict(agent_id: str, conversation_id: str | None) -> dict:
    """Build the hooks dict for ClaudeAgentOptions from the permission hook.

    Returns a dict like ``{"PreToolUse": [HookMatcher(...)]}`` ready
    to pass into ``ClaudeAgentOptions(hooks=...)``.
    """
    matcher, hook_fn = build_permission_hook(agent_id, conversation_id)
    # The SDK pattern (spike test_08) expects hooks to be a list on the matcher
    matcher.hooks = [hook_fn]
    return {"PreToolUse": [matcher]}


# ---------------------------------------------------------------------------
# SessionState
# ---------------------------------------------------------------------------


@dataclass
class SessionState:
    """In-memory tracking of an active SDK session."""

    sdk_session_id: str | None
    agent_id: str
    conversation_id: str
    space_id: str | None
    status: str  # "active", "background", "closing"
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_activity: datetime = field(default_factory=lambda: datetime.now(UTC))


# ---------------------------------------------------------------------------
# Module-level active session tracking
# ---------------------------------------------------------------------------
_active_sessions: dict[str, SessionState] = {}
_conversation_locks: dict[str, asyncio.Lock] = {}


# ---------------------------------------------------------------------------
# Concurrency helpers
# ---------------------------------------------------------------------------


def _count_sessions(status_filter: str | None = None) -> int:
    """Count active sessions, optionally filtered by status."""
    if status_filter is None:
        return len(_active_sessions)
    return sum(1 for s in _active_sessions.values() if s.status == status_filter)


def _check_concurrency(session_type: str = "active") -> None:
    """Check concurrency limits and raise 429 if exceeded.

    session_type: "active" for interactive, "background" for automation/background.
    """
    if session_type == "background":
        bg_count = _count_sessions("background")
        if bg_count >= MAX_AUTOMATION_SESSIONS:
            raise HTTPException(
                status_code=429,
                detail="Too many background sessions running. Please wait for one to complete.",
            )
    else:
        interactive_count = _count_sessions("active")
        if interactive_count >= MAX_INTERACTIVE_SESSIONS:
            raise HTTPException(
                status_code=429,
                detail="Too many active sessions. Please close a conversation first.",
            )


# ---------------------------------------------------------------------------
# Core operations
# ---------------------------------------------------------------------------


async def start_session(
    db: Session,
    *,
    conversation_id: str,
    agent_id: str,
) -> SessionState:
    """Start a new SDK session for a conversation.

    1. Load agent config and conversation from DB
    2. Assemble context via context_assembler
    3. Build MCP tools
    4. Call query() with the system prompt
    5. Store the sdk_session_id and return SessionState
    """
    from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

    # Concurrency check
    _check_concurrency("active")

    # Load from DB
    agent = agent_service.get_agent(db, agent_id)
    conversation = conversation_service.get_conversation(db, conversation_id)

    # Assemble context
    system_prompt = context_assembler.assemble_context(
        db,
        agent_id=agent_id,
        space_id=conversation.space_id,
        conversation_id=conversation_id,
    )

    # Build MCP tools — Odin gets extra tools
    is_odin = agent.name.lower() == "odin"
    mcp_server = build_odin_tools(agent.id) if is_odin else build_agent_tools(agent.name, agent.id)

    # Determine model
    model_name = conversation.model_override or agent.default_model
    model = resolve_model(model_name)

    # Build permission hooks
    hooks = _build_hooks_dict(agent_id, conversation_id)

    # Call the SDK
    sdk_session_id: str | None = None
    try:
        async for event in query(
            prompt=system_prompt,
            options=ClaudeAgentOptions(
                model=model,
                mcp_servers=[mcp_server],
                hooks=hooks,
            ),
        ):
            if isinstance(event, ResultMessage):
                sdk_session_id = event.session_id
    except (Exception, ExceptionGroup) as exc:
        logger.error("SDK error starting session for conversation %s: %s", conversation_id, exc)
        # Mark conversation as interrupted
        conversation_service.update_conversation(db, conversation_id, status="interrupted")
        notification_service.create_notification(
            db,
            type="system",
            title="Session start failed",
            body=f"Failed to start session for conversation {conversation_id}: {exc}",
            space_id=conversation.space_id,
            conversation_id=conversation_id,
        )
        raise

    # Persist sdk_session_id to conversation record
    conversation_service.update_conversation(db, conversation_id, sdk_session_id=sdk_session_id)

    # Track in memory
    now = datetime.now(UTC)
    state = SessionState(
        sdk_session_id=sdk_session_id,
        agent_id=agent_id,
        conversation_id=conversation_id,
        space_id=conversation.space_id,
        status="active",
        started_at=now,
        last_activity=now,
    )
    _active_sessions[conversation_id] = state

    return state


def _get_conversation_lock(conversation_id: str) -> asyncio.Lock:
    """Return (or create) the asyncio.Lock for a given conversation."""
    if conversation_id not in _conversation_locks:
        _conversation_locks[conversation_id] = asyncio.Lock()
    return _conversation_locks[conversation_id]


async def send_message(
    db: Session,
    *,
    conversation_id: str,
    message: str,
) -> AsyncGenerator[dict, None]:
    """Send a message to an active session and yield SSE-compatible events.

    1. Look up or resume the session
    2. Call query() with resume=sdk_session_id
    3. Yield streaming events for SSE forwarding
    4. Store user + assistant messages in DB
    5. Update last_activity

    Acquires a per-conversation lock to prevent concurrent send_message
    calls for the same conversation from racing.
    """
    lock = _get_conversation_lock(conversation_id)
    async with lock:
        async for event in _send_message_inner(
            db, conversation_id=conversation_id, message=message
        ):
            yield event


async def _send_message_inner(
    db: Session,
    *,
    conversation_id: str,
    message: str,
) -> AsyncGenerator[dict, None]:
    """Inner implementation of send_message (called under lock)."""
    from claude_agent_sdk import (
        ClaudeAgentOptions,
        ResultMessage,
        StreamEvent,
        query,
    )

    # Find active session or try to resume from DB
    state = _active_sessions.get(conversation_id)
    sdk_session_id: str | None = None

    if state and state.sdk_session_id:
        sdk_session_id = state.sdk_session_id
    else:
        # Try to resume from conversation record
        conversation = conversation_service.get_conversation(db, conversation_id)
        sdk_session_id = conversation.sdk_session_id

        if not sdk_session_id:
            yield {
                "type": "error",
                "error": "No active session found. Start a session first.",
            }
            return

        # Validate the session before resuming
        try:
            from claude_agent_sdk import get_session_info

            get_session_info(sdk_session_id)
        except Exception:
            yield {
                "type": "error",
                "error": "Session expired or invalid. Start a new session.",
            }
            return

        # Rebuild in-memory state
        state = SessionState(
            sdk_session_id=sdk_session_id,
            agent_id=conversation.agent_id,
            conversation_id=conversation_id,
            space_id=conversation.space_id,
            status="active",
        )
        _active_sessions[conversation_id] = state

    # Load agent for model + MCP tools
    agent = agent_service.get_agent(db, state.agent_id)
    is_odin = agent.name.lower() == "odin"
    mcp_server = build_odin_tools(agent.id) if is_odin else build_agent_tools(agent.name, agent.id)

    conversation = conversation_service.get_conversation(db, conversation_id)
    model_name = conversation.model_override or agent.default_model
    model = resolve_model(model_name)

    # Build permission hooks (re-register on resume)
    hooks = _build_hooks_dict(state.agent_id, conversation_id)

    # --- Proactive budget enforcement ---
    estimated_context = _estimate_conversation_context(db, conversation_id, message)
    utilization = estimated_context / CONTEXT_WINDOW_TOKENS
    if utilization > CHECKPOINT_THRESHOLD:
        logger.info(
            "Proactive compression: context at ~%.0f%% for conversation %s",
            utilization * 100,
            conversation_id,
        )
        # Flush memory first, then compress
        await flush_memory(db, conversation_id=conversation_id)
        await _compress_conversation(db, conversation_id=conversation_id)

    # Call the SDK with streaming
    # NOTE: The user message is saved by the API route, not here, to avoid double-saving.
    full_response = ""
    result_message: ResultMessage | None = None
    try:
        async for event in query(
            prompt=message,
            resume=sdk_session_id,
            options=ClaudeAgentOptions(
                model=model,
                mcp_servers=[mcp_server],
                hooks=hooks,
            ),
            include_partial_messages=True,
        ):
            if isinstance(event, StreamEvent):
                yield {"type": "stream", "event": event}
            elif isinstance(event, ResultMessage):
                result_message = event
                if event.result:
                    full_response = event.result
                # Update session_id in case it changed
                if event.session_id and event.session_id != sdk_session_id:
                    state.sdk_session_id = event.session_id
                    conversation_service.update_conversation(
                        db, conversation_id, sdk_session_id=event.session_id
                    )
    except (Exception, ExceptionGroup) as exc:
        logger.error("SDK error in send_message for conversation %s: %s", conversation_id, exc)
        # Mark conversation as interrupted
        conversation_service.update_conversation(db, conversation_id, status="interrupted")
        notification_service.create_notification(
            db,
            type="system",
            title="Message failed",
            body=f"SDK error in conversation {conversation_id}: {exc}",
            space_id=state.space_id,
            conversation_id=conversation_id,
        )
        yield {"type": "error", "error": str(exc)}
        return

    # Store assistant response in DB
    if full_response:
        conversation_service.add_message(
            db,
            conversation_id=conversation_id,
            role="assistant",
            content=full_response,
        )

    # Update last activity
    state.last_activity = datetime.now(UTC)

    # Monitor context usage after each response
    if result_message and hasattr(result_message, "usage") and result_message.usage:
        await monitor_context_usage(db, conversation_id=conversation_id, usage=result_message.usage)


async def flush_memory(db: Session, *, conversation_id: str) -> None:
    """Mandatory pre-compaction memory flush.

    Injects an instruction to the agent to save unsaved facts before
    any summarization or compression occurs. Called by close_session()
    and _create_checkpoint().
    """
    from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

    state = _active_sessions.get(conversation_id)
    if not state or not state.sdk_session_id:
        return

    conversation = conversation_service.get_conversation(db, conversation_id)
    agent = agent_service.get_agent(db, conversation.agent_id)
    is_odin = agent.name.lower() == "odin"
    mcp_server = build_odin_tools(agent.id) if is_odin else build_agent_tools(agent.name, agent.id)
    model_name = conversation.model_override or agent.default_model
    model = resolve_model(model_name)

    # Build permission hooks
    hooks = _build_hooks_dict(conversation.agent_id, conversation_id)

    try:
        async for event in query(
            prompt=FLUSH_MEMORY_PROMPT,
            resume=state.sdk_session_id,
            options=ClaudeAgentOptions(
                model=model,
                mcp_servers=[mcp_server],
                hooks=hooks,
            ),
        ):
            if isinstance(event, ResultMessage):
                # Update session_id if changed
                if event.session_id and event.session_id != state.sdk_session_id:
                    state.sdk_session_id = event.session_id
                    conversation_service.update_conversation(
                        db, conversation_id, sdk_session_id=event.session_id
                    )
    except (Exception, ExceptionGroup) as exc:
        logger.warning(
            "flush_memory failed for conversation %s (non-blocking): %s",
            conversation_id,
            exc,
        )


async def close_session(
    db: Session,
    *,
    conversation_id: str,
) -> str:
    """Close a session: generate summary, persist it, clean up.

    1. Send a summary prompt to the SDK
    2. Store summary via conversation_service.add_summary()
    3. Close the conversation
    4. Remove from _active_sessions
    5. Return the summary text
    """
    from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

    state = _active_sessions.get(conversation_id)
    sdk_session_id: str | None = None

    if state and state.sdk_session_id:
        sdk_session_id = state.sdk_session_id
    else:
        conversation = conversation_service.get_conversation(db, conversation_id)
        sdk_session_id = conversation.sdk_session_id

    summary_text = ""

    # Flush unsaved facts to memory before generating the closing summary
    await flush_memory(db, conversation_id=conversation_id)

    if sdk_session_id:
        # Load agent for model + MCP tools
        conversation = conversation_service.get_conversation(db, conversation_id)
        agent = agent_service.get_agent(db, conversation.agent_id)
        is_odin = agent.name.lower() == "odin"
        mcp_server = build_odin_tools(agent.id) if is_odin else build_agent_tools(agent.name, agent.id)
        model_name = conversation.model_override or agent.default_model
        model = resolve_model(model_name)

        # Build permission hooks
        hooks = _build_hooks_dict(conversation.agent_id, conversation_id)

        try:
            async for event in query(
                prompt=CLOSE_SESSION_PROMPT,
                resume=sdk_session_id,
                options=ClaudeAgentOptions(
                    model=model,
                    mcp_servers=[mcp_server],
                    hooks=hooks,
                ),
            ):
                if isinstance(event, ResultMessage):
                    summary_text = event.result or ""
        except (Exception, ExceptionGroup) as exc:
            logger.warning(
                "Failed to generate summary for conversation %s: %s",
                conversation_id,
                exc,
            )
            summary_text = f"(Summary generation failed: {exc})"

    # Store summary
    if summary_text:
        conversation_service.add_summary(
            db,
            conversation_id=conversation_id,
            summary=summary_text,
        )

    # Close the conversation
    conversation_service.close_conversation(db, conversation_id)

    # Remove from active sessions
    _active_sessions.pop(conversation_id, None)

    return summary_text


# ---------------------------------------------------------------------------
# Background delegation
# ---------------------------------------------------------------------------


async def delegate_background(
    db: Session,
    *,
    agent_id: str,
    instruction: str,
    space_id: str | None = None,
    item_id: str | None = None,
) -> str:
    """Delegate work to an agent as a background task.

    Creates a background_task record, starts an SDK session (no SSE streaming),
    and runs autonomously. On completion/failure, updates the task record and
    creates a notification. Returns the background_task ID.
    """
    # Concurrency check for background sessions
    _check_concurrency("background")

    # Create background task record
    task = background_task_service.create_background_task(
        db,
        agent_id=agent_id,
        instruction=instruction,
        space_id=space_id,
        item_id=item_id,
        status="running",
    )

    # Create a conversation for this background task
    agent = agent_service.get_agent(db, agent_id)
    conv = conversation_service.create_conversation(
        db,
        agent_id=agent_id,
        name=f"Background: {instruction[:50]}",
        space_id=space_id,
    )

    # Update task with conversation_id
    background_task_service.update_background_task(
        db,
        task.id,  # conversation_id not in updatable, link via the model directly
    )
    task.conversation_id = conv.id
    db.commit()

    # Track in memory
    now = datetime.now(UTC)
    state = SessionState(
        sdk_session_id=None,
        agent_id=agent_id,
        conversation_id=conv.id,
        space_id=space_id,
        status="background",
        started_at=now,
        last_activity=now,
    )
    _active_sessions[conv.id] = state

    # Fire-and-forget the actual execution.
    # NOTE: Do NOT pass the request-scoped db — the background task creates its own session.
    asyncio.create_task(
        _run_background_task(
            task_id=task.id,
            conversation_id=conv.id,
            agent_id=agent.id,
            agent_name=agent.name,
            default_model=agent.default_model,
            instruction=instruction,
            space_id=space_id,
        )
    )

    return task.id


async def _run_background_task(
    *,
    task_id: str,
    conversation_id: str,
    agent_id: str,
    agent_name: str,
    default_model: str,
    instruction: str,
    space_id: str | None,
) -> None:
    """Execute a background task. Runs as an asyncio task.

    Creates its own DB session because the request-scoped session that spawned
    this task will already be closed.
    """
    from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

    from backend.openloop.database import SessionLocal

    is_odin = agent_name.lower() == "odin"
    mcp_server = build_odin_tools(agent_id) if is_odin else build_agent_tools(agent_name, agent_id)
    model = resolve_model(default_model)

    db = SessionLocal()
    try:
        # Assemble context
        system_prompt = context_assembler.assemble_context(
            db,
            agent_id=agent_id,
            space_id=space_id,
            conversation_id=conversation_id,
        )

        full_prompt = f"{system_prompt}\n\n---\n\nTask: {instruction}"

        # Build permission hooks
        hooks = _build_hooks_dict(agent_id, conversation_id)

        sdk_session_id: str | None = None
        result_text = ""

        async for event in query(
            prompt=full_prompt,
            options=ClaudeAgentOptions(
                model=model,
                mcp_servers=[mcp_server],
                hooks=hooks,
            ),
        ):
            if isinstance(event, ResultMessage):
                sdk_session_id = event.session_id
                result_text = event.result or ""

        # Update session tracking
        state = _active_sessions.get(conversation_id)
        if state:
            state.sdk_session_id = sdk_session_id

        # Persist sdk_session_id
        conversation_service.update_conversation(db, conversation_id, sdk_session_id=sdk_session_id)

        # Mark task as completed
        background_task_service.update_background_task(
            db,
            task_id,
            status="completed",
            result_summary=result_text[:2000] if result_text else None,
            completed_at=datetime.now(UTC),
        )

        # Create completion notification
        notification_service.create_notification(
            db,
            type="task_completed",
            title="Background task completed",
            body=f"Task completed: {instruction[:100]}",
            space_id=space_id,
        )

    except (Exception, ExceptionGroup) as exc:
        logger.error("Background task %s failed: %s", task_id, exc)

        # Mark task as failed
        background_task_service.update_background_task(
            db,
            task_id,
            status="failed",
            error=str(exc)[:2000],
            completed_at=datetime.now(UTC),
        )

        # Mark conversation as interrupted
        conversation_service.update_conversation(db, conversation_id, status="interrupted")

        # Create failure notification
        notification_service.create_notification(
            db,
            type="task_failed",
            title="Background task failed",
            body=f"Task failed: {instruction[:100]}. Error: {exc}",
            space_id=space_id,
        )
    finally:
        db.close()
        # Remove from active sessions
        _active_sessions.pop(conversation_id, None)


# ---------------------------------------------------------------------------
# Reopen conversation
# ---------------------------------------------------------------------------


async def reopen_conversation(
    db: Session,
    *,
    conversation_id: str,
) -> SessionState:
    """Reopen a closed/interrupted conversation.

    If the conversation has an sdk_session_id, validate it. If valid, resume.
    If invalid or missing, start a new session with conversation summary + recent
    messages injected as context.
    """
    from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

    # Concurrency check
    _check_concurrency("active")

    conversation = conversation_service.get_conversation(db, conversation_id)

    # Reopen in DB (sets status back to active)
    conversation_service.reopen_conversation(db, conversation_id)

    sdk_session_id = conversation.sdk_session_id
    session_valid = False

    if sdk_session_id:
        try:
            from claude_agent_sdk import get_session_info

            get_session_info(sdk_session_id)
            session_valid = True
        except Exception:
            session_valid = False

    if session_valid:
        # Resume existing session
        now = datetime.now(UTC)
        state = SessionState(
            sdk_session_id=sdk_session_id,
            agent_id=conversation.agent_id,
            conversation_id=conversation_id,
            space_id=conversation.space_id,
            status="active",
            started_at=now,
            last_activity=now,
        )
        _active_sessions[conversation_id] = state
        return state

    # Session invalid or missing — start a new one with context injection
    agent = agent_service.get_agent(db, conversation.agent_id)
    is_odin = agent.name.lower() == "odin"
    mcp_server = build_odin_tools(agent.id) if is_odin else build_agent_tools(agent.name, agent.id)
    model_name = conversation.model_override or agent.default_model
    model = resolve_model(model_name)

    # Build context with summary + recent messages
    system_prompt = context_assembler.assemble_context(
        db,
        agent_id=conversation.agent_id,
        space_id=conversation.space_id,
        conversation_id=conversation_id,
    )

    # Add conversation summary if available
    summaries = conversation_service.get_summaries(db, conversation_id=conversation_id)
    if summaries:
        latest_summary = summaries[0].summary  # get_summaries orders by desc
        system_prompt += f"\n\n## Previous Conversation Summary\n{latest_summary}"

    # Add recent messages for context
    messages = conversation_service.get_messages(db, conversation_id)
    if messages:
        recent = messages[-10:]  # Last 10 messages
        msg_text = "\n".join(f"{m.role}: {m.content}" for m in recent)
        system_prompt += f"\n\n## Recent Messages\n{msg_text}"

    system_prompt += (
        "\n\n(This conversation was reopened. The above is context from the "
        "previous session. Continue from where we left off.)"
    )

    # Build permission hooks
    hooks = _build_hooks_dict(conversation.agent_id, conversation_id)

    new_sdk_session_id: str | None = None
    try:
        async for event in query(
            prompt=system_prompt,
            options=ClaudeAgentOptions(
                model=model,
                mcp_servers=[mcp_server],
                hooks=hooks,
            ),
        ):
            if isinstance(event, ResultMessage):
                new_sdk_session_id = event.session_id
    except (Exception, ExceptionGroup) as exc:
        logger.error("SDK error reopening conversation %s: %s", conversation_id, exc)
        conversation_service.update_conversation(db, conversation_id, status="interrupted")
        notification_service.create_notification(
            db,
            type="system",
            title="Reopen failed",
            body=f"Failed to reopen conversation {conversation_id}: {exc}",
            space_id=conversation.space_id,
            conversation_id=conversation_id,
        )
        raise

    # Persist new sdk_session_id
    conversation_service.update_conversation(db, conversation_id, sdk_session_id=new_sdk_session_id)

    now = datetime.now(UTC)
    state = SessionState(
        sdk_session_id=new_sdk_session_id,
        agent_id=conversation.agent_id,
        conversation_id=conversation_id,
        space_id=conversation.space_id,
        status="active",
        started_at=now,
        last_activity=now,
    )
    _active_sessions[conversation_id] = state

    return state


# ---------------------------------------------------------------------------
# Crash recovery
# ---------------------------------------------------------------------------


def recover_from_crash(db: Session) -> int:
    """Recover from a crash by marking active conversations as interrupted.

    Called during FastAPI lifespan startup. Returns the number of interrupted
    conversations.
    """
    active_convs = conversation_service.list_conversations(db, status="active", limit=10000)
    count = len(active_convs)

    for conv in active_convs:
        conversation_service.update_conversation(db, conv.id, status="interrupted")

    if count > 0:
        notification_service.create_notification(
            db,
            type="system",
            title="Conversations interrupted",
            body=f"{count} conversation(s) were interrupted by a restart.",
        )
        logger.warning("Crash recovery: marked %d active conversations as interrupted", count)

    # Clear any stale in-memory state
    _active_sessions.clear()

    return count


# ---------------------------------------------------------------------------
# Context usage monitoring
# ---------------------------------------------------------------------------


async def monitor_context_usage(
    db: Session,
    *,
    conversation_id: str,
    usage: dict,
) -> None:
    """Monitor context window usage and trigger checkpoints or warnings.

    Called after each send_message completes with the ResultMessage.usage dict.
    """
    input_tokens = usage.get("input_tokens", 0)
    cache_read = usage.get("cache_read_input_tokens", 0)
    total_context = input_tokens + cache_read

    utilization = total_context / CONTEXT_WINDOW_TOKENS if CONTEXT_WINDOW_TOKENS > 0 else 0

    conversation = conversation_service.get_conversation(db, conversation_id)

    if utilization > CLOSE_THRESHOLD:
        # > 90% — suggest closing
        notification_service.create_notification(
            db,
            type="context_warning",
            title="Context window nearly full",
            body=(
                f"Conversation is at {utilization:.0%} of context window "
                f"({total_context:,} / {CONTEXT_WINDOW_TOKENS:,} tokens). "
                "Consider closing this conversation and starting a new one."
            ),
            space_id=conversation.space_id,
            conversation_id=conversation_id,
        )
        logger.warning(
            "Context usage at %.0f%% for conversation %s",
            utilization * 100,
            conversation_id,
        )

    elif utilization > CHECKPOINT_THRESHOLD:
        # > 70% — trigger auto-checkpoint
        logger.info(
            "Context usage at %.0f%% for conversation %s — triggering checkpoint",
            utilization * 100,
            conversation_id,
        )
        await _create_checkpoint(db, conversation_id=conversation_id)


async def _create_checkpoint(
    db: Session,
    *,
    conversation_id: str,
) -> None:
    """Create a checkpoint summary for the conversation."""
    from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

    state = _active_sessions.get(conversation_id)
    if not state or not state.sdk_session_id:
        return

    # Flush unsaved facts to memory before checkpointing
    await flush_memory(db, conversation_id=conversation_id)

    conversation = conversation_service.get_conversation(db, conversation_id)
    agent = agent_service.get_agent(db, conversation.agent_id)
    is_odin = agent.name.lower() == "odin"
    mcp_server = build_odin_tools(agent.id) if is_odin else build_agent_tools(agent.name, agent.id)
    model_name = conversation.model_override or agent.default_model
    model = resolve_model(model_name)

    # Build permission hooks
    hooks = _build_hooks_dict(conversation.agent_id, conversation_id)

    summary_text = ""
    try:
        async for event in query(
            prompt=CHECKPOINT_PROMPT,
            resume=state.sdk_session_id,
            options=ClaudeAgentOptions(
                model=model,
                mcp_servers=[mcp_server],
                hooks=hooks,
            ),
        ):
            if isinstance(event, ResultMessage):
                summary_text = event.result or ""
                # Update session_id if changed
                if event.session_id and event.session_id != state.sdk_session_id:
                    state.sdk_session_id = event.session_id
                    conversation_service.update_conversation(
                        db, conversation_id, sdk_session_id=event.session_id
                    )
    except (Exception, ExceptionGroup) as exc:
        logger.warning(
            "Failed to create checkpoint for conversation %s: %s",
            conversation_id,
            exc,
        )
        return

    if summary_text:
        conversation_service.add_summary(
            db,
            conversation_id=conversation_id,
            summary=summary_text,
            is_checkpoint=True,
        )
        logger.info("Checkpoint created for conversation %s", conversation_id)


# ---------------------------------------------------------------------------
# Context estimation
# ---------------------------------------------------------------------------


def _estimate_conversation_context(
    db: Session, conversation_id: str, pending_message: str
) -> int:
    """Estimate total context tokens for a conversation.

    Sum of: system prompt estimate + all messages + pending message.
    Uses estimate_tokens() (4 chars ~ 1 token).
    """
    from backend.openloop.agents.context_assembler import estimate_tokens

    conversation = conversation_service.get_conversation(db, conversation_id)
    agent = agent_service.get_agent(db, conversation.agent_id)

    # Estimate system prompt size (read_only to avoid inflating access counters)
    system_tokens = estimate_tokens(
        context_assembler.assemble_context(
            db, agent_id=agent.id, space_id=conversation.space_id, read_only=True
        )
    )

    # Sum all message tokens
    messages = conversation_service.get_messages(db, conversation_id)
    message_tokens = sum(estimate_tokens(m.content) for m in messages)

    # Pending message
    pending_tokens = estimate_tokens(pending_message)

    return system_tokens + message_tokens + pending_tokens


# ---------------------------------------------------------------------------
# Observation masking — conversation compression
# ---------------------------------------------------------------------------


async def _compress_conversation(db: Session, *, conversation_id: str) -> None:
    """Compress older conversation turns while keeping recent ones verbatim.

    Observation masking strategy:
    1. Keep the most recent RECENT_TURNS_VERBATIM user+assistant exchange pairs verbatim
    2. Summarize older exchanges into a compact block
    3. Store the summary as a checkpoint
    4. Run verify_compaction() on the compressed content
    """
    from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

    state = _active_sessions.get(conversation_id)
    if not state or not state.sdk_session_id:
        return

    # Get all messages for the conversation
    messages = conversation_service.get_messages(db, conversation_id)
    if not messages:
        return

    # Identify exchanges: pairs of (user message, assistant response)
    exchanges: list[list] = []
    current_exchange: list = []
    for msg in messages:
        if msg.role == "user":
            # Start a new exchange
            if current_exchange:
                exchanges.append(current_exchange)
            current_exchange = [msg]
        elif msg.role == "assistant" and current_exchange:
            current_exchange.append(msg)
            exchanges.append(current_exchange)
            current_exchange = []

    # Don't forget a trailing partial exchange (user message with no response yet)
    if current_exchange:
        exchanges.append(current_exchange)

    # If not enough exchanges to compress, return early
    if len(exchanges) <= RECENT_TURNS_VERBATIM:
        logger.debug(
            "Only %d exchanges for conversation %s — nothing to compress",
            len(exchanges),
            conversation_id,
        )
        return

    # Split: older exchanges to compress vs recent to keep verbatim
    older_exchanges = exchanges[:-RECENT_TURNS_VERBATIM]
    # recent_exchanges stay in the SDK's context as-is

    # Collect older message content into a single text block
    older_lines: list[str] = []
    for exchange in older_exchanges:
        for msg in exchange:
            older_lines.append(f"{msg.role}: {msg.content}")

    older_content_text = "\n\n".join(older_lines)

    if not older_content_text.strip():
        return

    # Use the SDK to generate a summary of the older content
    conversation = conversation_service.get_conversation(db, conversation_id)
    agent = agent_service.get_agent(db, conversation.agent_id)
    is_odin = agent.name.lower() == "odin"
    mcp_server = build_odin_tools(agent.id) if is_odin else build_agent_tools(agent.name, agent.id)
    model_name = conversation.model_override or agent.default_model
    model = resolve_model(model_name)

    hooks = _build_hooks_dict(conversation.agent_id, conversation_id)

    compress_prompt = (
        "Summarize the following older conversation exchanges into a compact "
        "block. Preserve all key facts, decisions, action items, and user "
        "preferences. Be thorough but concise.\n\n"
        f"---\n{older_content_text}\n---"
    )

    summary_text = ""
    try:
        async for event in query(
            prompt=compress_prompt,
            resume=state.sdk_session_id,
            options=ClaudeAgentOptions(
                model=model,
                mcp_servers=[mcp_server],
                hooks=hooks,
            ),
        ):
            if isinstance(event, ResultMessage):
                summary_text = event.result or ""
                # Update session_id if changed
                if event.session_id and event.session_id != state.sdk_session_id:
                    state.sdk_session_id = event.session_id
                    conversation_service.update_conversation(
                        db, conversation_id, sdk_session_id=event.session_id
                    )
    except (Exception, ExceptionGroup) as exc:
        logger.warning(
            "Conversation compression failed for %s: %s",
            conversation_id,
            exc,
        )
        return

    if summary_text:
        conversation_service.add_summary(
            db,
            conversation_id=conversation_id,
            summary=summary_text,
            is_checkpoint=True,
        )
        logger.info(
            "Compressed %d older exchanges for conversation %s",
            len(older_exchanges),
            conversation_id,
        )

        # Post-compression verification
        await verify_compaction(
            db,
            conversation_id=conversation_id,
            compressed_content=older_content_text,
        )


# ---------------------------------------------------------------------------
# Post-compression verification
# ---------------------------------------------------------------------------

# Patterns that indicate decision-like or value-like lines worth checking
_DECISION_PATTERNS = re.compile(
    r"\b(decided|chose|will use|agreed on|selected|confirmed|approved|switched to)\b",
    re.IGNORECASE,
)
_VALUE_PATTERNS = re.compile(
    r"(?:^|\n)\s*\w[\w\s]*(?:is|:|=)\s+\S",
    re.IGNORECASE,
)


async def verify_compaction(
    db: Session,
    *,
    conversation_id: str,
    compressed_content: str,
) -> None:
    """Post-compaction verification: check that key facts from compressed content exist in memory.

    Non-blocking — logs warnings but doesn't hold up the conversation.
    Uses keyword/pattern extraction, NOT an LLM call.
    """
    # Extract key phrases from the compressed content
    key_phrases: list[str] = []

    for line in compressed_content.split("\n"):
        line = line.strip()
        if not line:
            continue

        # Lines that look like decisions
        if _DECISION_PATTERNS.search(line):
            # Extract a short phrase around the decision keyword
            phrase = line[:120].strip()
            if phrase:
                key_phrases.append(phrase)

        # Lines with specific values (key: value or key = value patterns)
        elif _VALUE_PATTERNS.search(line):
            phrase = line[:120].strip()
            if phrase:
                key_phrases.append(phrase)

    if not key_phrases:
        return

    # Check each phrase against active memory entries
    conversation = conversation_service.get_conversation(db, conversation_id)
    space_id = conversation.space_id

    # Determine which namespaces to search
    namespaces = ["global"]
    if space_id:
        namespaces.append(f"space:{space_id}")

    # Load all active memory entries from relevant namespaces
    all_memory_values: list[str] = []
    for ns in namespaces:
        entries = memory_service.list_entries(db, namespace=ns, limit=10000)
        for entry in entries:
            all_memory_values.append(entry.value.lower())
            all_memory_values.append(entry.key.lower())

    # Check each key phrase for a rough match in memory
    gaps: list[str] = []
    for phrase in key_phrases:
        phrase_lower = phrase.lower()
        # Extract significant words (4+ chars) from the phrase
        words = [w for w in re.findall(r"\b\w{4,}\b", phrase_lower)]
        if not words:
            continue

        # Check if at least half the significant words appear in any memory entry
        found = False
        for mem_value in all_memory_values:
            matches = sum(1 for w in words if w in mem_value)
            if matches >= max(1, len(words) // 2):
                found = True
                break

        if not found:
            gaps.append(phrase)

    for gap in gaps[:5]:  # Cap at 5 warnings to avoid log spam
        logger.warning(
            "Post-compaction gap: '%s' not found in memory for conversation %s",
            gap[:100],
            conversation_id,
        )


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def list_active() -> list[SessionState]:
    """Return all currently active sessions."""
    return list(_active_sessions.values())


# ---------------------------------------------------------------------------
# Internal helpers (exposed for testing)
# ---------------------------------------------------------------------------


def _get_active_sessions() -> dict[str, SessionState]:
    """Return the raw active sessions dict. For testing only."""
    return _active_sessions


def _clear_active_sessions() -> None:
    """Clear all active sessions and conversation locks. For testing only."""
    _active_sessions.clear()
    _conversation_locks.clear()
