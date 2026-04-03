"""Utility for making LLM calls via the Claude Agent SDK for system operations."""

import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

DEDUP_MODEL = "claude-haiku-4-5-20251001"


def _cleanup_session_file(session_id: str | None) -> None:
    """Delete the SDK session JSONL file for a one-shot utility call.

    SDK query() calls persist sessions as JSONL files under
    ``~/.claude/projects/<project-slug>/<session_id>.jsonl``.  Utility calls
    (dedup, consolidation) are stateless and never resumed, so their session
    files are pure waste.  This helper finds and removes the file.

    Silently ignores missing files or permission errors — cleanup failure must
    never affect the caller.
    """
    if not session_id:
        return
    try:
        claude_projects = Path.home() / ".claude" / "projects"
        if not claude_projects.is_dir():
            return
        filename = f"{session_id}.jsonl"
        for match in claude_projects.glob(f"*/{filename}"):
            match.unlink()
            logger.debug("Cleaned up utility session file: %s", match)
            return
    except OSError:
        logger.debug("Failed to clean up session file for %s", session_id, exc_info=True)


async def llm_compare_facts(new_fact: str, existing_facts: list[dict]) -> dict:
    """Compare new fact against existing ones using an LLM call.

    Args:
        new_fact: The new fact content to evaluate.
        existing_facts: List of dicts with 'id', 'key', 'value' fields.

    Returns:
        Dict with keys: decision (add|update|delete|noop), target_id, merged_content.
    """
    default_add = {"decision": "add", "target_id": None, "merged_content": None}

    if not existing_facts:
        return default_add

    # Format existing facts for the prompt
    facts_block = "\n".join(
        f"[{f['id']}] {f['key']}: {f['value']}" for f in existing_facts
    )

    prompt = (
        "You are a memory deduplication system. Compare a new fact against existing facts.\n"
        "\n"
        "Decide ONE of:\n"
        "- ADD: genuinely new information not covered by any existing fact\n"
        "- UPDATE: an existing fact should be modified to incorporate this (provide merged_content)\n"
        "- DELETE: an existing fact is now obsolete/contradicted (will be superseded)\n"
        "- NOOP: already adequately captured\n"
        "\n"
        f"Existing facts:\n{facts_block}\n"
        "\n"
        f"New fact: {new_fact}\n"
        "\n"
        'Respond with ONLY valid JSON: {"decision": "add|update|delete|noop", '
        '"target_id": "id_or_null", "merged_content": "text_or_null"}'
    )

    try:
        from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

        response_text = ""
        session_id: str | None = None
        async for event in query(
            prompt=prompt,
            options=ClaudeAgentOptions(model=DEDUP_MODEL),
        ):
            if isinstance(event, ResultMessage):
                response_text = event.result
                session_id = event.session_id
                break

        _cleanup_session_file(session_id)

        if not response_text:
            logger.warning("Empty response from SDK dedup call, defaulting to ADD")
            return default_add

        return _parse_llm_json(response_text)

    except (Exception, ExceptionGroup):
        logger.warning("SDK call failed for fact dedup, defaulting to ADD", exc_info=True)
        return default_add


async def llm_consolidate_facts(facts: list[dict]) -> dict:
    """Review a set of facts for consolidation opportunities using an LLM call.

    Args:
        facts: List of dicts with 'id', 'key', 'value', 'access_count', 'last_accessed' fields.

    Returns:
        Dict with keys: merges (list of merge proposals), contradictions (list),
        stale (list of stale entry ids).
    """
    default_empty = {"merges": [], "contradictions": [], "stale": []}

    if not facts or len(facts) < 2:
        return default_empty

    facts_block = "\n".join(
        f"[{f['id']}] {f['key']}: {f['value']} (accessed: {f['access_count']}x, last: {f['last_accessed']})"
        for f in facts
    )

    prompt = (
        "You are a memory consolidation system. Review the following facts and identify:\n"
        "1. MERGES: groups of facts that should be merged into one (provide merged_value)\n"
        "2. CONTRADICTIONS: pairs of facts that contradict each other\n"
        "3. STALE: facts with 0 access count that appear outdated or redundant\n"
        "\n"
        f"Facts:\n{facts_block}\n"
        "\n"
        "Respond with ONLY valid JSON:\n"
        '{\n'
        '  "merges": [{"source_ids": ["id1", "id2"], "merged_value": "combined text", "reason": "why"}],\n'
        '  "contradictions": [{"ids": ["id1", "id2"], "description": "what contradicts"}],\n'
        '  "stale": [{"id": "id1", "reason": "why stale"}]\n'
        '}'
    )

    try:
        from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

        response_text = ""
        session_id: str | None = None
        async for event in query(
            prompt=prompt,
            options=ClaudeAgentOptions(model=DEDUP_MODEL),
        ):
            if isinstance(event, ResultMessage):
                response_text = event.result
                session_id = event.session_id
                break

        _cleanup_session_file(session_id)

        if not response_text:
            logger.warning("Empty response from SDK consolidation call, returning empty report")
            return default_empty

        return _parse_consolidation_json(response_text)

    except (Exception, ExceptionGroup):
        logger.warning("SDK call failed for fact consolidation, returning empty report", exc_info=True)
        return default_empty


def _parse_consolidation_json(text: str) -> dict:
    """Parse JSON from LLM consolidation response.

    Returns a validated dict with merges/contradictions/stale keys.
    Falls back to empty report if parsing fails.
    """
    default_empty = {"merges": [], "contradictions": [], "stale": []}

    # Strip markdown code fences if present
    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1)

    text = text.strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("Failed to parse LLM consolidation response as JSON: %s", text[:200])
        return default_empty

    if not isinstance(parsed, dict):
        logger.warning("LLM consolidation response is not a dict: %s", type(parsed))
        return default_empty

    return {
        "merges": parsed.get("merges", []),
        "contradictions": parsed.get("contradictions", []),
        "stale": parsed.get("stale", []),
    }


def _parse_llm_json(text: str) -> dict:
    """Parse JSON from LLM response, handling markdown code fences.

    Returns a validated dict with decision/target_id/merged_content keys.
    Falls back to ADD if parsing fails.
    """
    default_add = {"decision": "add", "target_id": None, "merged_content": None}

    # Strip markdown code fences if present
    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1)

    text = text.strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("Failed to parse LLM dedup response as JSON: %s", text[:200])
        return default_add

    if not isinstance(parsed, dict):
        logger.warning("LLM dedup response is not a dict: %s", type(parsed))
        return default_add

    decision = parsed.get("decision", "").lower()
    if decision not in ("add", "update", "delete", "noop"):
        logger.warning("Invalid dedup decision '%s', defaulting to ADD", decision)
        return default_add

    return {
        "decision": decision,
        "target_id": parsed.get("target_id"),
        "merged_content": parsed.get("merged_content"),
    }
