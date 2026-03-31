from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.openloop.api.schemas import (
    ItemResponse,
    TodoCreate,
    TodoPromote,
    TodoResponse,
    TodoUpdate,
)
from backend.openloop.database import get_db
from backend.openloop.services import todo_service

router = APIRouter(prefix="/api/v1/todos", tags=["todos"])


@router.post("", response_model=TodoResponse, status_code=201)
def create_todo(body: TodoCreate, db: Session = Depends(get_db)) -> TodoResponse:
    todo = todo_service.create_todo(
        db, space_id=body.space_id, title=body.title, due_date=body.due_date
    )
    return TodoResponse.model_validate(todo)


@router.get("", response_model=list[TodoResponse])
def list_todos(
    space_id: str | None = Query(None),
    is_done: bool | None = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> list[TodoResponse]:
    todos = todo_service.list_todos(
        db, space_id=space_id, is_done=is_done, limit=limit, offset=offset
    )
    return [TodoResponse.model_validate(t) for t in todos]


@router.get("/{todo_id}", response_model=TodoResponse)
def get_todo(todo_id: str, db: Session = Depends(get_db)) -> TodoResponse:
    todo = todo_service.get_todo(db, todo_id)
    return TodoResponse.model_validate(todo)


@router.patch("/{todo_id}", response_model=TodoResponse)
def update_todo(todo_id: str, body: TodoUpdate, db: Session = Depends(get_db)) -> TodoResponse:
    updates = body.model_dump(exclude_unset=True)
    todo = todo_service.update_todo(db, todo_id, **updates)
    return TodoResponse.model_validate(todo)


@router.delete("/{todo_id}", status_code=204)
def delete_todo(todo_id: str, db: Session = Depends(get_db)) -> None:
    todo_service.delete_todo(db, todo_id)


@router.post("/{todo_id}/promote", response_model=ItemResponse, status_code=201)
def promote_todo(todo_id: str, body: TodoPromote, db: Session = Depends(get_db)) -> ItemResponse:
    item = todo_service.promote_to_item(db, todo_id, stage=body.stage)
    return ItemResponse.model_validate(item)
