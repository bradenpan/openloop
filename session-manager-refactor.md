# Session Manager Refactor — Implementation Plan

**Date:** 2026-04-02
**Status:** Proposed
**Triggered by:** Integration testing revealed that agent conversations don't work end-to-end. Root cause analysis showed the session_manager's architecture is fundamentally misaligned with how the Claude Agent SDK works.

---

## Why This Refactor

### The Problem

The current `session_manager.py` (1,728 lines) maintains a parallel state system on top of the Claude Agent SDK. It tracks sessions in an in-memory dictionary (`_active_sessions`), manages lifecycle transitions (start → active → closed), and requires a separate `start_session()` call before any message can be sent. This design has three problems:

1. **It doesn't work.** No code path ever calls `start_session()`, so the first message in every conversation fails with "No active session found." This is the bug that integration testing discovered.

2. **Close and reopen are also broken.** The close route (`POST /conversations/{id}/close`) calls `conversation_service.close_conversation()` directly — which just flips a status flag in the DB. It never calls `session_manager.close_session()`, so summary generation, memory flush, auto-consolidation, and in-memory cleanup are all skipped. Similarly, the reopen route calls `conversation_service.reopen_conversation()` directly, so the SDK session validation and context re-injection logic in `session_manager.reopen_conversation()` is dead code. This means conversations lose their summaries and accumulated facts on close.

3. **It duplicates what the SDK already does.** The SDK persists sessions as JSONL files, handles resume transparently, and manages conversation history. OpenLoop reimplements all of this in Python, creating a second source of truth that can (and does) get out of sync.

4. **It's based on a misunderstanding of the SDK.** The SDK's `query()` function is stateless per-call. Each call is self-contained — you pass a prompt, optional system_prompt, optional resume ID, and get back a response + session_id. There's no persistent "connection" to manage. The `start_session` / `send_message` / `close_session` lifecycle model was designed as if the SDK were a WebSocket server, but it's actually a request-response API.

### What the SDK Actually Provides

```python
# First message — creates session automatically
result = query(
    prompt="What spaces do I have?",
    options=ClaudeAgentOptions(
        system_prompt=assembled_context,    # <-- SDK handles this natively
        model="claude-sonnet-4-6",
        mcp_servers=[tool_server],
        hooks=permission_hooks,
    ),
)
# result.session_id = "abc-123" (SDK created this)

# Second message — resume is all that's needed
result = query(
    prompt="Create a task in the OpenLoop space",
    options=ClaudeAgentOptions(
        resume="abc-123",                   # <-- SDK loads full history from JSONL
        model="claude-sonnet-4-6",
        mcp_servers=[tool_server],
        hooks=permission_hooks,
    ),
)
```

No start_session needed. No in-memory state tracking. No lifecycle management. The SDK handles it all via the session_id and JSONL files.

### What OpenLoop Actually Needs

The session_manager does contain genuinely useful code mixed in with the redundant parts:

| Useful (keep) | Redundant (remove) |
|---|---|
| Context assembly dispatch | `_active_sessions` in-memory dict |
| MCP tool server selection | `SessionState` dataclass |
| Permission hook wiring | `start_session()` function |
| Rate limit retry wrapper | Concurrency tracking via memory |
| SSE event streaming | `_conversation_locks` dict |
| Close session (summary generation) | `_context_size_cache` |
| Flush memory (fact extraction) | `recover_from_crash` session cleanup |
| Compress conversation | Session state lookups/rebuilds |
| Background task turn loop | `_check_concurrency` via dict |
| Steering queue | `_get_conversation_lock` |
| Delegate background | `list_active` via dict |

### What Changes for the User

Nothing. The web UI, API, SSE streaming, agent conversations, background tasks, automations — all work exactly the same. The refactor is internal plumbing only.

---

## Implementation Plan

### Pre-flight: Fix the immediate bug first

Before refactoring, apply the minimal fix so conversations work during development:
- In `_send_message_inner`, when `sdk_session_id` is missing, use `system_prompt` in options instead of `resume`. This unblocks testing while the refactor is planned.

### Task 1: Create `agent_runner.py` (the thin wrapper)

**New file:** `backend/openloop/agents/agent_runner.py` (~300 lines)

This file replaces `session_manager.py` as the interface between OpenLoop and the Claude SDK. It contains:

