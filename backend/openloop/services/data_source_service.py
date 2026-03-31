from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.openloop.db.models import DataSource, Space


def create_data_source(
    db: Session,
    *,
    space_id: str,
    name: str,
    source_type: str,
    config: dict | None = None,
    refresh_schedule: str | None = None,
) -> DataSource:
    """Register a data source for a space."""
    space = db.query(Space).filter(Space.id == space_id).first()
    if not space:
        raise HTTPException(status_code=404, detail="Space not found")

    ds = DataSource(
        space_id=space_id,
        name=name,
        source_type=source_type,
        config=config,
        refresh_schedule=refresh_schedule,
    )
    db.add(ds)
    db.commit()
    db.refresh(ds)
    return ds


def get_data_source(db: Session, data_source_id: str) -> DataSource:
    """Get a data source by ID, or 404."""
    ds = db.query(DataSource).filter(DataSource.id == data_source_id).first()
    if not ds:
        raise HTTPException(status_code=404, detail="Data source not found")
    return ds


def list_data_sources(
    db: Session,
    *,
    space_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[DataSource]:
    """List data sources, optionally filtered by space."""
    query = db.query(DataSource)
    if space_id is not None:
        query = query.filter(DataSource.space_id == space_id)
    return query.order_by(DataSource.created_at.desc()).offset(offset).limit(limit).all()


def update_data_source(db: Session, data_source_id: str, **kwargs) -> DataSource:
    """Update a data source. Uses exclude_unset pattern."""
    ds = get_data_source(db, data_source_id)
    updatable = {"name", "config", "refresh_schedule", "status"}
    for field, value in kwargs.items():
        if field in updatable:
            setattr(ds, field, value)
    db.commit()
    db.refresh(ds)
    return ds


def delete_data_source(db: Session, data_source_id: str) -> None:
    """Delete a data source by ID, or 404."""
    ds = get_data_source(db, data_source_id)
    db.delete(ds)
    db.commit()
