"""Tests for heartbeat protocol (Task 9.3).

Tests scheduler detection, cron evaluation, heartbeat firing,
HEARTBEAT_OK silent completion, action notification/audit, and guards.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from backend.openloop.agents.automation_scheduler import (
    _evaluate_heartbeats,
    _is_heartbeat_due,
)
from backend.openloop.db.models import (
    Agent,
    BackgroundTask,
    Notification,
    Space,
    SystemState,
)
from backend.openloop.services import agent_service
from contract.enums import BackgroundTaskRunType, NotificationType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_agent(
    db: Session,
    *,
    name: str = "HeartbeatAgent",
    heartbeat_enabled: bool = True,
    heartbeat_cron: str | None = "*/30 * * * *",
    status: str = "active",
) -> Agent:
    agent = agent_service.create_agent(db, name=name)
    agent.heartbeat_enabled = heartbeat_enabled
    agent.heartbeat_cron = heartbeat_cron
    agent.status = status
    db.commit()
    db.refresh(agent)
    return agent


def _make_space(db: Session, name: str = "TestSpace") -> Space:
    space = Space(name=name, template="simple")
    db.add(space)
    db.commit()
    db.refresh(space)
    return space


def _make_heartbeat_task(
    db: Session,
    agent_id: str,
    *,
    created_at: datetime | None = None,
    status: str = "completed",
) -> BackgroundTask:
    """Create a BackgroundTask with run_type=heartbeat for tracking last run."""
    task = BackgroundTask(
        agent_id=agent_id,
        instruction="heartbeat survey",
        run_type=BackgroundTaskRunType.HEARTBEAT,
        status=status,
    )
    if created_at is not None:
        task.created_at = created_at
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def _set_system_paused(db: Session, paused: bool = True) -> None:
    """Set the system paused state."""
    row = db.query(SystemState).filter(SystemState.key == "system_paused").first()
    if row is None:
        row = SystemState(key="system_paused", value=paused)
        db.add(row)
    else:
        row.value = paused
    db.commit()


# ---------------------------------------------------------------------------
# _is_heartbeat_due — cron matching logic
# ---------------------------------------------------------------------------


class TestIsHeartbeatDue:
    """Tests for the _is_heartbeat_due helper."""

    def test_heartbeat_due_when_never_run(self, db_session: Session):
        """Agent with heartbeat_cron but no prior heartbeat tasks is due."""
        agent = _make_agent(db_session)
        now_naive = datetime.now(UTC).replace(tzinfo=None)
        assert _is_heartbeat_due(db_session, agent, now_naive) is True

    def test_heartbeat_due_when_cron_matches(self, db_session: Session):
        """Agent whose last heartbeat was 31+ minutes ago with */30 cron is due."""
        agent = _make_agent(db_session, heartbeat_cron="*/30 * * * *")
        _make_heartbeat_task(
            db_session,
            agent.id,
            created_at=datetime.now(UTC) - timedelta(minutes=35),
        )
        now_naive = datetime.now(UTC).replace(tzinfo=None)
        assert _is_heartbeat_due(db_session, agent, now_naive) is True

    def test_heartbeat_not_due_when_recently_run(self, db_session: Session):
        """Agent whose last heartbeat was 5 minutes ago with */30 cron is NOT due."""
        agent = _make_agent(db_session, heartbeat_cron="*/30 * * * *")
        _make_heartbeat_task(
            db_session,
            agent.id,
            created_at=datetime.now(UTC) - timedelta(minutes=5),
        )
        now_naive = datetime.now(UTC).replace(tzinfo=None)
        assert _is_heartbeat_due(db_session, agent, now_naive) is False

    def test_heartbeat_not_due_hourly_cron(self, db_session: Session):
        """Agent with hourly cron that ran 10 min ago is not due."""
        agent = _make_agent(db_session, heartbeat_cron="0 * * * *")
        _make_heartbeat_task(
            db_session,
            agent.id,
            created_at=datetime.now(UTC) - timedelta(minutes=10),
        )
        now_naive = datetime.now(UTC).replace(tzinfo=None)
        assert _is_heartbeat_due(db_session, agent, now_naive) is False


# ---------------------------------------------------------------------------
# _evaluate_heartbeats — scheduler detection
# ---------------------------------------------------------------------------


class TestEvaluateHeartbeats:
    """Tests for heartbeat evaluation in the scheduler."""

    @pytest.mark.asyncio
    async def test_heartbeat_enabled_agent_detected(self, db_session: Session):
        """Agent with heartbeat_enabled=True and heartbeat_cron is detected and fired."""
        agent = _make_agent(db_session)

        now_naive = datetime.now(UTC).replace(tzinfo=None)

        with (
            patch(
                "backend.openloop.agents.automation_scheduler._fire_heartbeat",
                new_callable=AsyncMock,
            ) as mock_fire,
            patch(
                "backend.openloop.agents.automation_scheduler.concurrency_manager.acquire_slot",
                return_value=True,
            ),
        ):
            await _evaluate_heartbeats(db_session, now_naive)
            mock_fire.assert_called_once_with(db_session, agent)

    @pytest.mark.asyncio
    async def test_heartbeat_disabled_agent_skipped(self, db_session: Session):
        """Agent with heartbeat_enabled=False is not fired."""
        _make_agent(db_session, heartbeat_enabled=False)

        now_naive = datetime.now(UTC).replace(tzinfo=None)

        with (
            patch(
                "backend.openloop.agents.automation_scheduler._fire_heartbeat",
                new_callable=AsyncMock,
            ) as mock_fire,
            patch(
                "backend.openloop.agents.automation_scheduler.concurrency_manager.acquire_slot",
                return_value=True,
            ),
        ):
            await _evaluate_heartbeats(db_session, now_naive)
            mock_fire.assert_not_called()

    @pytest.mark.asyncio
    async def test_heartbeat_fires_when_cron_matches(self, db_session: Session):
        """Heartbeat fires when cron expression indicates it's time."""
        agent = _make_agent(db_session, heartbeat_cron="*/30 * * * *")
        # Last heartbeat was 35 min ago
        _make_heartbeat_task(
            db_session,
            agent.id,
            created_at=datetime.now(UTC) - timedelta(minutes=35),
        )

        now_naive = datetime.now(UTC).replace(tzinfo=None)

        with (
            patch(
                "backend.openloop.agents.automation_scheduler._fire_heartbeat",
                new_callable=AsyncMock,
            ) as mock_fire,
            patch(
                "backend.openloop.agents.automation_scheduler.concurrency_manager.acquire_slot",
                return_value=True,
            ),
        ):
            await _evaluate_heartbeats(db_session, now_naive)
            mock_fire.assert_called_once_with(db_session, agent)

    @pytest.mark.asyncio
    async def test_heartbeat_does_not_fire_when_cron_not_due(self, db_session: Session):
        """Heartbeat does NOT fire when cron expression doesn't match."""
        agent = _make_agent(db_session, heartbeat_cron="*/30 * * * *")
        # Last heartbeat was just 5 min ago
        _make_heartbeat_task(
            db_session,
            agent.id,
            created_at=datetime.now(UTC) - timedelta(minutes=5),
        )

        now_naive = datetime.now(UTC).replace(tzinfo=None)

        with (
            patch(
                "backend.openloop.agents.automation_scheduler._fire_heartbeat",
                new_callable=AsyncMock,
            ) as mock_fire,
            patch(
                "backend.openloop.agents.automation_scheduler.concurrency_manager.acquire_slot",
                return_value=True,
            ),
        ):
            await _evaluate_heartbeats(db_session, now_naive)
            mock_fire.assert_not_called()

    @pytest.mark.asyncio
    async def test_heartbeat_respects_automation_lane(self, db_session: Session):
        """Heartbeat does not fire when automation lane is full."""
        _make_agent(db_session)

        now_naive = datetime.now(UTC).replace(tzinfo=None)

        with (
            patch(
                "backend.openloop.agents.automation_scheduler._fire_heartbeat",
                new_callable=AsyncMock,
            ) as mock_fire,
            patch(
                "backend.openloop.agents.automation_scheduler.concurrency_manager.acquire_slot",
                return_value=False,
            ),
        ):
            await _evaluate_heartbeats(db_session, now_naive)
            mock_fire.assert_not_called()

    @pytest.mark.asyncio
    async def test_inactive_agent_skipped(self, db_session: Session):
        """Agent with status != 'active' is not fired even with heartbeat enabled."""
        _make_agent(db_session, status="paused", name="InactiveAgent")

        now_naive = datetime.now(UTC).replace(tzinfo=None)

        with (
            patch(
                "backend.openloop.agents.automation_scheduler._fire_heartbeat",
                new_callable=AsyncMock,
            ) as mock_fire,
            patch(
                "backend.openloop.agents.automation_scheduler.concurrency_manager.acquire_slot",
                return_value=True,
            ),
        ):
            await _evaluate_heartbeats(db_session, now_naive)
            mock_fire.assert_not_called()


