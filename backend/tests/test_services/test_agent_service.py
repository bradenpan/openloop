import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.openloop.services import agent_service, space_service


def _make_space(db: Session, name: str = "Test Space", template: str = "project"):
    return space_service.create_space(db, name=name, template=template)


def test_create_agent(db_session: Session):
    agent = agent_service.create_agent(db_session, name="Odin")
    assert agent.name == "Odin"
    assert agent.default_model == "sonnet"
    assert agent.status == "active"
    assert agent.id is not None


def test_create_agent_with_description(db_session: Session):
    agent = agent_service.create_agent(db_session, name="Helper", description="A helpful agent")
    assert agent.description == "A helpful agent"


def test_create_agent_with_system_prompt(db_session: Session):
    agent = agent_service.create_agent(
        db_session, name="Prompted", system_prompt="You are a test agent."
    )
    assert agent.system_prompt == "You are a test agent."


def test_create_agent_with_tools(db_session: Session):
    agent = agent_service.create_agent(
        db_session, name="Tooled", tools=["search", "write"], mcp_tools=["notion"]
    )
    assert agent.tools == ["search", "write"]
    assert agent.mcp_tools == ["notion"]


def test_create_agent_with_spaces(db_session: Session):
    s1 = _make_space(db_session, name="S1")
    s2 = _make_space(db_session, name="S2")
    agent = agent_service.create_agent(db_session, name="Linked", space_ids=[s1.id, s2.id])
    assert len(agent.spaces) == 2


def test_create_agent_duplicate_name(db_session: Session):
    agent_service.create_agent(db_session, name="Unique")
    with pytest.raises(HTTPException) as exc_info:
        agent_service.create_agent(db_session, name="Unique")
    assert exc_info.value.status_code == 409


def test_get_agent(db_session: Session):
    created = agent_service.create_agent(db_session, name="Fetch Me")
    fetched = agent_service.get_agent(db_session, created.id)
    assert fetched.id == created.id
    assert fetched.name == "Fetch Me"


def test_get_agent_not_found(db_session: Session):
    with pytest.raises(HTTPException) as exc_info:
        agent_service.get_agent(db_session, "nonexistent-id")
    assert exc_info.value.status_code == 404


def test_list_agents_empty(db_session: Session):
    agents = agent_service.list_agents(db_session)
    assert agents == []


def test_list_agents(db_session: Session):
    agent_service.create_agent(db_session, name="A")
    agent_service.create_agent(db_session, name="B")
    agents = agent_service.list_agents(db_session)
    assert len(agents) == 2


def test_update_agent_name(db_session: Session):
    agent = agent_service.create_agent(db_session, name="Old Name")
    updated = agent_service.update_agent(db_session, agent.id, name="New Name")
    assert updated.name == "New Name"


def test_update_agent_description(db_session: Session):
    agent = agent_service.create_agent(db_session, name="Agent")
    updated = agent_service.update_agent(db_session, agent.id, description="Updated desc")
    assert updated.description == "Updated desc"


def test_update_agent_duplicate_name(db_session: Session):
    agent_service.create_agent(db_session, name="Taken")
    agent = agent_service.create_agent(db_session, name="Other")
    with pytest.raises(HTTPException) as exc_info:
        agent_service.update_agent(db_session, agent.id, name="Taken")
    assert exc_info.value.status_code == 409


def test_update_agent_not_found(db_session: Session):
    with pytest.raises(HTTPException) as exc_info:
        agent_service.update_agent(db_session, "nonexistent-id", name="Nope")
    assert exc_info.value.status_code == 404


def test_update_agent_no_changes(db_session: Session):
    agent = agent_service.create_agent(db_session, name="NoOp")
    updated = agent_service.update_agent(db_session, agent.id)
    assert updated.name == "NoOp"


def test_delete_agent(db_session: Session):
    agent = agent_service.create_agent(db_session, name="Delete Me")
    agent_service.delete_agent(db_session, agent.id)
    with pytest.raises(HTTPException) as exc_info:
        agent_service.get_agent(db_session, agent.id)
    assert exc_info.value.status_code == 404


def test_delete_agent_not_found(db_session: Session):
    with pytest.raises(HTTPException) as exc_info:
        agent_service.delete_agent(db_session, "nonexistent-id")
    assert exc_info.value.status_code == 404


# --- Agent-Space linking ---


def test_add_agent_to_space(db_session: Session):
    agent = agent_service.create_agent(db_session, name="Agent")
    space = _make_space(db_session)
    agent_service.add_agent_to_space(db_session, agent.id, space.id)
    refreshed = agent_service.get_agent(db_session, agent.id)
    assert len(refreshed.spaces) == 1
    assert refreshed.spaces[0].id == space.id


