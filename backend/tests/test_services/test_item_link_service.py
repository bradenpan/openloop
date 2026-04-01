"""Tests for item_link_service."""

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.openloop.services import item_link_service, item_service, space_service


def _make_space(db: Session, name: str = "Test Space", template: str = "project"):
    return space_service.create_space(db, name=name, template=template)


def _make_item(db: Session, space_id: str, title: str = "Item", **kwargs):
    return item_service.create_item(db, space_id=space_id, title=title, **kwargs)


# ---- create_link ----


def test_create_link(db_session: Session):
    space = _make_space(db_session)
    item_a = _make_item(db_session, space.id, title="A")
    item_b = _make_item(db_session, space.id, title="B")

    link = item_link_service.create_link(
        db_session, source_item_id=item_a.id, target_item_id=item_b.id
    )
    assert link.source_item_id == item_a.id
    assert link.target_item_id == item_b.id
    assert link.link_type == "related_to"
    assert link.id is not None


def test_create_link_custom_type(db_session: Session):
    space = _make_space(db_session)
    item_a = _make_item(db_session, space.id, title="A")
    item_b = _make_item(db_session, space.id, title="B")

    link = item_link_service.create_link(
        db_session,
        source_item_id=item_a.id,
        target_item_id=item_b.id,
        link_type="blocks",
    )
    assert link.link_type == "blocks"


def test_create_link_duplicate_raises_409(db_session: Session):
    space = _make_space(db_session)
    item_a = _make_item(db_session, space.id, title="A")
    item_b = _make_item(db_session, space.id, title="B")

    item_link_service.create_link(
        db_session, source_item_id=item_a.id, target_item_id=item_b.id
    )
    with pytest.raises(HTTPException) as exc_info:
        item_link_service.create_link(
            db_session, source_item_id=item_a.id, target_item_id=item_b.id
        )
    assert exc_info.value.status_code == 409


def test_create_link_self_raises_422(db_session: Session):
    space = _make_space(db_session)
    item = _make_item(db_session, space.id, title="Self")

    with pytest.raises(HTTPException) as exc_info:
        item_link_service.create_link(
            db_session, source_item_id=item.id, target_item_id=item.id
        )
    assert exc_info.value.status_code == 422


def test_create_link_source_not_found(db_session: Session):
    space = _make_space(db_session)
    item = _make_item(db_session, space.id, title="Real")

    with pytest.raises(HTTPException) as exc_info:
        item_link_service.create_link(
            db_session, source_item_id="nonexistent", target_item_id=item.id
        )
    assert exc_info.value.status_code == 404


def test_create_link_target_not_found(db_session: Session):
    space = _make_space(db_session)
    item = _make_item(db_session, space.id, title="Real")

    with pytest.raises(HTTPException) as exc_info:
        item_link_service.create_link(
            db_session, source_item_id=item.id, target_item_id="nonexistent"
        )
    assert exc_info.value.status_code == 404


# ---- delete_link ----


def test_delete_link(db_session: Session):
    space = _make_space(db_session)
    item_a = _make_item(db_session, space.id, title="A")
    item_b = _make_item(db_session, space.id, title="B")

    link = item_link_service.create_link(
        db_session, source_item_id=item_a.id, target_item_id=item_b.id
    )
    item_link_service.delete_link(db_session, link.id)

    # Verify gone
    links = item_link_service.list_links_for_item(db_session, item_a.id)
    assert len(links) == 0


def test_delete_link_not_found(db_session: Session):
    with pytest.raises(HTTPException) as exc_info:
        item_link_service.delete_link(db_session, "nonexistent")
    assert exc_info.value.status_code == 404


# ---- list_links_for_item ----


def test_list_links_bidirectional(db_session: Session):
    """Links are visible from both source and target item."""
    space = _make_space(db_session)
    item_a = _make_item(db_session, space.id, title="A")
    item_b = _make_item(db_session, space.id, title="B")

    item_link_service.create_link(
        db_session, source_item_id=item_a.id, target_item_id=item_b.id
    )

    # Source sees the link
    links_a = item_link_service.list_links_for_item(db_session, item_a.id)
    assert len(links_a) == 1

    # Target also sees the link
    links_b = item_link_service.list_links_for_item(db_session, item_b.id)
    assert len(links_b) == 1

    # Same link
    assert links_a[0].id == links_b[0].id


def test_list_links_empty(db_session: Session):
    space = _make_space(db_session)
    item = _make_item(db_session, space.id, title="Alone")
    links = item_link_service.list_links_for_item(db_session, item.id)
    assert links == []


def test_list_links_filter_by_type(db_session: Session):
    space = _make_space(db_session)
    item_a = _make_item(db_session, space.id, title="A")
    item_b = _make_item(db_session, space.id, title="B")
    item_c = _make_item(db_session, space.id, title="C")

    item_link_service.create_link(
        db_session,
        source_item_id=item_a.id,
        target_item_id=item_b.id,
        link_type="related_to",
    )
    item_link_service.create_link(
        db_session,
        source_item_id=item_a.id,
        target_item_id=item_c.id,
        link_type="blocks",
    )

    all_links = item_link_service.list_links_for_item(db_session, item_a.id)
    assert len(all_links) == 2

    related_only = item_link_service.list_links_for_item(
        db_session, item_a.id, link_type="related_to"
    )
    assert len(related_only) == 1
    assert related_only[0].target_item_id == item_b.id

    blocks_only = item_link_service.list_links_for_item(
        db_session, item_a.id, link_type="blocks"
    )
    assert len(blocks_only) == 1
    assert blocks_only[0].target_item_id == item_c.id