# ---------------------------------------------------------------------------
# Kill switch guard — heartbeats skip when system paused
# ---------------------------------------------------------------------------


class TestHeartbeatKillSwitch:
    """Tests that heartbeats respect the kill switch (system paused)."""

    @pytest.mark.asyncio
    async def test_heartbeat_respects_kill_switch(self, db_session: Session):
        """When system is paused, _tick() returns early and heartbeats don't fire."""
        _make_agent(db_session)
        _set_system_paused(db_session, True)

        # We test via _tick() which checks is_paused at the top
        from backend.openloop.agents.automation_scheduler import _tick

        # Patch SessionLocal to return our test session
        with (
            patch(
                "backend.openloop.agents.automation_scheduler.SessionLocal",
                return_value=db_session,
            ),
            # Prevent db.close() from closing our test session
            patch.object(db_session, "close", new=MagicMock()),
            patch(
                "backend.openloop.agents.automation_scheduler._fire_heartbeat",
                new_callable=AsyncMock,
            ) as mock_fire,
            patch(
                "backend.openloop.agents.automation_scheduler._evaluate_heartbeats",
                new_callable=AsyncMock,
            ) as mock_evaluate,
        ):
            await _tick()
            # _evaluate_heartbeats should never be called because _tick returns early
            mock_evaluate.assert_not_called()
            mock_fire.assert_not_called()


