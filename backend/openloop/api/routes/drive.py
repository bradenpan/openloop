from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy.orm import Session

from backend.openloop.api.schemas.drive import (
    DriveAuthStatusResponse,
    DriveLinkRequest,
    DriveLinkResponse,
    DriveRefreshResponse,
)
from backend.openloop.database import get_db
from backend.openloop.services import drive_integration_service, gdrive_client

router = APIRouter(prefix="/api/v1/drive", tags=["drive"])


@router.get("/auth-status", response_model=DriveAuthStatusResponse)
def auth_status() -> DriveAuthStatusResponse:
    return DriveAuthStatusResponse(authenticated=gdrive_client.is_authenticated())


@router.post("/link", response_model=DriveLinkResponse, status_code=201)
def link_drive_folder(
    body: DriveLinkRequest,
    db: Session = Depends(get_db),
) -> DriveLinkResponse:
    ds = drive_integration_service.link_drive_folder(
        db,
        space_id=body.space_id,
        folder_id=body.folder_id,
        folder_name=body.folder_name,
    )
    # Count documents that were indexed
    from backend.openloop.db.models import Document

    doc_count = (
        db.query(Document)
        .filter(
            Document.space_id == ds.space_id,
            Document.source == "drive",
            Document.drive_folder_id == body.folder_id,
        )
        .count()
    )
    return DriveLinkResponse(
        data_source_id=ds.id,
        folder_id=body.folder_id,
        folder_name=body.folder_name,
        documents_indexed=doc_count,
    )


@router.post("/refresh/{data_source_id}", response_model=DriveRefreshResponse)
def refresh_drive_index(
    data_source_id: str,
    db: Session = Depends(get_db),
) -> DriveRefreshResponse:
    result = drive_integration_service.refresh_drive_index(db, data_source_id=data_source_id)
    return DriveRefreshResponse(**result)


@router.get("/files/{file_id}/content")
def get_drive_file_content(file_id: str):
    """Proxy Drive file content to the frontend."""
    if not gdrive_client.is_authenticated():
        raise HTTPException(status_code=401, detail="Google Drive not authenticated")

    try:
        text = gdrive_client.read_file_text(file_id)
        if text is not None:
            return PlainTextResponse(content=text)

        # Binary file — return raw bytes
        content_bytes, mime_type = gdrive_client.read_file(file_id)
        return Response(content=content_bytes, media_type=mime_type)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to read Drive file: {e}")
