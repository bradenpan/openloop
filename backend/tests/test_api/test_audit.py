from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.openloop.services import agent_service, audit_service, conversation_service, space_service


def _make_agent(db: Session, name: str = "AuditRouteAgent") -> str:
    agent = agent_service.create_agent(db, name=name)
    return agent.id


def _make_audit_entry(db: Session, agent_id: str, tool_name: str = "Read", action: str = "allow"):
    return audit_service.log_tool_call(
        db, agent_id=agent_id, tool_name=tool_name, action=action
    )


# ---------------------------------------------------------------------------
# GET /api/v1/audit-log
# ---------------------------------------------------------------------------


def test_list_audit_log_empty(client: TestClient):
    resp = client.get("/api/v1/audit-log")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_audit_log(client: TestClient, db_session: Session):
    agent_id = _make_agent(db_session)
    _make_audit_entry(db_session, agent_id, "Read", "allow")
    _make_audit_entry(db_session, agent_id, "Write", "deny")
    resp = client.get("/api/v1/audit-log")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    # Should have standard fields
    assert "id" in data[0]
    assert "tool_name" in data[0]
    assert "action" in data[0]
    assert "timestamp" in data[0]


def test_list_audit_log_filter_by_agent_id(client: TestClient, db_session: Session):
    agent1 = _make_agent(db_session, "AuditAgent1")
    agent2 = _make_agent(db_session, "AuditAgent2")
    _make_audit_entry(db_session, agent1, "Read", "allow")
    _make_audit_entry(db_session, agent2, "Write", "deny")
    resp = client.get("/api/v1/audit-log", params={"agent_id": agent1})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["agent_id"] == agent1


def test_list_audit_log_filter_by_tool_name(client: TestClient, db_session: Session):
    agent_id = _make_agent(db_session)
    _make_audit_entry(db_session, agent_id, "Read", "allow")
    _make_audit_entry(db_session, agent_id, "Write", "deny")
    _make_audit_entry(db_session, agent_id, "Read", "deny")
    resp = client.get("/api/v1/audit-log", params={"tool_name": "Write"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["tool_name"] == "Write"


def test_list_audit_log_filter_by_conversation_id(client: TestClient, db_session: Session):
    agent_id = _make_agent(db_session)
    space = space_service.create_space(db_session, name="AuditRouteSpace", template="project")
    conv = conversation_service.create_conversation(
        db_session, agent_id=agent_id, name="AuditRouteConv", space_id=space.id
    )
    audit_service.log_tool_call(
        db_session,
        agent_id=agent_id,
        conversation_id=conv.id,
        tool_name="Read",
        action="allow",
    )
    _make_audit_entry(db_session, agent_id, "Write", "deny")
    resp = client.get("/api/v1/audit-log", params={"conversation_id": conv.id})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["conversation_id"] == conv.id


def test_list_audit_log_pagination(client: TestClient, db_session: Session):
    agent_id = _make_agent(db_session)
    for i in range(5):
        _make_audit_entry(db_session, agent_id, f"Tool{i}", "allow")
    resp = client.get("/api/v1/audit-log", params={"limit": 2, "offset": 0})
    assert resp.status_code == 200
    assert len(resp.json()) == 2

    resp2 = client.get("/api/v1/audit-log", params={"limit": 2, "offset": 3})
    assert resp2.status_code == 200
    assert len(resp2.json()) == 2


def test_list_audit_log_response_schema(client: TestClient, db_session: Session):
    agent_id = _make_agent(db_session)
    audit_service.log_tool_call(
        db_session,
        agent_id=agent_id,
        tool_name="Bash",
        action="allow",
        resource_id="bash",
        input_summary="command: ls -la",
    )
    resp = client.get("/api/v1/audit-log")
    assert resp.status_code == 200
    entry = resp.json()[0]
    assert entry["tool_name"] == "Bash"
    assert entry["action"] == "allow"
    assert entry["resource_id"] == "bash"
    assert entry["input_summary"] == "command: ls -la"
    assert entry["agent_id"] == agent_id
    assert entry["conversation_id"] is None
    assert entry["background_task_id"] is None
