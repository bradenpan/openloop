"""Summary generation service for autonomous runs.

Stateless module with plain functions. Every function receives db: Session.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from backend.openloop.db.models import (
    Agent,
    ApprovalQueue,
    AuditLog,
    BackgroundTask,
    ConversationMessage,
    SystemState,
)
from backend.openloop.services import notification_service

USER_LAST_SEEN_KEY = "user_last_seen"


def generate_run_summary(db: Session, background_task_id: str) -> str:
    """Generate a structured summary for a completed autonomous run.

    Compiles goal, duration, progress, token usage, approval counts,
    and key actions into a human-readable summary. Stores on the
    BackgroundTask record and creates a notification.
    """
    task = db.query(BackgroundTask).filter(BackgroundTask.id == background_task_id).first()
    if not task:
        return ""

    parts: list[str] = []

    # Goal
    goal_text = task.goal or task.instruction or "No goal specified"
    parts.append(f"Goal: {goal_text}")

    # Duration
    if task.started_at and task.completed_at:
        duration = task.completed_at - task.started_at
        hours, remainder = divmod(int(duration.total_seconds()), 3600)
        minutes, _ = divmod(remainder, 60)
        if hours > 0:
            parts.append(f"Duration: {hours}h {minutes}m")
        else:
            parts.append(f"Duration: {minutes}m")

    # Progress
    if task.total_count and task.total_count > 0:
        parts.append(f"Progress: {task.completed_count or 0}/{task.total_count} items completed")

    # Item breakdown from task_list
    if task.task_list:
        status_counts: dict[str, int] = {}
        for item in task.task_list:
            s = item.get("status", "pending") if isinstance(item, dict) else "pending"
            status_counts[s] = status_counts.get(s, 0) + 1
        breakdown = []
        for s in ["completed", "done", "skipped", "blocked", "failed", "pending", "in_progress"]:
            if s in status_counts:
                breakdown.append(f"{s}: {status_counts[s]}")
        if breakdown:
            parts.append("Items: " + ", ".join(breakdown))

    # Token usage
    if task.conversation_id:
        token_row = (
            db.query(
                func.coalesce(func.sum(ConversationMessage.input_tokens), 0),
                func.coalesce(func.sum(ConversationMessage.output_tokens), 0),
            )
            .filter(ConversationMessage.conversation_id == task.conversation_id)
            .first()
        )
        if token_row:
            input_t, output_t = token_row
            if input_t or output_t:
                parts.append(f"Token usage: {input_t:,} input, {output_t:,} output")

    # Approval counts
    approval_counts = (
        db.query(ApprovalQueue.status, func.count())
        .filter(ApprovalQueue.background_task_id == background_task_id)
        .group_by(ApprovalQueue.status)
        .all()
    )
    if approval_counts:
        acounts = {status: count for status, count in approval_counts}
        approval_parts = []
        for s in ["approved", "denied", "expired", "pending"]:
            if s in acounts:
                approval_parts.append(f"{acounts[s]} {s}")
        if approval_parts:
            parts.append("Approvals: " + ", ".join(approval_parts))

    # Key actions from audit log (top 10)
    audit_filters = []
    if task.conversation_id:
        audit_filters.append(AuditLog.conversation_id == task.conversation_id)
    audit_filters.append(AuditLog.background_task_id == background_task_id)

    if audit_filters:
        actions = (
            db.query(AuditLog.tool_name, AuditLog.action)
            .filter(or_(*audit_filters))
            .order_by(AuditLog.timestamp.desc())
            .limit(10)
            .all()
        )
        if actions:
            action_lines = [f"  - {a.tool_name}: {a.action}" for a in actions]
            parts.append("Key actions:\n" + "\n".join(action_lines))

    summary = "\n".join(parts)

    # Store on task
    task.run_summary = summary
    db.commit()

    # Create notification
    notification_service.create_notification(
        db,
        type="task_completed",
        title=f"Run summary: {(task.goal or task.instruction or 'Autonomous run')[:60]}",
        body=summary[:500],
        space_id=task.space_id,
    )

    return summary


def get_morning_brief(db: Session) -> dict:
    """Get morning brief data -- tasks completed since user's last visit.

    Returns dict with: agents (grouped runs), pending_approvals_count,
    failed_tasks_count, since (last_seen timestamp).
    """
    # Get last seen timestamp from system_state
    row = db.query(SystemState).filter(SystemState.key == USER_LAST_SEEN_KEY).first()
    since: datetime | None = None
    if row and row.value is not None:
        raw = row.value
        if isinstance(raw, str):
            try:
                since = datetime.fromisoformat(raw)
            except (ValueError, TypeError):
                since = None
        elif isinstance(raw, datetime):
            since = raw

    # Query completed tasks since last_seen
    query = (
        db.query(BackgroundTask)
        .filter(
            BackgroundTask.run_type.in_(["autonomous", "heartbeat"]),
            BackgroundTask.run_summary.isnot(None),
            BackgroundTask.status.in_(["completed", "failed"]),
        )
    )
    if since:
        query = query.filter(BackgroundTask.completed_at >= since)
    else:
        # If no last_seen, show last 24 hours
        cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=24)
        query = query.filter(BackgroundTask.completed_at >= cutoff)

    tasks = query.order_by(BackgroundTask.completed_at.desc()).all()

    # Group by agent
    agent_map: dict[str, dict] = {}
    for task in tasks:
        if task.agent_id not in agent_map:
            agent = db.query(Agent).filter(Agent.id == task.agent_id).first()
            agent_map[task.agent_id] = {
                "agent_id": task.agent_id,
                "agent_name": agent.name if agent else "Unknown",
                "runs": [],
            }
        agent_map[task.agent_id]["runs"].append({
            "task_id": task.id,
            "goal": task.goal or task.instruction,
            "run_summary": task.run_summary,
            "status": task.status,
            "completed_count": task.completed_count or 0,
            "total_count": task.total_count or 0,
            "started_at": task.started_at,
            "completed_at": task.completed_at,
        })

    # Pending approvals count
    pending_count = (
        db.query(func.count(ApprovalQueue.id))
        .filter(ApprovalQueue.status == "pending")
        .scalar()
        or 0
    )

    # Failed tasks since last_seen
    failed_query = db.query(func.count(BackgroundTask.id)).filter(
        BackgroundTask.status == "failed"
    )
    if since:
        failed_query = failed_query.filter(BackgroundTask.completed_at >= since)
    failed_count = failed_query.scalar() or 0

    return {
        "agents": list(agent_map.values()),
        "pending_approvals_count": pending_count,
        "failed_tasks_count": failed_count,
        "since": since,
    }


def update_last_seen(db: Session) -> None:
    """Update user_last_seen timestamp in system_state."""
    now_iso = datetime.now(UTC).replace(tzinfo=None).isoformat()
    row = db.query(SystemState).filter(SystemState.key == USER_LAST_SEEN_KEY).first()
    if row is None:
        row = SystemState(key=USER_LAST_SEEN_KEY, value=now_iso)
        db.add(row)
    else:
        row.value = now_iso
        row.updated_at = datetime.now(UTC)
    db.commit()
