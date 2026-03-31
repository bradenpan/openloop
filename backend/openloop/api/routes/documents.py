from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.openloop.api.schemas import DocumentCreate, DocumentResponse
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


@router.get("", response_model=list[DocumentResponse])
def list_documents(
    space_id: str | None = Query(None),
    search: str | None = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> list[DocumentResponse]:
    docs = document_service.list_documents(
        db, space_id=space_id, search=search, limit=limit, offset=offset
    )
    return [DocumentResponse.model_validate(d) for d in docs]


@router.get("/{document_id}", response_model=DocumentResponse)
def get_document(document_id: str, db: Session = Depends(get_db)) -> DocumentResponse:
    doc = document_service.get_document(db, document_id)
    return DocumentResponse.model_validate(doc)


@router.delete("/{document_id}", status_code=204)
def delete_document(document_id: str, db: Session = Depends(get_db)) -> None:
    document_service.delete_document(db, document_id)
