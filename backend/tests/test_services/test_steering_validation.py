"""Tests for steering message validation in agent_runner.steer()."""

import pytest
from fastapi import HTTPException


@pytest.mark.asyncio
async def test_steer_rejects_over_2000_chars():
    """Steering messages over 2000 characters should be rejected with 422."""
    from backend.openloop.agents.agent_runner import steer

    long_message = "x" * 2001
    with pytest.raises(HTTPException) as exc_info:
        await steer("some-conversation-id", long_message)
    assert exc_info.value.status_code == 422
    assert "2000-character limit" in exc_info.value.detail


@pytest.mark.asyncio
async def test_steer_accepts_exactly_2000_chars():
    """Steering messages at exactly 2000 characters should not be rejected
    (though they may still return False if no background task is running)."""
    from backend.openloop.agents.agent_runner import steer

    exact_message = "x" * 2000
    # No background task running for this conversation, so it returns False,
    # but it should NOT raise a 422 — length validation passes.
    result = await steer("nonexistent-conv", exact_message)
    assert result is False


@pytest.mark.asyncio
async def test_steer_rejects_empty_boundary():
    """Steering messages of 2001 chars should be rejected."""
    from backend.openloop.agents.agent_runner import steer

    message = "a" * 2001
    with pytest.raises(HTTPException) as exc_info:
        await steer("any-conv", message)
    assert exc_info.value.status_code == 422
