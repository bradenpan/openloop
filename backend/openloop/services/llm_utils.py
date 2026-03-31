"""Utility for making LLM calls via the Claude Agent SDK for system operations."""

import json
import logging
import re

logger = logging.getLogger(__name__)

DEDUP_MODEL = "claude-haiku-4-5-20251001"


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
        async for event in query(
            prompt=prompt,
            options=ClaudeAgentOptions(model=DEDUP_MODEL),
        ):
            if isinstance(event, ResultMessage):
                response_text = event.result
                break

        if not response_text:
            logger.warning("Empty response from SDK dedup call, defaulting to ADD")
            return default_add

        return _parse_llm_json(response_text)

    except (Exception, ExceptionGroup):
        logger.warning("SDK call failed for fact dedup, defaulting to ADD", exc_info=True)
        return default_add


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
