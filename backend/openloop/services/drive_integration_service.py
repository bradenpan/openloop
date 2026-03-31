"""Drive integration service — links Drive folders to spaces and indexes documents.

Stateless functions following the service pattern (db: Session first param).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.openloop.db.models import DataSource, Document, Space
from backend.openloop.services import gdrive_client

logger = logging.getLogger(__name__)


def link_drive_folder(
    db: Session,
    *,
    space_id: str,
    folder_id: str,
    folder_name: str,
) -> DataSource:
    """Create a DataSource for a Google Drive folder and run initial indexing.

    Returns the created DataSource.
    """
    space = db.query(Space).filter(Space.id == space_id).first()
    if not space:
        raise HTTPException(status_code=404, detail="Space not found")

    # Check for duplicate link
    existing = (
        db.query(DataSource)
        .filter(
            DataSource.space_id == space_id,
            DataSource.source_type == "google_drive",
        )
        .all()
    )
    for ds in existing:
        if ds.config and ds.config.get("folder_id") == folder_id:
            raise HTTPException(
                status_code=409,
                detail="This Drive folder is already linked to this space",
            )

    ds = DataSource(
        space_id=space_id,
        source_type="google_drive",
        name=folder_name,
        config={"folder_id": folder_id},
        status="active",
    )
    db.add(ds)
    db.commit()
    db.refresh(ds)

    # Run initial index
    try:
        index_drive_folder(db, data_source_id=ds.id)
    except Exception:
        logger.warning("Initial index failed for data_source %s", ds.id, exc_info=True)

    return ds


def index_drive_folder(db: Session, *, data_source_id: str) -> int:
    """List files in a linked Drive folder and create Document records.

    Returns count of new documents created.
    """
    ds = db.query(DataSource).filter(DataSource.id == data_source_id).first()
    if not ds:
        raise HTTPException(status_code=404, detail="Data source not found")
    if ds.source_type != "google_drive":
        raise HTTPException(status_code=422, detail="Data source is not a Google Drive link")

    folder_id = ds.config.get("folder_id") if ds.config else None
    if not folder_id:
        raise HTTPException(status_code=422, detail="Data source has no folder_id in config")

    files = gdrive_client.list_files(folder_id)

    # Get existing drive_file_ids for this space to avoid duplicates
    existing_ids: set[str] = set()
    existing_docs = (
        db.query(Document.drive_file_id)
        .filter(
            Document.space_id == ds.space_id,
            Document.source == "drive",
            Document.drive_file_id.isnot(None),
        )
        .all()
    )
    for (fid,) in existing_docs:
        existing_ids.add(fid)

    new_count = 0
    for f in files:
        if f["id"] in existing_ids:
            continue

        # Try to read text content for indexing
        content_text = None
        try:
            content_text = gdrive_client.read_file_text(f["id"])
        except Exception:
            logger.debug("Could not read text for Drive file %s", f["id"])

        file_size = int(f.get("size", 0)) if f.get("size") else None

        doc = Document(
            space_id=ds.space_id,
            title=f["name"],
            source="drive",
            drive_file_id=f["id"],
            drive_folder_id=folder_id,
            file_size=file_size,
            mime_type=f.get("mimeType"),
            content_text=content_text,
            indexed_at=datetime.now(UTC),
        )
        db.add(doc)
        new_count += 1

    if new_count > 0:
        db.commit()

    return new_count


def refresh_drive_index(db: Session, *, data_source_id: str) -> dict:
    """Re-index a linked Drive folder: add new, update changed, remove deleted.

    Returns {"added": int, "updated": int, "removed": int}.
    """
    ds = db.query(DataSource).filter(DataSource.id == data_source_id).first()
    if not ds:
        raise HTTPException(status_code=404, detail="Data source not found")
    if ds.source_type != "google_drive":
        raise HTTPException(status_code=422, detail="Data source is not a Google Drive link")

    folder_id = ds.config.get("folder_id") if ds.config else None
    if not folder_id:
        raise HTTPException(status_code=422, detail="Data source has no folder_id in config")

    # Current Drive state
    drive_files = gdrive_client.list_files(folder_id)
    drive_map = {f["id"]: f for f in drive_files}

    # Current DB state for this folder
    existing_docs = (
        db.query(Document)
        .filter(
            Document.space_id == ds.space_id,
            Document.source == "drive",
            Document.drive_folder_id == folder_id,
        )
        .all()
    )
    existing_map = {doc.drive_file_id: doc for doc in existing_docs if doc.drive_file_id}

    added = 0
    updated = 0
    removed = 0

    # Add new files
    for fid, f in drive_map.items():
        if fid not in existing_map:
            content_text = None
            try:
                content_text = gdrive_client.read_file_text(fid)
            except Exception:
                logger.debug("Could not read text for Drive file %s", fid)

            file_size = int(f.get("size", 0)) if f.get("size") else None

            doc = Document(
                space_id=ds.space_id,
                title=f["name"],
                source="drive",
                drive_file_id=fid,
                drive_folder_id=folder_id,
                file_size=file_size,
                mime_type=f.get("mimeType"),
                content_text=content_text,
                indexed_at=datetime.now(UTC),
            )
            db.add(doc)
            added += 1
        else:
            # Check if file was modified
            doc = existing_map[fid]
            drive_modified_str = f.get("modifiedTime", "")
            drive_modified_dt = None
            if drive_modified_str:
                drive_modified_dt = datetime.fromisoformat(
                    drive_modified_str.replace("Z", "+00:00")
                )
            if doc.title != f["name"] or (
                doc.indexed_at
                and drive_modified_dt
                and drive_modified_dt.replace(tzinfo=None) > doc.indexed_at.replace(tzinfo=None)
            ):
                doc.title = f["name"]
                doc.mime_type = f.get("mimeType")
                doc.file_size = int(f.get("size", 0)) if f.get("size") else None

                try:
                    doc.content_text = gdrive_client.read_file_text(fid)
                except Exception:
                    pass

                doc.indexed_at = datetime.now(UTC)
                updated += 1

    # Remove deleted files
    for fid, doc in existing_map.items():
        if fid not in drive_map:
            db.delete(doc)
            removed += 1

    if added or updated or removed:
        db.commit()

    return {"added": added, "updated": updated, "removed": removed}
