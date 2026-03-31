from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.openloop.api.schemas import SpaceCreate, SpaceResponse, SpaceUpdate
from backend.openloop.database import get_db
from backend.openloop.services import space_service

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


@router.get("/{space_id}/field-schema")
def get_field_schema(space_id: str, db: Session = Depends(get_db)):
    space = space_service.get_space(db, space_id)
    return space.custom_field_schema or []


@router.delete("/{space_id}", status_code=204)
def delete_space(space_id: str, db: Session = Depends(get_db)) -> None:
    space_service.delete_space(db, space_id)
