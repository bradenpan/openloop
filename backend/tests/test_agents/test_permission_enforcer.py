"""Tests for the permission enforcer module."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from contract.enums import GrantLevel, Operation, PermissionRequestStatus

from sqlalchemy import text

from backend.openloop.agents.permission_enforcer import (
    check_permission,
    is_system_blocked,
    map_tool_to_resource,
    match_permission,
)
from backend.openloop.db.models import Agent, AgentPermission, PermissionRequest, Space


def _scope_agent_to_space(db, agent):
    """Create a space and assign the agent to it so it is treated as a scoped
    agent (not a system agent) by the permission enforcer."""
    space = Space(name=f"test-space-{agent.id[:8]}", template="project")
    db.add(space)
    db.flush()
    db.execute(
        text("INSERT INTO agent_spaces (agent_id, space_id) VALUES (:aid, :sid)"),
        {"aid": agent.id, "sid": space.id},
    )
    return space

# ---------------------------------------------------------------------------
# map_tool_to_resource
# ---------------------------------------------------------------------------


class TestMapToolToResource:
    def test_read_tool(self):
        resource, op = map_tool_to_resource("Read", {"file_path": "/home/user/file.py"})
        assert resource == "/home/user/file.py"
        assert op == Operation.READ

    def test_glob_tool(self):
        resource, op = map_tool_to_resource("Glob", {"path": "/src", "pattern": "*.py"})
        assert resource == "/src"
        assert op == Operation.READ

    def test_grep_tool(self):
        resource, op = map_tool_to_resource("Grep", {"path": "/src", "pattern": "foo"})
        assert resource == "/src"
        assert op == Operation.READ

    def test_write_tool(self):
        resource, op = map_tool_to_resource("Write", {"file_path": "/tmp/out.txt"})
        assert resource == "/tmp/out.txt"
        assert op == Operation.EDIT

    def test_edit_tool(self):
        resource, op = map_tool_to_resource(
            "Edit", {"file_path": "/src/main.py", "old_string": "x", "new_string": "y"}
        )
        assert resource == "/src/main.py"
        assert op == Operation.EDIT

    def test_bash_tool(self):
        resource, op = map_tool_to_resource("Bash", {"command": "ls -la"})
        assert resource == "bash"
        assert op == Operation.EXECUTE

    def test_web_search_tool(self):
        resource, op = map_tool_to_resource("WebSearch", {"query": "test"})
        assert resource == "web"
        assert op == Operation.EXECUTE

    def test_web_fetch_tool(self):
        resource, op = map_tool_to_resource("WebFetch", {"url": "https://example.com"})
        assert resource == "web"
        assert op == Operation.EXECUTE

    def test_mcp_openloop_create_task(self):
        resource, op = map_tool_to_resource("mcp__openloop__create_task", {"title": "test"})
        assert resource == "openloop-board"
        assert op == Operation.CREATE

    def test_mcp_openloop_dynamic_agent_name(self):
        """Tool names with dynamic agent suffixes should map correctly."""
        resource, op = map_tool_to_resource(
            "mcp__openloop_RecruitingAgent__create_task", {"title": "test"}
        )
        assert resource == "openloop-board"
        assert op == Operation.CREATE

    def test_mcp_openloop_list_tasks(self):
        resource, op = map_tool_to_resource("mcp__openloop__list_tasks", {})
        assert resource == "openloop-board"
        assert op == Operation.READ

    def test_mcp_openloop_write_memory(self):
        resource, op = map_tool_to_resource(
            "mcp__openloop__write_memory", {"key": "k", "value": "v"}
        )
        assert resource == "openloop-memory"
        assert op == Operation.CREATE

    def test_mcp_openloop_read_memory(self):
        resource, op = map_tool_to_resource("mcp__openloop__read_memory", {"key": "k"})
        assert resource == "openloop-memory"
        assert op == Operation.READ

    def test_mcp_openloop_odin_tools(self):
        """Odin-specific tools should map via dynamic prefix."""
        resource, op = map_tool_to_resource("mcp__openloop_odin__list_spaces", {})
        assert resource == "openloop-spaces"
        assert op == Operation.READ

    def test_mcp_openloop_complete_task(self):
        resource, op = map_tool_to_resource(
            "mcp__openloop_TestAgent__complete_task", {"item_id": "123"}
        )
        assert resource == "openloop-board"
        assert op == Operation.EDIT

    def test_mcp_openloop_delegate_task(self):
        resource, op = map_tool_to_resource(
            "mcp__openloop_odin__delegate_task", {"agent_name": "test", "instruction": "do X"}
        )
        assert resource == "openloop-delegation"
        assert op == Operation.EXECUTE

    def test_mcp_openloop_document_tools(self):
        resource, op = map_tool_to_resource(
            "mcp__openloop_TestAgent__read_document", {"document_id": "123"}
        )
        assert resource == "openloop-docs"
        assert op == Operation.READ

    def test_mcp_gmail_read(self):
        resource, op = map_tool_to_resource("mcp__gmail__read_message", {"id": "123"})
        assert resource == "gmail"
        assert op == Operation.READ

    def test_mcp_gmail_send(self):
        resource, op = map_tool_to_resource("mcp__gmail__send_message", {"to": "a@b.com"})
        assert resource == "gmail"
        assert op == Operation.CREATE

    def test_mcp_gmail_delete(self):
        resource, op = map_tool_to_resource("mcp__gmail__delete_message", {"id": "123"})
        assert resource == "gmail"
        assert op == Operation.DELETE

    def test_unknown_tool(self):
        resource, op = map_tool_to_resource("SomeUnknownTool", {"x": 1})
        assert resource == "unknown"
        assert op == Operation.EXECUTE

    def test_file_tool_missing_path_uses_unknown(self):
        resource, op = map_tool_to_resource("Read", {})
        assert resource == "unknown"
        assert op == Operation.READ


# ---------------------------------------------------------------------------
# is_system_blocked
# ---------------------------------------------------------------------------


class TestIsSystemBlocked:
    def test_env_file(self):
        assert is_system_blocked(".env") is True

    def test_env_file_in_path(self):
        assert is_system_blocked("/project/.env") is True

    def test_env_local(self):
        assert is_system_blocked(".env.local") is True

    def test_env_production(self):
        assert is_system_blocked(".env.production") is True

    def test_credentials_json(self):
        assert is_system_blocked("credentials.json") is True

    def test_credentials_json_in_path(self):
        assert is_system_blocked("/home/user/credentials.json") is True

    def test_ssh_key(self):
        assert is_system_blocked("/home/user/.ssh/id_rsa") is True

    def test_aws_credentials(self):
        assert is_system_blocked("/home/user/.aws/credentials") is True

    def test_claude_config(self):
        assert is_system_blocked("/home/user/.claude/config.json") is True

    def test_openloop_db(self):
        assert is_system_blocked("openloop.db") is True

    def test_openloop_db_in_path(self):
        assert is_system_blocked("/data/openloop.db") is True

    def test_allowed_python_file(self):
        assert is_system_blocked("/src/main.py") is False

    def test_allowed_readme(self):
        assert is_system_blocked("/project/README.md") is False

    def test_allowed_regular_json(self):
        assert is_system_blocked("/project/config.json") is False

    def test_backslash_normalization(self):
        assert is_system_blocked("C:\\Users\\user\\.ssh\\id_rsa") is True


# ---------------------------------------------------------------------------
# match_permission
# ---------------------------------------------------------------------------


class TestMatchPermission:
    def _make_perm(
        self, resource_pattern: str, operation: str, grant_level: str
    ) -> AgentPermission:
        perm = AgentPermission()
        perm.resource_pattern = resource_pattern
        perm.operation = operation
        perm.grant_level = grant_level
        return perm

    def test_exact_match(self):
        perms = [self._make_perm("bash", Operation.EXECUTE, GrantLevel.ALWAYS)]
        assert match_permission("bash", perms, Operation.EXECUTE) == GrantLevel.ALWAYS

    def test_glob_pattern_match(self):
        perms = [self._make_perm("/src/*.py", Operation.READ, GrantLevel.ALWAYS)]
        assert match_permission("/src/main.py", perms, Operation.READ) == GrantLevel.ALWAYS

    def test_recursive_glob(self):
        perms = [self._make_perm("/project/*", Operation.EDIT, GrantLevel.APPROVAL)]
        result = match_permission("/project/src/file.py", perms, Operation.EDIT)
        assert result == GrantLevel.APPROVAL

    def test_no_match_returns_never(self):
        perms = [self._make_perm("bash", Operation.EXECUTE, GrantLevel.ALWAYS)]
        assert match_permission("web", perms, Operation.EXECUTE) == GrantLevel.NEVER

    def test_operation_mismatch(self):
        perms = [self._make_perm("bash", Operation.READ, GrantLevel.ALWAYS)]
        assert match_permission("bash", perms, Operation.EXECUTE) == GrantLevel.NEVER

    def test_wildcard_operation(self):
        perms = [self._make_perm("bash", "*", GrantLevel.ALWAYS)]
        assert match_permission("bash", perms, Operation.EXECUTE) == GrantLevel.ALWAYS
        assert match_permission("bash", perms, Operation.READ) == GrantLevel.ALWAYS

    def test_first_match_wins(self):
        perms = [
            self._make_perm("bash", Operation.EXECUTE, GrantLevel.NEVER),
            self._make_perm("bash", Operation.EXECUTE, GrantLevel.ALWAYS),
        ]
        assert match_permission("bash", perms, Operation.EXECUTE) == GrantLevel.NEVER

    def test_empty_permissions(self):
        assert match_permission("anything", [], Operation.READ) == GrantLevel.NEVER

    def test_backslash_normalization(self):
        perms = [self._make_perm("/project/*.py", Operation.READ, GrantLevel.ALWAYS)]
        assert match_permission("\\project\\main.py", perms, Operation.READ) == GrantLevel.ALWAYS


# ---------------------------------------------------------------------------
# check_permission — always/never/default-deny
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestCheckPermission:
    async def test_always_returns_allow(self, db_session):
        agent = Agent(name="test-agent", default_model="sonnet")
        db_session.add(agent)
        db_session.flush()
        _scope_agent_to_space(db_session, agent)

        perm = AgentPermission(
            agent_id=agent.id,
            resource_pattern="bash",
            operation=Operation.EXECUTE,
            grant_level=GrantLevel.ALWAYS,
        )
        db_session.add(perm)
        db_session.commit()

        result = await check_permission(
            db_session,
            agent_id=agent.id,
            conversation_id=None,
            tool_name="Bash",
            tool_input={"command": "echo hello"},
        )
        assert result == "allow"

    async def test_never_returns_deny(self, db_session):
        agent = Agent(name="test-agent-deny", default_model="sonnet")
        db_session.add(agent)
        db_session.flush()
        _scope_agent_to_space(db_session, agent)

        perm = AgentPermission(
            agent_id=agent.id,
            resource_pattern="bash",
            operation=Operation.EXECUTE,
            grant_level=GrantLevel.NEVER,
        )
        db_session.add(perm)
        db_session.commit()

        result = await check_permission(
            db_session,
            agent_id=agent.id,
            conversation_id=None,
            tool_name="Bash",
            tool_input={"command": "rm -rf /"},
        )
        assert result == "deny"

    async def test_no_matching_permission_returns_deny(self, db_session):
        agent = Agent(name="test-agent-nomatch", default_model="sonnet")
        db_session.add(agent)
        db_session.flush()
        _scope_agent_to_space(db_session, agent)
        db_session.commit()

        result = await check_permission(
            db_session,
            agent_id=agent.id,
            conversation_id=None,
            tool_name="Bash",
            tool_input={"command": "ls"},
        )
        assert result == "deny"

    async def test_system_guardrail_denies_env(self, db_session):
        agent = Agent(name="test-agent-env", default_model="sonnet")
        db_session.add(agent)
        db_session.flush()
        _scope_agent_to_space(db_session, agent)

        # Even with "always" permission, system guardrails take precedence
        perm = AgentPermission(
            agent_id=agent.id,
            resource_pattern="*",
            operation="*",
            grant_level=GrantLevel.ALWAYS,
        )
        db_session.add(perm)
        db_session.commit()

        result = await check_permission(
            db_session,
            agent_id=agent.id,
            conversation_id=None,
            tool_name="Read",
            tool_input={"file_path": "/project/.env"},
        )
        assert result == "deny"

    async def test_system_guardrail_denies_openloop_db(self, db_session):
        agent = Agent(name="test-agent-db", default_model="sonnet")
        db_session.add(agent)
        db_session.flush()
        _scope_agent_to_space(db_session, agent)
        db_session.commit()

        result = await check_permission(
            db_session,
            agent_id=agent.id,
            conversation_id=None,
            tool_name="Read",
            tool_input={"file_path": "/data/openloop.db"},
        )
        assert result == "deny"

    async def test_system_guardrail_denies_ssh(self, db_session):
        agent = Agent(name="test-agent-ssh", default_model="sonnet")
        db_session.add(agent)
        db_session.flush()
        _scope_agent_to_space(db_session, agent)
        db_session.commit()

        result = await check_permission(
            db_session,
            agent_id=agent.id,
            conversation_id=None,
            tool_name="Read",
            tool_input={"file_path": "/home/user/.ssh/id_rsa"},
        )
        assert result == "deny"

    async def test_file_glob_permission(self, db_session):
        agent = Agent(name="test-agent-glob", default_model="sonnet")
        db_session.add(agent)
        db_session.flush()
        _scope_agent_to_space(db_session, agent)

        perm = AgentPermission(
            agent_id=agent.id,
            resource_pattern="/src/*.py",
            operation=Operation.READ,
            grant_level=GrantLevel.ALWAYS,
        )
        db_session.add(perm)
        db_session.commit()

        result = await check_permission(
            db_session,
            agent_id=agent.id,
            conversation_id=None,
            tool_name="Read",
            tool_input={"file_path": "/src/main.py"},
        )
        assert result == "allow"


# ---------------------------------------------------------------------------
# check_permission — approval flow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestCheckPermissionApproval:
    async def test_approval_creates_request_and_resolves(self, db_session):
        """Approval grant level creates a PermissionRequest, then polls until resolved."""
        agent = Agent(name="test-agent-approval", default_model="sonnet")
        db_session.add(agent)
        db_session.flush()
        _scope_agent_to_space(db_session, agent)

        perm = AgentPermission(
            agent_id=agent.id,
            resource_pattern="bash",
            operation=Operation.EXECUTE,
            grant_level=GrantLevel.APPROVAL,
        )
        db_session.add(perm)
        db_session.commit()

        # Mock _poll_for_approval to return "approved" immediately
        with patch(
            "backend.openloop.agents.permission_enforcer._poll_for_approval",
            new_callable=AsyncMock,
            return_value=PermissionRequestStatus.APPROVED,
        ):
            result = await check_permission(
                db_session,
                agent_id=agent.id,
                conversation_id=None,
                tool_name="Bash",
                tool_input={"command": "echo test"},
            )

        assert result == "allow"

        # Verify a PermissionRequest was created in the DB
        req = db_session.query(PermissionRequest).first()
        assert req is not None
        assert req.agent_id == agent.id
        assert req.tool_name == "Bash"
        assert req.resource == "bash"
        assert req.operation == Operation.EXECUTE
        assert req.status == PermissionRequestStatus.PENDING

    async def test_approval_denied_returns_deny(self, db_session):
        """If the user denies the approval request, check_permission returns 'deny'."""
        agent = Agent(name="test-agent-approval-deny", default_model="sonnet")
        db_session.add(agent)
        db_session.flush()
        _scope_agent_to_space(db_session, agent)

        perm = AgentPermission(
            agent_id=agent.id,
            resource_pattern="web",
            operation=Operation.EXECUTE,
            grant_level=GrantLevel.APPROVAL,
        )
        db_session.add(perm)
        db_session.commit()

        with patch(
            "backend.openloop.agents.permission_enforcer._poll_for_approval",
            new_callable=AsyncMock,
            return_value=PermissionRequestStatus.DENIED,
        ):
            result = await check_permission(
                db_session,
                agent_id=agent.id,
                conversation_id=None,
                tool_name="WebSearch",
                tool_input={"query": "test"},
            )

        assert result == "deny"

    async def test_approval_publishes_event(self, db_session):
        """Approval flow publishes an SSE event via event_bus."""
        agent = Agent(name="test-agent-event", default_model="sonnet")
        db_session.add(agent)
        db_session.flush()
        _scope_agent_to_space(db_session, agent)

        perm = AgentPermission(
            agent_id=agent.id,
            resource_pattern="bash",
            operation=Operation.EXECUTE,
            grant_level=GrantLevel.APPROVAL,
        )
        db_session.add(perm)
        db_session.commit()

        mock_publish = AsyncMock()
        with (
            patch(
                "backend.openloop.agents.permission_enforcer._poll_for_approval",
                new_callable=AsyncMock,
                return_value=PermissionRequestStatus.APPROVED,
            ),
            patch(
                "backend.openloop.agents.event_bus.event_bus.publish",
                mock_publish,
            ),
        ):
            await check_permission(
                db_session,
                agent_id=agent.id,
                conversation_id=None,
                tool_name="Bash",
                tool_input={"command": "echo hi"},
            )

        mock_publish.assert_called_once()
        event_data = mock_publish.call_args[0][0]
        assert event_data["type"] == "approval_request"
        assert event_data["data"]["tool_name"] == "Bash"
        assert event_data["data"]["resource"] == "bash"


# ---------------------------------------------------------------------------
# _poll_for_approval — timeout behavior
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestPollForApprovalTimeout:
    async def test_poll_returns_denied_after_timeout(self, db_session):
        """_poll_for_approval should auto-deny after APPROVAL_TIMEOUT_SECONDS."""
        from backend.openloop.agents.permission_enforcer import (
            APPROVAL_TIMEOUT_SECONDS,
            _poll_for_approval,
        )

        agent = Agent(name="timeout-agent", default_model="sonnet")
        db_session.add(agent)
        db_session.flush()

        req = PermissionRequest(
            agent_id=agent.id,
            tool_name="Bash",
            resource="bash",
            operation=Operation.EXECUTE,
            status=PermissionRequestStatus.PENDING,
        )
        db_session.add(req)
        db_session.commit()
        db_session.refresh(req)

        request_id = req.id

        # Simulate immediate timeout: first call returns 0, second returns past timeout
        call_count = 0
        def fake_monotonic():
            nonlocal call_count
            call_count += 1
            if call_count <= 1:
                return 0.0
            return float(APPROVAL_TIMEOUT_SECONDS + 1)

        with (
            patch("backend.openloop.agents.permission_enforcer.time.monotonic", side_effect=fake_monotonic),
            patch("backend.openloop.agents.permission_enforcer.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await _poll_for_approval(db_session, request_id)

        assert result == PermissionRequestStatus.DENIED

        # Verify DB state was updated
        db_session.expire_all()
        updated_req = db_session.query(PermissionRequest).filter(
            PermissionRequest.id == request_id
        ).first()
        assert updated_req.status == PermissionRequestStatus.DENIED
        assert updated_req.resolved_by == "system"
        assert updated_req.resolved_at is not None

    async def test_poll_returns_approved_when_resolved_before_timeout(self, db_session):
        """If the request is approved before timeout, _poll_for_approval returns APPROVED."""
        from backend.openloop.agents.permission_enforcer import _poll_for_approval

        agent = Agent(name="approve-agent", default_model="sonnet")
        db_session.add(agent)
        db_session.flush()

        req = PermissionRequest(
            agent_id=agent.id,
            tool_name="Bash",
            resource="bash",
            operation=Operation.EXECUTE,
            status=PermissionRequestStatus.PENDING,
        )
        db_session.add(req)
        db_session.commit()
        db_session.refresh(req)

        request_id = req.id

        async def fake_sleep(_duration):
            # Simulate external approval during sleep
            r = db_session.query(PermissionRequest).filter(
                PermissionRequest.id == request_id
            ).first()
            r.status = PermissionRequestStatus.APPROVED
            r.resolved_by = "user"
            db_session.commit()

        monotonic_values = iter([0.0, 0.0, 2.0])

        with (
            patch(
                "backend.openloop.agents.permission_enforcer.time.monotonic",
                side_effect=lambda: next(monotonic_values),
            ),
            patch(
                "backend.openloop.agents.permission_enforcer.asyncio.sleep",
                side_effect=fake_sleep,
            ),
        ):
            result = await _poll_for_approval(db_session, request_id)

        assert result == PermissionRequestStatus.APPROVED
