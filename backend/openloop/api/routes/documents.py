
from fastapi import APIRouter, Depends, Query, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from sqlalchemy.orm import Session

from backend.openloop.api.schemas import (
    DocumentCreate,
    DocumentResponse,
    DocumentUpdate,
    ScanResponse,
)
from backend.openloop.database import get_db
from backend.openloop.services import document_service

router = APIRouter(prefix="/api/v1/documents", tags=["documents"])


@router.post("", response_model=DocumentResponse, status_code=201)
def create_document(body: DocumentCreate, db: Session = Depends(get_db)) -> DocumentResponse:
    doc = document_service.create_document(
        db,
        space_id=body.space_id,
        title=body.title,
        source=body.source,
        local_path=body.local_path,
        drive_file_id=body.drive_file_id,
        drive_folder_id=body.drive_folder_id,
        tags=body.tags,
    )
    return DocumentResponse.model_validate(doc)


@router.post("/upload", response_model=DocumentResponse, status_code=201)
async def upload_document(
    space_id: str = Query(...),
    file: UploadFile = ...,
    db: Session = Depends(get_db),
) -> DocumentResponse:
    content = await file.read()
    doc = document_service.upload_document(
        db,
        space_id=space_id,
        filename=file.filename or "untitled",
        file_content=content,
        content_type=file.content_type,
    )
    return DocumentResponse.model_validate(doc)


@router.post("/scan/{space_id}", response_model=ScanResponse)
def scan_directory(space_id: str, db: Session = Depends(get_db)) -> ScanResponse:
    count = document_service.scan_directory(db, space_id)
    return ScanResponse(new_count=count)


@router.get("", response_model=list[DocumentResponse])
def list_documents(
    space_id: str | None = Query(None),
    search: str | None = Query(None),
    tags: str | None = Query(None, description="Comma-separated tag filter"),
    mime_type: str | None = Query(None),
    sort_by: str | None = Query(None, description="title, size, updated, or default (created)"),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> list[DocumentResponse]:
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
    docs = document_service.list_documents(
        db,
        space_id=space_id,
        search=search,
        tags=tag_list,
        mime_type=mime_type,
        sort_by=sort_by,
        limit=limit,
        offset=offset,
    )
    return [DocumentResponse.model_validate(d) for d in docs]


@router.get("/{document_id}", response_model=DocumentResponse)
def get_document(document_id: str, db: Session = Depends(get_db)) -> DocumentResponse:
    doc = document_service.get_document(db, document_id)
    return DocumentResponse.model_validate(doc)


@router.get(
    "/{document_id}/content",
    responses={200: {"content": {"text/plain": {}, "application/octet-stream": {}}}},
)
def get_document_content(document_id: str, db: Session = Depends(get_db)):
    file_path, mime_type = document_service.get_document_content(db, document_id)
    # For text files, return plain text
    if document_service.is_text_file(file_path.name):
        text = file_path.read_text(encoding="utf-8", errors="replace")
        return PlainTextResponse(content=text)
    # For other files, stream as file download
    return FileResponse(
        path=str(file_path),
        media_type=mime_type or "application/octet-stream",
        filename=file_path.name,
    )


@router.patch("/{document_id}", response_model=DocumentResponse)
def update_document(
    document_id: str,
    body: DocumentUpdate,
    db: Session = Depends(get_db),
) -> DocumentResponse:
    kwargs = body.model_dump(exclude_unset=True)
    doc = document_service.update_document(db, document_id, **kwargs)
    return DocumentResponse.model_validate(doc)


@router.delete("/{document_id}", status_code=204)
def delete_document(document_id: str, db: Session = Depends(get_db)) -> None:
    document_service.delete_document(db, document_id)
