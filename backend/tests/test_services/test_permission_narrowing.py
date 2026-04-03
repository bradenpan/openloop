"""Phase 10.1 tests: permission narrowing engine for multi-agent delegation."""

import json

import pytest
from sqlalchemy.orm import Session

from backend.openloop.agents.permission_enforcer import (
    PermissionSet,
    _check_narrowed_permission,
    match_permission,
    narrow_permissions,
    validate_narrowing,
)
from backend.openloop.db.models import AgentPermission
from backend.openloop.services import agent_service, background_task_service
from contract.enums import GrantLevel, Operation


def _make_agent(db: Session, name: str = "Test Agent", max_spawn_depth: int | None = None, **kwargs):
    agent = agent_service.create_agent(db, name=name, **kwargs)
    if max_spawn_depth is not None:
        agent.max_spawn_depth = max_spawn_depth
        db.commit()
        db.refresh(agent)
    return agent


def _add_permission(db: Session, agent_id: str, resource: str, operation: str, grant: str = "always"):
    """Helper: add a permission row for an agent."""
    perm = AgentPermission(
        agent_id=agent_id,
        resource_pattern=resource,
        operation=operation,
        grant_level=grant,
    )
    db.add(perm)
    db.commit()
    db.refresh(perm)
    return perm


# ---------------------------------------------------------------------------
# PermissionSet basics
# ---------------------------------------------------------------------------


class TestPermissionSet:
    def test_has_permission_match(self):
        ps = PermissionSet(entries=[
            ("openloop-board", Operation.READ, GrantLevel.ALWAYS),
            ("openloop-board", Operation.CREATE, GrantLevel.ALWAYS),
        ])
        assert ps.has_permission("openloop-board", Operation.READ) == GrantLevel.ALWAYS
        assert ps.has_permission("openloop-board", Operation.CREATE) == GrantLevel.ALWAYS

    def test_has_permission_no_match(self):
        ps = PermissionSet(entries=[
            ("openloop-board", Operation.READ, GrantLevel.ALWAYS),
        ])
        assert ps.has_permission("openloop-board", Operation.DELETE) == GrantLevel.NEVER
        assert ps.has_permission("openloop-memory", Operation.READ) == GrantLevel.NEVER

    def test_has_permission_wildcard_op(self):
        ps = PermissionSet(entries=[
            ("openloop-board", "*", GrantLevel.ALWAYS),
        ])
        assert ps.has_permission("openloop-board", Operation.READ) == GrantLevel.ALWAYS
        assert ps.has_permission("openloop-board", Operation.DELETE) == GrantLevel.ALWAYS
        assert ps.has_permission("openloop-memory", Operation.READ) == GrantLevel.NEVER

    def test_empty_set_denies_all(self):
        ps = PermissionSet(entries=[])
        assert ps.has_permission("openloop-board", Operation.READ) == GrantLevel.NEVER


# ---------------------------------------------------------------------------
# Narrowing at depth 0 (no parent task — full permissions)
# ---------------------------------------------------------------------------


class TestNarrowDepth0:
    def test_depth0_returns_all_permissions(self, db_session: Session):
        agent = _make_agent(db_session)
        _add_permission(db_session, agent.id, "openloop-board", Operation.READ)
        _add_permission(db_session, agent.id, "openloop-board", Operation.CREATE)
        _add_permission(db_session, agent.id, "openloop-memory", Operation.CREATE)

        result = narrow_permissions(db_session, agent.id, delegation_depth=0)
        assert len(result.entries) == 3

    def test_depth0_includes_management_tools(self, db_session: Session):
        agent = _make_agent(db_session)
        _add_permission(db_session, agent.id, "openloop-agents", Operation.CREATE)
        _add_permission(db_session, agent.id, "openloop-delegation", Operation.EXECUTE)

        result = narrow_permissions(db_session, agent.id, delegation_depth=0)
        assert len(result.entries) == 2


# ---------------------------------------------------------------------------
# Sub-agent permission inheritance (all depths)
# ---------------------------------------------------------------------------


