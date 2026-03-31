import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.openloop.services import memory_service


def test_create_entry(db_session: Session):
    entry = memory_service.create_entry(
        db_session, namespace="global", key="user_name", value="Brad"
    )
    assert entry.namespace == "global"
    assert entry.key == "user_name"
    assert entry.value == "Brad"
    assert entry.source == "user"
    assert entry.id is not None


def test_create_entry_with_tags(db_session: Session):
    entry = memory_service.create_entry(
        db_session, namespace="global", key="prefs", value="dark mode", tags=["ui", "settings"]
    )
    assert entry.tags == ["ui", "settings"]


def test_create_entry_with_source(db_session: Session):
    entry = memory_service.create_entry(
        db_session, namespace="global", key="fact", value="something", source="agent"
    )
    assert entry.source == "agent"


def test_create_entry_duplicate(db_session: Session):
    memory_service.create_entry(db_session, namespace="global", key="dup", value="first")
    with pytest.raises(HTTPException) as exc_info:
        memory_service.create_entry(db_session, namespace="global", key="dup", value="second")
    assert exc_info.value.status_code == 409


def test_create_entry_same_key_different_namespace(db_session: Session):
    memory_service.create_entry(db_session, namespace="ns1", key="key", value="v1")
    entry = memory_service.create_entry(db_session, namespace="ns2", key="key", value="v2")
    assert entry.namespace == "ns2"


def test_get_entry(db_session: Session):
    created = memory_service.create_entry(
        db_session, namespace="global", key="fetch_me", value="data"
    )
    fetched = memory_service.get_entry(db_session, created.id)
    assert fetched.id == created.id
    assert fetched.key == "fetch_me"


def test_get_entry_not_found(db_session: Session):
    with pytest.raises(HTTPException) as exc_info:
        memory_service.get_entry(db_session, "nonexistent-id")
    assert exc_info.value.status_code == 404


def test_list_entries_empty(db_session: Session):
    entries = memory_service.list_entries(db_session)
    assert entries == []


def test_list_entries(db_session: Session):
    memory_service.create_entry(db_session, namespace="global", key="a", value="1")
    memory_service.create_entry(db_session, namespace="global", key="b", value="2")
    entries = memory_service.list_entries(db_session)
    assert len(entries) == 2


def test_list_entries_filter_by_namespace(db_session: Session):
    memory_service.create_entry(db_session, namespace="ns1", key="a", value="1")
    memory_service.create_entry(db_session, namespace="ns2", key="b", value="2")
    entries = memory_service.list_entries(db_session, namespace="ns1")
    assert len(entries) == 1
    assert entries[0].key == "a"


def test_list_entries_search_by_key(db_session: Session):
    memory_service.create_entry(db_session, namespace="global", key="user_name", value="Brad")
    memory_service.create_entry(db_session, namespace="global", key="color", value="blue")
    entries = memory_service.list_entries(db_session, search="user")
    assert len(entries) == 1
    assert entries[0].key == "user_name"


def test_list_entries_search_by_value(db_session: Session):
    memory_service.create_entry(db_session, namespace="global", key="name", value="Bradley")
    memory_service.create_entry(db_session, namespace="global", key="pet", value="cat")
    entries = memory_service.list_entries(db_session, search="Bradley")
    assert len(entries) == 1
    assert entries[0].value == "Bradley"


def test_update_entry_value(db_session: Session):
    entry = memory_service.create_entry(db_session, namespace="global", key="mutable", value="old")
    updated = memory_service.update_entry(db_session, entry.id, value="new")
    assert updated.value == "new"


def test_update_entry_tags(db_session: Session):
    entry = memory_service.create_entry(
        db_session, namespace="global", key="tagged", value="data", tags=["old"]
    )
    updated = memory_service.update_entry(db_session, entry.id, tags=["new", "updated"])
    assert updated.tags == ["new", "updated"]


def test_update_entry_not_found(db_session: Session):
    with pytest.raises(HTTPException) as exc_info:
        memory_service.update_entry(db_session, "nonexistent-id", value="nope")
    assert exc_info.value.status_code == 404


def test_update_entry_no_changes(db_session: Session):
    entry = memory_service.create_entry(db_session, namespace="global", key="noop", value="same")
    updated = memory_service.update_entry(db_session, entry.id)
    assert updated.value == "same"


def test_upsert_entry_creates(db_session: Session):
    entry = memory_service.upsert_entry(
        db_session, namespace="global", key="new_key", value="created"
    )
    assert entry.value == "created"
    assert entry.id is not None


def test_upsert_entry_updates(db_session: Session):
    created = memory_service.create_entry(
        db_session, namespace="global", key="upsert_key", value="original"
    )
    updated = memory_service.upsert_entry(
        db_session, namespace="global", key="upsert_key", value="updated"
    )
    assert updated.id == created.id
    assert updated.value == "updated"


def test_upsert_entry_updates_tags(db_session: Session):
    memory_service.create_entry(
        db_session, namespace="global", key="upsert_tags", value="v", tags=["old"]
    )
    updated = memory_service.upsert_entry(
        db_session, namespace="global", key="upsert_tags", value="v2", tags=["new"]
    )
    assert updated.tags == ["new"]


def test_delete_entry(db_session: Session):
    entry = memory_service.create_entry(
        db_session, namespace="global", key="delete_me", value="gone"
    )
    memory_service.delete_entry(db_session, entry.id)
    with pytest.raises(HTTPException) as exc_info:
        memory_service.get_entry(db_session, entry.id)
    assert exc_info.value.status_code == 404


def test_delete_entry_not_found(db_session: Session):
    with pytest.raises(HTTPException) as exc_info:
        memory_service.delete_entry(db_session, "nonexistent-id")
    assert exc_info.value.status_code == 404
