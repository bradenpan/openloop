"""Email API routes — inbox, messages, drafts, sync, and setup."""

from fastapi import APIRouter, Depends, HTTPException, Query
from googleapiclient.errors import HttpError
from sqlalchemy.orm import Session

from backend.openloop.api.schemas import DataSourceResponse
from backend.openloop.api.schemas.email import (
    DraftCreateRequest,
    DraftResponse,
    EmailAuthStatusResponse,
    EmailLabelRequest,
    EmailMessageResponse,
    EmailReplyRequest,
    EmailSetupRequest,
    EmailStatsResponse,
    EmailSyncResponse,
)
from backend.openloop.database import get_db
from backend.openloop.db.models import DataSource
from backend.openloop.services import email_integration_service, gmail_client
from contract.enums import SOURCE_TYPE_GMAIL

router = APIRouter(prefix="/api/v1/email", tags=["email"])


@router.get("/auth-status", response_model=EmailAuthStatusResponse)
def get_auth_status() -> EmailAuthStatusResponse:
    authenticated = gmail_client.is_authenticated()
    return EmailAuthStatusResponse(authenticated=authenticated)


@router.get("/messages", response_model=list[EmailMessageResponse])
def list_messages(
    label: str | None = Query(None),
    query: str | None = Query(None),
    unread_only: bool = Query(False),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> list[EmailMessageResponse]:
    messages = email_integration_service.get_cached_messages(
        db,
        label=label,
        query=query,
        unread_only=unread_only,
        limit=limit,
        offset=offset,
    )
    return [EmailMessageResponse.model_validate(m) for m in messages]


@router.get("/messages/{message_id}", response_model=EmailMessageResponse)
def get_message(message_id: str, db: Session = Depends(get_db)) -> EmailMessageResponse:
    from backend.openloop.db.models import EmailCache

    cached = (
        db.query(EmailCache)
        .filter(EmailCache.gmail_message_id == message_id)
        .first()
    )
    if not cached:
        raise HTTPException(status_code=404, detail="Email not found in cache")

    # Fetch full body from Gmail API
    try:
        full_msg = gmail_client.get_message(message_id)
    except HttpError as exc:
        raise HTTPException(status_code=400, detail=f"Gmail API error: {exc}")

    resp = EmailMessageResponse.model_validate(cached)
    resp.body = full_msg.get("body")
    return resp


@router.post("/messages/{message_id}/label", response_model=EmailMessageResponse)
def label_message(
    message_id: str,
    body: EmailLabelRequest,
    db: Session = Depends(get_db),
) -> EmailMessageResponse:
    try:
        cached = email_integration_service.label_message(
            db,
            message_id=message_id,
            add_labels=body.add_labels,
            remove_labels=body.remove_labels,
        )
    except HttpError as exc:
        raise HTTPException(status_code=400, detail=f"Gmail API error: {exc}")
    return EmailMessageResponse.model_validate(cached)


@router.post("/messages/{message_id}/archive", status_code=204)
def archive_message(message_id: str, db: Session = Depends(get_db)) -> None:
    try:
        email_integration_service.archive_message(db, message_id=message_id)
    except HttpError as exc:
        raise HTTPException(status_code=400, detail=f"Gmail API error: {exc}")


@router.post("/messages/{message_id}/read", status_code=204)
def mark_read(message_id: str, db: Session = Depends(get_db)) -> None:
    try:
        email_integration_service.mark_read(db, message_id=message_id)
    except HttpError as exc:
        raise HTTPException(status_code=400, detail=f"Gmail API error: {exc}")


@router.post("/messages/{message_id}/reply", response_model=EmailMessageResponse)
def reply_to_message(
    message_id: str,
    body: EmailReplyRequest,
    db: Session = Depends(get_db),
) -> EmailMessageResponse:
    try:
        email_integration_service.send_reply(db, message_id=message_id, body=body.body)
    except HttpError as exc:
        raise HTTPException(status_code=400, detail=f"Gmail API error: {exc}")

    # Return the original cached message (reply is a new message in the thread)
    from backend.openloop.db.models import EmailCache

    cached = (
        db.query(EmailCache)
        .filter(EmailCache.gmail_message_id == message_id)
        .first()
    )
    if not cached:
        raise HTTPException(status_code=404, detail="Email not found in cache")
    return EmailMessageResponse.model_validate(cached)


@router.post("/drafts", response_model=DraftResponse, status_code=201)
def create_draft(
    body: DraftCreateRequest,
    db: Session = Depends(get_db),
) -> DraftResponse:
    try:
        result = email_integration_service.create_draft(
            db,
            to=body.to,
            subject=body.subject,
            body=body.body,
            cc=body.cc,
            bcc=body.bcc,
            reply_to=body.reply_to,
        )
    except HttpError as exc:
        raise HTTPException(status_code=400, detail=f"Gmail API error: {exc}")
    return DraftResponse(
        draft_id=result.get("id", ""),
        message=result.get("message"),
    )


@router.post("/drafts/{draft_id}/send", response_model=DraftResponse)
def send_draft(draft_id: str, db: Session = Depends(get_db)) -> DraftResponse:
    try:
        result = email_integration_service.send_draft(db, draft_id=draft_id)
    except HttpError as exc:
        raise HTTPException(status_code=400, detail=f"Gmail API error: {exc}")
    return DraftResponse(
        draft_id=draft_id,
        message=result.get("message") if isinstance(result, dict) else result,
    )


@router.post("/sync", response_model=EmailSyncResponse)
def sync_inbox(db: Session = Depends(get_db)) -> EmailSyncResponse:
    ds = (
        db.query(DataSource)
        .filter(
            DataSource.source_type == SOURCE_TYPE_GMAIL,
            DataSource.space_id.is_(None),
        )
        .first()
    )
    if not ds:
        raise HTTPException(status_code=404, detail="No Gmail data source found")
    result = email_integration_service.sync_inbox(db, ds.id)
    return EmailSyncResponse(**result)


@router.get("/stats", response_model=EmailStatsResponse)
def get_stats(db: Session = Depends(get_db)) -> EmailStatsResponse:
    stats = email_integration_service.get_inbox_stats(db)
    return EmailStatsResponse(**stats)


@router.post("/setup", response_model=DataSourceResponse, status_code=201)
def setup_email(
    body: EmailSetupRequest,
    db: Session = Depends(get_db),
) -> DataSourceResponse:
    ds = email_integration_service.setup_email(db, triage_labels=body.triage_labels)
    return DataSourceResponse.model_validate(ds)


@router.post("/setup-labels")
def setup_labels(db: Session = Depends(get_db)) -> dict:
    created = email_integration_service.ensure_triage_labels(db)
    return {"labels_created": len(created)}
