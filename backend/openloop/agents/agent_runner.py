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
import os
import re
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.openloop.agents import context_assembler
from backend.openloop.agents.mcp_tools import build_agent_tools, build_odin_tools
from backend.openloop.agents.permission_enforcer import build_permission_hook
from backend.openloop.services import (
    agent_service,
    background_task_service,
    conversation_service,
    memory_service,
    notification_service,
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
# Concurrency limits
# ---------------------------------------------------------------------------
MAX_INTERACTIVE_SESSIONS = 5
MAX_AUTOMATION_SESSIONS = 2

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


def _build_hooks_dict(agent_id: str, conversation_id: str | None) -> dict:
    """Build the hooks dict for ClaudeAgentOptions from the permission hook."""
    matcher, hook_fn = build_permission_hook(agent_id, conversation_id)
    matcher.hooks = [hook_fn]
    return {"PreToolUse": [matcher]}


def _get_conversation_lock(conversation_id: str) -> asyncio.Lock:
    """Return (or create) the asyncio.Lock for a given conversation."""
    if conversation_id not in _conversation_locks:
        _conversation_locks[conversation_id] = asyncio.Lock()
    return _conversation_locks[conversation_id]


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


def _check_concurrency(db: Session, session_type: str = "active") -> None:
    """Check concurrency limits and raise 429 if exceeded.

    Uses DB queries instead of in-memory state.
    """
    from backend.openloop.db.models import BackgroundTask, Conversation

    if session_type == "background":
        bg_count = (
            db.query(BackgroundTask)
            .filter(BackgroundTask.status == "running")
            .count()
        )
        if bg_count >= MAX_AUTOMATION_SESSIONS:
            raise HTTPException(
                status_code=429,
                detail="Too many background sessions running. Please wait for one to complete.",
            )
    else:
        interactive_count = (
            db.query(Conversation)
            .filter(
                Conversation.status == "active",
                Conversation.sdk_session_id.isnot(None),
            )
            .count()
        )
        if interactive_count >= MAX_INTERACTIVE_SESSIONS:
            raise HTTPException(
                status_code=429,
                detail="Too many active sessions. Please close a conversation first.",
            )


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
        _check_concurrency(db, "active")

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
                mcp_servers=[mcp_server],
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
                mcp_servers=[mcp_server],
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
                yield {"type": "stream", "event": event}
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
                    mcp_servers=[mcp_server],
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
                        yield {"type": "stream", "event": event}
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

    # Store assistant response in DB
    if full_response:
        conversation_service.add_message(
            db,
            conversation_id=conversation_id,
            role="assistant",
            content=full_response,
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
                    mcp_servers=[mcp_server],
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
                mcp_servers=[mcp_server],
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
) -> str:
    """Delegate work to an agent as a background task.

    Creates a background_task record, fires a managed turn loop.
    Returns the background_task ID.
    """
    _check_concurrency(db, "background")

    task = background_task_service.create_background_task(
        db,
        agent_id=agent_id,
        instruction=instruction,
        space_id=space_id,
        item_id=item_id,
        parent_task_id=parent_task_id,
        status="running",
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
) -> None:
    """Managed turn loop — agent works in discrete turns with steering checkpoints.

    1. First turn: send the instruction with system_prompt in options
    2. Each subsequent turn: check steering queue, then continue or steer
    3. Agent signals completion with TASK_COMPLETE in its response
    4. Progress is tracked per-turn via background_task step updates
    """
    from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

    from backend.openloop.agents.event_bus import event_bus
    from backend.openloop.database import SessionLocal

    CONTINUATION_PROMPT = (
        "Continue working on your task. Report what you accomplished in this step "
        "and what you'll do next. Say TASK_COMPLETE when the entire task is finished."
    )
    MAX_TURNS = 20

    mcp_server = _build_mcp_server_by_name(agent_name, agent_id)
    model = resolve_model(model_override or default_model)

    db = SessionLocal()
    turn = 0
    try:
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
            "Say TASK_COMPLETE when the entire task is finished."
        )

        hooks = _build_hooks_dict(agent_id, conversation_id)

        sdk_session_id: str | None = None
        result_text = ""
        completed = False

        while turn < MAX_TURNS and not completed:
            turn += 1

            # Determine what to send this turn
            if turn == 1:
                prompt_message = task_instruction
            else:
                queue = _steering_queues.get(conversation_id, [])
                if queue:
                    prompt_message = queue.pop(0)
                    logger.info("Steering message applied for task %s at turn %d", task_id, turn)
                else:
                    prompt_message = CONTINUATION_PROMPT

            # Build query kwargs — system_prompt on turn 1, resume on subsequent turns
            if turn == 1:
                query_kwargs: dict = {
                    "prompt": prompt_message,
                    "options": ClaudeAgentOptions(
                        system_prompt=system_prompt,
                        model=model,
                        mcp_servers=[mcp_server],
                        hooks=hooks,
                    ),
                }
            else:
                query_kwargs = {
                    "prompt": prompt_message,
                    "options": ClaudeAgentOptions(
                        resume=sdk_session_id,
                        model=model,
                        mcp_servers=[mcp_server],
                        hooks=hooks,
                    ),
                }

            # Execute one turn with rate limit retry
            turn_result = ""
            async for event in _query_with_retry(
                query,
                query_kwargs,
                conversation_id=conversation_id,
                space_id=space_id,
            ):
                if isinstance(event, ResultMessage):
                    sdk_session_id = event.session_id
                    turn_result = event.result or ""

            result_text = turn_result

            # Check for completion signal
            if "TASK_COMPLETE" in (turn_result or "").upper():
                completed = True

            # Update step progress
            background_task_service.update_task_progress(
                db,
                task_id=task_id,
                current_step=turn,
                total_steps=turn if completed else MAX_TURNS,
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

        # Persist sdk_session_id
        conversation_service.update_conversation(db, conversation_id, sdk_session_id=sdk_session_id)

        # Mark task as completed
        status_note = "" if completed else " (max turns reached)"
        background_task_service.update_background_task(
            db,
            task_id,
            status="completed",
            result_summary=(result_text[:2000] if result_text else None),
            completed_at=datetime.now(UTC),
        )

        notification_service.create_notification(
            db,
            type="task_completed",
            title="Background task completed",
            body=f"Task completed{status_note}: {instruction[:100]}",
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
    for task in orphaned_tasks:
        task.status = BackgroundTaskStatus.FAILED
        task.error = "Server restarted during execution"
        task.completed_at = now
    if orphaned_tasks:
        db.commit()
        logger.info(
            "Crash recovery: marked %d orphaned background tasks as failed",
            len(orphaned_tasks),
        )

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
    for conv in interactive:
        results.append({
            "conversation_id": conv.id,
            "agent_id": conv.agent_id,
            "space_id": conv.space_id,
            "sdk_session_id": conv.sdk_session_id,
            "status": "active",
            "started_at": conv.created_at.isoformat() if conv.created_at else "",
            "last_activity": conv.updated_at.isoformat() if conv.updated_at else "",
        })

    # Background tasks that are currently running
    bg_tasks = (
        db.query(BackgroundTask)
        .filter(BackgroundTask.status == "running")
        .all()
    )
    for task in bg_tasks:
        results.append({
            "conversation_id": task.conversation_id or "",
            "agent_id": task.agent_id,
            "space_id": task.space_id,
            "sdk_session_id": None,
            "status": "background",
            "started_at": task.started_at.isoformat() if task.started_at else task.created_at.isoformat(),
            "last_activity": task.updated_at.isoformat() if task.updated_at else "",
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
                mcp_servers=[mcp_server],
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
                mcp_servers=[mcp_server],
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
