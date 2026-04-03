from datetime import datetime

from pydantic import BaseModel, ConfigDict

__all__ = [
    "MemoryCreate",
    "MemoryUpdate",
    "MemoryResponse",
    "MemoryHealthResponse",
    "ConsolidationMerge",
    "ConsolidationContradiction",
    "ConsolidationStale",
    "ConsolidationReportResponse",
    "ConsolidationApplyRequest",
    "ConsolidationApplyResponse",
]


class MemoryCreate(BaseModel):
    namespace: str
    key: str
    value: str
    tags: list[str] | None = None
    source: str = "user"


class MemoryUpdate(BaseModel):
    value: str | None = None
    tags: list[str] | None = None
    source: str | None = None
    importance: float | None = None
    category: str | None = None


class MemoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    namespace: str
    key: str
    value: str
    tags: list | None
    source: str
    importance: float
    access_count: int
    last_accessed: datetime | None
    valid_from: datetime
    valid_until: datetime | None
    archived_at: datetime | None
    category: str | None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Phase 7.1a: Memory lifecycle schemas
# ---------------------------------------------------------------------------


class MemoryHealthResponse(BaseModel):
    active_facts: int
    archived_facts: int
    active_rules: int
    inactive_rules: int


class ConsolidationMerge(BaseModel):
    source_ids: list[str]
    merged_value: str
    reason: str | None = None


class ConsolidationContradiction(BaseModel):
    ids: list[str]
    description: str | None = None


class ConsolidationStale(BaseModel):
    id: str
    reason: str | None = None


class ConsolidationReportResponse(BaseModel):
    merges: list[ConsolidationMerge]
    contradictions: list[ConsolidationContradiction]
    stale: list[ConsolidationStale]


class ConsolidationApplyRequest(BaseModel):
    merges: list[ConsolidationMerge] | None = None
    stale: list[ConsolidationStale] | None = None


class ConsolidationApplyResponse(BaseModel):
    merged: int
    archived: int
