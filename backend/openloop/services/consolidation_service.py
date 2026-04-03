"""Consolidation service — produces meta-summaries from individual conversation summaries.

Meta-summaries compress multiple per-conversation summaries into a single overview,
keeping context assembly efficient as conversation count grows.
"""

from __future__ import annotations

import json
import logging
import re

from sqlalchemy.orm import Session

from backend.openloop.db.models import ConversationSummary

logger = logging.getLogger(__name__)

CONSOLIDATION_MODEL = "claude-haiku-4-5-20251001"


def get_unconsolidated_count(db: Session, space_id: str) -> int:
    """Count summaries eligible for consolidation in a space.

    Eligible means: not a meta-summary, not a checkpoint, not already consolidated.
    """
    return (
        db.query(ConversationSummary)
        .filter(
            ConversationSummary.space_id == space_id,
            ConversationSummary.consolidated_into.is_(None),
            ConversationSummary.is_meta_summary.is_(False),
            ConversationSummary.is_checkpoint.is_(False),
        )
        .count()
    )


async def generate_meta_summary(db: Session, space_id: str) -> ConversationSummary:
    """Generate a meta-summary that consolidates unconsolidated summaries.

    Steps:
    1. Load unconsolidated individual summaries (oldest first).
    2. Load any existing current meta-summary for successive consolidation.
    3. Call LLM (Haiku) to produce a condensed overview.
    4. Store new meta-summary, mark all consumed summaries as consolidated.
    """
    # Guard: nothing to consolidate
    # (callers should check count first, but be safe)

    # Load unconsolidated individual summaries, oldest first
    individuals = (
        db.query(ConversationSummary)
        .filter(
            ConversationSummary.space_id == space_id,
            ConversationSummary.consolidated_into.is_(None),
            ConversationSummary.is_meta_summary.is_(False),
            ConversationSummary.is_checkpoint.is_(False),
        )
        .order_by(ConversationSummary.created_at.asc())
        .all()
    )

    # Load existing current meta-summary (if successive consolidation)
    existing_meta = (
        db.query(ConversationSummary)
        .filter(
            ConversationSummary.space_id == space_id,
            ConversationSummary.is_meta_summary.is_(True),
            ConversationSummary.consolidated_into.is_(None),
        )
        .first()
    )

    if not individuals and not existing_meta:
        raise ValueError("No summaries to consolidate")

    # Build input text for LLM
    summaries_to_consume: list[ConversationSummary] = []
    input_blocks: list[str] = []

    if existing_meta:
        input_blocks.append(
            f"## Previous Meta-Summary\n{existing_meta.summary}"
        )
        if existing_meta.decisions:
            input_blocks.append(
                "Previous decisions: " + json.dumps(existing_meta.decisions)
            )
        if existing_meta.open_questions:
            input_blocks.append(
                "Previous open questions: " + json.dumps(existing_meta.open_questions)
            )
        summaries_to_consume.append(existing_meta)

    for s in individuals:
        block = f"- [{s.created_at.isoformat()}] {s.summary}"
        if s.decisions:
            block += f"\n  Decisions: {json.dumps(s.decisions)}"
        if s.open_questions:
            block += f"\n  Open questions: {json.dumps(s.open_questions)}"
        input_blocks.append(block)
        summaries_to_consume.append(s)

    # Determine most recent conversation_id
    most_recent_conv_id = individuals[-1].conversation_id if individuals else (
        existing_meta.conversation_id if existing_meta else None
    )

    # Build the prompt
    prompt = (
        "You are a project-context consolidation system. Given the conversation summaries below, "
        "produce a single condensed meta-summary that captures:\n"
        "1. Key decisions made\n"
        "2. Major outcomes and progress\n"
        "3. Current trajectory / direction\n"
        "4. Open threads that need attention\n"
        "5. Time period covered (earliest to latest)\n\n"
        "Input summaries:\n"
        + "\n\n".join(input_blocks)
        + "\n\n"
        'Respond with ONLY valid JSON:\n'
        '{\n'
        '  "summary": "Condensed overview paragraph",\n'
        '  "decisions": ["decision1", "decision2", ...],\n'
        '  "open_questions": ["question1", "question2", ...]\n'
        '}'
    )

    # Call LLM
    result = await _call_consolidation_llm(prompt)

    # Create new meta-summary
    meta = ConversationSummary(
        conversation_id=most_recent_conv_id,
        space_id=space_id,
        summary=result["summary"],
        decisions=result["decisions"],
        open_questions=result["open_questions"],
        is_meta_summary=True,
        is_checkpoint=False,
    )
    db.add(meta)
    db.flush()  # Get the ID assigned

    # Mark all consumed summaries as consolidated into the new meta
    for s in summaries_to_consume:
        s.consolidated_into = meta.id

    # Let the caller (route handler) manage the commit, or commit here
    # for background callers (agent_runner close_conversation)
    db.commit()
    db.refresh(meta)
    return meta


async def _call_consolidation_llm(prompt: str) -> dict:
    """Call Haiku to produce the consolidation JSON.

    Returns parsed dict with summary, decisions, open_questions.
    Falls back to a simple concatenation on failure.
    """
    from backend.openloop.services.llm_utils import _cleanup_session_file

    try:
        from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

        response_text = ""
        session_id: str | None = None
        async for event in query(
            prompt=prompt,
            options=ClaudeAgentOptions(model=CONSOLIDATION_MODEL),
        ):
            if isinstance(event, ResultMessage):
                response_text = event.result
                session_id = event.session_id
                break

        if not response_text:
            logger.warning("Empty response from consolidation LLM, using fallback")
            return _fallback_result()

        return _parse_consolidation_json(response_text)

    except (Exception, ExceptionGroup):
        logger.warning("Consolidation LLM call failed, using fallback", exc_info=True)
        return _fallback_result()
    finally:
        _cleanup_session_file(session_id)


def _parse_consolidation_json(text: str) -> dict:
    """Parse JSON from LLM response, handling markdown code fences."""
    # Strip markdown code fences if present
    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1)

    text = text.strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("Failed to parse consolidation response as JSON: %s", text[:200])
        return _fallback_result()

    if not isinstance(parsed, dict):
        logger.warning("Consolidation response is not a dict: %s", type(parsed))
        return _fallback_result()

    return {
        "summary": parsed.get("summary", ""),
        "decisions": parsed.get("decisions", []),
        "open_questions": parsed.get("open_questions", []),
    }


def _fallback_result() -> dict:
    """Return a fallback result when LLM is unavailable."""
    return {
        "summary": "(Consolidation failed — summaries still available individually)",
        "decisions": [],
        "open_questions": [],
    }
