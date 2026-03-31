import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.openloop.services import agent_service, conversation_service, space_service


def _make_agent(db: Session, name: str = "TestAgent"):
    return agent_service.create_agent(db, name=name)


def _make_space(db: Session, name: str = "Test Space", template: str = "project"):
    return space_service.create_space(db, name=name, template=template)


def test_create_conversation(db_session: Session):
    agent = _make_agent(db_session)
    conv = conversation_service.create_conversation(db_session, agent_id=agent.id, name="Chat 1")
    assert conv.name == "Chat 1"
    assert conv.agent_id == agent.id
    assert conv.status == "active"
    assert conv.space_id is None
    assert conv.id is not None


def test_create_conversation_with_space(db_session: Session):
    agent = _make_agent(db_session)
    space = _make_space(db_session)
    conv = conversation_service.create_conversation(
        db_session, agent_id=agent.id, name="Scoped", space_id=space.id
    )
    assert conv.space_id == space.id


def test_create_conversation_with_model_override(db_session: Session):
    agent = _make_agent(db_session)
    conv = conversation_service.create_conversation(
        db_session, agent_id=agent.id, name="Custom Model", model_override="opus"
    )
    assert conv.model_override == "opus"


def test_create_conversation_agent_not_found(db_session: Session):
    with pytest.raises(HTTPException) as exc_info:
        conversation_service.create_conversation(db_session, agent_id="nonexistent", name="Orphan")
    assert exc_info.value.status_code == 404


def test_create_conversation_space_not_found(db_session: Session):
    agent = _make_agent(db_session)
    with pytest.raises(HTTPException) as exc_info:
        conversation_service.create_conversation(
            db_session, agent_id=agent.id, name="Bad Space", space_id="nonexistent"
        )
    assert exc_info.value.status_code == 404


def test_get_conversation(db_session: Session):
    agent = _make_agent(db_session)
    created = conversation_service.create_conversation(
        db_session, agent_id=agent.id, name="Fetch Me"
    )
    fetched = conversation_service.get_conversation(db_session, created.id)
    assert fetched.id == created.id
    assert fetched.name == "Fetch Me"


def test_get_conversation_not_found(db_session: Session):
    with pytest.raises(HTTPException) as exc_info:
        conversation_service.get_conversation(db_session, "nonexistent-id")
    assert exc_info.value.status_code == 404


def test_list_conversations_empty(db_session: Session):
    convs = conversation_service.list_conversations(db_session)
    assert convs == []


def test_list_conversations(db_session: Session):
    agent = _make_agent(db_session)
    conversation_service.create_conversation(db_session, agent_id=agent.id, name="A")
    conversation_service.create_conversation(db_session, agent_id=agent.id, name="B")
    convs = conversation_service.list_conversations(db_session)
    assert len(convs) == 2


def test_list_conversations_filter_by_space(db_session: Session):
    agent = _make_agent(db_session)
    space = _make_space(db_session)
    conversation_service.create_conversation(
        db_session, agent_id=agent.id, name="In Space", space_id=space.id
    )
    conversation_service.create_conversation(db_session, agent_id=agent.id, name="No Space")
    convs = conversation_service.list_conversations(db_session, space_id=space.id)
    assert len(convs) == 1
    assert convs[0].name == "In Space"


def test_list_conversations_filter_by_status(db_session: Session):
    agent = _make_agent(db_session)
    conv = conversation_service.create_conversation(db_session, agent_id=agent.id, name="Active")
    conversation_service.create_conversation(db_session, agent_id=agent.id, name="Also Active")
    conversation_service.close_conversation(db_session, conv.id)
    active = conversation_service.list_conversations(db_session, status="active")
    assert len(active) == 1
    assert active[0].name == "Also Active"


def test_close_conversation(db_session: Session):
    agent = _make_agent(db_session)
    conv = conversation_service.create_conversation(db_session, agent_id=agent.id, name="Closeable")
    closed = conversation_service.close_conversation(db_session, conv.id)
    assert closed.status == "closed"
    assert closed.closed_at is not None


def test_close_conversation_not_active(db_session: Session):
    agent = _make_agent(db_session)
    conv = conversation_service.create_conversation(db_session, agent_id=agent.id, name="Closeable")
    conversation_service.close_conversation(db_session, conv.id)
    with pytest.raises(HTTPException) as exc_info:
        conversation_service.close_conversation(db_session, conv.id)
    assert exc_info.value.status_code == 409


def test_close_conversation_not_found(db_session: Session):
    with pytest.raises(HTTPException) as exc_info:
        conversation_service.close_conversation(db_session, "nonexistent-id")
    assert exc_info.value.status_code == 404


def test_reopen_conversation(db_session: Session):
    agent = _make_agent(db_session)
    conv = conversation_service.create_conversation(db_session, agent_id=agent.id, name="Reopen Me")
    conversation_service.close_conversation(db_session, conv.id)
    reopened = conversation_service.reopen_conversation(db_session, conv.id)
    assert reopened.status == "active"
    assert reopened.closed_at is None


def test_reopen_conversation_already_active(db_session: Session):
    agent = _make_agent(db_session)
    conv = conversation_service.create_conversation(
        db_session, agent_id=agent.id, name="Already Active"
    )
    with pytest.raises(HTTPException) as exc_info:
        conversation_service.reopen_conversation(db_session, conv.id)
    assert exc_info.value.status_code == 409


