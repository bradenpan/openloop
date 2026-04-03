from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.openloop.api.schemas import AuditLogResponse
from backend.openloop.database import get_db
from backend.openloop.services import audit_service

router = APIRouter(prefix="/api/v1/audit-log", tags=["audit"])


@router.get("", response_model=list[AuditLogResponse])
def list_audit_log(
    agent_id: str | None = Query(None),
    conversation_id: str | None = Query(None),
    tool_name: str | None = Query(None),
    after: datetime | None = Query(None),
    before: datetime | None = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> list[AuditLogResponse]:
    entries = audit_service.query_log(
        db,
        agent_id=agent_id,
        conversation_id=conversation_id,
        tool_name=tool_name,
        after=after,
        before=before,
        limit=limit,
        offset=offset,
    )
    return [AuditLogResponse.model_validate(e) for e in entries]
