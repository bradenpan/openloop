from pydantic import BaseModel

__all__ = [
    "TokenStatsResponse",
    "TokenStatsBucket",
    "DailyTokenStatsResponse",
    "DailyTokenBucket",
]


class TokenStatsBucket(BaseModel):
    """A single bucket of aggregated token usage."""
    agent_id: str | None = None
    agent_name: str | None = None
    space_id: str | None = None
    space_name: str | None = None
    total_input_tokens: int
    total_output_tokens: int
    total_tokens: int
    message_count: int


class TokenStatsResponse(BaseModel):
    """Aggregated token usage stats."""
    period: str
    buckets: list[TokenStatsBucket]
    total_input_tokens: int
    total_output_tokens: int
    total_tokens: int


class DailyTokenBucket(BaseModel):
    """Token usage for a single day."""
    date: str  # YYYY-MM-DD
    total_input_tokens: int
    total_output_tokens: int
    total_tokens: int


class DailyTokenStatsResponse(BaseModel):
    """Daily-bucketed token usage for sparkline rendering."""
    days: int
    buckets: list[DailyTokenBucket]
    total_tokens: int
