from fastapi import HTTPException
from sqlalchemy import insert, delete
from sqlalchemy.orm import Session

from backend.openloop.db.models import DataSource, Space, space_data_source_exclusions


def create_data_source(
    db: Session,
    *,
    space_id: str | None = None,
    name: str,
    source_type: str,
    config: dict | None = None,
    refresh_schedule: str | None = None,
) -> DataSource:
    """Register a data source, optionally linked to a space."""
    if space_id is not None:
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
    system: bool | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[DataSource]:
    """List data sources, optionally filtered by space or system status."""
    query = db.query(DataSource)
    if space_id is not None:
        query = query.filter(DataSource.space_id == space_id)
    if system is True:
        query = query.filter(DataSource.space_id.is_(None))
    elif system is False:
        query = query.filter(DataSource.space_id.isnot(None))
    return query.order_by(DataSource.created_at.desc()).offset(offset).limit(limit).all()


def list_system_data_sources(db: Session) -> list[DataSource]:
    """Return all system-level data sources (space_id IS NULL)."""
    return (
        db.query(DataSource)
        .filter(DataSource.space_id.is_(None))
        .order_by(DataSource.created_at.desc())
        .all()
    )


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


def is_excluded(db: Session, space_id: str, data_source_id: str) -> bool:
    """Check whether a system data source is excluded from a space."""
    row = db.execute(
        space_data_source_exclusions.select().where(
            space_data_source_exclusions.c.space_id == space_id,
            space_data_source_exclusions.c.data_source_id == data_source_id,
        )
    ).first()
    return row is not None


def exclude_from_space(db: Session, space_id: str, data_source_id: str) -> None:
    """Exclude a system data source from a specific space."""
    # Validate both exist
    space = db.query(Space).filter(Space.id == space_id).first()
    if not space:
        raise HTTPException(status_code=404, detail="Space not found")
    ds = get_data_source(db, data_source_id)  # raises 404

    # Only system-level data sources can be excluded from spaces
    if ds.space_id is not None:
        raise HTTPException(
            status_code=422, detail="Only system data sources (space_id=null) can be excluded from spaces"
        )

    if is_excluded(db, space_id, data_source_id):
        return  # already excluded, idempotent

    db.execute(
        insert(space_data_source_exclusions).values(
            space_id=space_id, data_source_id=data_source_id
        )
    )
    db.commit()


def include_in_space(db: Session, space_id: str, data_source_id: str) -> None:
    """Remove an exclusion — re-include a system data source in a space."""
    # Validate both exist
    space = db.query(Space).filter(Space.id == space_id).first()
    if not space:
        raise HTTPException(status_code=404, detail="Space not found")
    get_data_source(db, data_source_id)  # raises 404

    db.execute(
        delete(space_data_source_exclusions).where(
            space_data_source_exclusions.c.space_id == space_id,
            space_data_source_exclusions.c.data_source_id == data_source_id,
        )
    )
    db.commit()
