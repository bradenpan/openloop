from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.openloop.api.schemas import MemoryCreate, MemoryResponse, MemoryUpdate
from backend.openloop.database import get_db
from backend.openloop.services import memory_service

router = APIRouter(prefix="/api/v1/memory", tags=["memory"])


@router.post("", response_model=MemoryResponse, status_code=201)
def create_entry(body: MemoryCreate, db: Session = Depends(get_db)) -> MemoryResponse:
    entry = memory_service.create_entry(
        db,
        namespace=body.namespace,
        key=body.key,
        value=body.value,
        tags=body.tags,
        source=body.source,
    )
    return MemoryResponse.model_validate(entry)


@router.get("", response_model=list[MemoryResponse])
def list_entries(
    namespace: str | None = Query(None),
    search: str | None = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> list[MemoryResponse]:
    entries = memory_service.list_entries(
        db, namespace=namespace, search=search, limit=limit, offset=offset
    )
    return [MemoryResponse.model_validate(e) for e in entries]


@router.get("/{entry_id}", response_model=MemoryResponse)
def get_entry(entry_id: str, db: Session = Depends(get_db)) -> MemoryResponse:
    entry = memory_service.get_entry(db, entry_id)
    return MemoryResponse.model_validate(entry)


@router.patch("/{entry_id}", response_model=MemoryResponse)
def update_entry(
    entry_id: str, body: MemoryUpdate, db: Session = Depends(get_db)
) -> MemoryResponse:
    updates = body.model_dump(exclude_unset=True)
    entry = memory_service.update_entry(db, entry_id, **updates)
    return MemoryResponse.model_validate(entry)


@router.delete("/{entry_id}", status_code=204)
def delete_entry(entry_id: str, db: Session = Depends(get_db)) -> None:
    memory_service.delete_entry(db, entry_id)
