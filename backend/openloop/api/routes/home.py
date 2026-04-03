from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.openloop.api.schemas import DashboardResponse, MorningBriefResponse
from backend.openloop.database import get_db
from backend.openloop.db.models import Conversation, Item, PermissionRequest, Space
from backend.openloop.services import notification_service, summary_service

router = APIRouter(prefix="/api/v1/home", tags=["home"])


@router.get("/dashboard", response_model=DashboardResponse)
def get_dashboard(db: Session = Depends(get_db)) -> DashboardResponse:
    total_spaces = db.query(Space).count()
    open_tasks = (
        db.query(Item)
        .filter(
            Item.item_type == "task",
            Item.is_done == False,  # noqa: E712
            Item.archived == False,  # noqa: E712
        )
        .count()
    )
    pending = db.query(PermissionRequest).filter(PermissionRequest.status == "pending").count()
    active_convs = db.query(Conversation).filter(Conversation.status == "active").count()
    unread = notification_service.unread_count(db)

    return DashboardResponse(
        total_spaces=total_spaces,
        open_task_count=open_tasks,
        pending_approvals=pending,
        active_conversations=active_convs,
        unread_notifications=unread,
    )


@router.post("/morning-brief/dismiss", status_code=204)
def dismiss_morning_brief(db: Session = Depends(get_db)):
    """Mark morning brief as dismissed by updating user_last_seen."""
    summary_service.update_last_seen(db)


@router.get("/morning-brief", response_model=MorningBriefResponse)
def get_morning_brief(db: Session = Depends(get_db)):
    data = summary_service.get_morning_brief(db)
    return data
