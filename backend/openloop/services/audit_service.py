"""Audit logging service — records tool calls and agent actions."""

from datetime import datetime

from sqlalchemy.orm import Session

from backend.openloop.db.models import AuditLog


def log_tool_call(
    db: Session,
    *,
    agent_id: str,
    conversation_id: str | None = None,
    background_task_id: str | None = None,
    tool_name: str,
    action: str,
    resource_id: str | None = None,
    input_summary: str | None = None,
) -> AuditLog:
    """Record a tool call in the audit log."""
    entry = AuditLog(
        agent_id=agent_id,
        conversation_id=conversation_id,
        background_task_id=background_task_id,
        tool_name=tool_name,
        action=action,
        resource_id=resource_id,
        input_summary=input_summary,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def log_action(
    db: Session,
    *,
    agent_id: str,
    action: str,
    conversation_id: str | None = None,
    background_task_id: str | None = None,
    tool_name: str = "system",
    resource_id: str | None = None,
    input_summary: str | None = None,
) -> AuditLog:
    """Convenience wrapper to log a general agent action."""
    return log_tool_call(
        db,
        agent_id=agent_id,
        conversation_id=conversation_id,
        background_task_id=background_task_id,
        tool_name=tool_name,
        action=action,
        resource_id=resource_id,
        input_summary=input_summary,
    )


def query_log(
    db: Session,
    *,
    agent_id: str | None = None,
    conversation_id: str | None = None,
    tool_name: str | None = None,
    after: datetime | None = None,
    before: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[AuditLog]:
    """Query audit log with optional filters."""
    q = db.query(AuditLog)
    if agent_id is not None:
        q = q.filter(AuditLog.agent_id == agent_id)
    if conversation_id is not None:
        q = q.filter(AuditLog.conversation_id == conversation_id)
    if tool_name is not None:
        q = q.filter(AuditLog.tool_name == tool_name)
    if after is not None:
        q = q.filter(AuditLog.timestamp >= after)
    if before is not None:
        q = q.filter(AuditLog.timestamp <= before)
    return q.order_by(AuditLog.timestamp.desc()).offset(offset).limit(limit).all()
