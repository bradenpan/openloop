from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.openloop.api.schemas import NotificationResponse
from backend.openloop.database import get_db
from backend.openloop.services import notification_service

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])


@router.post("/mark-all-read")
def mark_all_read(db: Session = Depends(get_db)) -> dict:
    count = notification_service.mark_all_read(db)
    return {"marked_read": count}


@router.get("", response_model=list[NotificationResponse])
def list_notifications(
    is_read: bool | None = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> list[NotificationResponse]:
    notifs = notification_service.list_notifications(
        db, is_read=is_read, limit=limit, offset=offset
    )
    return [NotificationResponse.model_validate(n) for n in notifs]


@router.post("/{notification_id}/read", response_model=NotificationResponse)
def mark_read(notification_id: str, db: Session = Depends(get_db)) -> NotificationResponse:
    notif = notification_service.mark_read(db, notification_id)
    return NotificationResponse.model_validate(notif)
