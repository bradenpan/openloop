from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.openloop.api.schemas import (
    ConsolidationApplyRequest,
    ConsolidationApplyResponse,
    ConsolidationReportResponse,
    MemoryCreate,
    MemoryHealthResponse,
    MemoryResponse,
    MemoryUpdate,
)
from backend.openloop.database import get_db
from backend.openloop.services import memory_service, space_service

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
    include_archived: bool = Query(False),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> list[MemoryResponse]:
    entries = memory_service.list_entries(
        db, namespace=namespace, search=search, include_archived=include_archived, limit=limit, offset=offset
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


@router.post("/{entry_id}/archive", status_code=204)
def archive_entry(entry_id: str, db: Session = Depends(get_db)) -> None:
    memory_service.archive_entry(db, entry_id)


@router.delete("/{entry_id}", status_code=204)
def delete_entry(entry_id: str, db: Session = Depends(get_db)) -> None:
    memory_service.delete_entry(db, entry_id)


# ---------------------------------------------------------------------------
# Phase 7.1a: Memory lifecycle endpoints (space-scoped)
# ---------------------------------------------------------------------------

space_memory_router = APIRouter(prefix="/api/v1/spaces", tags=["memory"])


@space_memory_router.get(
    "/{space_id}/memory/health",
    response_model=MemoryHealthResponse,
)
def get_memory_health(
    space_id: str, db: Session = Depends(get_db)
) -> MemoryHealthResponse:
    space_service.get_space(db, space_id)  # raises 404 if not found
    stats = memory_service.get_memory_health(db, space_id)
    return MemoryHealthResponse(**stats)


@space_memory_router.post(
    "/{space_id}/memory/consolidate",
    response_model=ConsolidationReportResponse,
)
async def consolidate_memory(
    space_id: str, db: Session = Depends(get_db)
) -> ConsolidationReportResponse:
    space_service.get_space(db, space_id)  # raises 404 if not found
    report = await memory_service.consolidate_space_memory(db, space_id)
    return ConsolidationReportResponse(**report)


@space_memory_router.post(
    "/{space_id}/memory/consolidate/apply",
    response_model=ConsolidationApplyResponse,
)
def apply_consolidation(
    space_id: str,
    body: ConsolidationApplyRequest,
    db: Session = Depends(get_db),
) -> ConsolidationApplyResponse:
    report = body.model_dump(exclude_unset=True)
    result = memory_service.apply_consolidation_report(db, space_id, report)
    return ConsolidationApplyResponse(**result)
