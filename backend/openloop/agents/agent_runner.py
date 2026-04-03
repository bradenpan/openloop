"""Agent Runner — thin wrapper between OpenLoop and the Claude Agent SDK.

Replaces session_manager.py. No in-memory session state; the DB's
sdk_session_id on the Conversation record is the single source of truth.

Public API:
    run_interactive()       — send a message, stream SSE events
    close_conversation()    — flush memory, generate summary, close
    flush_memory()          — extract facts before compression/close
    steer()                 — queue a steering message for background tasks
    delegate_background()   — fire-and-forget agent work
    recover_from_crash()    — mark stale conversations as interrupted
    list_running()          — DB query for active sessions + running tasks
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import re
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.openloop.agents import concurrency_manager, context_assembler
from backend.openloop.agents.mcp_tools import build_agent_tools, build_odin_tools
from backend.openloop.agents.permission_enforcer import build_permission_hook
from backend.openloop.services import (
    agent_service,
    background_task_service,
    conversation_service,
    memory_service,
    notification_service,
    summary_service,
    system_service,
)

# ---------------------------------------------------------------------------
# Windows encoding fix (from spike/results.md)
# ---------------------------------------------------------------------------
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Model name mapping — short names to full SDK model IDs
# ---------------------------------------------------------------------------
MODEL_MAP: dict[str, str] = {
    "haiku": "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-4-6",
    "opus": "claude-opus-4-6",
}

# ---------------------------------------------------------------------------
# Prompt constants
# ---------------------------------------------------------------------------

CLOSE_SESSION_PROMPT = (
    "Please summarize this conversation: key decisions, outcomes, and any "
    "open questions. Format as a brief structured summary."
)

CHECKPOINT_PROMPT = (
    "Please provide a comprehensive summary of this conversation so far: "
    "key topics discussed, decisions made, current status of tasks, and any "
    "open questions. This will be used as a checkpoint for context management."
)

FLUSH_MEMORY_PROMPT = (
    "Review this conversation for any important facts, decisions, or user "
    "preferences that haven't been saved to memory yet. Save them now using "
    "your memory tools (save_fact, save_rule). This is mandatory before "
    "context compression."
)

# Observation masking: keep this many recent user+assistant exchange pairs verbatim
RECENT_TURNS_VERBATIM = 7

# ---------------------------------------------------------------------------
# Rate limit retry configuration
# ---------------------------------------------------------------------------
RATE_LIMIT_BACKOFF_SECONDS = [30, 60, 120]  # Exponential backoff schedule
RATE_LIMIT_MAX_RETRIES = 3

# ---------------------------------------------------------------------------
# Concurrency limits (now managed by concurrency_manager.py)
# ---------------------------------------------------------------------------

# Context window estimation (all models treated as 200K for now)
CONTEXT_WINDOW_TOKENS = 200_000
CHECKPOINT_THRESHOLD = 0.70  # 70% — trigger auto-checkpoint
CLOSE_THRESHOLD = 0.90  # 90% — suggest closing

# ---------------------------------------------------------------------------
# Module-level lightweight state (no SessionState objects)
# ---------------------------------------------------------------------------

# Per-conversation asyncio locks (prevents concurrent sends to the same conversation)
_conversation_locks: dict[str, asyncio.Lock] = {}

# Background task tracking
_background_tasks: set[asyncio.Task] = set()
_background_conversations: set[str] = set()  # conversation_ids with active bg tasks

# Steering queues (Phase 5 — mid-task course correction)
_steering_queues: dict[str, list[str]] = {}
MAX_STEERING_MESSAGES = 10


def _task_done(task: asyncio.Task) -> None:
    """Done callback for fire-and-forget tasks: log exceptions, discard ref."""
    _background_tasks.discard(task)
    if not task.cancelled() and task.exception():
        logger.error("Background task failed: %s", task.exception())


# ---------------------------------------------------------------------------
# Short-lived DB session helper (mockable in tests)
# ---------------------------------------------------------------------------


def _new_db_session() -> Session:
    """Create a short-lived DB session for post-await writes.

    Isolated as a function so tests can patch it to return their
    in-memory test session instead of the real SessionLocal().
    """
    from backend.openloop.database import SessionLocal

    return SessionLocal()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def resolve_model(model_name: str) -> str:
    """Resolve a short model name to a full SDK model ID.

    If the name is already a full ID (contains a hyphen and digits), returns as-is.
    """
    return MODEL_MAP.get(model_name, model_name)


def _build_hooks_dict(
    agent_id: str,
    conversation_id: str | None,
    background_task_id: str | None = None,
    autonomous_mode: bool = False,
    narrowed_permissions=None,
) -> dict:
    """Build the hooks dict for ClaudeAgentOptions from the permission hook."""
    matcher, hook_fn = build_permission_hook(
        agent_id, conversation_id,
        background_task_id=background_task_id,
        autonomous_mode=autonomous_mode,
        narrowed_permissions=narrowed_permissions,
    )
    matcher.hooks = [hook_fn]
    return {"PreToolUse": [matcher]}


def _get_conversation_lock(conversation_id: str) -> asyncio.Lock:
    """Return (or create) the asyncio.Lock for a given conversation."""
    if conversation_id not in _conversation_locks:
        _conversation_locks[conversation_id] = asyncio.Lock()
    return _conversation_locks[conversation_id]


def _convert_stream_event(stream_event, conversation_id: str) -> dict | None:
    """Convert a raw SDK StreamEvent to a serializable SSE-compatible dict.

    Returns None for events that should not be forwarded to the frontend
    (thinking blocks, signatures, message_start/stop, etc.).
    """
    inner = stream_event.event  # The raw API event dict
    event_type = inner.get("type", "")

    if event_type == "content_block_delta":
        delta = inner.get("delta", {})
        delta_type = delta.get("type", "")
        if delta_type == "text_delta":
            return {
                "type": "token",
                "conversation_id": conversation_id,
                "content": delta.get("text", ""),
            }
        if delta_type == "input_json_delta":
            # Tool input streaming — skip for now
            return None
        # thinking_delta, signature_delta — skip
        return None

    if event_type == "content_block_start":
        block = inner.get("content_block", {})
        if block.get("type") == "tool_use":
            return {
                "type": "tool_call",
                "conversation_id": conversation_id,
                "tool_name": block.get("name", "unknown"),
                "status": "started",
            }
        return None

    # content_block_stop, message_start, message_delta, message_stop — skip
    return None


def _build_mcp_server(agent, agent_id: str):
    """Build the appropriate MCP tool server for an agent."""
    is_odin = agent.name.lower() == "odin"
    is_agent_builder = agent.name.lower() in ("agent-builder", "agent builder")
    if is_odin:
        return build_odin_tools(agent_id)
    elif is_agent_builder:
        from backend.openloop.agents.mcp_tools import build_agent_builder_tools

        return build_agent_builder_tools(agent.name, agent_id)
    else:
        return build_agent_tools(agent.name, agent_id)


def _check_concurrency(db: Session, lane: str) -> None:
    """Check concurrency limits via the lane-based concurrency manager.

    Raises 429 if the requested lane is full or total background cap reached.
    """
    if not concurrency_manager.acquire_slot(db, lane):
        if lane == "interactive":
            detail = "Too many active sessions. Please close a conversation first."
        else:
            detail = f"Concurrency limit reached for '{lane}' lane. Please wait for a session to complete."
        raise HTTPException(status_code=429, detail=detail)


# ---------------------------------------------------------------------------
# Rate limit detection & retry
# ---------------------------------------------------------------------------


def _is_rate_limit_error(exc: BaseException) -> bool:
    """Check if an exception is a rate limit / overloaded error.

    Inspects both HTTP status codes (429) and error message text.
    Handles ExceptionGroup by checking all contained exceptions.
    """
    if isinstance(exc, ExceptionGroup):
        return any(_is_rate_limit_error(e) for e in exc.exceptions)

    exc_str = str(exc).lower()
    if "429" in exc_str:
        return True
    for phrase in ("rate limit", "rate_limit", "overloaded", "too many requests"):
        if phrase in exc_str:
            return True
    status_code = getattr(exc, "status_code", None)
    if status_code == 429:
        return True
    response = getattr(exc, "response", None)
    if response is not None and getattr(response, "status_code", None) == 429:
        return True
    return False


def _is_session_expired_error(exc: BaseException) -> bool:
    """Check if an exception indicates an expired or invalid SDK session.

    This catches cases where the JSONL session file was deleted, corrupted,
    or the session_id is otherwise unrecognized by the SDK.
    """
    if isinstance(exc, ExceptionGroup):
        return any(_is_session_expired_error(e) for e in exc.exceptions)

    exc_str = str(exc).lower()
    for phrase in ("session not found", "session_not_found", "invalid session",
                   "no such session", "session expired", "session does not exist"):
        if phrase in exc_str:
            return True
    return False


async def _query_with_retry(
    query_fn,
    query_kwargs: dict,
    *,
    conversation_id: str,
    space_id: str | None = None,
) -> AsyncGenerator:
    """Wrap an SDK query() call with rate limit retry logic.

    On rate limit errors: notification + SSE event + exponential backoff + retry.
    On final failure, re-raises the exception.
    Yields events from the successful query() call.
    """
    from backend.openloop.agents.event_bus import event_bus
    from backend.openloop.database import SessionLocal

    last_exc: BaseException | None = None
    events_yielded = False
    for attempt in range(RATE_LIMIT_MAX_RETRIES + 1):
        try:
            async for event in query_fn(**query_kwargs):
                events_yielded = True
                yield event
            return  # Success
        except (Exception, ExceptionGroup) as exc:
            if events_yielded or not _is_rate_limit_error(exc):
                raise  # Don't retry if we already streamed partial events

            last_exc = exc
            if attempt >= RATE_LIMIT_MAX_RETRIES:
                break

            wait_seconds = RATE_LIMIT_BACKOFF_SECONDS[attempt]
            logger.warning(
                "Rate limited (attempt %d/%d) for conversation %s — "
                "retrying in %ds: %s",
                attempt + 1,
                RATE_LIMIT_MAX_RETRIES,
                conversation_id,
                wait_seconds,
                exc,
            )

            try:
                db_notify = SessionLocal()
                try:
                    notification_service.create_notification(
                        db_notify,
                        type="system",
                        title="Rate limited — retrying",
                        body=(
                            f"API rate limit hit (attempt {attempt + 1}/{RATE_LIMIT_MAX_RETRIES}). "
                            f"Retrying in {wait_seconds}s."
                        ),
                        space_id=space_id,
                        conversation_id=conversation_id,
                    )
                finally:
                    db_notify.close()
            except Exception:
                logger.debug("Failed to create rate limit notification", exc_info=True)

            await event_bus.publish({
                "type": "rate_limited",
                "conversation_id": conversation_id,
                "attempt": attempt + 1,
                "max_retries": RATE_LIMIT_MAX_RETRIES,
                "retry_after_seconds": wait_seconds,
            })

            await asyncio.sleep(wait_seconds)

    if last_exc is not None:
        raise last_exc


# ---------------------------------------------------------------------------
# Token helpers (Phase 8.4)
# ---------------------------------------------------------------------------


def _extract_usage(result_message) -> tuple[int | None, int | None]:
    """Extract input_tokens and output_tokens from a ResultMessage.

    Returns (input_tokens, output_tokens) — both may be None.
    """
    if not result_message or not hasattr(result_message, "usage") or not result_message.usage:
        return None, None
    usage = result_message.usage
    if not isinstance(usage, dict):
        usage = vars(usage) if hasattr(usage, "__dict__") else {}
    return usage.get("input_tokens"), usage.get("output_tokens")


def _sum_conversation_tokens(db: Session, conversation_id: str) -> int:
    """Sum total tokens (input + output) across all messages in a conversation."""
    from sqlalchemy import func

    from backend.openloop.db.models import ConversationMessage

    row = (
        db.query(
            func.coalesce(func.sum(ConversationMessage.input_tokens), 0),
            func.coalesce(func.sum(ConversationMessage.output_tokens), 0),
        )
        .filter(ConversationMessage.conversation_id == conversation_id)
        .one()
    )
    return int(row[0]) + int(row[1])


# ---------------------------------------------------------------------------
# Context estimation
# ---------------------------------------------------------------------------


def _estimate_conversation_context(
    db: Session, conversation_id: str, pending_message: str
) -> int:
    """Estimate total context tokens for a conversation.

    Sum of: system prompt estimate + all messages + pending message.
    Uses estimate_tokens() (4 chars ~ 1 token).

    Always assembles context fresh (read_only=True) since we have no cache.
    """
    from backend.openloop.agents.context_assembler import estimate_tokens

    conversation = conversation_service.get_conversation(db, conversation_id)
    agent = agent_service.get_agent(db, conversation.agent_id)
    system_tokens = estimate_tokens(
        context_assembler.assemble_context(
            db, agent_id=agent.id, space_id=conversation.space_id, read_only=True
        )
    )

    messages = conversation_service.get_messages(db, conversation_id)
    message_tokens = sum(estimate_tokens(m.content) for m in messages)
    pending_tokens = estimate_tokens(pending_message)

    return system_tokens + message_tokens + pending_tokens


# ---------------------------------------------------------------------------
# PersistentData — data that survives compaction (Phase 8.6a)
# ---------------------------------------------------------------------------


@dataclass
class PersistentData:
    """Data that must survive context compaction in long-running background tasks.

    Attributes:
        instruction: The original task goal/instruction.
        constraints: Any user-specified constraints on the task.
        extra: Extensible dict for future data.  Task 9.2b will add the
            autonomous task list here via the ``_persistent_data_extractors``
            registry.
    """

    instruction: str
    constraints: list[str] = field(default_factory=list)
    extra: dict = field(default_factory=dict)


# Registry of callables that extract additional persistent data.
#
# Each extractor receives (instruction: str, turn_results: list[str]) and
# returns a dict of key-value pairs to merge into PersistentData.extra.
# Task 9.2b will register an extractor here for the autonomous task list.
_persistent_data_extractors: list = []


def register_persistent_extractor(fn) -> None:
    """Register a callable that extracts data to survive compaction.

    ``fn(instruction: str, turn_results: list[str]) -> dict``

    The returned dict is merged into ``PersistentData.extra``.
    """
    _persistent_data_extractors.append(fn)


def _build_persistent_data(instruction: str, turn_results: list[str]) -> PersistentData:
    """Build a PersistentData instance for the current task.

    Calls all registered extractors and merges their results into ``extra``.
    """
    pd = PersistentData(instruction=instruction)
    for extractor in _persistent_data_extractors:
        try:
            extra = extractor(instruction, turn_results)
            if isinstance(extra, dict):
                pd.extra.update(extra)
        except Exception:
            logger.debug("Persistent data extractor failed", exc_info=True)
    return pd


# ---------------------------------------------------------------------------
# Compaction cycle for background tasks (Phase 8.6a)
# ---------------------------------------------------------------------------

COMPACTION_SUMMARY_PROMPT = (
    "Summarize the conversation so far: key actions taken, results achieved, "
    "decisions made, and current status. Be thorough but concise — this "
    "summary will replace older turns to free up context space."
)


async def _run_compaction_cycle(
    *,
    db: "Session",
    task_id: str,
    conversation_id: str,
    agent_id: str,
    agent_name: str,
    space_id: str | None,
    instruction: str,
    turn_results: list[str],
    sdk_session_id: str | None,
    model: str,
    hooks: dict,
) -> tuple[bool, str | None, str | None]:
    """Execute the compaction cycle for a background task.

    Follows the OpenClaw pattern: instructions are stored externally (on the
    BackgroundTask record's ``goal`` field) and re-injected each turn via
    ``_build_continuation_prompt()``.  Compaction only affects conversation
    history, not instructions.

    Steps:
    1. Flush memory (agent persists important working context)
    2. Generate a conversation summary (replaces older turns)

    After compaction, ``_build_continuation_prompt()`` re-injects the goal
    from the DB and includes the compaction summary, so the agent never
    loses its objective.

    Returns (success, summary_text, new_sdk_session_id).
    """
    from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

    logger.info(
        "Compaction cycle triggered for task %s (conversation %s)",
        task_id,
        conversation_id,
    )

    # 1. Flush memory — agent saves important working context
    await flush_memory(db, conversation_id=conversation_id)

    # Re-read conversation in case flush_memory changed the session_id
    conversation = conversation_service.get_conversation(db, conversation_id)
    current_session_id = conversation.sdk_session_id or sdk_session_id

    if not current_session_id:
        logger.warning("No SDK session for compaction — skipping")
        return True, None, None

    # 2. Generate summary of completed work
    mcp_server = _build_mcp_server_by_name(agent_name, agent_id)
    summary_text = ""
    new_session_id: str | None = None
    try:
        async for event in query(
            prompt=COMPACTION_SUMMARY_PROMPT,
            options=ClaudeAgentOptions(
                resume=current_session_id,
                model=model,
                mcp_servers={mcp_server["name"]: mcp_server},
                hooks=hooks,
            ),
        ):
            if isinstance(event, ResultMessage):
                summary_text = event.result or ""
                if event.session_id and event.session_id != current_session_id:
                    new_session_id = event.session_id
    except (Exception, ExceptionGroup) as exc:
        logger.warning(
            "Compaction summary generation failed for task %s: %s",
            task_id,
            exc,
        )
        # Non-fatal — continue without compaction
        return True, None, new_session_id

    # Persist the summary as a checkpoint
    if summary_text:
        conversation_service.add_summary(
            db,
            conversation_id=conversation_id,
            summary=summary_text,
            is_checkpoint=True,
        )

    # Update session_id if changed
    final_session_id = new_session_id or current_session_id
    if new_session_id:
        conversation_service.update_conversation(
            db, conversation_id, sdk_session_id=new_session_id
        )

    logger.info(
        "Compaction cycle completed for task %s — summary generated, "
        "goal will be re-injected from DB on next continuation",
        task_id,
    )
    return True, summary_text, final_session_id


# ===================================================================
# PUBLIC API
# ===================================================================


async def run_interactive(
    db: Session,
    *,
    conversation_id: str,
    message: str,
) -> AsyncGenerator[dict, None]:
    """Send a message to a conversation and yield SSE-compatible events.

    Handles both first messages (no sdk_session_id) and continuations.
    Acquires a per-conversation lock to prevent concurrent sends.
    """
    lock = _get_conversation_lock(conversation_id)
    async with lock:
        async for event in _run_interactive_inner(
            db, conversation_id=conversation_id, message=message
        ):
            yield event


async def _run_interactive_inner(
    db: Session,
    *,
    conversation_id: str,
    message: str,
) -> AsyncGenerator[dict, None]:
    """Inner implementation of run_interactive (called under lock)."""
    from claude_agent_sdk import (
        ClaudeAgentOptions,
        ResultMessage,
        StreamEvent,
        query,
    )

    conversation = conversation_service.get_conversation(db, conversation_id)
    agent = agent_service.get_agent(db, conversation.agent_id)
    sdk_session_id = conversation.sdk_session_id
    is_first_message = sdk_session_id is None

    # Concurrency check for interactive sessions (first message only — resuming
    # an existing session doesn't count as a new concurrent session)
    if is_first_message:
        _check_concurrency(db, "interactive")

    # Build MCP tools + model + hooks
    mcp_server = _build_mcp_server(agent, agent.id)
    model_name = conversation.model_override or agent.default_model
    model = resolve_model(model_name)
    hooks = _build_hooks_dict(agent.id, conversation_id)

    # --- Proactive budget enforcement (skip for first message — no history yet) ---
    if not is_first_message:
        estimated_context = _estimate_conversation_context(db, conversation_id, message)
        utilization = estimated_context / CONTEXT_WINDOW_TOKENS
        if utilization > CHECKPOINT_THRESHOLD:
            logger.info(
                "Proactive compression: context at ~%.0f%% for conversation %s",
                utilization * 100,
                conversation_id,
            )
            await flush_memory(db, conversation_id=conversation_id)
            await _compress_conversation(db, conversation_id=conversation_id)

    # Build query kwargs — different for first message vs continuation
    if is_first_message:
        # Assemble full context for the system prompt
        system_prompt = context_assembler.assemble_context(
            db,
            agent_id=agent.id,
            space_id=conversation.space_id,
            conversation_id=conversation_id,
        )
        query_kwargs: dict = {
            "prompt": message,
            "options": ClaudeAgentOptions(
                system_prompt=system_prompt,
                model=model,
                mcp_servers={mcp_server["name"]: mcp_server},
                hooks=hooks,
                include_partial_messages=True,
            ),
        }
    else:
        query_kwargs = {
            "prompt": message,
            "options": ClaudeAgentOptions(
                resume=sdk_session_id,
                model=model,
                mcp_servers={mcp_server["name"]: mcp_server},
                hooks=hooks,
                include_partial_messages=True,
            ),
        }

    # Call the SDK with streaming + rate limit retry
    # NOTE: The user message is saved by the API route, not here, to avoid double-saving.
    full_response = ""
    result_message: ResultMessage | None = None
    try:
        async for event in _query_with_retry(
            query,
            query_kwargs,
            conversation_id=conversation_id,
            space_id=conversation.space_id,
        ):
            if isinstance(event, StreamEvent):
                sse_event = _convert_stream_event(event, conversation_id)
                if sse_event is not None:
                    yield sse_event
            elif isinstance(event, ResultMessage):
                result_message = event
                if event.result:
                    full_response = event.result
                # Persist sdk_session_id
                if event.session_id:
                    conversation_service.update_conversation(
                        db, conversation_id, sdk_session_id=event.session_id
                    )
    except (Exception, ExceptionGroup) as exc:
        # If resume failed (stale/missing SDK session), retry as first message
        # with fresh context. The conversation history is in the DB; the agent
        # gets summaries and facts via context assembly.
        if not is_first_message and _is_session_expired_error(exc):
            logger.warning(
                "SDK session expired for conversation %s — retrying with fresh context",
                conversation_id,
            )
            # Clear stale sdk_session_id
            conversation_service.update_conversation(db, conversation_id, sdk_session_id=None)
            # Assemble fresh context and retry as first message
            system_prompt = context_assembler.assemble_context(
                db,
                agent_id=agent.id,
                space_id=conversation.space_id,
                conversation_id=conversation_id,
            )
            # Inject summary of prior conversation for continuity
            summaries = conversation_service.get_summaries(db, conversation_id=conversation_id)
            if summaries:
                system_prompt += f"\n\n## Previous Conversation Summary\n{summaries[0].summary}"
            retry_kwargs: dict = {
                "prompt": message,
                "options": ClaudeAgentOptions(
                    system_prompt=system_prompt,
                    model=model,
                    mcp_servers={mcp_server["name"]: mcp_server},
                    hooks=hooks,
                    include_partial_messages=True,
                ),
            }
            try:
                async for event in _query_with_retry(
                    query,
                    retry_kwargs,
                    conversation_id=conversation_id,
                    space_id=conversation.space_id,
                ):
                    if isinstance(event, StreamEvent):
                        sse_event = _convert_stream_event(event, conversation_id)
                        if sse_event is not None:
                            yield sse_event
                    elif isinstance(event, ResultMessage):
                        result_message = event
                        if event.result:
                            full_response = event.result
                        if event.session_id:
                            conversation_service.update_conversation(
                                db, conversation_id, sdk_session_id=event.session_id
                            )
            except (Exception, ExceptionGroup) as retry_exc:
                logger.error(
                    "SDK error in run_interactive (retry) for conversation %s: %s",
                    conversation_id,
                    retry_exc,
                )
                conversation_service.update_conversation(db, conversation_id, status="interrupted")
                notification_service.create_notification(
                    db,
                    type="system",
                    title="Message failed",
                    body=f"SDK error in conversation {conversation_id}: {retry_exc}",
                    space_id=conversation.space_id,
                    conversation_id=conversation_id,
                )
                yield {"type": "error", "error": str(retry_exc)}
                return
        else:
            logger.error("SDK error in run_interactive for conversation %s: %s", conversation_id, exc)
            conversation_service.update_conversation(db, conversation_id, status="interrupted")
            notification_service.create_notification(
                db,
                type="system",
                title="Message failed",
                body=f"SDK error in conversation {conversation_id}: {exc}",
                space_id=conversation.space_id,
                conversation_id=conversation_id,
            )
            yield {"type": "error", "error": str(exc)}
            return

    # Extract token usage from result (Phase 8.4)
    input_tokens, output_tokens = _extract_usage(result_message)

    # Store assistant response in DB
    if full_response:
        conversation_service.add_message(
            db,
            conversation_id=conversation_id,
            role="assistant",
            content=full_response,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    # Signal stream completion to frontend
    from backend.openloop.agents.event_bus import event_bus

    await event_bus.publish_to(conversation_id, {
        "type": "stream_end",
        "conversation_id": conversation_id,
    })

    # Monitor context usage after each response
    if result_message and hasattr(result_message, "usage") and result_message.usage:
        await monitor_context_usage(db, conversation_id=conversation_id, usage=result_message.usage)


# ---------------------------------------------------------------------------
# Close conversation
# ---------------------------------------------------------------------------


async def close_conversation(
    db: Session,
    *,
    conversation_id: str,
) -> str:
    """Close a conversation: flush memory, generate summary, persist, clean up.

    Returns the summary text.
    """
    from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

    conversation = conversation_service.get_conversation(db, conversation_id)

    # Flush unsaved facts to memory before generating the closing summary
    await flush_memory(db, conversation_id=conversation_id)

    # Re-read in case flush_memory changed the session_id
    conversation = conversation_service.get_conversation(db, conversation_id)
    sdk_session_id = conversation.sdk_session_id

    summary_text = ""

    if sdk_session_id:
        agent = agent_service.get_agent(db, conversation.agent_id)
        mcp_server = _build_mcp_server(agent, agent.id)
        model_name = conversation.model_override or agent.default_model
        model = resolve_model(model_name)
        hooks = _build_hooks_dict(conversation.agent_id, conversation_id)

        try:
            async for event in query(
                prompt=CLOSE_SESSION_PROMPT,
                options=ClaudeAgentOptions(
                    resume=sdk_session_id,
                    model=model,
                    mcp_servers={mcp_server["name"]: mcp_server},
                    hooks=hooks,
                ),
            ):
                if isinstance(event, ResultMessage):
                    summary_text = event.result or ""
        except (Exception, ExceptionGroup) as exc:
            logger.warning(
                "Failed to generate summary for conversation %s: %s",
                conversation_id,
                exc,
            )
            summary_text = f"(Summary generation failed: {exc})"

    # Store summary
    if summary_text:
        conversation_service.add_summary(
            db,
            conversation_id=conversation_id,
            summary=summary_text,
        )

    # Auto-consolidate if threshold reached
    conversation = conversation_service.get_conversation(db, conversation_id)
    if conversation.space_id:
        try:
            from backend.openloop.services import consolidation_service

            count = consolidation_service.get_unconsolidated_count(db, conversation.space_id)
            if count >= 20:
                logger.info(
                    "Auto-consolidating %d summaries for space %s",
                    count,
                    conversation.space_id,
                )
                await consolidation_service.generate_meta_summary(db, conversation.space_id)
        except (Exception, ExceptionGroup) as exc:
            logger.warning(
                "Auto-consolidation failed for space %s (non-blocking): %s",
                conversation.space_id,
                exc,
            )

    # Close the conversation in DB
    conversation_service.close_conversation(db, conversation_id)

    # Clean up conversation lock
    _conversation_locks.pop(conversation_id, None)

    return summary_text


# ---------------------------------------------------------------------------
# Flush memory
# ---------------------------------------------------------------------------


async def flush_memory(db: Session, *, conversation_id: str) -> None:
    """Mandatory pre-compaction memory flush.

    Injects an instruction to the agent to save unsaved facts before
    any summarization or compression occurs.
    """
    from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

    conversation = conversation_service.get_conversation(db, conversation_id)
    sdk_session_id = conversation.sdk_session_id
    if not sdk_session_id:
        return

    agent = agent_service.get_agent(db, conversation.agent_id)
    mcp_server = _build_mcp_server(agent, agent.id)
    model_name = conversation.model_override or agent.default_model
    model = resolve_model(model_name)
    hooks = _build_hooks_dict(conversation.agent_id, conversation_id)

    new_session_id: str | None = None
    try:
        async for event in query(
            prompt=FLUSH_MEMORY_PROMPT,
            options=ClaudeAgentOptions(
                resume=sdk_session_id,
                model=model,
                mcp_servers={mcp_server["name"]: mcp_server},
                hooks=hooks,
            ),
        ):
            if isinstance(event, ResultMessage):
                if event.session_id and event.session_id != sdk_session_id:
                    new_session_id = event.session_id
    except (Exception, ExceptionGroup) as exc:
        logger.warning(
            "flush_memory failed for conversation %s (non-blocking): %s",
            conversation_id,
            exc,
        )
        return

    # Persist session_id change with a short-lived DB session
    if new_session_id:
        db_post = _new_db_session()
        try:
            conversation_service.update_conversation(
                db_post, conversation_id, sdk_session_id=new_session_id
            )
        finally:
            db_post.close()


# ---------------------------------------------------------------------------
# Steering
# ---------------------------------------------------------------------------


async def steer(conversation_id: str, message: str) -> bool:
    """Queue a steering message for a running background task.

    The managed turn loop picks this up at the next turn boundary.
    Returns True if queued successfully.
    """
    from backend.openloop.agents.event_bus import event_bus

    # Validate steering message length
    if len(message) > 2000:
        raise HTTPException(
            status_code=422,
            detail="Steering message exceeds 2000-character limit",
        )

    if conversation_id not in _background_conversations:
        return False

    queue = _steering_queues.setdefault(conversation_id, [])
    if len(queue) >= MAX_STEERING_MESSAGES:
        return False

    queue.append(message)

    await event_bus.publish_to(conversation_id, {
        "type": "steering_received",
        "conversation_id": conversation_id,
        "message": message,
    })
    logger.info("Steering message queued for conversation %s", conversation_id)
    return True


# ---------------------------------------------------------------------------
# Soft budget constants (Phase 8.6b)
# ---------------------------------------------------------------------------

# Absolute safety limit — should almost never be hit if budgets + compaction work
MAX_TURNS = 500

# Default time budget: 4 hours (seconds).  Applied when time_budget is None.
DEFAULT_TIME_BUDGET = 14400

# Budget-exhausted final turn prompt
BUDGET_EXHAUSTED_PROMPT = (
    "Your budget is exhausted. Summarize your progress, save any important "
    "context to memory, and report what's done and what remains."
)


def _format_time_remaining(seconds: float) -> str:
    """Format remaining seconds as 'Xh Ym' or 'Ym' if under an hour."""
    if seconds <= 0:
        return "0m"
    hours = int(seconds // 3600)
    minutes = int(math.ceil((seconds % 3600) / 60))
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def _check_budget_exhausted(
    *,
    db: "Session",
    task_id: str,
    conversation_id: str,
    started_at: datetime,
) -> tuple[bool, str | None]:
    """Check whether the task's token or time budget has been exceeded.

    Returns (exhausted, reason_string).
    """
    task_record = background_task_service.get_background_task(db, task_id)

    # --- Token budget ---
    if task_record.token_budget and task_record.token_budget > 0:
        total_used = _sum_conversation_tokens(db, conversation_id)
        if total_used >= task_record.token_budget:
            return True, (
                f"token budget exhausted ({total_used:,} / "
                f"{task_record.token_budget:,} tokens used)"
            )

    # --- Time budget ---
    effective_time_budget = task_record.time_budget or DEFAULT_TIME_BUDGET
    # Ensure started_at is timezone-aware (SQLite may return naive datetimes)
    aware_started = started_at if started_at.tzinfo else started_at.replace(tzinfo=UTC)
    elapsed = (datetime.now(UTC) - aware_started).total_seconds()
    if elapsed >= effective_time_budget:
        return True, (
            f"time budget exhausted ({_format_time_remaining(elapsed)} elapsed, "
            f"budget was {_format_time_remaining(effective_time_budget)})"
        )

    return False, None


def _build_continuation_prompt(
    *,
    db: "Session",
    task_id: str,
    conversation_id: str,
    turn: int,
    started_at: datetime,
    compacted: bool = False,
    compaction_summary: str | None = None,
) -> str:
    """Build a context-aware continuation prompt for the background turn loop.

    The goal/instruction is re-injected from the DB on every continuation
    prompt so it is never lost during compaction. This follows the OpenClaw
    pattern: instructions stored externally, re-injected each turn.

    Includes: original goal, turn number, progress (if available), budget
    remaining, queued approvals (if any), and compaction note (if just
    compacted).

    For non-autonomous tasks (no task list / no progress tracking),
    produces a simpler prompt.
    """
    task_record = background_task_service.get_background_task(db, task_id)
    parts: list[str] = []

    # --- Re-inject goal from DB (survives compaction) ---
    goal_text = task_record.goal or task_record.instruction
    if goal_text:
        parts.append(f"Goal: {goal_text}")

    # --- Compaction note ---
    if compacted:
        note = (
            "Context was compacted — older turns have been summarized."
        )
        if compaction_summary:
            note += f" Summary of prior work: {compaction_summary}"
        parts.append(note)

    # --- Progress info (only if total_count > 0, which is a Phase 9 field) ---
    total_count = getattr(task_record, "total_count", 0) or 0
    completed_count = getattr(task_record, "completed_count", 0) or 0
    is_autonomous = total_count > 0

    if is_autonomous:
        parts.append(f"Turn {turn}. Progress: {completed_count}/{total_count} items completed.")
    else:
        parts.append(f"Turn {turn}.")

    # --- Budget remaining ---
    budget_parts: list[str] = []

    # Token budget
    if task_record.token_budget and task_record.token_budget > 0:
        total_used = _sum_conversation_tokens(db, conversation_id)
        remaining = max(0, task_record.token_budget - total_used)
        budget_parts.append(f"{remaining:,} tokens remaining")

    # Time budget
    effective_time_budget = task_record.time_budget or DEFAULT_TIME_BUDGET
    aware_started = started_at if started_at.tzinfo else started_at.replace(tzinfo=UTC)
    elapsed = (datetime.now(UTC) - aware_started).total_seconds()
    time_remaining = max(0.0, effective_time_budget - elapsed)
    budget_parts.append(f"{_format_time_remaining(time_remaining)} remaining")

    if budget_parts:
        parts.append("Budget: " + ", ".join(budget_parts) + ".")

    # --- Queued approvals (Phase 9 field, may not exist yet) ---
    queued = getattr(task_record, "queued_approvals_count", 0) or 0
    if queued > 0:
        parts.append(f"{queued} approval(s) queued — check before continuing.")

    # --- Delegation status (Phase 10.2) ---
    child_tasks = background_task_service.list_child_tasks(db, task_id)
    if child_tasks:
        delegation_lines = ["Sub-agent status:"]
        for child in child_tasks:
            label = child.instruction[:60] if child.instruction else "Unknown"
            line = f'- Task "{label}" ({child.id}): {child.status.upper()}'
            if child.status == "completed" and child.result_summary:
                line += f' — "{child.result_summary[:100]}"'
            elif child.status == "running":
                c_done = child.completed_count or 0
                c_total = child.total_count or 0
                if c_total > 0:
                    line += f" — step {c_done}/{c_total}"
            elif child.status == "failed" and child.error:
                line += f' — "{child.error[:100]}"'
            delegation_lines.append(line)
        parts.append("\n".join(delegation_lines))

    # --- Closing instruction ---
    if is_autonomous:
        parts.append(
            "Pick the next item to work on. If priorities have shifted "
            "based on what you've learned, adjust your approach."
        )
    else:
        parts.append("Continue working on the task.")

    parts.append("Say TASK_COMPLETE or GOAL_COMPLETE when finished.")

    return " ".join(parts)


# ---------------------------------------------------------------------------
# Background delegation
# ---------------------------------------------------------------------------


async def delegate_background(
    db: Session,
    *,
    agent_id: str,
    instruction: str,
    space_id: str | None = None,
    item_id: str | None = None,
    parent_task_id: str | None = None,
    automation_run_id: str | None = None,
    model_override: str | None = None,
    run_type: str = "task",
    delegation_depth: int = 0,
    narrowed_permissions=None,
) -> str:
    """Delegate work to an agent as a background task.

    Creates a background_task record, fires a managed turn loop.
    Returns the background_task ID.

    When delegation_depth > 0 and narrowed_permissions is provided, the
    child task runs with a restricted permission set enforced by the hook.
    """
    # Kill switch guard — refuse new background work while paused
    if system_service.is_paused(db):
        raise HTTPException(
            status_code=503,
            detail="System is paused (emergency stop active). Resume before starting background work.",
        )

    # Determine the concurrency lane based on task type
    if parent_task_id:
        lane = "subagent"
    elif automation_run_id or run_type == "heartbeat":
        lane = "automation"
    else:
        lane = "autonomous"
    _check_concurrency(db, lane)

    # Resolve automation_id from the run record (for lane tracking on BackgroundTask)
    resolved_automation_id: str | None = None
    if automation_run_id:
        from backend.openloop.db.models import AutomationRun

        run = db.query(AutomationRun).filter(AutomationRun.id == automation_run_id).first()
        if run:
            resolved_automation_id = run.automation_id

    task = background_task_service.create_background_task(
        db,
        agent_id=agent_id,
        instruction=instruction,
        space_id=space_id,
        item_id=item_id,
        parent_task_id=parent_task_id,
        automation_id=resolved_automation_id,
        goal=instruction,
        run_type=run_type,
        status="running",
        delegation_depth=delegation_depth,
    )

    agent = agent_service.get_agent(db, agent_id)
    conv = conversation_service.create_conversation(
        db,
        agent_id=agent_id,
        name=f"Background: {instruction[:50]}",
        space_id=space_id,
    )

    # Link task to conversation
    task.conversation_id = conv.id
    db.commit()

    # Track this conversation as having an active background task
    _background_conversations.add(conv.id)

    # Fire-and-forget the actual execution.
    # Pass start_time so the turn loop can compute elapsed wall-clock time
    bg = asyncio.create_task(
        _run_background_task(
            task_id=task.id,
            conversation_id=conv.id,
            agent_id=agent.id,
            agent_name=agent.name,
            default_model=agent.default_model,
            instruction=instruction,
            space_id=space_id,
            automation_run_id=automation_run_id,
            model_override=model_override,
            run_type=run_type,
            narrowed_permissions=narrowed_permissions,
        )
    )
    _background_tasks.add(bg)
    bg.add_done_callback(_task_done)

    return task.id


async def _run_background_task(
    *,
    task_id: str,
    conversation_id: str,
    agent_id: str,
    agent_name: str,
    default_model: str,
    instruction: str,
    space_id: str | None,
    automation_run_id: str | None = None,
    model_override: str | None = None,
    run_type: str = "task",
    narrowed_permissions=None,
) -> None:
    """Managed turn loop — agent works in discrete turns with steering checkpoints.

    1. First turn: send the instruction with system_prompt in options
    2. Each subsequent turn: check steering queue, then continue or steer
    3. Agent signals completion with TASK_COMPLETE in its response
    4. Progress is tracked per-turn via background_task step updates
    5. Context monitoring after each turn — triggers compaction at 70% (Phase 8.6a)
    """
    from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, StreamEvent, query

    from backend.openloop.agents.event_bus import event_bus
    from backend.openloop.services import audit_service

    mcp_server = _build_mcp_server_by_name(agent_name, agent_id)
    model = resolve_model(model_override or default_model)

    db = _new_db_session()
    turn = 0
    # Track all turn results for PersistentData extractors (Phase 8.6a)
    all_turn_results: list[str] = []
    # Track compaction count
    compaction_count = 0
    try:
        # Kill switch guard — abort if system is paused before starting
        if system_service.is_paused(db):
            logger.info("Background task %s skipped — system is paused", task_id)
            background_task_service.update_background_task(
                db,
                task_id,
                status="interrupted",
                error="System paused (emergency stop)",
                completed_at=datetime.now(UTC),
            )
            return

        # Store the goal on the task record for compaction verification
        background_task_service.update_background_task(db, task_id, goal=instruction)

        # Record started_at for time budget tracking (ensure timezone-aware)
        task_record = background_task_service.get_background_task(db, task_id)
        raw_started = task_record.started_at or datetime.now(UTC)
        started_at = raw_started if raw_started.tzinfo else raw_started.replace(tzinfo=UTC)

        # Assemble context for the system prompt
        system_prompt = context_assembler.assemble_context(
            db,
            agent_id=agent_id,
            space_id=space_id,
            conversation_id=conversation_id,
        )

        task_instruction = (
            f"Task: {instruction}\n\n"
            "Work incrementally. Complete one meaningful step per turn. "
            "Report what you did and what you plan to do next. "
            "Say TASK_COMPLETE or GOAL_COMPLETE when the entire task is finished."
        )

        hooks = _build_hooks_dict(
            agent_id, conversation_id,
            background_task_id=task_id,
            narrowed_permissions=narrowed_permissions,
        )

        sdk_session_id: str | None = None
        result_text = ""
        completed = False
        budget_exhausted = False
        # Flag: set after compaction so next continuation uses special prompt
        just_compacted = False
        compaction_summary: str | None = None

        while not completed and not budget_exhausted and turn < MAX_TURNS:
            turn += 1

            # Determine what to send this turn
            if turn == 1:
                prompt_message = task_instruction
            else:
                # Check for steering messages first
                queue = _steering_queues.get(conversation_id, [])
                if queue:
                    raw_steering = queue.pop(0)
                    prompt_message = f"<steering>{raw_steering}</steering>"
                    logger.info("Steering message applied for task %s at turn %d", task_id, turn)
                else:
                    prompt_message = _build_continuation_prompt(
                        db=db,
                        task_id=task_id,
                        conversation_id=conversation_id,
                        turn=turn,
                        started_at=started_at,
                        compacted=just_compacted,
                        compaction_summary=compaction_summary if just_compacted else None,
                    )
                # Reset compaction flags after building prompt
                if just_compacted:
                    just_compacted = False
                    compaction_summary = None

            # Build query kwargs — system_prompt on turn 1, resume on subsequent turns
            if turn == 1:
                query_kwargs: dict = {
                    "prompt": prompt_message,
                    "options": ClaudeAgentOptions(
                        system_prompt=system_prompt,
                        model=model,
                        mcp_servers={mcp_server["name"]: mcp_server},
                        hooks=hooks,
                    ),
                }
            else:
                query_kwargs = {
                    "prompt": prompt_message,
                    "options": ClaudeAgentOptions(
                        resume=sdk_session_id,
                        model=model,
                        mcp_servers={mcp_server["name"]: mcp_server},
                        hooks=hooks,
                    ),
                }

            # Execute one turn with rate limit retry
            turn_result = ""
            turn_result_message = None
            async for event in _query_with_retry(
                query,
                query_kwargs,
                conversation_id=conversation_id,
                space_id=space_id,
            ):
                if isinstance(event, StreamEvent):
                    # StreamEvent processing — tool calls are audited by the
                    # permission hook (which now has background_task_id), so
                    # no duplicate logging here.
                    pass
                elif isinstance(event, ResultMessage):
                    sdk_session_id = event.session_id
                    turn_result = event.result or ""
                    turn_result_message = event

            result_text = turn_result
            all_turn_results.append(turn_result)

            # --- Token extraction (Phase 8.4) ---
            turn_input_tokens: int | None = None
            turn_output_tokens: int | None = None
            if turn_result_message and hasattr(turn_result_message, "usage") and turn_result_message.usage:
                usage = turn_result_message.usage
                if not isinstance(usage, dict):
                    usage = vars(usage) if hasattr(usage, "__dict__") else {}
                turn_input_tokens = usage.get("input_tokens")
                turn_output_tokens = usage.get("output_tokens")

            # Store assistant message with token counts
            if turn_result:
                conversation_service.add_message(
                    db,
                    conversation_id=conversation_id,
                    role="assistant",
                    content=turn_result,
                    input_tokens=turn_input_tokens,
                    output_tokens=turn_output_tokens,
                )

            # Check for completion signal (TASK_COMPLETE, GOAL_COMPLETE, or HEARTBEAT_OK)
            upper_result = (turn_result or "").upper()
            if "TASK_COMPLETE" in upper_result or "GOAL_COMPLETE" in upper_result:
                completed = True
            elif run_type == "heartbeat" and "HEARTBEAT_OK" in upper_result:
                completed = True

            # Update step progress (don't predict total_steps from MAX_TURNS —
            # with soft budgets the total is unknown until completion)
            background_task_service.update_task_progress(
                db,
                task_id=task_id,
                current_step=turn,
                total_steps=turn if completed else 0,
                step_summary=turn_result[:500] if turn_result else f"Turn {turn}",
            )

            # Publish activity to SSE
            await event_bus.publish_to(conversation_id, {
                "type": "background_progress",
                "conversation_id": conversation_id,
                "task_id": task_id,
                "turn": turn,
                "completed": completed,
                "summary": turn_result[:200] if turn_result else "",
            })

            # --- Kill switch check at turn boundary (Phase 8.4) ---
            if not completed and system_service.is_paused(db):
                logger.info("Background task %s interrupted by kill switch at turn %d", task_id, turn)
                background_task_service.update_background_task(
                    db,
                    task_id,
                    status="interrupted",
                    error="System paused (emergency stop) at turn boundary",
                    completed_at=datetime.now(UTC),
                )
                return

            # --- Soft budget check (Phase 8.6b — replaces 8.4 token-only check) ---
            if not completed:
                exhausted, reason = _check_budget_exhausted(
                    db=db,
                    task_id=task_id,
                    conversation_id=conversation_id,
                    started_at=started_at,
                )
                if exhausted:
                    logger.info(
                        "Budget exhausted for task %s (%s) — giving agent "
                        "one final turn",
                        task_id,
                        reason,
                    )
                    budget_exhausted = True
                    # Give the agent one final turn to wrap up
                    final_kwargs = {
                        "prompt": BUDGET_EXHAUSTED_PROMPT,
                        "options": ClaudeAgentOptions(
                            resume=sdk_session_id,
                            model=model,
                            mcp_servers={mcp_server["name"]: mcp_server},
                            hooks=hooks,
                        ),
                    }
                    final_result = ""
                    async for evt in _query_with_retry(
                        query,
                        final_kwargs,
                        conversation_id=conversation_id,
                        space_id=space_id,
                    ):
                        if isinstance(evt, ResultMessage):
                            sdk_session_id = evt.session_id
                            final_result = evt.result or ""
                            # Extract final turn tokens
                            if hasattr(evt, "usage") and evt.usage:
                                f_usage = evt.usage
                                if not isinstance(f_usage, dict):
                                    f_usage = vars(f_usage) if hasattr(f_usage, "__dict__") else {}
                                conversation_service.add_message(
                                    db,
                                    conversation_id=conversation_id,
                                    role="assistant",
                                    content=final_result,
                                    input_tokens=f_usage.get("input_tokens"),
                                    output_tokens=f_usage.get("output_tokens"),
                                )
                            elif final_result:
                                conversation_service.add_message(
                                    db,
                                    conversation_id=conversation_id,
                                    role="assistant",
                                    content=final_result,
                                )

                    result_text = final_result or result_text

            # --- Context monitoring & compaction (Phase 8.6a) ---
            if not completed and not budget_exhausted:
                estimated_context = _estimate_conversation_context(
                    db, conversation_id, ""
                )
                utilization = estimated_context / CONTEXT_WINDOW_TOKENS
                if utilization > CHECKPOINT_THRESHOLD:
                    logger.info(
                        "Background task %s context at ~%.0f%% — triggering "
                        "compaction cycle (turn %d)",
                        task_id,
                        utilization * 100,
                        turn,
                    )
                    success, cycle_summary, new_sid = await _run_compaction_cycle(
                        db=db,
                        task_id=task_id,
                        conversation_id=conversation_id,
                        agent_id=agent_id,
                        agent_name=agent_name,
                        space_id=space_id,
                        instruction=instruction,
                        turn_results=all_turn_results,
                        sdk_session_id=sdk_session_id,
                        model=model,
                        hooks=hooks,
                    )
                    if new_sid:
                        sdk_session_id = new_sid
                    if not success:
                        # Verification failed — session already marked interrupted
                        return
                    compaction_count += 1
                    just_compacted = True
                    compaction_summary = cycle_summary

        # Persist sdk_session_id
        conversation_service.update_conversation(db, conversation_id, sdk_session_id=sdk_session_id)

        # Mark task as completed
        if completed:
            status_note = ""
        elif budget_exhausted:
            status_note = " (budget exhausted)"
        else:
            status_note = " (max turns reached)"
        background_task_service.update_background_task(
            db,
            task_id,
            status="completed",
            result_summary=(result_text[:2000] if result_text else None),
            completed_at=datetime.now(UTC),
        )

        # Heartbeat-specific completion handling
        is_heartbeat = run_type == "heartbeat"
        heartbeat_ok = is_heartbeat and "HEARTBEAT_OK" in (result_text or "").upper()

        if heartbeat_ok:
            # Silent completion — no user-visible notification
            logger.info("Heartbeat OK for agent %s (task %s) — no action needed", agent_id, task_id)
        elif is_heartbeat:
            # Heartbeat took action — create audit log + notification
            audit_service.log_action(
                db,
                agent_id=agent_id,
                action="heartbeat_action",
                background_task_id=task_id,
                tool_name="heartbeat",
                input_summary=f"Heartbeat took action: {result_text[:200] if result_text else 'unknown'}",
            )
            notification_service.create_notification(
                db,
                type="heartbeat_action",
                title=f"Heartbeat: {agent_name} took action",
                body=result_text[:500] if result_text else "Agent took action during heartbeat check-in.",
                space_id=space_id,
            )
        else:
            notification_service.create_notification(
                db,
                type="task_completed",
                title="Background task completed",
                body=f"Task completed{status_note}: {instruction[:100]}",
                space_id=space_id,
            )

        # Sub-agent completion notification (Phase 10.1)
        from contract.enums import NotificationType
        task_record = background_task_service.get_background_task(db, task_id)
        if task_record.parent_task_id:
            notification_service.create_notification(
                db,
                type=NotificationType.SUB_TASK_COMPLETED,
                title=f"Sub-task completed: {agent_name}",
                body=(
                    f"Delegated sub-task finished: {instruction[:100]}"
                    + (f"\nResult: {result_text[:300]}" if result_text else "")
                ),
                space_id=space_id,
            )

        # Complete the automation run if this was triggered by an automation
        if automation_run_id:
            from backend.openloop.services import automation_service

            automation_service.complete_run(
                db,
                run_id=automation_run_id,
                status="completed",
                result_summary=result_text[:2000] if result_text else None,
            )

    except (Exception, ExceptionGroup) as exc:
        logger.error("Background task %s failed at turn %d: %s", task_id, turn, exc)
        db.rollback()

        background_task_service.update_background_task(
            db,
            task_id,
            status="failed",
            error=str(exc)[:2000],
            completed_at=datetime.now(UTC),
        )

        # Cascade-cancel all child tasks (Phase 10.1)
        cancelled_count = background_task_service.cascade_update_status(
            db, task_id,
            new_status="cancelled",
            error_note=f"Parent task {task_id} failed",
        )
        if cancelled_count > 0:
            logger.info(
                "Cascade-cancelled %d child task(s) of failed task %s",
                cancelled_count, task_id,
            )

        conversation_service.update_conversation(db, conversation_id, status="interrupted")

        notification_service.create_notification(
            db,
            type="task_failed",
            title="Background task failed",
            body=f"Task failed: {instruction[:100]}. Error: {exc}",
            space_id=space_id,
        )

        if automation_run_id:
            try:
                from backend.openloop.services import automation_service

                automation_service.complete_run(
                    db,
                    run_id=automation_run_id,
                    status="failed",
                    error=str(exc)[:2000],
                )
            except Exception:
                logger.error("Failed to complete automation run %s", automation_run_id)
    finally:
        db.close()
        # Clean up background tracking and steering queue
        _background_conversations.discard(conversation_id)
        _steering_queues.pop(conversation_id, None)


# ---------------------------------------------------------------------------
# Autonomous launch — goal-driven execution (Phase 9.2b)
# ---------------------------------------------------------------------------

# Prompt constants for autonomous mode
AUTONOMOUS_FIRST_TURN_PROMPT = (
    "You are starting an autonomous run. Your goal: {goal}\n\n"
    "{constraints_text}"
    "Survey the space and generate a task list. Output your plan as a JSON "
    'array of items: [{{"title": "...", "status": "pending"}}, ...]\n\n'
    "Work incrementally. Complete one meaningful step per turn. "
    "Report what you did and what you plan to do next. "
    "Say GOAL_COMPLETE when the entire goal is finished."
)

AUTONOMOUS_NEXT_ITEM_PROMPT = (
    "Pick the next pending item from your task list and work on it. "
    "After completing an item, use the update_task_list tool to mark it done. "
    "Say GOAL_COMPLETE when all items are finished."
)

# In-memory set of paused task IDs (checked at turn boundaries)
_paused_tasks: set[str] = set()


async def launch_autonomous(
    db: Session,
    *,
    agent_id: str,
    space_id: str | None = None,
    goal: str,
    constraints: str | None = None,
    token_budget: int | None = None,
    time_budget: int | None = None,
) -> tuple[str, str]:
    """Start an autonomous launch conversation.

    Creates a BackgroundTask (status=pending) and a Conversation for the
    clarification phase. The agent does NOT start autonomous execution yet —
    the user chats with the agent to clarify the goal, then calls
    approve_autonomous_launch() to begin.

    Returns (conversation_id, task_id).
    Raises 409 if the agent already has an active autonomous run.
    """
    from backend.openloop.db.models import BackgroundTask as BT

    # Guard: one autonomous run per agent at a time
    existing = (
        db.query(BT)
        .filter(
            BT.agent_id == agent_id,
            BT.run_type == "autonomous",
            BT.status.in_(["pending", "running"]),
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail="Agent already has an active autonomous run",
        )

    # Kill switch guard
    if system_service.is_paused(db):
        raise HTTPException(
            status_code=503,
            detail="System is paused (emergency stop active). Resume before starting autonomous work.",
        )

    # Concurrency check
    _check_concurrency(db, "autonomous")

    # Validate agent exists
    agent = agent_service.get_agent(db, agent_id)

    # Create conversation for clarification phase
    conv = conversation_service.create_conversation(
        db,
        agent_id=agent_id,
        name=f"Autonomous: {goal[:50]}",
        space_id=space_id,
    )

    # Create BackgroundTask with status=pending (not running yet)
    task = background_task_service.create_background_task(
        db,
        agent_id=agent_id,
        instruction=goal,
        space_id=space_id,
        conversation_id=conv.id,
        goal=goal,
        time_budget=time_budget,
        token_budget=token_budget,
        run_type="autonomous",
        status="pending",
    )

    return conv.id, task.id


async def approve_autonomous_launch(
    db: Session,
    *,
    task_id: str,
) -> None:
    """Transition an autonomous task from pending to running.

    Fires the autonomous turn loop as an asyncio background task.
    """
    task = background_task_service.get_background_task(db, task_id)

    if task.status != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"Task is '{task.status}', not 'pending'. Cannot approve.",
        )

    if task.run_type != "autonomous":
        raise HTTPException(
            status_code=422,
            detail="Only autonomous tasks can be approved via this endpoint.",
        )

    # Kill switch guard
    if system_service.is_paused(db):
        raise HTTPException(
            status_code=503,
            detail="System is paused. Resume before approving autonomous work.",
        )

    # Transition to running
    background_task_service.update_background_task(db, task_id, status="running")

    agent = agent_service.get_agent(db, task.agent_id)

    # Track this conversation as having an active background task
    if task.conversation_id:
        _background_conversations.add(task.conversation_id)

    # Fire autonomous execution loop
    bg = asyncio.create_task(
        _run_autonomous_task(
            task_id=task.id,
            conversation_id=task.conversation_id,
            agent_id=agent.id,
            agent_name=agent.name,
            default_model=agent.default_model,
            goal=task.goal or task.instruction,
            constraints=None,  # constraints stored in goal text
            space_id=task.space_id,
        )
    )
    _background_tasks.add(bg)
    bg.add_done_callback(_task_done)


async def _run_autonomous_task(
    *,
    task_id: str,
    conversation_id: str | None,
    agent_id: str,
    agent_name: str,
    default_model: str,
    goal: str,
    constraints: str | None,
    space_id: str | None,
) -> None:
    """Autonomous turn loop — agent generates a task list and iterates through it.

    Similar to _run_background_task but with autonomous-specific behavior:
    1. First turn: agent receives goal + instruction to generate task list
    2. Parse task list from first response, store on BackgroundTask
    3. Subsequent turns: work through items, update progress
    4. Completion on GOAL_COMPLETE or budget exhaustion
    """
    from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, StreamEvent, query

    from backend.openloop.agents.event_bus import event_bus

    mcp_server = _build_mcp_server_by_name(agent_name, agent_id)
    model = resolve_model(default_model)

    db = _new_db_session()
    turn = 0
    all_turn_results: list[str] = []
    compaction_count = 0

    try:
        # Kill switch guard
        if system_service.is_paused(db):
            logger.info("Autonomous task %s skipped — system is paused", task_id)
            background_task_service.update_background_task(
                db, task_id,
                status="interrupted",
                error="System paused (emergency stop)",
                completed_at=datetime.now(UTC),
            )
            return

        # Record started_at for time budget tracking
        task_record = background_task_service.get_background_task(db, task_id)
        raw_started = task_record.started_at or datetime.now(UTC)
        started_at = raw_started if raw_started.tzinfo else raw_started.replace(tzinfo=UTC)

        # Assemble context for the system prompt
        system_prompt = context_assembler.assemble_context(
            db,
            agent_id=agent_id,
            space_id=space_id,
            conversation_id=conversation_id,
        )

        # Build first turn prompt
        constraints_text = f"Constraints: {constraints}\n\n" if constraints else ""
        first_prompt = AUTONOMOUS_FIRST_TURN_PROMPT.format(
            goal=goal, constraints_text=constraints_text
        )

        hooks = _build_hooks_dict(
            agent_id, conversation_id,
            background_task_id=task_id,
            autonomous_mode=True,
        )

        sdk_session_id: str | None = None
        # If the conversation already has an SDK session from clarification,
        # resume it instead of starting fresh
        if conversation_id:
            conv_record = conversation_service.get_conversation(db, conversation_id)
            if conv_record.sdk_session_id:
                sdk_session_id = conv_record.sdk_session_id

        result_text = ""
        completed = False
        budget_exhausted = False
        just_compacted = False
        compaction_summary: str | None = None
        task_list_parsed = False

        while not completed and not budget_exhausted and turn < MAX_TURNS:
            turn += 1

            # --- Pause check at turn boundary ---
            if task_id in _paused_tasks:
                logger.info("Autonomous task %s paused at turn %d", task_id, turn)
                background_task_service.update_background_task(
                    db, task_id, status="paused"
                )
                # Wait until resumed
                while task_id in _paused_tasks:
                    await asyncio.sleep(2)
                    # Check kill switch while paused
                    if system_service.is_paused(db):
                        background_task_service.update_background_task(
                            db, task_id,
                            status="interrupted",
                            error="System paused during autonomous pause",
                            completed_at=datetime.now(UTC),
                        )
                        return
                # Resumed — set status back to running
                background_task_service.update_background_task(
                    db, task_id, status="running"
                )
                logger.info("Autonomous task %s resumed at turn %d", task_id, turn)

            # Determine what to send this turn
            if turn == 1 and not sdk_session_id:
                # First turn — fresh start with system prompt
                prompt_message = first_prompt
            elif turn == 1 and sdk_session_id:
                # Resuming from clarification conversation — transition to autonomous
                prompt_message = (
                    "The user has approved the autonomous launch. Begin execution now.\n\n"
                    + first_prompt
                )
            else:
                # Check for steering messages
                queue = _steering_queues.get(conversation_id, [])
                if queue:
                    raw_steering = queue.pop(0)
                    prompt_message = f"<steering>{raw_steering}</steering>"
                    logger.info("Steering message applied for autonomous task %s at turn %d", task_id, turn)
                else:
                    prompt_message = _build_continuation_prompt(
                        db=db,
                        task_id=task_id,
                        conversation_id=conversation_id,
                        turn=turn,
                        started_at=started_at,
                        compacted=just_compacted,
                        compaction_summary=compaction_summary if just_compacted else None,
                    )
                if just_compacted:
                    just_compacted = False
                    compaction_summary = None

            # Build query kwargs
            if turn == 1 and not sdk_session_id:
                query_kwargs: dict = {
                    "prompt": prompt_message,
                    "options": ClaudeAgentOptions(
                        system_prompt=system_prompt,
                        model=model,
                        mcp_servers={mcp_server["name"]: mcp_server},
                        hooks=hooks,
                    ),
                }
            else:
                query_kwargs = {
                    "prompt": prompt_message,
                    "options": ClaudeAgentOptions(
                        resume=sdk_session_id,
                        model=model,
                        mcp_servers={mcp_server["name"]: mcp_server},
                        hooks=hooks,
                    ),
                }

            # Execute one turn
            turn_result = ""
            turn_result_message = None
            async for event in _query_with_retry(
                query, query_kwargs,
                conversation_id=conversation_id,
                space_id=space_id,
            ):
                if isinstance(event, StreamEvent):
                    pass
                elif isinstance(event, ResultMessage):
                    sdk_session_id = event.session_id
                    turn_result = event.result or ""
                    turn_result_message = event

            result_text = turn_result
            all_turn_results.append(turn_result)

            # Token extraction
            turn_input_tokens, turn_output_tokens = _extract_usage(turn_result_message)

            # Store assistant message
            if turn_result and conversation_id:
                conversation_service.add_message(
                    db,
                    conversation_id=conversation_id,
                    role="assistant",
                    content=turn_result,
                    input_tokens=turn_input_tokens,
                    output_tokens=turn_output_tokens,
                )

            # --- Parse task list from first turn response (or any turn) ---
            if not task_list_parsed and turn_result:
                parsed_list = _extract_task_list_json(turn_result)
                if parsed_list:
                    task_list_parsed = True
                    total = len(parsed_list)
                    completed_count = sum(
                        1 for item in parsed_list
                        if item.get("status") in ("done", "completed")
                    )
                    background_task_service.update_background_task(
                        db, task_id,
                        task_list=parsed_list,
                        task_list_version=1,
                        total_count=total,
                        completed_count=completed_count,
                    )
                    logger.info(
                        "Autonomous task %s: parsed task list with %d items",
                        task_id, total,
                    )

            # Check for completion signal
            upper_result = (turn_result or "").upper()
            if "GOAL_COMPLETE" in upper_result or "TASK_COMPLETE" in upper_result:
                completed = True

            # Update step progress
            background_task_service.update_task_progress(
                db, task_id,
                current_step=turn,
                total_steps=turn if completed else 0,
                step_summary=turn_result[:500] if turn_result else f"Turn {turn}",
            )

            # Publish autonomous progress SSE event
            task_record = background_task_service.get_background_task(db, task_id)
            await event_bus.publish({
                "type": "autonomous_progress",
                "task_id": task_id,
                "conversation_id": conversation_id,
                "turn": turn,
                "completed": completed,
                "completed_count": task_record.completed_count or 0,
                "total_count": task_record.total_count or 0,
                "task_list_version": task_record.task_list_version or 0,
                "summary": turn_result[:200] if turn_result else "",
            })

            # Also publish to conversation channel
            if conversation_id:
                await event_bus.publish_to(conversation_id, {
                    "type": "autonomous_progress",
                    "task_id": task_id,
                    "conversation_id": conversation_id,
                    "turn": turn,
                    "completed": completed,
                    "completed_count": task_record.completed_count or 0,
                    "total_count": task_record.total_count or 0,
                    "summary": turn_result[:200] if turn_result else "",
                })

            # Kill switch check
            if not completed and system_service.is_paused(db):
                logger.info("Autonomous task %s interrupted by kill switch at turn %d", task_id, turn)
                background_task_service.update_background_task(
                    db, task_id,
                    status="interrupted",
                    error="System paused (emergency stop) at turn boundary",
                    completed_at=datetime.now(UTC),
                )
                return

            # Soft budget check
            if not completed:
                exhausted, reason = _check_budget_exhausted(
                    db=db, task_id=task_id,
                    conversation_id=conversation_id,
                    started_at=started_at,
                )
                if exhausted:
                    logger.info(
                        "Budget exhausted for autonomous task %s (%s) — final turn",
                        task_id, reason,
                    )
                    budget_exhausted = True
                    final_kwargs = {
                        "prompt": BUDGET_EXHAUSTED_PROMPT,
                        "options": ClaudeAgentOptions(
                            resume=sdk_session_id,
                            model=model,
                            mcp_servers={mcp_server["name"]: mcp_server},
                            hooks=hooks,
                        ),
                    }
                    final_result = ""
                    async for evt in _query_with_retry(
                        query, final_kwargs,
                        conversation_id=conversation_id,
                        space_id=space_id,
                    ):
                        if isinstance(evt, ResultMessage):
                            sdk_session_id = evt.session_id
                            final_result = evt.result or ""
                            f_in, f_out = _extract_usage(evt)
                            if final_result and conversation_id:
                                conversation_service.add_message(
                                    db,
                                    conversation_id=conversation_id,
                                    role="assistant",
                                    content=final_result,
                                    input_tokens=f_in,
                                    output_tokens=f_out,
                                )
                    result_text = final_result or result_text

            # Context monitoring & compaction
            if not completed and not budget_exhausted and conversation_id:
                estimated_context = _estimate_conversation_context(
                    db, conversation_id, ""
                )
                utilization = estimated_context / CONTEXT_WINDOW_TOKENS
                if utilization > CHECKPOINT_THRESHOLD:
                    logger.info(
                        "Autonomous task %s context at ~%.0f%% — compacting (turn %d)",
                        task_id, utilization * 100, turn,
                    )
                    success, cycle_summary, new_sid = await _run_compaction_cycle(
                        db=db,
                        task_id=task_id,
                        conversation_id=conversation_id,
                        agent_id=agent_id,
                        agent_name=agent_name,
                        space_id=space_id,
                        instruction=goal,
                        turn_results=all_turn_results,
                        sdk_session_id=sdk_session_id,
                        model=model,
                        hooks=hooks,
                    )
                    if new_sid:
                        sdk_session_id = new_sid
                    if not success:
                        return
                    compaction_count += 1
                    just_compacted = True
                    compaction_summary = cycle_summary

        # Persist sdk_session_id
        if conversation_id:
            conversation_service.update_conversation(
                db, conversation_id, sdk_session_id=sdk_session_id
            )

        # Mark task completed first (sets completed_at for duration calc)
        background_task_service.update_background_task(
            db, task_id,
            status="completed",
            result_summary=result_text[:2000] if result_text else None,
            completed_at=datetime.now(UTC),
        )

        # Generate structured run summary (creates notification too)
        try:
            run_summary = summary_service.generate_run_summary(db, task_id)
        except Exception as e:
            logger.warning("Failed to generate run summary: %s", e)
            # Fallback summary
            if completed:
                run_summary = result_text[:2000] if result_text else "Goal completed."
            elif budget_exhausted:
                run_summary = f"Budget exhausted after {turn} turns. {result_text[:1500] if result_text else ''}"
            else:
                run_summary = f"Stopped after {turn} turns (max reached). {result_text[:1500] if result_text else ''}"
            background_task_service.update_background_task(
                db, task_id, run_summary=run_summary,
            )
            # Fallback notification
            notification_service.create_notification(
                db,
                type="task_completed",
                title="Autonomous run completed",
                body=f"Goal completed: {goal[:100]}",
                space_id=space_id,
            )

        # Publish goal_complete SSE event
        await event_bus.publish({
            "type": "goal_complete",
            "task_id": task_id,
            "conversation_id": conversation_id,
            "run_summary": (run_summary or "")[:500],
        })

    except (Exception, ExceptionGroup) as exc:
        logger.error("Autonomous task %s failed at turn %d: %s", task_id, turn, exc)
        db.rollback()

        background_task_service.update_background_task(
            db, task_id,
            status="failed",
            error=str(exc)[:2000],
            completed_at=datetime.now(UTC),
        )

        if conversation_id:
            conversation_service.update_conversation(db, conversation_id, status="interrupted")

        notification_service.create_notification(
            db,
            type="task_failed",
            title="Autonomous run failed",
            body=f"Goal failed: {goal[:100]}. Error: {exc}",
            space_id=space_id,
        )
    finally:
        db.close()
        if conversation_id:
            _background_conversations.discard(conversation_id)
            _steering_queues.pop(conversation_id, None)


def _extract_task_list_json(text: str) -> list | None:
    """Extract a JSON array from agent response text.

    Looks for the first JSON array in the text (possibly wrapped in markdown
    code blocks). Returns the parsed list or None.
    """
    import json as _json

    # Try to find JSON array in markdown code blocks first
    code_block_pattern = re.compile(r"```(?:json)?\s*\n?(\[.*?\])\s*\n?```", re.DOTALL)
    match = code_block_pattern.search(text)
    if match:
        try:
            parsed = _json.loads(match.group(1))
            if isinstance(parsed, list) and len(parsed) > 0:
                return parsed
        except (ValueError, TypeError):
            pass

    # Try to find a bare JSON array
    bracket_pattern = re.compile(r"\[[\s\S]*?\]")
    for match in bracket_pattern.finditer(text):
        try:
            parsed = _json.loads(match.group())
            if isinstance(parsed, list) and len(parsed) > 0:
                # Validate it looks like a task list
                if all(isinstance(item, dict) and "title" in item for item in parsed):
                    return parsed
        except (ValueError, TypeError):
            continue

    return None


async def pause_autonomous(db: Session, *, task_id: str) -> None:
    """Pause an autonomous task at the next turn boundary.

    The turn loop checks _paused_tasks at each iteration.
    Also cascade-pauses all child tasks (Phase 10.1).
    """
    task = background_task_service.get_background_task(db, task_id)

    if task.run_type != "autonomous":
        raise HTTPException(status_code=422, detail="Only autonomous tasks can be paused.")

    if task.status not in ("running", "pending"):
        raise HTTPException(
            status_code=409,
            detail=f"Task is '{task.status}', cannot pause.",
        )

    _paused_tasks.add(task_id)
    # If it's still pending (not yet in the turn loop), mark immediately
    if task.status == "pending":
        background_task_service.update_background_task(db, task_id, status="paused")

    # Cascade-pause child tasks (Phase 10.1)
    paused_count = background_task_service.cascade_update_status(
        db, task_id,
        new_status="paused",
    )
    # Also add child tasks to the in-memory paused set so their turn loops stop
    for child_id in background_task_service.get_all_descendant_task_ids(db, task_id):
        _paused_tasks.add(child_id)

    if paused_count > 0:
        logger.info("Cascade-paused %d child task(s) of task %s", paused_count, task_id)

    logger.info("Autonomous task %s marked for pause", task_id)


async def resume_autonomous(db: Session, *, task_id: str) -> None:
    """Resume a paused autonomous task.

    If the task was paused mid-run, the turn loop will resume.
    If the task was paused before the loop started (pending->paused),
    we re-fire the turn loop.
    Also cascade-resumes all child tasks (Phase 10.1).
    """
    task = background_task_service.get_background_task(db, task_id)

    if task.run_type != "autonomous":
        raise HTTPException(status_code=422, detail="Only autonomous tasks can be resumed.")

    if task.status != "paused":
        raise HTTPException(
            status_code=409,
            detail=f"Task is '{task.status}', not 'paused'. Cannot resume.",
        )

    # Remove from paused set — the turn loop will notice and continue
    _paused_tasks.discard(task_id)

    # Cascade-resume child tasks (Phase 10.1)
    descendant_ids = background_task_service.get_all_descendant_task_ids(db, task_id)
    for child_id in descendant_ids:
        _paused_tasks.discard(child_id)
    # Update DB status for paused children back to running
    from backend.openloop.db.models import BackgroundTask as BT

    resumed_count = 0
    for child_id in descendant_ids:
        child_task = db.query(BT).filter(BT.id == child_id).first()
        if child_task and child_task.status == "paused":
            child_task.status = "running"
            resumed_count += 1
    if resumed_count > 0:
        db.commit()
        logger.info("Cascade-resumed %d child task(s) of task %s", resumed_count, task_id)

    # Check if the task is actually in the turn loop (has a conversation in _background_conversations)
    if task.conversation_id and task.conversation_id in _background_conversations:
        # Turn loop is alive, it will pick up the resume
        background_task_service.update_background_task(db, task_id, status="running")
        logger.info("Autonomous task %s resumed (turn loop active)", task_id)
    else:
        # Turn loop is not running — need to re-fire it
        background_task_service.update_background_task(db, task_id, status="running")
        agent = agent_service.get_agent(db, task.agent_id)

        if task.conversation_id:
            _background_conversations.add(task.conversation_id)

        bg = asyncio.create_task(
            _run_autonomous_task(
                task_id=task.id,
                conversation_id=task.conversation_id,
                agent_id=agent.id,
                agent_name=agent.name,
                default_model=agent.default_model,
                goal=task.goal or task.instruction,
                constraints=None,
                space_id=task.space_id,
            )
        )
        _background_tasks.add(bg)
        bg.add_done_callback(_task_done)
        logger.info("Autonomous task %s resumed (turn loop re-fired)", task_id)


# ---------------------------------------------------------------------------
# PersistentData extractor for autonomous task lists (Phase 9.2b)
# ---------------------------------------------------------------------------


def _extract_autonomous_task_list(instruction: str, turn_results: list[str]) -> dict:
    """Extract the current task list from the most recent BackgroundTask.

    This is called during compaction to ensure the task list survives
    context compression.
    """
    db = _new_db_session()
    try:
        from backend.openloop.db.models import BackgroundTask as BT

        # Find the most recent autonomous task matching this instruction
        task = (
            db.query(BT)
            .filter(
                BT.run_type == "autonomous",
                BT.goal == instruction,
                BT.status.in_(["running", "paused"]),
            )
            .order_by(BT.created_at.desc())
            .first()
        )
        if task and task.task_list:
            return {
                "task_list": task.task_list,
                "task_list_version": task.task_list_version,
                "completed_count": task.completed_count,
                "total_count": task.total_count,
            }
    except Exception:
        logger.debug("Failed to extract autonomous task list", exc_info=True)
    finally:
        db.close()
    return {}


# Register the extractor at module load time
register_persistent_extractor(_extract_autonomous_task_list)


def _build_mcp_server_by_name(agent_name: str, agent_id: str):
    """Build MCP server from agent name (used in background tasks where we
    don't have the full agent ORM object)."""
    is_odin = agent_name.lower() == "odin"
    is_agent_builder = agent_name.lower() in ("agent-builder", "agent builder")
    if is_odin:
        return build_odin_tools(agent_id)
    elif is_agent_builder:
        from backend.openloop.agents.mcp_tools import build_agent_builder_tools

        return build_agent_builder_tools(agent_name, agent_id)
    else:
        return build_agent_tools(agent_name, agent_id)


# ---------------------------------------------------------------------------
# Crash recovery
# ---------------------------------------------------------------------------


def recover_from_crash(db: Session) -> int:
    """Recover from a crash by marking active conversations as interrupted.

    Called during FastAPI lifespan startup. Returns the number of interrupted
    conversations.
    """
    active_convs = conversation_service.list_conversations(db, status="active", limit=10000)
    count = len(active_convs)

    for conv in active_convs:
        conversation_service.update_conversation(db, conv.id, status="interrupted")

    if count > 0:
        notification_service.create_notification(
            db,
            type="system",
            title="Conversations interrupted",
            body=f"{count} conversation(s) were interrupted by a restart.",
        )
        logger.warning("Crash recovery: marked %d active conversations as interrupted", count)

    # Clean up orphaned background tasks (running/queued at crash time)
    from contract.enums import BackgroundTaskStatus

    from backend.openloop.db.models import BackgroundTask

    stale_statuses = [BackgroundTaskStatus.RUNNING, BackgroundTaskStatus.QUEUED]
    orphaned_tasks = (
        db.query(BackgroundTask)
        .filter(BackgroundTask.status.in_(stale_statuses))
        .all()
    )
    now = datetime.now(UTC)

    # Pass 1: Autonomous tasks — check if resumable
    autonomous_tasks = [t for t in orphaned_tasks if t.run_type == "autonomous"]
    regular_tasks = [
        t for t in orphaned_tasks
        if t.run_type != "autonomous" and not t.parent_task_id
    ]
    subagent_tasks = [
        t for t in orphaned_tasks
        if t.parent_task_id is not None and t.run_type != "autonomous"
    ]

    resumed_count = 0
    failed_count = 0

    for task in autonomous_tasks:
        if _is_resumable(task):
            task.status = BackgroundTaskStatus.PENDING_RESUME
            resumed_count += 1
        else:
            progress = (
                f" (completed {task.completed_count}/{task.total_count} items)"
                if task.total_count
                else ""
            )
            task.error = f"Server restarted during execution{progress}"
            task.status = BackgroundTaskStatus.FAILED
            task.completed_at = now
            failed_count += 1

    # Pass 2: Sub-agent tasks — always mark failed (coordinator will re-delegate)
    for task in subagent_tasks:
        task.status = BackgroundTaskStatus.FAILED
        task.error = "Server restarted during execution (sub-agent)"
        task.completed_at = now
        failed_count += 1

    # Pass 3: Regular tasks + heartbeats — existing behavior
    for task in regular_tasks:
        task.status = BackgroundTaskStatus.FAILED
        task.error = "Server restarted during execution"
        task.completed_at = now
        failed_count += 1

    if orphaned_tasks:
        db.commit()
        parts = []
        if resumed_count:
            parts.append(f"{resumed_count} autonomous run(s) queued for resume")
        if failed_count:
            parts.append(f"{failed_count} task(s) marked failed")
        if parts:
            notification_service.create_notification(
                db,
                type="system",
                title="System recovered",
                body=", ".join(parts) + ".",
            )
        logger.info(
            "Crash recovery: %d orphaned tasks — %d queued for resume, %d failed",
            len(orphaned_tasks),
            resumed_count,
            failed_count,
        )

    return count


def _is_resumable(task) -> bool:
    """Check if an autonomous task can be resumed from its task list."""
    if not task.goal:
        return False
    if not task.task_list:
        return False
    # Check if there are any non-completed items
    try:
        for item in task.task_list:
            status = item.get("status", "pending") if isinstance(item, dict) else "pending"
            if status != "completed":
                return True
    except (TypeError, AttributeError, KeyError):
        return False
    return False


async def resume_autonomous_tasks(db: Session) -> int:
    """Resume autonomous tasks that were marked pending_resume during crash recovery."""
    from contract.enums import BackgroundTaskStatus

    from backend.openloop.db.models import BackgroundTask

    pending = (
        db.query(BackgroundTask)
        .filter(BackgroundTask.status == BackgroundTaskStatus.PENDING_RESUME)
        .all()
    )

    if not pending:
        return 0

    count = 0
    for task in pending:
        # Restore conversation if exists
        if task.conversation_id:
            conversation_service.update_conversation(db, task.conversation_id, status="active")
            _background_conversations.add(task.conversation_id)

        # Update task status
        task.status = BackgroundTaskStatus.RUNNING
        task.started_at = datetime.now(UTC)
        db.commit()

        # Load agent for the run
        agent = agent_service.get_agent(db, task.agent_id)
        if not agent:
            task.status = BackgroundTaskStatus.FAILED
            task.error = "Agent not found during resume"
            task.completed_at = datetime.now(UTC)
            db.commit()
            continue

        # Fire the autonomous task loop (same pattern as approve_autonomous_launch)
        bg = asyncio.create_task(
            _run_autonomous_task(
                task_id=task.id,
                conversation_id=task.conversation_id,
                agent_id=task.agent_id,
                agent_name=agent.name,
                default_model=agent.default_model,
                goal=task.goal or task.instruction,
                constraints=None,
                space_id=task.space_id,
            )
        )
        _background_tasks.add(bg)
        bg.add_done_callback(_task_done)

        notification_service.create_notification(
            db,
            type="system",
            title="Autonomous run resumed",
            body=f"Resumed after restart: {(task.goal or task.instruction)[:100]}",
            space_id=task.space_id,
        )
        count += 1

    logger.info("Resumed %d autonomous task(s) after crash recovery", count)
    return count


# ---------------------------------------------------------------------------
# List running sessions (replaces list_active)
# ---------------------------------------------------------------------------


def list_running(db: Session) -> list[dict]:
    """Return all running sessions: active conversations with SDK sessions + running background tasks.

    Uses DB queries instead of in-memory state.
    """
    from backend.openloop.db.models import BackgroundTask, Conversation

    results: list[dict] = []

    # Interactive sessions: active conversations with an SDK session
    interactive = (
        db.query(Conversation)
        .filter(
            Conversation.status == "active",
            Conversation.sdk_session_id.isnot(None),
        )
        .all()
    )
    # Build a lookup of background tasks keyed by conversation_id for enrichment
    bg_by_conv: dict[str, BackgroundTask] = {}
    all_bg = (
        db.query(BackgroundTask)
        .filter(BackgroundTask.status.in_(["running", "queued"]))
        .all()
    )
    for bt in all_bg:
        if bt.conversation_id:
            bg_by_conv[bt.conversation_id] = bt

    for conv in interactive:
        bt = bg_by_conv.get(conv.id)
        results.append({
            "conversation_id": conv.id,
            "agent_id": conv.agent_id,
            "space_id": conv.space_id,
            "sdk_session_id": conv.sdk_session_id,
            "status": "active",
            "started_at": conv.created_at.isoformat() if conv.created_at else "",
            "last_activity": conv.updated_at.isoformat() if conv.updated_at else "",
            "run_type": bt.run_type if bt else "interactive",
            "background_task_id": bt.id if bt else None,
            "instruction": bt.instruction if bt else None,
            "completed_count": bt.completed_count if bt else None,
            "total_count": bt.total_count if bt else None,
            "token_budget": bt.token_budget if bt else None,
            "parent_task_id": bt.parent_task_id if bt else None,
            "delegation_depth": bt.delegation_depth if bt else None,
        })

    # Background tasks that are currently running (not already covered via conversation)
    seen_conv_ids = {r["conversation_id"] for r in results}
    running_bg = [bt for bt in all_bg if bt.status == "running"]
    for task in running_bg:
        if task.conversation_id and task.conversation_id in seen_conv_ids:
            continue
        results.append({
            "conversation_id": task.conversation_id or "",
            "agent_id": task.agent_id,
            "space_id": task.space_id,
            "sdk_session_id": None,
            "status": "background",
            "started_at": task.started_at.isoformat() if task.started_at else task.created_at.isoformat(),
            "last_activity": task.updated_at.isoformat() if task.updated_at else "",
            "run_type": task.run_type,
            "background_task_id": task.id,
            "instruction": task.instruction,
            "completed_count": task.completed_count,
            "total_count": task.total_count,
            "token_budget": task.token_budget,
            "parent_task_id": task.parent_task_id,
            "delegation_depth": task.delegation_depth,
        })

    return results


# ---------------------------------------------------------------------------
# Context usage monitoring
# ---------------------------------------------------------------------------


async def monitor_context_usage(
    db: Session,
    *,
    conversation_id: str,
    usage: dict,
) -> None:
    """Monitor context window usage and trigger checkpoints or warnings."""
    # Handle both dict and object-style usage (SDK may return either)
    if not isinstance(usage, dict):
        usage = vars(usage) if hasattr(usage, "__dict__") else {}
    input_tokens = usage.get("input_tokens", 0)
    cache_read = usage.get("cache_read_input_tokens", 0)
    total_context = input_tokens + cache_read

    utilization = total_context / CONTEXT_WINDOW_TOKENS if CONTEXT_WINDOW_TOKENS > 0 else 0

    conversation = conversation_service.get_conversation(db, conversation_id)

    if utilization > CLOSE_THRESHOLD:
        notification_service.create_notification(
            db,
            type="context_warning",
            title="Context window nearly full",
            body=(
                f"Conversation is at {utilization:.0%} of context window "
                f"({total_context:,} / {CONTEXT_WINDOW_TOKENS:,} tokens). "
                "Consider closing this conversation and starting a new one."
            ),
            space_id=conversation.space_id,
            conversation_id=conversation_id,
        )
        logger.warning(
            "Context usage at %.0f%% for conversation %s",
            utilization * 100,
            conversation_id,
        )

    elif utilization > CHECKPOINT_THRESHOLD:
        logger.info(
            "Context usage at %.0f%% for conversation %s — triggering checkpoint",
            utilization * 100,
            conversation_id,
        )
        await _create_checkpoint(db, conversation_id=conversation_id)


async def _create_checkpoint(
    db: Session,
    *,
    conversation_id: str,
) -> None:
    """Create a checkpoint summary for the conversation."""
    from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

    conversation = conversation_service.get_conversation(db, conversation_id)
    sdk_session_id = conversation.sdk_session_id
    if not sdk_session_id:
        return

    # Flush unsaved facts to memory before checkpointing
    await flush_memory(db, conversation_id=conversation_id)

    agent = agent_service.get_agent(db, conversation.agent_id)
    mcp_server = _build_mcp_server(agent, agent.id)
    model_name = conversation.model_override or agent.default_model
    model = resolve_model(model_name)
    hooks = _build_hooks_dict(conversation.agent_id, conversation_id)

    summary_text = ""
    new_session_id: str | None = None
    try:
        async for event in query(
            prompt=CHECKPOINT_PROMPT,
            options=ClaudeAgentOptions(
                resume=sdk_session_id,
                model=model,
                mcp_servers={mcp_server["name"]: mcp_server},
                hooks=hooks,
            ),
        ):
            if isinstance(event, ResultMessage):
                summary_text = event.result or ""
                if event.session_id and event.session_id != sdk_session_id:
                    new_session_id = event.session_id
    except (Exception, ExceptionGroup) as exc:
        logger.warning(
            "Failed to create checkpoint for conversation %s: %s",
            conversation_id,
            exc,
        )
        return

    if summary_text or new_session_id:
        db_post = _new_db_session()
        try:
            if new_session_id:
                conversation_service.update_conversation(
                    db_post, conversation_id, sdk_session_id=new_session_id
                )
            if summary_text:
                conversation_service.add_summary(
                    db_post,
                    conversation_id=conversation_id,
                    summary=summary_text,
                    is_checkpoint=True,
                )
                logger.info("Checkpoint created for conversation %s", conversation_id)
        finally:
            db_post.close()


# ---------------------------------------------------------------------------
# Observation masking — conversation compression
# ---------------------------------------------------------------------------


async def _compress_conversation(db: Session, *, conversation_id: str) -> None:
    """Compress older conversation turns while keeping recent ones verbatim.

    Observation masking strategy:
    1. Keep the most recent RECENT_TURNS_VERBATIM user+assistant exchange pairs
    2. Summarize older exchanges into a compact block
    3. Store the summary as a checkpoint
    4. Run verify_compaction() on the compressed content
    """
    from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

    conversation = conversation_service.get_conversation(db, conversation_id)
    sdk_session_id = conversation.sdk_session_id
    if not sdk_session_id:
        return

    messages = conversation_service.get_messages(db, conversation_id)
    if not messages:
        return

    # Identify exchanges: pairs of (user message, assistant response)
    exchanges: list[list] = []
    current_exchange: list = []
    for msg in messages:
        if msg.role == "user":
            if current_exchange:
                exchanges.append(current_exchange)
            current_exchange = [msg]
        elif msg.role == "assistant" and current_exchange:
            current_exchange.append(msg)
            exchanges.append(current_exchange)
            current_exchange = []

    if current_exchange:
        exchanges.append(current_exchange)

    if len(exchanges) <= RECENT_TURNS_VERBATIM:
        logger.debug(
            "Only %d exchanges for conversation %s — nothing to compress",
            len(exchanges),
            conversation_id,
        )
        return

    older_exchanges = exchanges[:-RECENT_TURNS_VERBATIM]

    older_lines: list[str] = []
    for exchange in older_exchanges:
        for msg in exchange:
            older_lines.append(f"{msg.role}: {msg.content}")

    older_content_text = "\n\n".join(older_lines)

    if not older_content_text.strip():
        return

    agent = agent_service.get_agent(db, conversation.agent_id)
    mcp_server = _build_mcp_server(agent, agent.id)
    model_name = conversation.model_override or agent.default_model
    model = resolve_model(model_name)
    hooks = _build_hooks_dict(conversation.agent_id, conversation_id)

    compress_prompt = (
        "Summarize the following older conversation exchanges into a compact "
        "block. Preserve all key facts, decisions, action items, and user "
        "preferences. Be thorough but concise.\n\n"
        f"---\n{older_content_text}\n---"
    )

    summary_text = ""
    new_session_id: str | None = None
    try:
        async for event in query(
            prompt=compress_prompt,
            options=ClaudeAgentOptions(
                resume=sdk_session_id,
                model=model,
                mcp_servers={mcp_server["name"]: mcp_server},
                hooks=hooks,
            ),
        ):
            if isinstance(event, ResultMessage):
                summary_text = event.result or ""
                if event.session_id and event.session_id != sdk_session_id:
                    new_session_id = event.session_id
    except (Exception, ExceptionGroup) as exc:
        logger.warning(
            "Conversation compression failed for %s: %s",
            conversation_id,
            exc,
        )
        return

    if summary_text or new_session_id:
        db_post = _new_db_session()
        try:
            if new_session_id:
                conversation_service.update_conversation(
                    db_post, conversation_id, sdk_session_id=new_session_id
                )
            if summary_text:
                conversation_service.add_summary(
                    db_post,
                    conversation_id=conversation_id,
                    summary=summary_text,
                    is_checkpoint=True,
                )
                logger.info(
                    "Compressed %d older exchanges for conversation %s",
                    len(older_exchanges),
                    conversation_id,
                )
        finally:
            db_post.close()

    # Post-compression verification
    if summary_text:
        await verify_compaction(
            db,
            conversation_id=conversation_id,
            compressed_content=older_content_text,
        )


# ---------------------------------------------------------------------------
# Post-compression verification
# ---------------------------------------------------------------------------

_DECISION_PATTERNS = re.compile(
    r"\b(decided|chose|will use|agreed on|selected|confirmed|approved|switched to)\b",
    re.IGNORECASE,
)
_VALUE_PATTERNS = re.compile(
    r"(?:^|\n)\s*\w[\w\s]*(?:is|:|=)\s+\S",
    re.IGNORECASE,
)


async def verify_compaction(
    db: Session,
    *,
    conversation_id: str,
    compressed_content: str,
) -> None:
    """Post-compaction verification: check that key facts from compressed content exist in memory.

    Non-blocking — logs warnings but doesn't hold up the conversation.
    Uses keyword/pattern extraction, NOT an LLM call.
    """
    key_phrases: list[str] = []

    for line in compressed_content.split("\n"):
        line = line.strip()
        if not line:
            continue

        if _DECISION_PATTERNS.search(line):
            phrase = line[:120].strip()
            if phrase:
                key_phrases.append(phrase)
        elif _VALUE_PATTERNS.search(line):
            phrase = line[:120].strip()
            if phrase:
                key_phrases.append(phrase)

    if not key_phrases:
        return

    conversation = conversation_service.get_conversation(db, conversation_id)
    space_id = conversation.space_id

    namespaces = ["global"]
    if space_id:
        namespaces.append(f"space:{space_id}")

    all_memory_values: list[str] = []
    for ns in namespaces:
        entries = memory_service.list_entries(db, namespace=ns, limit=10000)
        for entry in entries:
            all_memory_values.append(entry.value.lower())
            all_memory_values.append(entry.key.lower())

    gaps: list[str] = []
    for phrase in key_phrases:
        phrase_lower = phrase.lower()
        words = [w for w in re.findall(r"\b\w{4,}\b", phrase_lower)]
        if not words:
            continue

        found = False
        for mem_value in all_memory_values:
            matches = sum(1 for w in words if w in mem_value)
            if matches >= max(1, len(words) // 2):
                found = True
                break

        if not found:
            gaps.append(phrase)

    for gap in gaps[:5]:
        logger.warning(
            "Post-compaction gap: '%s' not found in memory for conversation %s",
            gap[:100],
            conversation_id,
        )
