from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.openloop.api.schemas import (
    AgentCreate,
    AgentPermissionResponse,
    AgentPermissionSet,
    AgentResponse,
    AgentUpdate,
    PermissionRequestResponse,
    PermissionRequestUpdate,
)
from backend.openloop.database import get_db
from backend.openloop.services import agent_service

# NOTE: running_router (in running.py) shares prefix /api/v1/agents and is
# included BEFORE this router in main.py so that /agents/running resolves
# before the /{agent_id} catch-all here.  Do not reorder without updating
# the include order in main.py.
router = APIRouter(prefix="/api/v1/agents", tags=["agents"])


@router.post("", response_model=AgentResponse, status_code=201)
def create_agent(body: AgentCreate, db: Session = Depends(get_db)) -> AgentResponse:
    agent = agent_service.create_agent(
        db,
        name=body.name,
        description=body.description,
        system_prompt=body.system_prompt,
        default_model=body.default_model,
        tools=body.tools,
        mcp_tools=body.mcp_tools,
        space_ids=body.space_ids,
    )
    return AgentResponse.model_validate(agent)


@router.get("", response_model=list[AgentResponse])
def list_agents(
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> list[AgentResponse]:
    agents = agent_service.list_agents(db, limit=limit, offset=offset)
    return [AgentResponse.model_validate(a) for a in agents]


@router.get("/{agent_id}", response_model=AgentResponse)
def get_agent(agent_id: str, db: Session = Depends(get_db)) -> AgentResponse:
    agent = agent_service.get_agent(db, agent_id)
    return AgentResponse.model_validate(agent)


@router.patch("/{agent_id}", response_model=AgentResponse)
def update_agent(agent_id: str, body: AgentUpdate, db: Session = Depends(get_db)) -> AgentResponse:
    updates = body.model_dump(exclude_unset=True)
    agent = agent_service.update_agent(db, agent_id, **updates)
    return AgentResponse.model_validate(agent)


@router.delete("/{agent_id}", status_code=204)
def delete_agent(agent_id: str, db: Session = Depends(get_db)) -> None:
    agent_service.delete_agent(db, agent_id)


# --- Permissions ---


@router.get("/{agent_id}/permissions", response_model=list[AgentPermissionResponse])
def get_permissions(agent_id: str, db: Session = Depends(get_db)) -> list[AgentPermissionResponse]:
    perms = agent_service.get_permissions(db, agent_id)
    return [AgentPermissionResponse.model_validate(p) for p in perms]


@router.post("/permissions", response_model=AgentPermissionResponse, status_code=201)
def set_permission(
    body: AgentPermissionSet, db: Session = Depends(get_db)
) -> AgentPermissionResponse:
    perm = agent_service.set_permission(
        db,
        agent_id=body.agent_id,
        resource_pattern=body.resource_pattern,
        operation=body.operation.value,
        grant_level=body.grant_level.value,
    )
    return AgentPermissionResponse.model_validate(perm)


@router.delete("/permissions/{permission_id}", status_code=204)
def delete_permission(permission_id: str, db: Session = Depends(get_db)) -> None:
    agent_service.delete_permission(db, permission_id)


# --- Permission Requests ---


@router.patch(
    "/permission-requests/{request_id}",
    response_model=PermissionRequestResponse,
)
def resolve_permission_request(
    request_id: str,
    body: PermissionRequestUpdate,
    db: Session = Depends(get_db),
) -> PermissionRequestResponse:
    req = agent_service.resolve_permission_request(db, request_id, status=body.status.value)
    return PermissionRequestResponse.model_validate(req)
