from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.openloop.database import get_db
from backend.openloop.db.models import Conversation, Item, PermissionRequest, Space
from backend.openloop.services import notification_service


class DashboardResponse(BaseModel):
    total_spaces: int
    open_task_count: int
    pending_approvals: int
    active_conversations: int
    unread_notifications: int


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