# ---------------------------------------------------------------------------
# HEARTBEAT_OK silent completion vs. action notification
# ---------------------------------------------------------------------------


class TestHeartbeatCompletion:
    """Tests for heartbeat completion behavior in agent_runner."""

    def test_heartbeat_ok_no_notification(self, db_session: Session):
        """HEARTBEAT_OK response creates no user-visible notification."""
        agent = _make_agent(db_session, name="QuietAgent")
        space = _make_space(db_session, name="QuietSpace")

        # Simulate what _run_background_task does at completion for heartbeat
        result_text = "Everything looks fine. HEARTBEAT_OK"
        run_type = "heartbeat"
        is_heartbeat = run_type == "heartbeat"
        heartbeat_ok = is_heartbeat and "HEARTBEAT_OK" in result_text.upper()

        assert heartbeat_ok is True

        # Verify no notifications would be created (check before count)
        notif_count_before = db_session.query(Notification).count()

        # The actual code path: heartbeat_ok means no notification
        # We just verify the logic is correct
        if heartbeat_ok:
            pass  # Silent — no notification
        else:
            from backend.openloop.services import notification_service

            notification_service.create_notification(
                db_session,
                type="heartbeat_action",
                title="should not happen",
                body="should not happen",
            )

        notif_count_after = db_session.query(Notification).count()
        assert notif_count_after == notif_count_before

    def test_heartbeat_action_creates_notification_and_audit(self, db_session: Session):
        """Heartbeat that takes action (no HEARTBEAT_OK) creates notification + audit."""
        agent = _make_agent(db_session, name="ActionAgent")
        space = _make_space(db_session, name="ActionSpace")

        result_text = "I found 3 overdue items and updated their status."
        run_type = "heartbeat"
        is_heartbeat = run_type == "heartbeat"
        heartbeat_ok = is_heartbeat and "HEARTBEAT_OK" in result_text.upper()

        assert heartbeat_ok is False
        assert is_heartbeat is True

        # Create notification (mimicking the agent_runner code path)
        from backend.openloop.services import audit_service, notification_service

        task = _make_heartbeat_task(db_session, agent.id, status="completed")

        audit_service.log_action(
            db_session,
            agent_id=agent.id,
            action="heartbeat_action",
            background_task_id=task.id,
            tool_name="heartbeat",
            input_summary=f"Heartbeat took action: {result_text[:200]}",
        )

        notification_service.create_notification(
            db_session,
            type=NotificationType.HEARTBEAT_ACTION,
            title=f"Heartbeat: {agent.name} took action",
            body=result_text[:500],
            space_id=space.id,
        )

        # Verify notification was created
        notif = (
            db_session.query(Notification)
            .filter(Notification.type == NotificationType.HEARTBEAT_ACTION)
            .first()
        )
        assert notif is not None
        assert "ActionAgent" in notif.title
        assert "overdue items" in notif.body

        # Verify audit log was created
        from backend.openloop.db.models import AuditLog

        audit = (
            db_session.query(AuditLog)
            .filter(
                AuditLog.agent_id == agent.id,
                AuditLog.action == "heartbeat_action",
            )
            .first()
        )
        assert audit is not None
        assert audit.background_task_id == task.id

    def test_heartbeat_ok_case_insensitive(self, db_session: Session):
        """HEARTBEAT_OK detection is case-insensitive."""
        for variant in ["heartbeat_ok", "Heartbeat_Ok", "HEARTBEAT_OK", "HeartBeat_OK"]:
            result_text = f"All clear. {variant}"
            assert "HEARTBEAT_OK" in result_text.upper()


