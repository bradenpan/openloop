from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.openloop.db.models import Item, ItemLink


def create_link(
    db: Session,
    *,
    source_item_id: str,
    target_item_id: str,
    link_type: str = "related_to",
) -> ItemLink:
    """Create a link between two items."""
    # Verify both items exist
    source = db.query(Item).filter(Item.id == source_item_id).first()
    if not source:
        raise HTTPException(status_code=404, detail="Source item not found")
    target = db.query(Item).filter(Item.id == target_item_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Target item not found")

    if source_item_id == target_item_id:
        raise HTTPException(status_code=422, detail="Cannot link an item to itself")

    # Check for existing link
    existing = (
        db.query(ItemLink)
        .filter(
            ItemLink.source_item_id == source_item_id,
            ItemLink.target_item_id == target_item_id,
            ItemLink.link_type == link_type,
        )
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="Link already exists")

    link = ItemLink(
        source_item_id=source_item_id,
        target_item_id=target_item_id,
        link_type=link_type,
    )
    db.add(link)
    db.commit()
    db.refresh(link)
    return link


def delete_link(db: Session, link_id: str) -> None:
    """Delete an item link by ID."""
    link = db.query(ItemLink).filter(ItemLink.id == link_id).first()
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")
    db.delete(link)
    db.commit()


def list_links_for_item(
    db: Session,
    item_id: str,
    *,
    link_type: str | None = None,
) -> list[ItemLink]:
    """List all links where item is source OR target (bidirectional)."""
    query = db.query(ItemLink).filter(
        (ItemLink.source_item_id == item_id) | (ItemLink.target_item_id == item_id)
    )
    if link_type:
        query = query.filter(ItemLink.link_type == link_type)
    return query.order_by(ItemLink.created_at.desc()).all()
