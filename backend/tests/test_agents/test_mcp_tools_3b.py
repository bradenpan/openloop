"""Tests for Phase 3b MCP tools.

Covers: save_fact, recall_facts, update_fact, delete_fact,
save_rule, confirm_rule, override_rule, list_rules.

All tools are async. save_fact requires mocking save_fact_with_dedup since
it calls the LLM.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.orm import Session

from backend.openloop.agents.mcp_tools import (
    confirm_rule,
    delete_fact,
    list_rules,
    override_rule,
    recall_facts,
    save_fact,
    save_rule,
    update_fact,
)
from backend.openloop.services import (
    agent_service,
    behavioral_rule_service,
    memory_service,
)
from contract.enums import DedupDecision


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse(result_str: str) -> dict:
    """Parse the JSON string returned by MCP tools."""
    return json.loads(result_str)


def _make_agent(db: Session, name: str = "TestAgent"):
    return agent_service.create_agent(db, name=name)


# ---------------------------------------------------------------------------
# save_fact
# ---------------------------------------------------------------------------


class TestSaveFact:
    @pytest.mark.asyncio
    async def test_save_fact_add(self, db_session: Session):
        """save_fact should return the ADD decision and created entry info."""
        entry = memory_service.create_entry(
            db_session, namespace="agent:test", key="test", value="test value"
        )
        with patch(
            "backend.openloop.agents.mcp_tools.memory_service.save_fact_with_dedup",
            new_callable=AsyncMock,
        ) as mock_dedup:
            mock_dedup.return_value = (DedupDecision.ADD, entry)
            result_str = await save_fact(
                "test content", _db=db_session, _agent_name="test"
            )

        result = _parse(result_str)
        assert "result" in result
        assert result["result"]["decision"] == "add"
        assert result["result"]["id"] == entry.id

    @pytest.mark.asyncio
    async def test_save_fact_noop(self, db_session: Session):
        """save_fact should return NOOP decision."""
        entry = memory_service.create_entry(
            db_session, namespace="agent:test", key="existing", value="already exists"
        )
        with patch(
            "backend.openloop.agents.mcp_tools.memory_service.save_fact_with_dedup",
            new_callable=AsyncMock,
        ) as mock_dedup:
            mock_dedup.return_value = (DedupDecision.NOOP, entry)
            result_str = await save_fact(
                "already exists", _db=db_session, _agent_name="test"
            )

        result = _parse(result_str)
        assert result["result"]["decision"] == "noop"
        assert result["result"]["id"] == entry.id

    @pytest.mark.asyncio
    async def test_save_fact_default_namespace(self, db_session: Session):
        """When no namespace is provided, it should default to agent:<agent_name>."""
        entry = memory_service.create_entry(
            db_session, namespace="agent:myagent", key="k", value="v"
        )
        with patch(
            "backend.openloop.agents.mcp_tools.memory_service.save_fact_with_dedup",
            new_callable=AsyncMock,
        ) as mock_dedup:
            mock_dedup.return_value = (DedupDecision.ADD, entry)
            await save_fact("some fact", _db=db_session, _agent_name="myagent")

        # Verify the namespace passed to save_fact_with_dedup
        call_kwargs = mock_dedup.call_args
        assert call_kwargs[1]["namespace"] == "agent:myagent" or call_kwargs[0][1] == "agent:myagent"

    @pytest.mark.asyncio
    async def test_save_fact_error_handling(self, db_session: Session):
        """save_fact should return an error JSON on exception."""
        with patch(
            "backend.openloop.agents.mcp_tools.memory_service.save_fact_with_dedup",
            new_callable=AsyncMock,
        ) as mock_dedup:
            mock_dedup.side_effect = RuntimeError("LLM unavailable")
            result_str = await save_fact(
                "something", _db=db_session, _agent_name="test"
            )

        result = _parse(result_str)
        assert result["is_error"] is True
        assert "LLM unavailable" in result["error"]


# ---------------------------------------------------------------------------
# recall_facts
# ---------------------------------------------------------------------------


class TestRecallFacts:
    @pytest.mark.asyncio
    async def test_recall_with_namespace(self, db_session: Session):
        """recall_facts with namespace should return scored entries."""
        memory_service.create_entry(
            db_session, namespace="space:test", key="fact1", value="value1"
        )
        memory_service.create_entry(
            db_session, namespace="space:test", key="fact2", value="value2"
        )

        result_str = await recall_facts(
            namespace="space:test", _db=db_session
        )
        result = _parse(result_str)
        assert len(result["result"]) == 2

    @pytest.mark.asyncio
    async def test_recall_with_query(self, db_session: Session):
        """recall_facts with query should search across entries."""
        memory_service.create_entry(
            db_session, namespace="global", key="tech", value="Python + React"
        )
        memory_service.create_entry(
            db_session, namespace="global", key="weather", value="sunny today"
        )

        result_str = await recall_facts(query="Python", _db=db_session)
        result = _parse(result_str)
        assert len(result["result"]) == 1
        assert "Python" in result["result"][0]["value"]

    @pytest.mark.asyncio
    async def test_recall_with_category_filter(self, db_session: Session):
        """recall_facts should filter by category when provided."""
        e1 = memory_service.create_entry(
            db_session, namespace="space:test", key="a", value="val a"
        )
        e1.category = "preference"
        e2 = memory_service.create_entry(
            db_session, namespace="space:test", key="b", value="val b"
        )
        e2.category = "fact"
        db_session.commit()

        result_str = await recall_facts(
            namespace="space:test", category="preference", _db=db_session
        )
        result = _parse(result_str)
        assert len(result["result"]) == 1
        assert result["result"][0]["category"] == "preference"


# ---------------------------------------------------------------------------
# update_fact
# ---------------------------------------------------------------------------


class TestUpdateFact:
    @pytest.mark.asyncio
    async def test_update_existing(self, db_session: Session):
        entry = memory_service.create_entry(
            db_session, namespace="global", key="mutable", value="old"
        )
        result_str = await update_fact(entry.id, "new value", _db=db_session)
        result = _parse(result_str)

        assert result["result"]["value"] == "new value"
        assert result["result"]["id"] == entry.id

    @pytest.mark.asyncio
    async def test_update_nonexistent(self, db_session: Session):
        result_str = await update_fact("bad-id", "nope", _db=db_session)
        result = _parse(result_str)
        assert result["is_error"] is True


# ---------------------------------------------------------------------------
# delete_fact
# ---------------------------------------------------------------------------


class TestDeleteFact:
    @pytest.mark.asyncio
    async def test_delete_sets_valid_until(self, db_session: Session):
        entry = memory_service.create_entry(
            db_session, namespace="global", key="to-delete", value="will expire"
        )
        assert entry.valid_until is None

        result_str = await delete_fact(entry.id, reason="outdated", _db=db_session)
        result = _parse(result_str)

        assert result["result"]["id"] == entry.id
        assert result["result"]["valid_until"] is not None
        assert result["result"]["reason"] == "outdated"

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, db_session: Session):
        result_str = await delete_fact("bad-id", _db=db_session)
        result = _parse(result_str)
        assert result["is_error"] is True


# ---------------------------------------------------------------------------
# save_rule
# ---------------------------------------------------------------------------


class TestSaveRule:
    @pytest.mark.asyncio
    async def test_save_rule_creates(self, db_session: Session):
        agent = _make_agent(db_session)
        result_str = await save_rule(
            "Always respond in bullet points",
            source_type="correction",
            _db=db_session,
            _agent_name=agent.name, _agent_id=agent.id,
        )
        result = _parse(result_str)

        assert "result" in result
        assert result["result"]["rule"] == "Always respond in bullet points"
        assert result["result"]["confidence"] == 0.5
        assert result["result"]["source_type"] == "correction"

    @pytest.mark.asyncio
    async def test_save_rule_default_source_type(self, db_session: Session):
        agent = _make_agent(db_session)
        result_str = await save_rule(
            "Some rule", _db=db_session, _agent_name=agent.name, _agent_id=agent.id
        )
        result = _parse(result_str)
        assert result["result"]["source_type"] == "correction"


# ---------------------------------------------------------------------------
# confirm_rule
# ---------------------------------------------------------------------------


class TestConfirmRuleTool:
    @pytest.mark.asyncio
    async def test_confirm_increases_confidence(self, db_session: Session):
        agent = _make_agent(db_session)
        rule = behavioral_rule_service.create_rule(
            db_session, agent_id=agent.id, rule="test rule"
        )
        assert rule.confidence == 0.5

        result_str = await confirm_rule(rule.id, _db=db_session)
        result = _parse(result_str)

        assert abs(result["result"]["confidence"] - 0.6) < 0.001

    @pytest.mark.asyncio
    async def test_confirm_nonexistent(self, db_session: Session):
        result_str = await confirm_rule("bad-id", _db=db_session)
        result = _parse(result_str)
        assert result["is_error"] is True


# ---------------------------------------------------------------------------
# override_rule
# ---------------------------------------------------------------------------


class TestOverrideRuleTool:
    @pytest.mark.asyncio
    async def test_override_decreases_confidence(self, db_session: Session):
        agent = _make_agent(db_session)
        rule = behavioral_rule_service.create_rule(
            db_session, agent_id=agent.id, rule="test rule"
        )

        result_str = await override_rule(rule.id, _db=db_session)
        result = _parse(result_str)

        assert abs(result["result"]["confidence"] - 0.3) < 0.001

    @pytest.mark.asyncio
    async def test_override_nonexistent(self, db_session: Session):
        result_str = await override_rule("bad-id", _db=db_session)
        result = _parse(result_str)
        assert result["is_error"] is True


# ---------------------------------------------------------------------------
# list_rules
# ---------------------------------------------------------------------------


class TestListRulesTool:
    @pytest.mark.asyncio
    async def test_list_returns_active_rules(self, db_session: Session):
        agent = _make_agent(db_session)
        behavioral_rule_service.create_rule(
            db_session, agent_id=agent.id, rule="Rule A"
        )
        behavioral_rule_service.create_rule(
            db_session, agent_id=agent.id, rule="Rule B"
        )

        result_str = await list_rules(
            agent_id=agent.id, _db=db_session, _agent_name=agent.name, _agent_id=agent.id
        )
        result = _parse(result_str)
        assert len(result["result"]) == 2

    @pytest.mark.asyncio
    async def test_list_uses_agent_name_as_default(self, db_session: Session):
        """When agent_id is empty, should default to _agent_name."""
        agent = _make_agent(db_session)
        behavioral_rule_service.create_rule(
            db_session, agent_id=agent.id, rule="Rule"
        )

        result_str = await list_rules(
            agent_id="", _db=db_session, _agent_name=agent.name, _agent_id=agent.id
        )
        result = _parse(result_str)
        assert len(result["result"]) == 1