class TestPermissionInheritance:
    def test_depth1_inherits_all_parent_permissions(self, db_session: Session):
        """Depth-1 sub-agent gets the same permissions as parent — no stripping."""
        agent = _make_agent(db_session)
        _add_permission(db_session, agent.id, "openloop-board", Operation.READ)
        _add_permission(db_session, agent.id, "openloop-board", Operation.CREATE)
        _add_permission(db_session, agent.id, "openloop-agents", Operation.CREATE)
        _add_permission(db_session, agent.id, "openloop-delegation", Operation.EXECUTE)
        _add_permission(db_session, agent.id, "openloop-conversations", Operation.CREATE)
        _add_permission(db_session, agent.id, "openloop-memory", Operation.CREATE)

        result = narrow_permissions(db_session, agent.id, delegation_depth=1)
        assert len(result.entries) == 6

        resources = [(r, o) for r, o, _ in result.entries]
        assert ("openloop-board", Operation.READ) in resources
        assert ("openloop-board", Operation.CREATE) in resources
        assert ("openloop-agents", Operation.CREATE) in resources
        assert ("openloop-delegation", Operation.EXECUTE) in resources
        assert ("openloop-conversations", Operation.CREATE) in resources
        assert ("openloop-memory", Operation.CREATE) in resources

    def test_depth2_inherits_all_parent_permissions(self, db_session: Session):
        """Depth-2 sub-agent also gets the same permissions — no depth-based restriction."""
        agent = _make_agent(db_session)
        _add_permission(db_session, agent.id, "openloop-board", Operation.READ)
        _add_permission(db_session, agent.id, "openloop-board", Operation.CREATE)
        _add_permission(db_session, agent.id, "openloop-board", Operation.EDIT)
        _add_permission(db_session, agent.id, "openloop-memory", Operation.READ)
        _add_permission(db_session, agent.id, "openloop-memory", Operation.CREATE)
        _add_permission(db_session, agent.id, "openloop-docs", Operation.READ)
        _add_permission(db_session, agent.id, "openloop-docs", Operation.CREATE)
        _add_permission(db_session, agent.id, "openloop-delegation", Operation.EXECUTE)
        _add_permission(db_session, agent.id, "openloop-conversations", Operation.READ)

        result = narrow_permissions(db_session, agent.id, delegation_depth=2)
        assert len(result.entries) == 9

    def test_wildcard_preserved_at_any_depth(self, db_session: Session):
        """Wildcard permissions pass through unchanged at all depths."""
        agent = _make_agent(db_session)
        _add_permission(db_session, agent.id, "openloop-board", "*")

        result = narrow_permissions(db_session, agent.id, delegation_depth=2)
        assert len(result.entries) == 1
        assert result.entries[0] == ("openloop-board", "*", GrantLevel.ALWAYS)

    def test_depth1_can_delegate_if_max_spawn_depth_allows(self, db_session: Session):
        """A depth-1 agent can delegate further if max_spawn_depth >= 2."""
        agent = _make_agent(db_session, name="Deep Agent", max_spawn_depth=3)
        _add_permission(db_session, agent.id, "openloop-board", Operation.READ)

        parent_task = background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="Parent", delegation_depth=1,
        )
        child_depth = parent_task.delegation_depth + 1
        assert child_depth <= agent.max_spawn_depth


# ---------------------------------------------------------------------------
# Depth limit enforcement
# ---------------------------------------------------------------------------


class TestDepthLimitEnforcement:
    def test_depth1_cannot_delegate_if_max_spawn_depth_is_1(self, db_session: Session):
        """An agent at depth 1 cannot delegate if max_spawn_depth = 1."""
        agent = _make_agent(db_session, name="Shallow Agent", max_spawn_depth=1)
        _add_permission(db_session, agent.id, "openloop-board", Operation.READ)

        parent_task = background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="Parent work", delegation_depth=1,
        )
        child_depth = parent_task.delegation_depth + 1
        # child_depth = 2 > max_spawn_depth = 1 — delegation should be rejected
        assert child_depth > agent.max_spawn_depth

    @pytest.mark.asyncio
    async def test_delegate_task_rejects_depth_exceeded(self, db_session: Session):
        """delegate_task() MCP tool returns error when depth limit exceeded."""
        from backend.openloop.agents.mcp_tools import delegate_task

        # Create parent agent with max_spawn_depth=1
        parent_agent = _make_agent(db_session, name="Parent Agent", max_spawn_depth=1)
        _add_permission(db_session, parent_agent.id, "openloop-delegation", Operation.EXECUTE)

        # Create child agent with max_spawn_depth=1
        child_agent = _make_agent(db_session, name="Child Agent", max_spawn_depth=1)

        # Create a parent task at depth 1
        parent_task = background_task_service.create_background_task(
            db_session, agent_id=parent_agent.id, instruction="Parent", delegation_depth=1,
        )

        # Try to delegate from depth 1 — child would be depth 2, exceeding max_spawn_depth=1
        result = await delegate_task(
            agent_name="Child Agent",
            instruction="Do child work",
            _db=db_session,
            _agent_id=parent_agent.id,
            _background_task_id=parent_task.id,
        )
        data = json.loads(result)
        assert data.get("is_error") is True
        assert "depth" in data.get("error", "").lower()


