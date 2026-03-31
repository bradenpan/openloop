from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.openloop.database import get_db
from backend.openloop.db.models import Conversation, PermissionRequest, Space, Todo
from backend.openloop.services import notification_service


class DashboardResponse(BaseModel):
    total_spaces: int
    open_todo_count: int
    pending_approvals: int
    active_conversations: int
    unread_notifications: int


router = APIRouter(prefix="/api/v1/home", tags=["home"])


@router.get("/dashboard", response_model=DashboardResponse)
def get_dashboard(db: Session = Depends(get_db)) -> DashboardResponse:
    total_spaces = db.query(Space).count()
    open_todos = (
        db.query(Todo)
        .filter(Todo.is_done == False, Todo.promoted_to_item_id == None)  # noqa: E711, E712
        .count()
    )
    pending = db.query(PermissionRequest).filter(PermissionRequest.status == "pending").count()
    active_convs = db.query(Conversation).filter(Conversation.status == "active").count()
    unread = notification_service.unread_count(db)

    return DashboardResponse(
        total_spaces=total_spaces,
        open_todo_count=open_todos,
        pending_approvals=pending,
        active_conversations=active_convs,
        unread_notifications=unread,
    )
