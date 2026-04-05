from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.openloop.api.schemas import (
    AutomationCreate,
    AutomationResponse,
    AutomationRunResponse,
    AutomationUpdate,
    TriggerResponse,
)
from backend.openloop.database import get_db
from backend.openloop.services import automation_service

router = APIRouter(prefix="/api/v1/automations", tags=["automations"])


@router.post("", response_model=AutomationResponse, status_code=201)
def create_automation(
    body: AutomationCreate,
    db: Session = Depends(get_db),
) -> AutomationResponse:
    automation = automation_service.create_automation(
        db,
        name=body.name,
        description=body.description,
        agent_id=body.agent_id,
        instruction=body.instruction,
        trigger_type=body.trigger_type,
        cron_expression=body.cron_expression,
        space_id=body.space_id,
        model_override=body.model_override,
        enabled=body.enabled,
    )
    response = AutomationResponse.model_validate(automation)
    response.runs = []
    return response


@router.get("", response_model=list[AutomationResponse])
def list_automations(
    enabled: bool | None = Query(None),
    include_system: bool = Query(False),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> list[AutomationResponse]:
    automations = automation_service.list_automations(
        db, enabled=enabled, include_system=include_system, limit=limit, offset=offset
    )
    responses = []
    for a in automations:
        r = AutomationResponse(
            id=a.id,
            name=a.name,
            description=a.description,
            space_id=a.space_id,
            agent_id=a.agent_id,
            instruction=a.instruction,
            trigger_type=a.trigger_type,
            cron_expression=a.cron_expression,
            event_source=a.event_source,
            event_filter=a.event_filter,
            model_override=a.model_override,
            enabled=a.enabled,
            last_run_at=a.last_run_at,
            last_run_status=a.last_run_status,
            created_at=a.created_at,
            updated_at=a.updated_at,
            runs=[],
        )
        responses.append(r)
    return responses


@router.get("/{automation_id}", response_model=AutomationResponse)
def get_automation(
    automation_id: str,
    db: Session = Depends(get_db),
) -> AutomationResponse:
    automation = automation_service.get_automation(db, automation_id)
    response = AutomationResponse.model_validate(automation)
    # Populate runs for the detail endpoint
    runs = automation_service.list_runs(db, automation_id, limit=20)
    response.runs = [AutomationRunResponse.model_validate(r) for r in runs]
    return response


@router.patch("/{automation_id}", response_model=AutomationResponse)
def update_automation(
    automation_id: str,
    body: AutomationUpdate,
    db: Session = Depends(get_db),
) -> AutomationResponse:
    updates = body.model_dump(exclude_unset=True)
    automation = automation_service.update_automation(db, automation_id, **updates)
    response = AutomationResponse.model_validate(automation)
    response.runs = []
    return response


@router.delete("/{automation_id}", status_code=204)
def delete_automation(
    automation_id: str,
    db: Session = Depends(get_db),
) -> None:
    automation_service.delete_automation(db, automation_id)


@router.post("/{automation_id}/trigger", response_model=TriggerResponse)
async def trigger_automation(
    automation_id: str,
    db: Session = Depends(get_db),
) -> TriggerResponse:
    run = await automation_service.trigger_automation(db, automation_id)
    return TriggerResponse(run=AutomationRunResponse.model_validate(run))


@router.get("/{automation_id}/runs", response_model=list[AutomationRunResponse])
def list_runs(
    automation_id: str,
    limit: int = Query(20, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> list[AutomationRunResponse]:
    # Confirm automation exists (raises 404 if not)
    automation_service.get_automation(db, automation_id)
    runs = automation_service.list_runs(db, automation_id, limit=limit, offset=offset)
    return [AutomationRunResponse.model_validate(r) for r in runs]
