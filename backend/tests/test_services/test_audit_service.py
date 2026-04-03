from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from backend.openloop.services import agent_service, audit_service, conversation_service, space_service


def _make_agent(db: Session, name: str = "AuditTestAgent") -> str:
    agent = agent_service.create_agent(db, name=name)
    return agent.id


def _make_conversation(db: Session, agent_id: str) -> str:
    space = space_service.create_space(db, name="AuditSpace", template="project")
    conv = conversation_service.create_conversation(
        db, agent_id=agent_id, name="AuditConv", space_id=space.id
    )
    return conv.id


# ---------------------------------------------------------------------------
# log_tool_call
# ---------------------------------------------------------------------------


def test_log_tool_call_basic(db_session: Session):
    agent_id = _make_agent(db_session)
    entry = audit_service.log_tool_call(
        db_session,
        agent_id=agent_id,
        tool_name="Read",
        action="allow",
    )
    assert entry.id is not None
    assert entry.agent_id == agent_id
    assert entry.tool_name == "Read"
    assert entry.action == "allow"
    assert entry.conversation_id is None
    assert entry.background_task_id is None
    assert entry.resource_id is None
    assert entry.input_summary is None
    assert entry.timestamp is not None


def test_log_tool_call_full(db_session: Session):
    agent_id = _make_agent(db_session)
    conv_id = _make_conversation(db_session, agent_id)
    entry = audit_service.log_tool_call(
        db_session,
        agent_id=agent_id,
        conversation_id=conv_id,
        background_task_id=None,
        tool_name="Write",
        action="deny",
        resource_id="/some/file.txt",
        input_summary="file_path: /some/file.txt, content: hello...",
    )
    assert entry.conversation_id == conv_id
    assert entry.resource_id == "/some/file.txt"
    assert entry.input_summary == "file_path: /some/file.txt, content: hello..."


# ---------------------------------------------------------------------------
# log_action
# ---------------------------------------------------------------------------


def test_log_action(db_session: Session):
    agent_id = _make_agent(db_session)
    entry = audit_service.log_action(
        db_session,
        agent_id=agent_id,
        action="steering_applied",
    )
    assert entry.tool_name == "system"
    assert entry.action == "steering_applied"


# ---------------------------------------------------------------------------
# query_log
# ---------------------------------------------------------------------------


def test_query_log_empty(db_session: Session):
    results = audit_service.query_log(db_session)
    assert results == []


def test_query_log_returns_entries(db_session: Session):
    agent_id = _make_agent(db_session)
    audit_service.log_tool_call(
        db_session, agent_id=agent_id, tool_name="Read", action="allow"
    )
    audit_service.log_tool_call(
        db_session, agent_id=agent_id, tool_name="Write", action="deny"
    )
    results = audit_service.query_log(db_session)
    assert len(results) == 2


def test_query_log_filter_by_agent_id(db_session: Session):
    agent1 = _make_agent(db_session, "Agent1")
    agent2 = _make_agent(db_session, "Agent2")
    audit_service.log_tool_call(
        db_session, agent_id=agent1, tool_name="Read", action="allow"
    )
    audit_service.log_tool_call(
        db_session, agent_id=agent2, tool_name="Write", action="deny"
    )
    results = audit_service.query_log(db_session, agent_id=agent1)
    assert len(results) == 1
    assert results[0].agent_id == agent1


def test_query_log_filter_by_conversation_id(db_session: Session):
    agent_id = _make_agent(db_session)
    conv_id = _make_conversation(db_session, agent_id)
    audit_service.log_tool_call(
        db_session,
        agent_id=agent_id,
        conversation_id=conv_id,
        tool_name="Read",
        action="allow",
    )
    audit_service.log_tool_call(
        db_session, agent_id=agent_id, tool_name="Write", action="deny"
    )
    results = audit_service.query_log(db_session, conversation_id=conv_id)
    assert len(results) == 1
    assert results[0].conversation_id == conv_id


def test_query_log_filter_by_tool_name(db_session: Session):
    agent_id = _make_agent(db_session)
    audit_service.log_tool_call(
        db_session, agent_id=agent_id, tool_name="Read", action="allow"
    )
    audit_service.log_tool_call(
        db_session, agent_id=agent_id, tool_name="Write", action="deny"
    )
    audit_service.log_tool_call(
        db_session, agent_id=agent_id, tool_name="Read", action="deny"
    )
    results = audit_service.query_log(db_session, tool_name="Read")
    assert len(results) == 2


def test_query_log_filter_by_time_range(db_session: Session):
    agent_id = _make_agent(db_session)
    # Create entries — timestamps auto-set to utcnow
    audit_service.log_tool_call(
        db_session, agent_id=agent_id, tool_name="Read", action="allow"
    )
    now = datetime.now(UTC).replace(tzinfo=None)
    results_after = audit_service.query_log(
        db_session, after=now - timedelta(minutes=1)
    )
    assert len(results_after) == 1

    results_before = audit_service.query_log(
        db_session, before=now - timedelta(minutes=1)
    )
    assert len(results_before) == 0


def test_query_log_limit_and_offset(db_session: Session):
    agent_id = _make_agent(db_session)
    for i in range(5):
        audit_service.log_tool_call(
            db_session, agent_id=agent_id, tool_name=f"Tool{i}", action="allow"
        )
    results = audit_service.query_log(db_session, limit=2)
    assert len(results) == 2

    results_offset = audit_service.query_log(db_session, limit=2, offset=3)
    assert len(results_offset) == 2


def test_query_log_ordered_by_timestamp_desc(db_session: Session):
    agent_id = _make_agent(db_session)
    audit_service.log_tool_call(
        db_session, agent_id=agent_id, tool_name="First", action="allow"
    )
    audit_service.log_tool_call(
        db_session, agent_id=agent_id, tool_name="Second", action="allow"
    )
    results = audit_service.query_log(db_session)
    # Most recent first
    assert results[0].tool_name == "Second"
    assert results[1].tool_name == "First"
