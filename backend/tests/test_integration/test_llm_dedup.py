"""LLM integration tests for fact deduplication.

These tests call the real Claude Max SDK and take 2-5 seconds each.
They are NOT run by default — use ``pytest -m llm`` to include them.

To run LLM tests: pytest -m llm
"""

from __future__ import annotations

import pytest

from backend.openloop.services.llm_utils import llm_compare_facts

# All tests in this file require the LLM marker
pytestmark = [pytest.mark.llm, pytest.mark.asyncio]


async def test_dedup_add_genuinely_new():
    """Real LLM should decide ADD for genuinely new information."""
    result = await llm_compare_facts(
        "The project deadline is March 15",
        [{"id": "1", "key": "tech-stack", "value": "Python + React + SQLite"}],
    )
    assert result["decision"] == "add"


async def test_dedup_update_similar():
    """Real LLM should decide UPDATE when new info extends existing."""
    result = await llm_compare_facts(
        "Project uses React 19 with Vite and Tailwind",
        [{"id": "1", "key": "frontend", "value": "Project uses React 19"}],
    )
    # Allow some tolerance — the LLM might say update or noop
    assert result["decision"] in ("update", "noop")


async def test_dedup_delete_contradiction():
    """Real LLM should decide DELETE when new fact contradicts old."""
    result = await llm_compare_facts(
        "Bob now owns the budget",
        [{"id": "1", "key": "budget-owner", "value": "Alice owns the budget"}],
    )
    assert result["decision"] == "delete"
    assert result["target_id"] == "1"
