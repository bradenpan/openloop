from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.openloop.api.schemas import (
    ConsolidationResponse,
    SpaceCreate,
    SpaceResponse,
    SpaceUpdate,
)
from backend.openloop.database import get_db
from backend.openloop.services import consolidation_service, space_service

router = APIRouter(prefix="/api/v1/spaces", tags=["spaces"])


@router.post("", response_model=SpaceResponse, status_code=201)
def create_space(body: SpaceCreate, db: Session = Depends(get_db)) -> SpaceResponse:
    space = space_service.create_space(
        db, name=body.name, template=body.template.value, description=body.description
    )
    return SpaceResponse.model_validate(space)


@router.get("", response_model=list[SpaceResponse])
def list_spaces(
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> list[SpaceResponse]:
    spaces = space_service.list_spaces(db, limit=limit, offset=offset)
    return [SpaceResponse.model_validate(s) for s in spaces]


@router.get("/{space_id}", response_model=SpaceResponse)
def get_space(space_id: str, db: Session = Depends(get_db)) -> SpaceResponse:
    space = space_service.get_space(db, space_id)
    return SpaceResponse.model_validate(space)


@router.patch("/{space_id}", response_model=SpaceResponse)
def update_space(space_id: str, body: SpaceUpdate, db: Session = Depends(get_db)) -> SpaceResponse:
    updates = body.model_dump(exclude_unset=True)
    space = space_service.update_space(db, space_id, **updates)
    return SpaceResponse.model_validate(space)


@router.get("/{space_id}/field-schema", response_model=list)
def get_field_schema(space_id: str, db: Session = Depends(get_db)):
    space = space_service.get_space(db, space_id)
    return space.custom_field_schema or []


@router.post("/{space_id}/consolidate", response_model=ConsolidationResponse)
async def consolidate_summaries(
    space_id: str, db: Session = Depends(get_db)
) -> ConsolidationResponse:
    # 404 if space not found
    space_service.get_space(db, space_id)

    count = consolidation_service.get_unconsolidated_count(db, space_id)
    if count < 2:
        raise HTTPException(
            status_code=409,
            detail=f"Not enough unconsolidated summaries to consolidate (found {count}, need at least 2)",
        )

    meta = await consolidation_service.generate_meta_summary(db, space_id)
    return ConsolidationResponse.model_validate(meta)


@router.delete("/{space_id}", status_code=204)
def delete_space(space_id: str, db: Session = Depends(get_db)) -> None:
    space_service.delete_space(db, space_id)