# ---------------------------------------------------------------------------
# validate_narrowing
# ---------------------------------------------------------------------------


class TestValidateNarrowing:
    def test_valid_subset(self):
        parent = PermissionSet(entries=[
            ("openloop-board", Operation.READ, GrantLevel.ALWAYS),
            ("openloop-board", Operation.CREATE, GrantLevel.ALWAYS),
            ("openloop-memory", Operation.READ, GrantLevel.ALWAYS),
        ])
        child = PermissionSet(entries=[
            ("openloop-board", Operation.READ, GrantLevel.ALWAYS),
        ])
        assert validate_narrowing(parent, child) is True

    def test_child_exceeds_parent_resource(self):
        """Child has permission for resource parent doesn't have."""
        parent = PermissionSet(entries=[
            ("openloop-board", Operation.READ, GrantLevel.ALWAYS),
        ])
        child = PermissionSet(entries=[
            ("openloop-board", Operation.READ, GrantLevel.ALWAYS),
            ("openloop-memory", Operation.CREATE, GrantLevel.ALWAYS),
        ])
        assert validate_narrowing(parent, child) is False

    def test_child_exceeds_parent_grant_level(self):
        """Child has 'always' but parent only has 'approval'."""
        parent = PermissionSet(entries=[
            ("openloop-board", Operation.READ, GrantLevel.APPROVAL),
        ])
        child = PermissionSet(entries=[
            ("openloop-board", Operation.READ, GrantLevel.ALWAYS),
        ])
        assert validate_narrowing(parent, child) is False

    def test_child_approval_under_parent_always(self):
        """Child 'approval' under parent 'always' is valid (narrower)."""
        parent = PermissionSet(entries=[
            ("openloop-board", Operation.READ, GrantLevel.ALWAYS),
        ])
        child = PermissionSet(entries=[
            ("openloop-board", Operation.READ, GrantLevel.APPROVAL),
        ])
        assert validate_narrowing(parent, child) is True

    def test_empty_child_is_valid(self):
        parent = PermissionSet(entries=[
            ("openloop-board", Operation.READ, GrantLevel.ALWAYS),
        ])
        child = PermissionSet(entries=[])
        assert validate_narrowing(parent, child) is True

    def test_empty_parent_rejects_any_child(self):
        parent = PermissionSet(entries=[])
        child = PermissionSet(entries=[
            ("openloop-board", Operation.READ, GrantLevel.ALWAYS),
        ])
        assert validate_narrowing(parent, child) is False


# ---------------------------------------------------------------------------
# Cascade termination
# ---------------------------------------------------------------------------


class TestCascadeTermination:
    def test_cascade_cancel_children(self, db_session: Session):
        """Stopping a parent recursively cancels all descendants."""
        agent = _make_agent(db_session)
        parent = background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="Parent"
        )
        child1 = background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="Child 1",
            parent_task_id=parent.id, delegation_depth=1,
        )
        child2 = background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="Child 2",
            parent_task_id=parent.id, delegation_depth=1,
        )
        grandchild = background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="Grandchild",
            parent_task_id=child1.id, delegation_depth=2,
        )

        count = background_task_service.cascade_update_status(
            db_session, parent.id,
            new_status="cancelled",
            error_note="Parent cancelled",
        )
        assert count == 3  # child1, child2, grandchild

        # Verify statuses
        c1 = background_task_service.get_background_task(db_session, child1.id)
        c2 = background_task_service.get_background_task(db_session, child2.id)
        gc = background_task_service.get_background_task(db_session, grandchild.id)
        assert c1.status == "cancelled"
        assert c2.status == "cancelled"
        assert gc.status == "cancelled"
        assert gc.error == "Parent cancelled"

    def test_cascade_skips_already_completed(self, db_session: Session):
        """Completed children are not affected by cascade."""
        agent = _make_agent(db_session)
        parent = background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="Parent"
        )
        child_running = background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="Running child",
            parent_task_id=parent.id,
        )
        child_done = background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="Done child",
            parent_task_id=parent.id, status="completed",
        )
        # Manually set to completed (create_background_task sets status via arg)
        background_task_service.update_background_task(
            db_session, child_done.id, status="completed",
        )

        count = background_task_service.cascade_update_status(
            db_session, parent.id,
            new_status="cancelled",
            error_note="Parent cancelled",
        )
        assert count == 1  # only running child

        done = background_task_service.get_background_task(db_session, child_done.id)
        assert done.status == "completed"


