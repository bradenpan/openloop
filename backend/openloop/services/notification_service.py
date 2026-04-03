from contract.enums import NotificationType
from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.openloop.db.models import Notification


def create_notification(
    db: Session,
    *,
    type: str,
    title: str,
    body: str | None = None,
    space_id: str | None = None,
    conversation_id: str | None = None,
    automation_id: str | None = None,
) -> Notification:
    """Create a notification."""
    valid_types = {t.value for t in NotificationType}
    if type not in valid_types:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid notification type '{type}'. Valid: {sorted(valid_types)}",
        )
    notif = Notification(
        type=type,
        title=title,
        body=body,
        space_id=space_id,
        conversation_id=conversation_id,
        automation_id=automation_id,
    )
    db.add(notif)
    db.commit()
    db.refresh(notif)
    return notif


def list_notifications(
    db: Session,
    *,
    is_read: bool | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Notification]:
    """List notifications, optionally filtered by read status."""
    query = db.query(Notification)
    if is_read is not None:
        query = query.filter(Notification.is_read == is_read)
    return query.order_by(Notification.created_at.desc()).offset(offset).limit(limit).all()


def mark_read(db: Session, notification_id: str) -> Notification:
    """Mark a notification as read."""
    notif = db.query(Notification).filter(Notification.id == notification_id).first()
    if not notif:
        raise HTTPException(status_code=404, detail="Notification not found")
    notif.is_read = True
    db.commit()
    db.refresh(notif)
    return notif


def mark_all_read(db: Session) -> int:
    """Mark all unread notifications as read. Returns the count of notifications updated."""
    count = (
        db.query(Notification)
        .filter(Notification.is_read == False)  # noqa: E712
        .update({"is_read": True})
    )
    db.commit()
    return count


def unread_count(db: Session) -> int:
    """Get the count of unread notifications."""
    return db.query(Notification).filter(Notification.is_read == False).count()  # noqa: E712