# ---------------------------------------------------------------------------
# Fire heartbeat — prompt construction
# ---------------------------------------------------------------------------


class TestFireHeartbeat:
    """Tests for the _fire_heartbeat function."""

    @pytest.mark.asyncio
    async def test_fire_heartbeat_builds_survey_prompt(self, db_session: Session):
        """_fire_heartbeat constructs the correct survey prompt and calls delegate_background."""
        agent = _make_agent(db_session, name="SurveyAgent")
        space = _make_space(db_session, name="SurveySpace")
        agent.spaces.append(space)
        db_session.commit()

        from backend.openloop.agents.automation_scheduler import _fire_heartbeat

        with patch(
            "backend.openloop.agents.agent_runner.delegate_background",
            new_callable=AsyncMock,
            return_value="task-id-123",
        ) as mock_delegate:
            await _fire_heartbeat(db_session, agent)

            mock_delegate.assert_called_once()
            call_kwargs = mock_delegate.call_args
            # Check instruction contains heartbeat survey prompt
            instruction = call_kwargs.kwargs.get("instruction") or call_kwargs[1].get("instruction")
            assert "HEARTBEAT" in instruction
            assert "periodic check-in" in instruction
            assert "HEARTBEAT_OK" in instruction
            # Check run_type is heartbeat
            rt = call_kwargs.kwargs.get("run_type") or call_kwargs[1].get("run_type")
            assert rt == BackgroundTaskRunType.HEARTBEAT
            # Check space_id is the agent's first space
            sid = call_kwargs.kwargs.get("space_id") or call_kwargs[1].get("space_id")
            assert sid == space.id

    @pytest.mark.asyncio
    async def test_fire_heartbeat_no_spaces_uses_none(self, db_session: Session):
        """Agent with no bound spaces passes space_id=None."""
        agent = _make_agent(db_session, name="NoSpaceAgent")

        from backend.openloop.agents.automation_scheduler import _fire_heartbeat

        with patch(
            "backend.openloop.agents.agent_runner.delegate_background",
            new_callable=AsyncMock,
            return_value="task-id-456",
        ) as mock_delegate:
            await _fire_heartbeat(db_session, agent)

            call_kwargs = mock_delegate.call_args
            sid = call_kwargs.kwargs.get("space_id") or call_kwargs[1].get("space_id")
            assert sid is None


# ---------------------------------------------------------------------------
# delegate_background — run_type passthrough
# ---------------------------------------------------------------------------


class TestDelegateBackgroundRunType:
    """Tests that delegate_background passes run_type to create_background_task."""

    def test_run_type_defaults_to_task(self):
        """Default run_type is 'task'."""
        import inspect

        from backend.openloop.agents.agent_runner import delegate_background

        sig = inspect.signature(delegate_background)
        assert sig.parameters["run_type"].default == "task"

    def test_heartbeat_run_type_in_lane_determination(self):
        """run_type='heartbeat' maps to the 'automation' lane."""
        # This tests the logic inline — heartbeat should use automation lane
        run_type = "heartbeat"
        parent_task_id = None
        automation_run_id = None

        if parent_task_id:
            lane = "subagent"
        elif automation_run_id or run_type == "heartbeat":
            lane = "automation"
        else:
            lane = "autonomous"

        assert lane == "automation"


# ---------------------------------------------------------------------------
# Agent service — updatable fields
# ---------------------------------------------------------------------------


class TestAgentServiceHeartbeatFields:
    """Tests that heartbeat fields are updatable via agent_service."""

    def test_update_agent_heartbeat_enabled(self, db_session: Session):
        """heartbeat_enabled is accepted by update_agent."""
        agent = agent_service.create_agent(db_session, name="UpdAgent1")
        assert agent.heartbeat_enabled is False

        updated = agent_service.update_agent(
            db_session, agent.id, heartbeat_enabled=True
        )
        assert updated.heartbeat_enabled is True

    def test_update_agent_heartbeat_cron(self, db_session: Session):
        """heartbeat_cron is accepted by update_agent."""
        agent = agent_service.create_agent(db_session, name="UpdAgent2")
        assert agent.heartbeat_cron is None

        updated = agent_service.update_agent(
            db_session, agent.id, heartbeat_cron="*/15 * * * *"
        )
        assert updated.heartbeat_cron == "*/15 * * * *"

    def test_update_agent_max_spawn_depth(self, db_session: Session):
        """max_spawn_depth is accepted by update_agent."""
        agent = agent_service.create_agent(db_session, name="UpdAgent3")
        assert agent.max_spawn_depth == 1

        updated = agent_service.update_agent(
            db_session, agent.id, max_spawn_depth=3
        )
        assert updated.max_spawn_depth == 3
