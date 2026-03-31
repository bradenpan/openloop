from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.openloop.db.models import Agent, AgentPermission, Space


def create_agent(
    db: Session,
    *,
    name: str,
    description: str | None = None,
    system_prompt: str | None = None,
    default_model: str = "sonnet",
    tools: list | None = None,
    mcp_tools: list | None = None,
    space_ids: list[str] | None = None,
) -> Agent:
    """Create a new agent."""
    existing = db.query(Agent).filter(Agent.name == name).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Agent with name '{name}' already exists")

    agent = Agent(
        name=name,
        description=description,
        system_prompt=system_prompt,
        default_model=default_model,
        tools=tools,
        mcp_tools=mcp_tools,
    )
    db.add(agent)
    db.flush()

    # Link to spaces if provided
    if space_ids:
        for sid in space_ids:
            space = db.query(Space).filter(Space.id == sid).first()
            if space:
                agent.spaces.append(space)

    db.commit()
    db.refresh(agent)
    return agent


def get_agent(db: Session, agent_id: str) -> Agent:
    """Get an agent by ID, or 404."""
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


def list_agents(
    db: Session,
    *,
    limit: int = 50,
    offset: int = 0,
) -> list[Agent]:
    """List all agents."""
    return db.query(Agent).order_by(Agent.created_at.desc()).offset(offset).limit(limit).all()


def update_agent(db: Session, agent_id: str, **kwargs) -> Agent:
    """Update an agent. Uses exclude_unset pattern."""
    agent = get_agent(db, agent_id)
    updatable = {
        "name",
        "description",
        "system_prompt",
        "default_model",
        "tools",
        "mcp_tools",
        "status",
    }
    for field, value in kwargs.items():
        if field == "name" and value is not None:
            existing = db.query(Agent).filter(Agent.name == value, Agent.id != agent_id).first()
            if existing:
                raise HTTPException(
                    status_code=409, detail=f"Agent with name '{value}' already exists"
                )
        if field in updatable:
            setattr(agent, field, value)
    db.commit()
    db.refresh(agent)
    return agent


def delete_agent(db: Session, agent_id: str) -> None:
    """Delete an agent by ID, or 404."""
    agent = get_agent(db, agent_id)
    db.delete(agent)
    db.commit()


# --- Agent-Space linking ---


def add_agent_to_space(db: Session, agent_id: str, space_id: str) -> None:
    """Link an agent to a space."""
    agent = get_agent(db, agent_id)
    space = db.query(Space).filter(Space.id == space_id).first()
    if not space:
        raise HTTPException(status_code=404, detail="Space not found")
    if space not in agent.spaces:
        agent.spaces.append(space)
        db.commit()


def remove_agent_from_space(db: Session, agent_id: str, space_id: str) -> None:
    """Unlink an agent from a space."""
    agent = get_agent(db, agent_id)
    space = db.query(Space).filter(Space.id == space_id).first()
    if space and space in agent.spaces:
        agent.spaces.remove(space)
        db.commit()


# --- Permissions ---


def set_permission(
    db: Session,
    *,
    agent_id: str,
    resource_pattern: str,
    operation: str,
    grant_level: str,
) -> AgentPermission:
    """Set or update a permission for an agent.

    Upserts by (agent_id, resource_pattern, operation).
    """
    get_agent(db, agent_id)  # Verify agent exists

    existing = (
        db.query(AgentPermission)
        .filter(
            AgentPermission.agent_id == agent_id,
            AgentPermission.resource_pattern == resource_pattern,
            AgentPermission.operation == operation,
        )
        .first()
    )
    if existing:
        existing.grant_level = grant_level
        db.commit()
        db.refresh(existing)
        return existing

    perm = AgentPermission(
        agent_id=agent_id,
        resource_pattern=resource_pattern,
        operation=operation,
        grant_level=grant_level,
    )
    db.add(perm)
    db.commit()
    db.refresh(perm)
    return perm


def get_permissions(db: Session, agent_id: str) -> list[AgentPermission]:
    """Get all permissions for an agent."""
    get_agent(db, agent_id)  # Verify agent exists
    return db.query(AgentPermission).filter(AgentPermission.agent_id == agent_id).all()


def delete_permission(db: Session, permission_id: str) -> None:
    """Delete a specific permission entry."""
    perm = db.query(AgentPermission).filter(AgentPermission.id == permission_id).first()
    if not perm:
        raise HTTPException(status_code=404, detail="Permission not found")
    db.delete(perm)
    db.commit()
