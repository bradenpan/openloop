"""Token usage stats API."""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.openloop.api.schemas.stats import (
    DailyTokenBucket,
    DailyTokenStatsResponse,
    TokenStatsBucket,
    TokenStatsResponse,
)
from backend.openloop.database import get_db
from backend.openloop.db.models import Agent, Conversation, ConversationMessage, Space

router = APIRouter(prefix="/api/v1/stats", tags=["stats"])

_PERIOD_HOURS = {
    "24h": 24,
    "7d": 7 * 24,
    "30d": 30 * 24,
}


@router.get("/tokens", response_model=TokenStatsResponse)
def get_token_stats(
    db: Session = Depends(get_db),
    agent_id: str | None = Query(None),
    space_id: str | None = Query(None),
    period: str = Query("24h"),
) -> TokenStatsResponse:
    """Return aggregated token usage, optionally filtered by agent, space, period."""
    hours = _PERIOD_HOURS.get(period, 24)
    cutoff = datetime.now(UTC) - timedelta(hours=hours)

    # Base query: messages that have token data
    q = (
        db.query(
            Conversation.agent_id,
            Conversation.space_id,
            func.coalesce(func.sum(ConversationMessage.input_tokens), 0).label("total_input"),
            func.coalesce(func.sum(ConversationMessage.output_tokens), 0).label("total_output"),
            func.count(ConversationMessage.id).label("msg_count"),
        )
        .join(Conversation, ConversationMessage.conversation_id == Conversation.id)
        .filter(
            ConversationMessage.created_at >= cutoff,
            (ConversationMessage.input_tokens.isnot(None))
            | (ConversationMessage.output_tokens.isnot(None)),
        )
    )

    if agent_id:
        q = q.filter(Conversation.agent_id == agent_id)
    if space_id:
        q = q.filter(Conversation.space_id == space_id)

    rows = q.group_by(Conversation.agent_id, Conversation.space_id).all()

    # Resolve names for display
    agent_names: dict[str, str] = {}
    space_names: dict[str, str] = {}

    agent_ids = {r[0] for r in rows if r[0]}
    space_ids = {r[1] for r in rows if r[1]}

    if agent_ids:
        for agent in db.query(Agent).filter(Agent.id.in_(agent_ids)).all():
            agent_names[agent.id] = agent.name
    if space_ids:
        for space in db.query(Space).filter(Space.id.in_(space_ids)).all():
            space_names[space.id] = space.name

    buckets: list[TokenStatsBucket] = []
    grand_input = 0
    grand_output = 0

    for row_agent_id, row_space_id, total_input, total_output, msg_count in rows:
        total_input = int(total_input)
        total_output = int(total_output)
        buckets.append(
            TokenStatsBucket(
                agent_id=row_agent_id,
                agent_name=agent_names.get(row_agent_id),
                space_id=row_space_id,
                space_name=space_names.get(row_space_id) if row_space_id else None,
                total_input_tokens=total_input,
                total_output_tokens=total_output,
                total_tokens=total_input + total_output,
                message_count=int(msg_count),
            )
        )
        grand_input += total_input
        grand_output += total_output

    return TokenStatsResponse(
        period=period,
        buckets=buckets,
        total_input_tokens=grand_input,
        total_output_tokens=grand_output,
        total_tokens=grand_input + grand_output,
    )


@router.get("/tokens/daily", response_model=DailyTokenStatsResponse)
def get_daily_token_stats(
    db: Session = Depends(get_db),
    days: int = Query(7, ge=1, le=90),
) -> DailyTokenStatsResponse:
    """Return token usage bucketed by day for sparkline rendering."""
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=days)

    # SQLite date() function extracts YYYY-MM-DD from a datetime column
    day_label = func.date(ConversationMessage.created_at)

    rows = (
        db.query(
            day_label.label("day"),
            func.coalesce(func.sum(ConversationMessage.input_tokens), 0).label("total_input"),
            func.coalesce(func.sum(ConversationMessage.output_tokens), 0).label("total_output"),
        )
        .filter(
            ConversationMessage.created_at >= cutoff,
            (ConversationMessage.input_tokens.isnot(None))
            | (ConversationMessage.output_tokens.isnot(None)),
        )
        .group_by(day_label)
        .order_by(day_label)
        .all()
    )

    # Build a lookup of day -> (input, output)
    day_data: dict[str, tuple[int, int]] = {}
    for day_str, inp, out in rows:
        day_data[str(day_str)] = (int(inp), int(out))

    # Fill in all days in the range (including zeros)
    buckets: list[DailyTokenBucket] = []
    grand_total = 0
    for i in range(days):
        d = (now - timedelta(days=days - 1 - i)).strftime("%Y-%m-%d")
        inp, out = day_data.get(d, (0, 0))
        total = inp + out
        grand_total += total
        buckets.append(
            DailyTokenBucket(
                date=d,
                total_input_tokens=inp,
                total_output_tokens=out,
                total_tokens=total,
            )
        )

    return DailyTokenStatsResponse(
        days=days,
        buckets=buckets,
        total_tokens=grand_total,
    )