```
run_interactive(db, conversation_id, message) -> AsyncGenerator[dict]
    # The core function. Called by routes for every message.
    # 1. Load conversation from DB
    # 2. Load agent config
    # 3. Assemble context via context_assembler
    # 4. Build MCP tools
    # 5. Build permission hooks
    # 6. Call query() with system_prompt + resume (if session exists)
    # 7. Stream SSE events
    # 8. Store session_id, save assistant message
    # 9. Publish stream_end event

run_background(db, task_id, agent_id, instruction, ...) -> None
    # Managed turn loop for autonomous work.
    # Same as current _run_background_task but uses the simplified query pattern.

close_conversation(db, conversation_id) -> str
    # Send summary prompt, store summary, update conversation status.

flush_memory(db, conversation_id) -> None
    # Ask LLM to extract facts. Unchanged logic.

compress_conversation(db, conversation_id) -> None
    # Ask LLM to compress history. Unchanged logic.

steer(conversation_id, message) -> bool
    # Queue a steering message. Unchanged logic.

delegate_background(db, agent_id, instruction, ...) -> str
    # Create conversation + background task. Simplified.
```

**Key design decisions:**
- No in-memory session state. The `sdk_session_id` lives on the `Conversation` DB record only.
- No `start_session` function. The first `query()` call creates the session.
- `system_prompt` is passed via `ClaudeAgentOptions.system_prompt`, not as the `prompt`.
- `resume` is set from `conversation.sdk_session_id` if it exists, omitted on first message.
- Rate limit retry wrapper moves here (generic utility).
- Context estimation uses a simple heuristic (message count × avg tokens), not a full re-assembly.

### Task 2: Update route handlers (including close/reopen)

**Files:** `api/routes/conversations.py`, `api/routes/odin.py`

Change imports from `session_manager` to `agent_runner`. The route-level code barely changes:

```python
# Before (conversations.py)
from backend.openloop.agents import session_manager
async for event in session_manager.send_message(db, conversation_id=cid, message=msg):
    await event_bus.publish(event)

# After
from backend.openloop.agents import agent_runner
async for event in agent_runner.run_interactive(db, conversation_id=cid, message=msg):
    await event_bus.publish(event)
```

Odin route: same change, `odin_service.send_message` calls `agent_runner.run_interactive` instead of `session_manager.send_message`.

**Critical fix — close route:** The current close route calls `conversation_service.close_conversation()` directly, which only flips a DB status flag. It skips summary generation, memory flush, auto-consolidation, and session cleanup. The refactored close route must call `agent_runner.close_conversation()` instead:

```python
# Before (broken — skips summary + memory flush)
@router.post("/{conversation_id}/close")
def close_conversation(conversation_id, db):
    conv = conversation_service.close_conversation(db, conversation_id)
    return ConversationResponse.model_validate(conv)

# After (summary generation, memory flush, consolidation all happen)
@router.post("/{conversation_id}/close")
async def close_conversation(conversation_id, db):
    summary = await agent_runner.close_conversation(db, conversation_id=conversation_id)
    conv = conversation_service.get_conversation(db, conversation_id)
    return ConversationResponse.model_validate(conv)
```

Note: this changes the close endpoint from sync to async because `close_conversation` awaits SDK calls for summary generation and memory flush.

**Critical fix — reopen route:** Same issue. The current reopen route calls `conversation_service.reopen_conversation()` directly, skipping SDK session validation and context re-injection. The refactored reopen route should call `agent_runner.reopen_conversation()` if the agent_runner needs to do SDK-level work (validate/recreate session), or can remain as-is if the new design handles session creation lazily on first message (which is the proposed approach — no `start_session`, just `query()` on first message). In the lazy model, reopen only needs the DB status flip, so the current route is actually correct for the new design. Document this decision explicitly.

### Task 3: Update odin_service.py

Simplify `OdinService.send_message` to call `agent_runner.run_interactive` directly. The `ensure_conversation` logic stays unchanged.

### Task 4: Update background task callers

**Files:** `automation_scheduler.py`, any route that calls `delegate_background`

Change `session_manager.delegate_background` → `agent_runner.delegate_background`.

### Task 5: Update main.py lifespan