# ---------------------------------------------------------------------------
# Cascade pause
# ---------------------------------------------------------------------------


class TestCascadePause:
    def test_cascade_pause_children(self, db_session: Session):
        """Pausing a parent pauses all descendants."""
        agent = _make_agent(db_session)
        parent = background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="Parent"
        )
        child = background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="Child",
            parent_task_id=parent.id,
        )
        grandchild = background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="Grandchild",
            parent_task_id=child.id,
        )

        count = background_task_service.cascade_update_status(
            db_session, parent.id,
            new_status="paused",
        )
        assert count == 2

        c = background_task_service.get_background_task(db_session, child.id)
        gc = background_task_service.get_background_task(db_session, grandchild.id)
        assert c.status == "paused"
        assert gc.status == "paused"


# ---------------------------------------------------------------------------
# Narrowed permission hook check
# ---------------------------------------------------------------------------


class TestNarrowedPermissionCheck:
    def test_allowed_tool_passes(self):
        """Tool that maps to an allowed resource+op passes the narrowed check."""
        ps = PermissionSet(entries=[
            ("openloop-board", Operation.READ, GrantLevel.ALWAYS),
        ])
        # list_items maps to ("openloop-board", Operation.READ)
        result = _check_narrowed_permission(ps, "mcp__openloop_TestAgent__list_items", {})
        assert result == "allow"

    def test_denied_tool_blocked(self):
        """Tool that maps to a resource not in narrowed set is blocked."""
        ps = PermissionSet(entries=[
            ("openloop-board", Operation.READ, GrantLevel.ALWAYS),
        ])
        # delegate_task maps to ("openloop-delegation", Operation.EXECUTE)
        result = _check_narrowed_permission(ps, "mcp__openloop_TestAgent__delegate_task", {})
        assert result == "deny"

    def test_approval_treated_as_deny_in_narrowed(self):
        """In narrowed mode, 'approval' grants are treated as deny."""
        ps = PermissionSet(entries=[
            ("openloop-board", Operation.CREATE, GrantLevel.APPROVAL),
        ])
        result = _check_narrowed_permission(ps, "mcp__openloop_TestAgent__create_item", {})
        assert result == "deny"

    def test_system_guardrail_still_applies(self):
        """System-blocked resources are denied even with narrowed allow."""
        ps = PermissionSet(entries=[
            ("*.env", "*", GrantLevel.ALWAYS),
        ])
        result = _check_narrowed_permission(ps, "Read", {"file_path": "test.env"})
        assert result == "deny"

    def test_child_inherits_management_tools(self, db_session: Session):
        """Sub-agents inherit all parent permissions including management tools."""
        agent = _make_agent(db_session, name="Manager Agent")
        _add_permission(db_session, agent.id, "openloop-agents", Operation.CREATE)
        _add_permission(db_session, agent.id, "openloop-board", Operation.READ)

        narrowed = narrow_permissions(db_session, agent.id, delegation_depth=1)

        # register_agent should be allowed — sub-agent inherits parent permissions
        result = _check_narrowed_permission(
            narrowed, "mcp__openloop_TestAgent__register_agent", {},
        )
        assert result == "allow"

        # list_items should also work
        result = _check_narrowed_permission(
            narrowed, "mcp__openloop_TestAgent__list_items", {},
        )
        assert result == "allow"


# ---------------------------------------------------------------------------
# Delegation depth stored on task
# ---------------------------------------------------------------------------


class TestDelegationDepthStorage:
    def test_create_task_with_depth(self, db_session: Session):
        agent = _make_agent(db_session, name="Depth Agent")
        task = background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="Work",
            delegation_depth=2,
        )
        assert task.delegation_depth == 2

    def test_default_depth_is_zero(self, db_session: Session):
        agent = _make_agent(db_session, name="Default Agent")
        task = background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="Work",
        )
        assert task.delegation_depth == 0

    def test_get_all_descendants(self, db_session: Session):
        agent = _make_agent(db_session, name="Tree Agent")
        root = background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="Root",
        )
        child1 = background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="Child 1",
            parent_task_id=root.id,
        )
        child2 = background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="Child 2",
            parent_task_id=root.id,
        )
        grandchild = background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="Grandchild",
            parent_task_id=child1.id,
        )

        descendants = background_task_service.get_all_descendant_task_ids(db_session, root.id)
        assert len(descendants) == 3
        assert child1.id in descendants
        assert child2.id in descendants
        assert grandchild.id in descendants
