"""Phase 5 tests: delegation, step tracking, parent-child hierarchy, steering, agent registration."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.openloop.services import agent_service, background_task_service, space_service


def _make_agent(db: Session, name: str = "Test Agent", **kwargs):
    return agent_service.create_agent(db, name=name, **kwargs)


def _make_space(db: Session, name: str = "Test Space"):
    return space_service.create_space(db, name=name, template="simple")


# ---------------------------------------------------------------------------
# Step tracking
# ---------------------------------------------------------------------------


class TestStepTracking:
    def test_update_task_progress(self, db_session: Session):
        agent = _make_agent(db_session)
        task = background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="Multi-step work"
        )
        updated = background_task_service.update_task_progress(
            db_session, task_id=task.id, current_step=1, total_steps=5, step_summary="Step 1 done"
        )
        assert updated.current_step == 1
        assert updated.total_steps == 5
        assert len(updated.step_results) == 1
        assert updated.step_results[0]["step"] == 1
        assert updated.step_results[0]["summary"] == "Step 1 done"

    def test_step_results_accumulate(self, db_session: Session):
        agent = _make_agent(db_session)
        task = background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="Work"
        )
        background_task_service.update_task_progress(
            db_session, task_id=task.id, current_step=1, total_steps=3, step_summary="First"
        )
        background_task_service.update_task_progress(
            db_session, task_id=task.id, current_step=2, total_steps=3, step_summary="Second"
        )
        background_task_service.update_task_progress(
            db_session, task_id=task.id, current_step=3, total_steps=3, step_summary="Third"
        )
        task = background_task_service.get_background_task(db_session, task.id)
        assert task.current_step == 3
        assert len(task.step_results) == 3
        assert task.step_results[2]["summary"] == "Third"

    def test_update_task_progress_not_found(self, db_session: Session):
        with pytest.raises(HTTPException) as exc_info:
            background_task_service.update_task_progress(
                db_session, task_id="nonexistent", current_step=1, total_steps=1, step_summary="X"
            )
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Parent-child linking
# ---------------------------------------------------------------------------


class TestParentChildTasks:
    def test_create_with_parent(self, db_session: Session):
        agent = _make_agent(db_session)
        parent = background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="Parent task"
        )
        child = background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="Child task", parent_task_id=parent.id
        )
        assert child.parent_task_id == parent.id

    def test_list_child_tasks(self, db_session: Session):
        agent = _make_agent(db_session)
        parent = background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="Parent"
        )
        background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="Child 1", parent_task_id=parent.id
        )
        background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="Child 2", parent_task_id=parent.id
        )
        children = background_task_service.list_child_tasks(db_session, parent.id)
        assert len(children) == 2

    def test_list_by_parent_filter(self, db_session: Session):
        agent = _make_agent(db_session)
        parent = background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="Parent"
        )
        background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="Child", parent_task_id=parent.id
        )
        background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="Orphan"
        )
        filtered = background_task_service.list_background_tasks(
            db_session, parent_task_id=parent.id
        )
        assert len(filtered) == 1
        assert filtered[0].instruction == "Child"

    def test_parent_relationship_accessible(self, db_session: Session):
        agent = _make_agent(db_session)
        parent = background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="Parent"
        )
        child = background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="Child", parent_task_id=parent.id
        )
        fetched = background_task_service.get_background_task(db_session, child.id)
        assert fetched.parent_task.id == parent.id


# ---------------------------------------------------------------------------
# Stale/stuck detection
# ---------------------------------------------------------------------------


class TestStaleStuckDetection:
    def test_detect_stale_queued(self, db_session: Session):
        agent = _make_agent(db_session)
        task = background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="Stale", status="queued"
        )
        # Backdate created_at to simulate staleness
        task.created_at = datetime.now(UTC) - timedelta(minutes=15)
        db_session.commit()
        problems = background_task_service.detect_stale_stuck(db_session)
        assert any(t.id == task.id for t in problems)

    def test_detect_stuck_running(self, db_session: Session):
        agent = _make_agent(db_session)
        task = background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="Stuck"
        )
        # Backdate started_at to simulate being stuck
        task.started_at = datetime.now(UTC) - timedelta(minutes=35)
        db_session.commit()
        problems = background_task_service.detect_stale_stuck(db_session)
        assert any(t.id == task.id for t in problems)

    def test_no_false_positives(self, db_session: Session):
        agent = _make_agent(db_session)
        # Recent running task — should not be detected
        background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="Fresh"
        )
        problems = background_task_service.detect_stale_stuck(db_session)
        assert len(problems) == 0

    def test_completed_tasks_not_detected(self, db_session: Session):
        agent = _make_agent(db_session)
        task = background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="Done"
        )
        background_task_service.update_background_task(
            db_session, task.id, status="completed", completed_at=datetime.now(UTC)
        )
        task.started_at = datetime.now(UTC) - timedelta(minutes=60)
        db_session.commit()
        problems = background_task_service.detect_stale_stuck(db_session)
        assert len(problems) == 0


# ---------------------------------------------------------------------------
# Agent service: get_by_name, skill_path
# ---------------------------------------------------------------------------


class TestAgentSkillPath:
    def test_get_agent_by_name(self, db_session: Session):
        agent = _make_agent(db_session, name="Named Agent")
        found = agent_service.get_agent_by_name(db_session, "Named Agent")
        assert found.id == agent.id

    def test_get_agent_by_name_not_found(self, db_session: Session):
        with pytest.raises(HTTPException) as exc_info:
            agent_service.get_agent_by_name(db_session, "Ghost")
        assert exc_info.value.status_code == 404

    def test_create_agent_with_skill_path(self, db_session: Session):
        agent = agent_service.create_agent(
            db_session, name="Skilled", skill_path="agents/skills/test-skill"
        )
        assert agent.skill_path == "agents/skills/test-skill"

    def test_update_agent_skill_path(self, db_session: Session):
        agent = _make_agent(db_session, name="Updatable")
        updated = agent_service.update_agent(
            db_session, agent.id, skill_path="agents/skills/new-skill"
        )
        assert updated.skill_path == "agents/skills/new-skill"


# ---------------------------------------------------------------------------
# Steer API endpoint
# ---------------------------------------------------------------------------


class TestSteerEndpoint:
    def test_steer_no_active_session(self, client):
        resp = client.post(
            "/api/v1/conversations/nonexistent/steer",
            json={"message": "change course"},
        )
        assert resp.status_code == 404

    def test_steer_schema_validation(self, client):
        resp = client.post(
            "/api/v1/conversations/test/steer",
            json={},  # missing 'message'
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# MCP tools (delegate_task, update_task_progress)
# ---------------------------------------------------------------------------


class TestMCPDelegationTools:
    @pytest.mark.asyncio
    async def test_update_task_progress_tool(self, db_session: Session):
        from backend.openloop.agents.mcp_tools import update_task_progress

        agent = _make_agent(db_session)
        task = background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="Tool test"
        )
        result = await update_task_progress(
            task_id=task.id, step="1", total_steps="3", summary="First step", _db=db_session
        )
        import json

        data = json.loads(result)
        assert data["result"]["step"] == 1
        assert data["result"]["total_steps"] == 3

    @pytest.mark.asyncio
    async def test_update_task_progress_bad_step(self, db_session: Session):
        from backend.openloop.agents.mcp_tools import update_task_progress

        result = await update_task_progress(
            task_id="whatever", step="abc", total_steps="3", summary="Bad", _db=db_session
        )
        import json

        data = json.loads(result)
        assert data.get("is_error") is True

    @pytest.mark.asyncio
    async def test_delegate_task_agent_not_found(self, db_session: Session):
        from backend.openloop.agents.mcp_tools import delegate_task

        result = await delegate_task(
            agent_name="NonexistentAgent", instruction="Do stuff", _db=db_session
        )
        import json

        data = json.loads(result)
        assert data.get("is_error") is True


# ---------------------------------------------------------------------------
# Context assembler: skill_path resolution
# ---------------------------------------------------------------------------


class TestSkillPathResolution:
    def test_load_skill_prompt_valid(self):
        from backend.openloop.agents.context_assembler import _load_skill_prompt

        # The agent-builder SKILL.md we just created should be loadable
        result = _load_skill_prompt("agents/skills/agent-builder")
        assert result is not None
        assert "Agent Builder" in result
        # Frontmatter should be stripped
        assert "---" not in result.split("\n")[0]

    def test_load_skill_prompt_missing(self):
        from backend.openloop.agents.context_assembler import _load_skill_prompt

        result = _load_skill_prompt("agents/skills/nonexistent")
        assert result is None

    def test_agent_identity_with_skill_path(self, db_session: Session):
        from backend.openloop.agents.context_assembler import _build_agent_identity

        agent = agent_service.create_agent(
            db_session,
            name="Skill Agent",
            skill_path="agents/skills/agent-builder",
            system_prompt="fallback prompt",
        )
        identity = _build_agent_identity(agent)
        # Should use SKILL.md content, not the fallback
        assert "Agent Builder" in identity
        assert "fallback prompt" not in identity

    def test_agent_identity_fallback_to_system_prompt(self, db_session: Session):
        from backend.openloop.agents.context_assembler import _build_agent_identity

        agent = agent_service.create_agent(
            db_session,
            name="Prompt Agent",
            system_prompt="You are a test agent.",
        )
        identity = _build_agent_identity(agent)
        assert "You are a test agent." in identity
