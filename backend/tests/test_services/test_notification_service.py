import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.openloop.services import (
    agent_service,
    conversation_service,
    notification_service,
    space_service,
)


def test_create_notification(db_session: Session):
    notif = notification_service.create_notification(db_session, type="system", title="Hello")
    assert notif.type == "system"
    assert notif.title == "Hello"
    assert notif.is_read is False
    assert notif.id is not None


def test_create_notification_with_body(db_session: Session):
    notif = notification_service.create_notification(
        db_session, type="task_completed", title="Done", body="Task X finished"
    )
    assert notif.body == "Task X finished"


def test_create_notification_with_ids(db_session: Session):
    space = space_service.create_space(db_session, name="Notif Space", template="project")
    agent = agent_service.create_agent(db_session, name="NotifAgent")
    conv = conversation_service.create_conversation(
        db_session, space_id=space.id, agent_id=agent.id, name="Notif Conv"
    )
    notif = notification_service.create_notification(
        db_session,
        type="approval_request",
        title="Approve",
        space_id=space.id,
        conversation_id=conv.id,
    )
    assert notif.space_id == space.id
    assert notif.conversation_id == conv.id


def test_list_notifications_empty(db_session: Session):
    notifs = notification_service.list_notifications(db_session)
    assert notifs == []


def test_list_notifications(db_session: Session):
    notification_service.create_notification(db_session, type="system", title="A")
    notification_service.create_notification(db_session, type="system", title="B")
    notifs = notification_service.list_notifications(db_session)
    assert len(notifs) == 2


def test_list_notifications_filter_unread(db_session: Session):
    n1 = notification_service.create_notification(db_session, type="system", title="Read")
    notification_service.create_notification(db_session, type="system", title="Unread")
    notification_service.mark_read(db_session, n1.id)
    unread = notification_service.list_notifications(db_session, is_read=False)
    assert len(unread) == 1
    assert unread[0].title == "Unread"


def test_list_notifications_filter_read(db_session: Session):
    n1 = notification_service.create_notification(db_session, type="system", title="Read")
    notification_service.create_notification(db_session, type="system", title="Unread")
    notification_service.mark_read(db_session, n1.id)
    read = notification_service.list_notifications(db_session, is_read=True)
    assert len(read) == 1
    assert read[0].title == "Read"


def test_mark_read(db_session: Session):
    notif = notification_service.create_notification(db_session, type="system", title="Mark Me")
    assert notif.is_read is False
    marked = notification_service.mark_read(db_session, notif.id)
    assert marked.is_read is True


def test_mark_read_not_found(db_session: Session):
    with pytest.raises(HTTPException) as exc_info:
        notification_service.mark_read(db_session, "nonexistent-id")
    assert exc_info.value.status_code == 404


def test_mark_read_idempotent(db_session: Session):
    notif = notification_service.create_notification(db_session, type="system", title="Twice")
    notification_service.mark_read(db_session, notif.id)
    marked_again = notification_service.mark_read(db_session, notif.id)
    assert marked_again.is_read is True


def test_unread_count_zero(db_session: Session):
    count = notification_service.unread_count(db_session)
    assert count == 0


def test_unread_count(db_session: Session):
    notification_service.create_notification(db_session, type="system", title="A")
    notification_service.create_notification(db_session, type="system", title="B")
    notification_service.create_notification(db_session, type="system", title="C")
    count = notification_service.unread_count(db_session)
    assert count == 3


def test_unread_count_after_marking(db_session: Session):
    n1 = notification_service.create_notification(db_session, type="system", title="A")
    notification_service.create_notification(db_session, type="system", title="B")
    notification_service.mark_read(db_session, n1.id)
    count = notification_service.unread_count(db_session)
    assert count == 1
