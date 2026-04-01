from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.openloop.api.schemas import (
    ItemCreate,
    ItemEventResponse,
    ItemLinkCreate,
    ItemLinkResponse,
    ItemMove,
    ItemResponse,
    ItemUpdate,
    RecordChildrenResponse,
)
from backend.openloop.database import get_db
from backend.openloop.services import item_link_service, item_service

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
        parent_item_id=body.parent_item_id,
        is_agent_task=body.is_agent_task,
        is_done=body.is_done,
    )
    return ItemResponse.model_validate(item)


@router.get("", response_model=list[ItemResponse])
def list_items(
    space_id: str | None = Query(None),
    stage: str | None = Query(None),
    item_type: str | None = Query(None),
    parent_item_id: str | None = Query(None),
    is_done: bool | None = Query(None),
    archived: bool = Query(False),
    sort_by: str | None = Query(None),
    sort_order: str = Query("asc"),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> list[ItemResponse]:
    items = item_service.list_items(
        db,
        space_id=space_id,
        stage=stage,
        item_type=item_type,
        parent_item_id=parent_item_id,
        is_done=is_done,
        archived=archived,
        sort_by=sort_by,
        sort_order=sort_order,
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


@router.get("/{item_id}/children", response_model=RecordChildrenResponse)
def get_record_children(item_id: str, db: Session = Depends(get_db)) -> RecordChildrenResponse:
    result = item_service.get_record_with_children(db, item_id)
    return RecordChildrenResponse(
        record=ItemResponse.model_validate(result["record"]),
        child_records=[ItemResponse.model_validate(c) for c in result["child_records"]],
        linked_items=[ItemResponse.model_validate(i) for i in result["linked_items"]],
    )


@router.post("/{item_id}/links", response_model=ItemLinkResponse, status_code=201)
def create_item_link(item_id: str, body: ItemLinkCreate, db: Session = Depends(get_db)):
    link = item_link_service.create_link(
        db, source_item_id=item_id, target_item_id=body.target_item_id, link_type=body.link_type
    )
    return ItemLinkResponse.model_validate(link)


@router.get("/{item_id}/links", response_model=list[ItemLinkResponse])
def list_item_links(item_id: str, link_type: str | None = Query(None), db: Session = Depends(get_db)):
    links = item_link_service.list_links_for_item(db, item_id, link_type=link_type)
    return [ItemLinkResponse.model_validate(l) for l in links]


@router.delete("/{item_id}/links/{link_id}", status_code=204)
def delete_item_link(item_id: str, link_id: str, db: Session = Depends(get_db)):
    item_link_service.delete_link(db, link_id)


@router.get("/{item_id}/events", response_model=list[ItemEventResponse])
def get_item_events(item_id: str, db: Session = Depends(get_db)) -> list[ItemEventResponse]:
    item = item_service.get_item(db, item_id)
    return [ItemEventResponse.model_validate(e) for e in item.events]
