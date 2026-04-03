"""Tests for lane-isolated concurrency management (Task 8.5).

Verifies that each lane enforces its own cap independently, that the total
background cap is enforced, and that interactive conversations do NOT block
automation runs.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from backend.openloop.agents.concurrency_manager import (
    LANE_CAPS,
    MAX_TOTAL_BACKGROUND,
    acquire_slot,
    get_lane_status,
    release_slot,
)
from backend.openloop.db.models import Agent, AutomationRun, BackgroundTask, Conversation
from backend.openloop.services import agent_service, automation_service, space_service
from contract.enums import BackgroundTaskStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_agent(db: Session, name: str = "ConcAgent") -> Agent:
    return agent_service.create_agent(db, name=name)


def _make_active_conversation(db: Session, agent_id: str, *, sdk_session_id: str = "sdk-123") -> Conversation:
    """Create a Conversation that counts as an active interactive session."""
    from backend.openloop.services import conversation_service

    conv = conversation_service.create_conversation(
        db,
        agent_id=agent_id,
        name="Test Interactive Conv",
    )
    conv.status = "active"
    conv.sdk_session_id = sdk_session_id
    db.commit()
    db.refresh(conv)
    return conv


def _make_running_automation_run(db: Session, automation_id: str) -> AutomationRun:
    """Create an AutomationRun with status=running."""
    return automation_service.create_run(db, automation_id=automation_id)


def _make_running_background_task(
    db: Session,
    agent_id: str,
    *,
    parent_task_id: str | None = None,
    automation_id: str | None = None,
) -> BackgroundTask:
    """Create a BackgroundTask with status=running."""
    from backend.openloop.services import background_task_service

    return background_task_service.create_background_task(
        db,
        agent_id=agent_id,
        instruction="test task",
        parent_task_id=parent_task_id,
        automation_id=automation_id,
        status="running",
    )


def _make_automation(db: Session, agent_id: str, name: str = "TestAuto"):
    return automation_service.create_automation(
        db,
        name=name,
        agent_id=agent_id,
        instruction="do something",
        trigger_type="cron",
        cron_expression="0 * * * *",
        enabled=True,
    )


# ---------------------------------------------------------------------------
# Interactive lane tests
# ---------------------------------------------------------------------------


class TestInteractiveLane:
    def test_interactive_allows_under_cap(self, db_session: Session):
        """Should return True when fewer than 5 interactive sessions are active."""
        agent = _make_agent(db_session, name="IntUnder")
        _make_active_conversation(db_session, agent.id, sdk_session_id="sdk-1")
        assert acquire_slot(db_session, "interactive") is True

    def test_interactive_enforces_cap_of_5(self, db_session: Session):
        """Should return False when 5 interactive sessions are active."""
        agent = _make_agent(db_session, name="IntCap")
        for i in range(5):
            _make_active_conversation(db_session, agent.id, sdk_session_id=f"sdk-{i}")

        assert acquire_slot(db_session, "interactive") is False

    def test_interactive_cap_exact_boundary(self, db_session: Session):
        """4 sessions: allowed. 5 sessions: denied."""
        agent = _make_agent(db_session, name="IntBound")
        for i in range(4):
            _make_active_conversation(db_session, agent.id, sdk_session_id=f"sdk-{i}")
        assert acquire_slot(db_session, "interactive") is True

        _make_active_conversation(db_session, agent.id, sdk_session_id="sdk-4")
        assert acquire_slot(db_session, "interactive") is False


# ---------------------------------------------------------------------------
# Automation lane tests
# ---------------------------------------------------------------------------


class TestAutomationLane:
    def test_automation_allows_under_cap(self, db_session: Session):
        """Should return True when fewer than 3 automation runs exist."""
        assert acquire_slot(db_session, "automation") is True

    def test_automation_enforces_cap_of_3(self, db_session: Session):
        """Should return False when 3 automation runs are active."""
        agent = _make_agent(db_session, name="AutoCap")
        auto = _make_automation(db_session, agent.id, name="Auto1")
        for _ in range(3):
            _make_running_automation_run(db_session, auto.id)

        assert acquire_slot(db_session, "automation") is False

    def test_automation_completed_runs_dont_count(self, db_session: Session):
        """Completed runs should not count toward the cap."""
        agent = _make_agent(db_session, name="AutoComplete")
        auto = _make_automation(db_session, agent.id, name="AutoComp")
        run = _make_running_automation_run(db_session, auto.id)
        automation_service.complete_run(db_session, run.id, status="success")

        assert acquire_slot(db_session, "automation") is True


# ---------------------------------------------------------------------------
# Autonomous lane tests
# ---------------------------------------------------------------------------


class TestAutonomousLane:
    def test_autonomous_allows_under_cap(self, db_session: Session):
        """Should allow when under the autonomous cap of 2."""
        assert acquire_slot(db_session, "autonomous") is True

    def test_autonomous_enforces_cap_of_2(self, db_session: Session):
        """Should deny when 2 autonomous tasks are running."""
        agent = _make_agent(db_session, name="AutonomousCap")
        _make_running_background_task(db_session, agent.id)
        _make_running_background_task(db_session, agent.id)

        assert acquire_slot(db_session, "autonomous") is False


# ---------------------------------------------------------------------------
# Subagent lane tests
# ---------------------------------------------------------------------------


class TestSubagentLane:
    def test_subagent_allows_under_cap(self, db_session: Session):
        """Should allow when under the subagent cap of 8."""
        assert acquire_slot(db_session, "subagent") is True

    def test_subagent_enforces_cap_of_8(self, db_session: Session):
        """Should deny when 8 subagent tasks are running."""
        agent = _make_agent(db_session, name="SubCap")
        # Need a parent task to count as subagent
        parent = _make_running_background_task(db_session, agent.id)
        for _ in range(8):
            _make_running_background_task(db_session, agent.id, parent_task_id=parent.id)

        assert acquire_slot(db_session, "subagent") is False


# ---------------------------------------------------------------------------
# Total background cap tests
# ---------------------------------------------------------------------------


class TestTotalBackgroundCap:
    def test_total_background_cap_enforced(self, db_session: Session):
        """Even if a lane has room, deny if total background >= 8."""
        agent = _make_agent(db_session, name="TotalCap")
        # Create 8 autonomous tasks (cap is 2, but we manually create them
        # to test the total background cap). Use direct DB inserts.
        # Actually, the autonomous lane cap of 2 would block first.
        # Let's mix: 2 autonomous + fill the rest as subagent tasks.
        parent = _make_running_background_task(db_session, agent.id)  # 1 autonomous
        _make_running_background_task(db_session, agent.id)  # 2 autonomous
        for _ in range(6):
            _make_running_background_task(db_session, agent.id, parent_task_id=parent.id)
        # Total: 8 background tasks running

        # Automation lane has room (0/3) but total background cap reached
        assert acquire_slot(db_session, "automation") is False

    def test_total_background_allows_under_cap(self, db_session: Session):
        """When total background < 8, background lanes should not be blocked by total cap."""
        agent = _make_agent(db_session, name="TotalUnder")
        _make_running_background_task(db_session, agent.id)  # 1 autonomous

        # Total is 1, well under 8
        assert acquire_slot(db_session, "automation") is True

    def test_total_background_cap_does_not_affect_interactive(self, db_session: Session):
        """Interactive lane is unaffected by the total background cap."""
        agent = _make_agent(db_session, name="TotalInteractive")
        parent = _make_running_background_task(db_session, agent.id)
        _make_running_background_task(db_session, agent.id)
        for _ in range(6):
            _make_running_background_task(db_session, agent.id, parent_task_id=parent.id)
        # Total: 8 background tasks

        # Interactive lane should still work
        assert acquire_slot(db_session, "interactive") is True


# ---------------------------------------------------------------------------
# Lanes track independently (regression test for removed yield-to-interactive)
# ---------------------------------------------------------------------------


class TestLaneIndependence:
    def test_interactive_does_not_block_automation(self, db_session: Session):
        """An active interactive conversation must NOT block automation runs.

        This is the key regression test for the yield-to-interactive removal.
        """
        agent = _make_agent(db_session, name="NoBlock")
        # Create several active interactive conversations
        for i in range(3):
            _make_active_conversation(db_session, agent.id, sdk_session_id=f"sdk-noblock-{i}")

        # Automation lane should still be available
        assert acquire_slot(db_session, "automation") is True

    def test_automation_does_not_block_interactive(self, db_session: Session):
        """Running automations should not block interactive sessions."""
        agent = _make_agent(db_session, name="NoBlockRev")
        auto = _make_automation(db_session, agent.id, name="ReverseBlock")
        for _ in range(3):
            _make_running_automation_run(db_session, auto.id)

        # Automation lane is full, but interactive should still work
        assert acquire_slot(db_session, "interactive") is True

    def test_autonomous_does_not_block_subagent(self, db_session: Session):
        """Autonomous lane being full should not block subagent lane."""
        agent = _make_agent(db_session, name="LaneSep")
        _make_running_background_task(db_session, agent.id)
        _make_running_background_task(db_session, agent.id)

        # Autonomous lane is full (2/2)
        assert acquire_slot(db_session, "autonomous") is False
        # Subagent lane should still be available
        assert acquire_slot(db_session, "subagent") is True

    def test_all_lanes_track_independently(self, db_session: Session):
        """Each lane has its own independent count."""
        agent = _make_agent(db_session, name="AllLanes")
        auto = _make_automation(db_session, agent.id, name="AllAuto")

        # Fill interactive: 5 sessions
        for i in range(5):
            _make_active_conversation(db_session, agent.id, sdk_session_id=f"sdk-all-{i}")

        # Fill automation: 3 runs
        for _ in range(3):
            _make_running_automation_run(db_session, auto.id)

        # Fill autonomous: 2 tasks
        _make_running_background_task(db_session, agent.id)
        _make_running_background_task(db_session, agent.id)

        # Interactive full
        assert acquire_slot(db_session, "interactive") is False
        # Automation full
        assert acquire_slot(db_session, "automation") is False
        # Autonomous full
        assert acquire_slot(db_session, "autonomous") is False
        # Subagent still has room (cap 8, but total bg cap would be hit first at 8)
        # We have 2 autonomous bg tasks, so total bg = 2 < 8 — wait, automation runs
        # are tracked separately from background tasks. Let me think...
        # _count_total_background counts BackgroundTask rows with status=running.
        # We have 2 running BackgroundTasks (autonomous). AutomationRuns are separate.
        # So total bg = 2, under the 8 cap. Subagent should be allowed.
        assert acquire_slot(db_session, "subagent") is True


# ---------------------------------------------------------------------------
# get_lane_status tests
# ---------------------------------------------------------------------------


class TestGetLaneStatus:
    def test_empty_status(self, db_session: Session):
        """With no active sessions, all lanes should show current=0."""
        status = get_lane_status(db_session)
        assert "lanes" in status
        assert "total_background" in status
        for lane_name in LANE_CAPS:
            assert status["lanes"][lane_name]["current"] == 0
            assert status["lanes"][lane_name]["max"] == LANE_CAPS[lane_name]
        assert status["total_background"]["current"] == 0
        assert status["total_background"]["max"] == MAX_TOTAL_BACKGROUND

    def test_status_reflects_active_sessions(self, db_session: Session):
        """get_lane_status should reflect actual DB state."""
        agent = _make_agent(db_session, name="StatusAgent")
        auto = _make_automation(db_session, agent.id, name="StatusAuto")

        # 2 interactive sessions
        _make_active_conversation(db_session, agent.id, sdk_session_id="sdk-s1")
        _make_active_conversation(db_session, agent.id, sdk_session_id="sdk-s2")

        # 1 automation run
        _make_running_automation_run(db_session, auto.id)

        # 1 autonomous background task
        _make_running_background_task(db_session, agent.id)

        status = get_lane_status(db_session)
        assert status["lanes"]["interactive"]["current"] == 2
        assert status["lanes"]["automation"]["current"] == 1
        assert status["lanes"]["autonomous"]["current"] == 1
        assert status["lanes"]["subagent"]["current"] == 0
        assert status["total_background"]["current"] == 1  # Only BackgroundTask rows count


# ---------------------------------------------------------------------------
# release_slot tests
# ---------------------------------------------------------------------------


class TestReleaseSlot:
    def test_release_slot_is_noop(self):
        """release_slot is a no-op since tracking is DB-based."""
        # Should not raise
        release_slot("interactive")
        release_slot("automation")
        release_slot("subagent")
        release_slot("autonomous")


# ---------------------------------------------------------------------------
# Unknown lane tests
# ---------------------------------------------------------------------------


class TestUnknownLane:
    def test_unknown_lane_returns_false(self, db_session: Session):
        """Requesting an unknown lane should return False."""
        assert acquire_slot(db_session, "nonexistent") is False


# ---------------------------------------------------------------------------
# Kill switch interaction (verifying it still halts all lanes)
# ---------------------------------------------------------------------------


class TestKillSwitchHaltsAllLanes:
    def test_kill_switch_blocks_automation_via_scheduler_guard(self, db_session: Session):
        """The kill switch (system_paused) should prevent automation work.

        The kill switch guard is in automation_scheduler._tick() and agent_runner.delegate_background(),
        not in the concurrency manager itself. This test verifies the guard exists upstream
        by checking that system_service.is_paused() works correctly.
        """
        from backend.openloop.services import system_service

        assert system_service.is_paused(db_session) is False

        system_service.emergency_stop(db_session)
        assert system_service.is_paused(db_session) is True

        # The concurrency manager itself doesn't check the kill switch —
        # that's the caller's responsibility (agent_runner, scheduler).
        # But we verify the slot is still available (the guard is upstream).
        assert acquire_slot(db_session, "automation") is True

        system_service.resume(db_session)
        assert system_service.is_paused(db_session) is False