Remove session-manager-specific startup/shutdown:
- `recover_from_crash` no longer needs to clean `_active_sessions` (doesn't exist)
- Background task cleanup still needed (mark DB records as failed) — move to `agent_runner` or keep standalone

### Task 6: Update tests

Test files that mock `session_manager` functions need to be updated to mock `agent_runner` equivalents. The test logic stays the same — only import paths change.

### Task 7: Remove session_manager.py

Once all callers are migrated and tests pass, delete `session_manager.py`. 

### Task 8: Update running sessions endpoint

`GET /api/v1/agents/running` currently reads from `_active_sessions` dict. Replace with a DB query. The response shape stays the same.

**Query design:** `status='active' AND sdk_session_id IS NOT NULL` alone is insufficient — a conversation can be "active" in the DB without an agent actually running (e.g., user opened a conversation but hasn't sent a message yet). The query should combine:
- Conversations with `status='active'` AND `sdk_session_id IS NOT NULL` (interactive sessions that have been used)
- Background tasks with `status='running'` (joined to their conversations for the response shape)

This is actually an improvement over the in-memory dict, which lost all tracking on server restart.

### Task 9: Verify and test

- Run full test suite (941 tests)
- Run live integration tests (API smoke + UI flows + agent conversation)
- Verify Odin conversation works end-to-end
- Verify background task delegation works
- Verify close/reopen conversation cycle works

---

## What Stays Unchanged

- `context_assembler.py` — untouched, still assembles system prompts
- `mcp_tools.py` — untouched, still builds MCP tool servers
- `permission_enforcer.py` — untouched, still builds SDK hooks
- `event_bus.py` — untouched, still publishes SSE events
- `task_monitor.py` — untouched, still checks for stale tasks
- `automation_scheduler.py` — only import path changes
- `lifecycle_scheduler.py` — untouched
- All service modules — untouched
- All frontend code — untouched
- All schemas — untouched
- Database models — untouched

---

## Risk Assessment

**Low risk.** The refactor:
- Removes code (net negative lines)
- Doesn't change the database schema
- Doesn't change the API contract (response shapes unchanged)
- Doesn't change the frontend
- Doesn't change the SDK integration pattern (still uses `query()` with the same options)
- The background task turn loop (`_run_background_task`) already uses the correct SDK pattern — we're bringing the interactive path in line with it

**Risks and mitigations:**

1. **Missing a caller during migration.** Mitigation: grep for all `session_manager` imports and verify each is updated. Known callers (verified via spike):
   - `api/routes/conversations.py` — `send_message`, `steer`
   - `api/routes/running.py` — `list_active`
   - `agents/odin_service.py` — `send_message`
   - `agents/mcp_tools.py` — `delegate_background` (×2)
   - `services/automation_service.py` — `delegate_background`
   - `services/consolidation_service.py` — import only (consolidation trigger)
   - `main.py` — `recover_from_crash`

2. **Close route becomes async.** The close endpoint currently synchronous. After the fix, it must be `async` because `agent_runner.close_conversation()` awaits SDK calls for summary generation and memory flush. This is a minor behavioral change — the close operation will take a few seconds instead of being instant, because it's now actually doing work (generating a summary). The frontend may need a loading state for the close button, but the API contract (request/response shape) doesn't change.

3. **Reopen design decision.** The old session_manager had elaborate reopen logic (validate SDK session, re-inject summaries + recent messages). The new lazy design means reopen just flips a DB flag, and the next `run_interactive` call handles session creation. This is simpler but means the agent won't receive a "you're resuming a previous conversation" prompt until the user sends a message. This is acceptable — it matches how Claude Code's own resume works.

---

## Execution Approach

9 tasks, mostly sequential (agent_runner must exist before callers migrate). Estimated: 2-3 agent rounds.

- Tasks 1-2 can be one agent (create agent_runner + update routes including close/reopen fixes)
- Tasks 3-5 can be one agent (update callers)
- Task 6 is one agent (update tests)
- Tasks 7-9 are verification (delete old file, update running endpoint, test)

**Note on close route:** Task 2 now includes a critical fix — the close route must call through `agent_runner` to trigger summary generation and memory flush. This is not just an import swap; it changes the route from sync to async and adds real work (SDK calls) to what was previously a DB-only operation. Test this path explicitly in Task 9.
