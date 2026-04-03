from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.openloop.agents import agent_runner
from backend.openloop.api.schemas import (
    AutonomousLaunchResponse,
    TaskListResponse,
    TaskListUpdateRequest,
)
from backend.openloop.database import get_db
from backend.openloop.services import background_task_service

router = APIRouter(prefix="/api/v1/background-tasks", tags=["background-tasks"])


@router.post("/{task_id}/approve-launch", response_model=AutonomousLaunchResponse)
async def approve_launch(task_id: str, db: Session = Depends(get_db)) -> AutonomousLaunchResponse:
    """Approve an autonomous launch — transitions from clarification to execution."""
    task = background_task_service.get_background_task(db, task_id)
    await agent_runner.approve_autonomous_launch(db, task_id=task_id)
    return AutonomousLaunchResponse(
        conversation_id=task.conversation_id or "",
        task_id=task_id,
    )


@router.get("/{task_id}/task-list", response_model=TaskListResponse)
def get_task_list(task_id: str, db: Session = Depends(get_db)) -> TaskListResponse:
    """Return the current task list for an autonomous run."""
    task = background_task_service.get_background_task(db, task_id)
    return TaskListResponse(
        task_list=task.task_list,
        task_list_version=task.task_list_version or 0,
        completed_count=task.completed_count or 0,
        total_count=task.total_count or 0,
    )


@router.patch("/{task_id}/task-list", response_model=TaskListResponse)
def update_task_list(
    task_id: str,
    body: TaskListUpdateRequest,
    db: Session = Depends(get_db),
) -> TaskListResponse:
    """User can modify the task list mid-run."""
    task = background_task_service.get_background_task(db, task_id)
    new_list = body.task_list
    completed = sum(1 for item in new_list if item.get("status") in ("done", "completed"))
    total = len(new_list)
    new_version = (task.task_list_version or 0) + 1

    updated = background_task_service.update_background_task(
        db, task_id,
        task_list=new_list,
        task_list_version=new_version,
        completed_count=completed,
        total_count=total,
    )
    return TaskListResponse(
        task_list=updated.task_list,
        task_list_version=updated.task_list_version,
        completed_count=updated.completed_count,
        total_count=updated.total_count,
    )


@router.post("/{task_id}/pause", status_code=204)
async def pause_task(task_id: str, db: Session = Depends(get_db)) -> None:
    """Pause a running autonomous task at the next turn boundary."""
    await agent_runner.pause_autonomous(db, task_id=task_id)


@router.post("/{task_id}/resume", status_code=204)
async def resume_task(task_id: str, db: Session = Depends(get_db)) -> None:
    """Resume a paused autonomous task."""
    await agent_runner.resume_autonomous(db, task_id=task_id)
