"""Search routes — full-text search across the system."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.openloop.api.schemas.search import SearchResponse, SearchResultItem
from backend.openloop.database import get_db
from backend.openloop.services import search_service

router = APIRouter(prefix="/api/v1/search", tags=["search"])


@router.get("", response_model=SearchResponse)
def search(
    q: str = Query(..., min_length=1, description="Search query"),
    space_id: str | None = Query(None, description="Filter by space"),
    conversation_id: str | None = Query(
        None, description="Filter message search to a specific conversation"
    ),
    type: str | None = Query(
        None,
        description="Filter by type: messages, summaries, memory, documents, items",
    ),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> SearchResponse:
    """Full-text search across conversations, summaries, memory, documents, and items."""
    # Fetch extra rows to satisfy offset, then slice
    fetch_limit = limit + offset
    if type:
        # Single-type search
        results: dict[str, list] = {}
        if type == "messages":
            results["messages"] = search_service.search_messages(
                db, q, space_id=space_id, conversation_id=conversation_id, limit=fetch_limit
            )
        elif type == "summaries":
            results["summaries"] = search_service.search_summaries(
                db, q, space_id=space_id, limit=fetch_limit
            )
        elif type == "memory":
            results["memory"] = search_service.search_memory(db, q, limit=fetch_limit)
        elif type == "documents":
            results["documents"] = search_service.search_documents(
                db, q, space_id=space_id, limit=fetch_limit
            )
        elif type == "items":
            results["items"] = search_service.search_items(
                db, q, space_id=space_id, limit=fetch_limit
            )
        else:
            results = {}
    else:
        results = search_service.search_all(db, q, space_id=space_id, limit=fetch_limit)

    # Convert raw dicts to pydantic models, applying offset
    typed_results: dict[str, list[SearchResultItem]] = {}
    total = 0
    for key, items in results.items():
        typed_results[key] = [SearchResultItem(**item) for item in items[offset:]]
        total += len(typed_results[key])

    return SearchResponse(query=q, total_count=total, results=typed_results)


@router.post("/rebuild", status_code=200)
def rebuild_indexes(db: Session = Depends(get_db)) -> dict[str, str]:
    """Rebuild all FTS5 indexes from source tables."""
    search_service.rebuild_fts_indexes(db)
    return {"status": "ok", "message": "FTS indexes rebuilt"}
