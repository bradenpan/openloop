from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.openloop.api.schemas import (
    ItemCreate,
    ItemEventResponse,
    ItemMove,
    ItemResponse,
    ItemUpdate,
)
from backend.openloop.database import get_db
from backend.openloop.services import item_service

router = APIRouter(prefix="/api/v1/items", tags=["items"])


@router.post("", response_model=ItemResponse, status_code=201)
def create_item(body: ItemCreate, db: Session = Depends(get_db)) -> ItemResponse:
    item = item_service.create_item(
        db,
        space_id=body.space_id,
        title=body.title,
        item_type=body.item_type.value,
        description=body.description,
        stage=body.stage,
        priority=body.priority,
        custom_fields=body.custom_fields,
        due_date=body.due_date,
        assigned_agent_id=body.assigned_agent_id,
        parent_record_id=body.parent_record_id,
        is_agent_task=body.is_agent_task,
    )
    return ItemResponse.model_validate(item)


@router.get("", response_model=list[ItemResponse])
def list_items(
    space_id: str | None = Query(None),
    stage: str | None = Query(None),
    item_type: str | None = Query(None),
    archived: bool = Query(False),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> list[ItemResponse]:
    items = item_service.list_items(
        db,
        space_id=space_id,
        stage=stage,
        item_type=item_type,
        archived=archived,
        limit=limit,
        offset=offset,
    )
    return [ItemResponse.model_validate(i) for i in items]


@router.get("/{item_id}", response_model=ItemResponse)
def get_item(item_id: str, db: Session = Depends(get_db)) -> ItemResponse:
    item = item_service.get_item(db, item_id)
    return ItemResponse.model_validate(item)


@router.patch("/{item_id}", response_model=ItemResponse)
def update_item(item_id: str, body: ItemUpdate, db: Session = Depends(get_db)) -> ItemResponse:
    updates = body.model_dump(exclude_unset=True)
    item = item_service.update_item(db, item_id, **updates)
    return ItemResponse.model_validate(item)


@router.post("/{item_id}/move", response_model=ItemResponse)
def move_item(item_id: str, body: ItemMove, db: Session = Depends(get_db)) -> ItemResponse:
    item = item_service.move_item(db, item_id, body.stage)
    return ItemResponse.model_validate(item)


@router.post("/{item_id}/archive", response_model=ItemResponse)
def archive_item(item_id: str, db: Session = Depends(get_db)) -> ItemResponse:
    item = item_service.archive_item(db, item_id)
    return ItemResponse.model_validate(item)


@router.get("/{item_id}/events", response_model=list[ItemEventResponse])
def get_item_events(item_id: str, db: Session = Depends(get_db)) -> list[ItemEventResponse]:
    item = item_service.get_item(db, item_id)
    return [ItemEventResponse.model_validate(e) for e in item.events]
