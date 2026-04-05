from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.openloop.api.schemas import DataSourceCreate, DataSourceResponse, DataSourceUpdate
from backend.openloop.database import get_db
from backend.openloop.services import data_source_service

router = APIRouter(prefix="/api/v1/data-sources", tags=["data-sources"])


class ExcludeBody(BaseModel):
    space_id: str


@router.post("", response_model=DataSourceResponse, status_code=201)
def create_data_source(body: DataSourceCreate, db: Session = Depends(get_db)) -> DataSourceResponse:
    ds = data_source_service.create_data_source(
        db,
        space_id=body.space_id,
        name=body.name,
        source_type=body.source_type,
        config=body.config,
        refresh_schedule=body.refresh_schedule,
    )
    return DataSourceResponse.model_validate(ds)


@router.get("", response_model=list[DataSourceResponse])
def list_data_sources(
    space_id: str | None = Query(None),
    system: bool | None = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> list[DataSourceResponse]:
    sources = data_source_service.list_data_sources(
        db, space_id=space_id, system=system, limit=limit, offset=offset
    )
    return [DataSourceResponse.model_validate(s) for s in sources]


@router.get("/{data_source_id}", response_model=DataSourceResponse)
def get_data_source(data_source_id: str, db: Session = Depends(get_db)) -> DataSourceResponse:
    ds = data_source_service.get_data_source(db, data_source_id)
    return DataSourceResponse.model_validate(ds)


@router.patch("/{data_source_id}", response_model=DataSourceResponse)
def update_data_source(
    data_source_id: str, body: DataSourceUpdate, db: Session = Depends(get_db)
) -> DataSourceResponse:
    updates = body.model_dump(exclude_unset=True)
    ds = data_source_service.update_data_source(db, data_source_id, **updates)
    return DataSourceResponse.model_validate(ds)


@router.delete("/{data_source_id}", status_code=204)
def delete_data_source(data_source_id: str, db: Session = Depends(get_db)) -> None:
    data_source_service.delete_data_source(db, data_source_id)


@router.post("/{data_source_id}/exclude", status_code=204)
def exclude_data_source(
    data_source_id: str, body: ExcludeBody, db: Session = Depends(get_db)
) -> None:
    data_source_service.exclude_from_space(db, body.space_id, data_source_id)


@router.delete("/{data_source_id}/exclude", status_code=204)
def include_data_source(
    data_source_id: str,
    space_id: str = Query(...),
    db: Session = Depends(get_db),
) -> None:
    data_source_service.include_in_space(db, space_id, data_source_id)