def test_reopen_conversation_not_found(db_session: Session):
    with pytest.raises(HTTPException) as exc_info:
        conversation_service.reopen_conversation(db_session, "nonexistent-id")
    assert exc_info.value.status_code == 404


def test_update_conversation_name(db_session: Session):
    agent = _make_agent(db_session)
    conv = conversation_service.create_conversation(db_session, agent_id=agent.id, name="Old Name")
    updated = conversation_service.update_conversation(db_session, conv.id, name="New Name")
    assert updated.name == "New Name"


def test_update_conversation_not_found(db_session: Session):
    with pytest.raises(HTTPException) as exc_info:
        conversation_service.update_conversation(db_session, "nonexistent-id", name="Nope")
    assert exc_info.value.status_code == 404


# --- Messages ---


def test_add_message(db_session: Session):
    agent = _make_agent(db_session)
    conv = conversation_service.create_conversation(db_session, agent_id=agent.id, name="Chat")
    msg = conversation_service.add_message(
        db_session, conversation_id=conv.id, role="user", content="Hello"
    )
    assert msg.conversation_id == conv.id
    assert msg.role == "user"
    assert msg.content == "Hello"
    assert msg.id is not None


def test_add_message_with_tool_calls(db_session: Session):
    agent = _make_agent(db_session)
    conv = conversation_service.create_conversation(db_session, agent_id=agent.id, name="Chat")
    msg = conversation_service.add_message(
        db_session,
        conversation_id=conv.id,
        role="assistant",
        content="Let me search...",
        tool_calls={"tool": "search", "input": {"query": "test"}},
    )
    assert msg.tool_calls == {"tool": "search", "input": {"query": "test"}}


def test_add_message_conversation_not_found(db_session: Session):
    with pytest.raises(HTTPException) as exc_info:
        conversation_service.add_message(
            db_session, conversation_id="nonexistent", role="user", content="Hello"
        )
    assert exc_info.value.status_code == 404


def test_get_messages(db_session: Session):
    agent = _make_agent(db_session)
    conv = conversation_service.create_conversation(db_session, agent_id=agent.id, name="Chat")
    conversation_service.add_message(db_session, conversation_id=conv.id, role="user", content="Hi")
    conversation_service.add_message(
        db_session, conversation_id=conv.id, role="assistant", content="Hello!"
    )
    msgs = conversation_service.get_messages(db_session, conv.id)
    assert len(msgs) == 2
    assert msgs[0].role == "user"
    assert msgs[1].role == "assistant"


def test_get_messages_empty(db_session: Session):
    agent = _make_agent(db_session)
    conv = conversation_service.create_conversation(
        db_session, agent_id=agent.id, name="Empty Chat"
    )
    msgs = conversation_service.get_messages(db_session, conv.id)
    assert msgs == []


def test_get_messages_conversation_not_found(db_session: Session):
    with pytest.raises(HTTPException) as exc_info:
        conversation_service.get_messages(db_session, "nonexistent")
    assert exc_info.value.status_code == 404


# --- Summaries ---


def test_add_summary(db_session: Session):
    agent = _make_agent(db_session)
    conv = conversation_service.create_conversation(db_session, agent_id=agent.id, name="Chat")
    summary = conversation_service.add_summary(
        db_session, conversation_id=conv.id, summary="We discussed testing."
    )
    assert summary.conversation_id == conv.id
    assert summary.summary == "We discussed testing."
    assert summary.is_checkpoint is False
    assert summary.id is not None


def test_add_summary_with_decisions(db_session: Session):
    agent = _make_agent(db_session)
    conv = conversation_service.create_conversation(db_session, agent_id=agent.id, name="Chat")
    summary = conversation_service.add_summary(
        db_session,
        conversation_id=conv.id,
        summary="Decisions made",
        decisions=["Use pytest", "Use SQLite"],
        open_questions=["What about CI?"],
    )
    assert summary.decisions == ["Use pytest", "Use SQLite"]
    assert summary.open_questions == ["What about CI?"]


def test_add_summary_checkpoint(db_session: Session):
    agent = _make_agent(db_session)
    conv = conversation_service.create_conversation(db_session, agent_id=agent.id, name="Chat")
    summary = conversation_service.add_summary(
        db_session, conversation_id=conv.id, summary="Checkpoint", is_checkpoint=True
    )
    assert summary.is_checkpoint is True


def test_add_summary_conversation_not_found(db_session: Session):
    with pytest.raises(HTTPException) as exc_info:
        conversation_service.add_summary(
            db_session, conversation_id="nonexistent", summary="No conv"
        )
    assert exc_info.value.status_code == 404


def test_add_summary_inherits_space_id(db_session: Session):
    agent = _make_agent(db_session)
    space = _make_space(db_session)
    conv = conversation_service.create_conversation(
        db_session, agent_id=agent.id, name="Scoped", space_id=space.id
    )
    summary = conversation_service.add_summary(
        db_session, conversation_id=conv.id, summary="Space-scoped summary"
    )
    assert summary.space_id == space.id


def test_get_summaries(db_session: Session):
    agent = _make_agent(db_session)
    conv = conversation_service.create_conversation(db_session, agent_id=agent.id, name="Chat")
    conversation_service.add_summary(db_session, conversation_id=conv.id, summary="First")
    conversation_service.add_summary(db_session, conversation_id=conv.id, summary="Second")
    summaries = conversation_service.get_summaries(db_session, conversation_id=conv.id)
    assert len(summaries) == 2
