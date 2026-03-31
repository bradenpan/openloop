"""Search schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

__all__ = [
    "SearchResultItem",
    "SearchResponse",
]


class SearchResultItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    type: str
    title: str
    excerpt: str
    space_id: str | None = None
    space_name: str | None = None
    relevance_score: float
    created_at: datetime
    source_id: str


class SearchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    query: str
    total_count: int
    results: dict[str, list[SearchResultItem]]