def test_add_agent_to_space_idempotent(db_session: Session):
    agent = agent_service.create_agent(db_session, name="Agent")
    space = _make_space(db_session)
    agent_service.add_agent_to_space(db_session, agent.id, space.id)
    agent_service.add_agent_to_space(db_session, agent.id, space.id)
    refreshed = agent_service.get_agent(db_session, agent.id)
    assert len(refreshed.spaces) == 1


def test_add_agent_to_space_agent_not_found(db_session: Session):
    space = _make_space(db_session)
    with pytest.raises(HTTPException) as exc_info:
        agent_service.add_agent_to_space(db_session, "nonexistent", space.id)
    assert exc_info.value.status_code == 404


def test_add_agent_to_space_space_not_found(db_session: Session):
    agent = agent_service.create_agent(db_session, name="Agent")
    with pytest.raises(HTTPException) as exc_info:
        agent_service.add_agent_to_space(db_session, agent.id, "nonexistent")
    assert exc_info.value.status_code == 404


def test_remove_agent_from_space(db_session: Session):
    agent = agent_service.create_agent(db_session, name="Agent")
    space = _make_space(db_session)
    agent_service.add_agent_to_space(db_session, agent.id, space.id)
    agent_service.remove_agent_from_space(db_session, agent.id, space.id)
    refreshed = agent_service.get_agent(db_session, agent.id)
    assert len(refreshed.spaces) == 0


def test_remove_agent_from_space_not_linked(db_session: Session):
    """Removing from a space the agent is not linked to is a no-op."""
    agent = agent_service.create_agent(db_session, name="Agent")
    space = _make_space(db_session)
    # Should not raise
    agent_service.remove_agent_from_space(db_session, agent.id, space.id)


# --- Permissions ---


def test_set_permission(db_session: Session):
    agent = agent_service.create_agent(db_session, name="Agent")
    perm = agent_service.set_permission(
        db_session,
        agent_id=agent.id,
        resource_pattern="spaces/*",
        operation="read",
        grant_level="always",
    )
    assert perm.agent_id == agent.id
    assert perm.resource_pattern == "spaces/*"
    assert perm.operation == "read"
    assert perm.grant_level == "always"
    assert perm.id is not None


def test_set_permission_upsert(db_session: Session):
    agent = agent_service.create_agent(db_session, name="Agent")
    perm1 = agent_service.set_permission(
        db_session,
        agent_id=agent.id,
        resource_pattern="spaces/*",
        operation="read",
        grant_level="always",
    )
    perm2 = agent_service.set_permission(
        db_session,
        agent_id=agent.id,
        resource_pattern="spaces/*",
        operation="read",
        grant_level="approval",
    )
    assert perm1.id == perm2.id
    assert perm2.grant_level == "approval"


def test_set_permission_agent_not_found(db_session: Session):
    with pytest.raises(HTTPException) as exc_info:
        agent_service.set_permission(
            db_session,
            agent_id="nonexistent",
            resource_pattern="spaces/*",
            operation="read",
            grant_level="always",
        )
    assert exc_info.value.status_code == 404


def test_get_permissions(db_session: Session):
    agent = agent_service.create_agent(db_session, name="Agent")
    agent_service.set_permission(
        db_session,
        agent_id=agent.id,
        resource_pattern="spaces/*",
        operation="read",
        grant_level="always",
    )
    agent_service.set_permission(
        db_session,
        agent_id=agent.id,
        resource_pattern="items/*",
        operation="create",
        grant_level="approval",
    )
    perms = agent_service.get_permissions(db_session, agent.id)
    assert len(perms) == 2


def test_get_permissions_agent_not_found(db_session: Session):
    with pytest.raises(HTTPException) as exc_info:
        agent_service.get_permissions(db_session, "nonexistent")
    assert exc_info.value.status_code == 404


def test_delete_permission(db_session: Session):
    agent = agent_service.create_agent(db_session, name="Agent")
    perm = agent_service.set_permission(
        db_session,
        agent_id=agent.id,
        resource_pattern="spaces/*",
        operation="read",
        grant_level="always",
    )
    agent_service.delete_permission(db_session, perm.id)
    perms = agent_service.get_permissions(db_session, agent.id)
    assert len(perms) == 0


def test_delete_permission_not_found(db_session: Session):
    with pytest.raises(HTTPException) as exc_info:
        agent_service.delete_permission(db_session, "nonexistent-id")
    assert exc_info.value.status_code == 404
