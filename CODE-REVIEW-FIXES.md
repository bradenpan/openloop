# OpenLoop Code Review — Fix Plan

**Date:** 2026-04-02
**Reviewers:** 4 parallel agents (Backend Services, API Routes, Agent System, Frontend)
**Total findings:** 90 (7 critical, 39 important, 44 minor)

Each phase is a self-contained batch: fix, review, test, then move on.

---

## Phase 1: Critical Fixes (7 items)

These are bugs that will cause visible problems or security risks during real use.

### 1.1 — Automation double-fire

**Source:** Agent System F22
**Files:** `backend/openloop/agents/automation_scheduler.py`, `backend/openloop/services/automation_service.py`
**Problem:** If an automation takes longer than 60 seconds, the scheduler fires it again because `last_run_at` isn't updated until the task finishes. The scheduler's `_is_due()` check sees stale `last_run_at` and re-triggers.
**Impact:** Duplicate agent runs — duplicate emails drafted, duplicate task reviews, wasted API credits.
**Fix:** Update `automation.last_run_at` immediately in `trigger_automation()` before firing the async task, not in `complete_run()`. The scheduler then sees the updated timestamp on the next 60s tick.

### 1.2 — Odin bar receives ALL streaming tokens

**Source:** Frontend F2
**Files:** `frontend/src/components/layout/odin-bar.tsx`
**Problem:** The Odin bar listens for all SSE `token` events with no `conversation_id` filter. When any agent is streaming (background tasks, other conversations), those tokens are concatenated into Odin's display.
**Impact:** Odin shows garbled text mixing multiple conversations. Unusable during background agent execution.
**Fix:** Track Odin's own `conversation_id` (returned when sending a message via POST `/api/v1/odin/message`) and filter SSE events to only process tokens matching that ID.

### 1.3 — XSS in search results (verify)

**Source:** Frontend F1
**Files:** `frontend/src/components/search-modal.tsx`, `backend/openloop/services/search_service.py`
**Problem:** Search results use `dangerouslySetInnerHTML` with `highlightExcerpt()` which is a pass-through. If the backend's FTS snippet doesn't sanitize content, HTML/script injection is possible.
**Impact:** Potential script injection via stored content appearing in search results.
**Fix:** First, verify the backend's HTML-escaping (Phase 4 fix documented in progress.md says "HTML-escaped excerpts with safe `<mark>` restoration"). If the backend escaping is confirmed solid, add a comment documenting the safety guarantee. If not, add DOMPurify sanitization in the frontend before rendering, allowing only `<mark>` tags.

### 1.4 — Permission polling blocks forever

**Source:** Agent System F18
**Files:** `backend/openloop/agents/permission_enforcer.py`
**Problem:** `_poll_for_approval` loops forever with `while True`, polling the DB every 2 seconds. If a user never responds to an approval request, the agent session is permanently stuck, holding a DB session open indefinitely.
**Impact:** Resource leak — DB session and asyncio task consumed forever per unanswered approval.
**Fix:** Add a configurable timeout (default 30 minutes). After timeout, deny the request, create a notification ("Approval request expired"), and clean up the session. The hook's `finally` block already closes the DB session, so the timeout just needs to break the loop.

### 1.5 — Migration never explicitly adds `is_done` to items table

**Source:** Services F26
**Files:** `backend/alembic/versions/4c1_unified_item_model.py`
**Problem:** The `is_done` column on the items table is never explicitly created by any migration. It works by accident because Alembic batch mode recreates the table using the current ORM model metadata, which includes `is_done`.
**Impact:** If migrations are replayed with different metadata state, the INSERT statements that reference `is_done` will fail. Fragile and undocumented.
**Fix:** Add an explicit `batch_op.add_column(sa.Column("is_done", sa.Boolean(), nullable=False, server_default="0"))` in the 4c1 migration before the INSERT statements. Or create a new migration that ensures the column exists.

### 1.6 — FK cascade mismatch between migrations and ORM models

**Source:** Services F27 + F3
**Files:** `backend/alembic/versions/f94010dbad8e_initial_schema.py`, `backend/openloop/db/models.py`
**Problem:** Migrations create FK constraints without `ondelete="CASCADE"`, but ORM models define cascades. Tests use `create_all()` (correct cascades), but production uses migrations (no cascades). Deleting a space/agent in production could leave orphan records or throw FK errors.
**Impact:** Production and tests have different cascade behavior. Deleting entities in production is unsafe.
**Fix:** Create a new Alembic migration that recreates FK constraints with correct `ondelete` clauses using batch mode. Cover all FKs listed in the ORM models, including join tables (`agent_spaces`, `document_items`).

### 1.7 — Orphaned background tasks after server restart

**Source:** Agent System F5
**Files:** `backend/openloop/agents/agent_runner.py`
**Problem:** `recover_from_crash` marks conversations as interrupted but doesn't clean up `BackgroundTask` records. Tasks in "running" status remain stuck forever after restart.
**Impact:** Background tasks show as "running" permanently in the UI. Task monitor flags them as "stuck" but they never reach a terminal state.
**Fix:** In `recover_from_crash`, also query `BackgroundTask` records with `status="running"` or `status="queued"` and mark them as `status="failed"` with a result message like "Server restarted during execution."

---

## Phase 2: Security & Authorization (5 items)

### 2.1 — No space scoping in MCP tools

**Source:** Agent System F13
**Files:** `backend/openloop/agents/mcp_tools.py`
**Problem:** MCP tools accept `space_id` as a parameter but don't validate that the calling agent has access to that space. An agent assigned to Space A can create items or read memory in Space B.
**Impact:** Agents can operate outside their assigned spaces. Breaks the spatial isolation model.
**Fix:** Add a helper function `_validate_agent_space_access(agent_id, space_id, db)` that checks the `agent_spaces` join table. Call it at the top of every tool that accepts `space_id`. Odin (system agent) bypasses the check.

### 2.2 — Test agent created with no space restrictions

**Source:** Agent System F16
**Files:** `backend/openloop/agents/mcp_tools.py` (test_agent tool)
**Problem:** The Agent Builder's `test_agent` tool creates agents without linking them to any spaces. An agent with no space entries gets `None` from `_get_agent_space_ids`, which means "search everything."
**Impact:** Test agents can access data across all spaces during testing.
**Fix:** When creating a test agent, inherit the space restrictions of the requesting agent (the Agent Builder), or explicitly restrict to the space the Agent Builder is operating in.

### 2.3 — Layout widget operations don't validate space ownership

**Source:** API F21
**Files:** `backend/openloop/api/routes/layout.py`, `backend/openloop/services/layout_service.py`
**Problem:** `update_widget` and `remove_widget` use only `widget_id` — the `space_id` in the URL path is unchecked. A request to `PATCH /spaces/space-A/layout/widgets/widget-from-space-B` would succeed.
**Impact:** Widgets can be modified through the wrong space's URL.
**Fix:** In the service layer, validate `widget.space_id == space_id` before proceeding. Return 404 if mismatch.

### 2.4 — Google Drive uses full-access scope

**Source:** Services F23
**Files:** `backend/openloop/services/gdrive_client.py`
**Problem:** The OAuth scope is `https://www.googleapis.com/auth/drive` (full read/write/delete on ALL Drive files). The app only needs to read linked folders and optionally create files.
**Impact:** If the token is compromised, full Drive access is exposed. Principle of least privilege violation.
**Fix:** Change to `https://www.googleapis.com/auth/drive.readonly` if write access isn't needed, or `https://www.googleapis.com/auth/drive.file` to scope to app-created files only. Note: changing scope requires re-authentication.

### 2.5 — Windows path case sensitivity in permission enforcer

**Source:** Agent System F20
**Files:** `backend/openloop/agents/permission_enforcer.py`
**Problem:** `is_system_blocked` uses `fnmatch` which is case-sensitive. On Windows, `OPENLOOP.DB` or `Openloop.db` would bypass the `openloop.db` guardrail.
**Impact:** An agent could access blocked files using different casing on Windows.
**Fix:** Lowercase both the normalized path and the patterns before matching when `sys.platform == "win32"`.

---

## Phase 3: Data Correctness (7 items)

### 3.1 — Memory `_active_filter` excludes future-dated `valid_until`

**Source:** Services F11
**Files:** `backend/openloop/services/memory_service.py`
**Problem:** `_active_filter` checks `valid_until IS NULL`, which means entries with a future `valid_until` date are treated as inactive/expired even though they haven't expired yet.
**Impact:** The temporal facts model is broken for future-dated entries. "This fact is valid until December 2026" would be excluded from active results immediately.
**Fix:** Change the filter to `(MemoryEntry.valid_until.is_(None)) | (MemoryEntry.valid_until > func.now())`.

### 3.2 — Memory create silently drops `importance` and `category`

**Source:** API F3
**Files:** `backend/openloop/api/routes/memory.py`, `backend/openloop/api/schemas/memory.py`
**Problem:** `MemoryCreate` schema accepts `importance` and `category` fields, but the route and service ignore them.
**Impact:** Users set values that are silently dropped. Schema promises functionality that doesn't exist.
**Fix:** Either pass these fields through to the service (add `importance` and `category` params to `create_entry`), or remove them from the `MemoryCreate` schema if they're not meant to be user-settable.

### 3.3 — `update_item` silently ignores `stage` field

**Source:** Services F6
**Files:** `backend/openloop/services/item_service.py`
**Problem:** `stage` is not in the `updatable` set for `update_item`. A PATCH that includes `stage` silently does nothing.
**Impact:** If the route passes stage through the generic update path, it won't work. Forces use of `move_item`.
**Fix:** Either add `stage` to the updatable set with board_columns validation (checking the target stage is valid), or add a clear docstring/comment documenting that stage changes must go through `move_item`.

### 3.4 — `create_automation` doesn't validate trigger_type or cron_expression

**Source:** Services F9
**Files:** `backend/openloop/services/automation_service.py`
**Problem:** No validation that `trigger_type` is a valid enum value or that `cron_expression` is valid/non-null when `trigger_type == "cron"`.
**Impact:** Invalid automations stored silently, fail at runtime when the scheduler tries to compute next run.
**Fix:** Validate `trigger_type` against `AutomationTriggerType` enum. When `trigger_type == "cron"`, require `cron_expression` to be non-null and validate with `croniter.is_valid()`. Raise 422 on invalid.

### 3.5 — `move_item` missing guard on empty `board_columns`

**Source:** Services F5
**Files:** `backend/openloop/services/item_service.py`
**Problem:** `move_item` accesses `space.board_columns[-1]` as the "done" column without guarding against empty lists. `toggle_done` and `update_item` both have this guard.
**Impact:** If `board_columns` is somehow empty, the done column resolves to empty string.
**Fix:** Add the same `if space and space.board_columns:` guard used in the other methods.

### 3.6 — `recall_facts` commits access tracking in a read path

**Source:** Agent System F14
**Files:** `backend/openloop/agents/mcp_tools.py`
**Problem:** The FTS5 search path in `recall_facts` increments `access_count` and `last_accessed` on matched entries, then commits. A read operation has write side effects.
**Impact:** Read-only operations modify the database. If concurrent recall operations run on overlapping entries, access counts are inaccurate (last-write-wins).
**Fix:** Separate the access tracking into a deferred/batched operation, or accept the minor inaccuracy and add a comment explaining the tradeoff. The access tracking feeds into the Ebbinghaus scoring model, so removing it entirely isn't ideal.

### 3.7 — Timezone inconsistency in memory service

**Source:** Services F12
**Files:** `backend/openloop/services/memory_service.py`
**Problem:** `save_fact_with_dedup` stores `valid_until = datetime.now(UTC)` (timezone-aware), but `auto_archive_superseded` compares with `.replace(tzinfo=None)` (naive). Inconsistent storage/comparison.
**Impact:** Archival timing could be off. Entries might not archive on schedule.
**Fix:** Standardize on naive UTC datetimes throughout (strip tzinfo before storing), consistent with how `_compute_score` already handles both cases.

---

## Phase 4: Resource Leaks & Stability (7 items)

### 4.1 — Conversation locks never cleaned up

**Source:** Agent System F2
**Files:** `backend/openloop/agents/agent_runner.py`
**Problem:** `_conversation_locks` dict grows unboundedly — locks are created per conversation but never removed.
**Impact:** Memory leak proportional to total conversations over time.
**Fix:** Remove locks from `_conversation_locks` when conversations are closed in `close_conversation`. *Note: The agent_runner refactor removed most in-memory state; this fix is partially superseded.*

### 4.2 — DB sessions held across async boundaries

**Source:** Agent System F1
**Files:** `backend/openloop/agents/agent_runner.py`
**Problem:** The request-scoped `db: Session` is held open during long `async for event in query(...)` SDK calls, which can take minutes for background tasks.
**Impact:** Under concurrent load, "database is locked" errors. The `busy_timeout=5000` pragma mitigates but doesn't eliminate.
**Fix:** Create short-lived sessions for each DB operation within async functions, similar to `_run_background_task`'s pattern. This is a larger refactor — consider doing it for the most long-running paths first (background tasks, flush_memory, compress_conversation).

### 4.3 — Event bus queues unbounded

**Source:** Agent System F33
**Files:** `backend/openloop/services/event_bus.py`
**Problem:** `asyncio.Queue()` created without size limit. If an SSE client disconnects without unsubscribing, events accumulate forever.
**Impact:** Memory leak proportional to events published times disconnected subscribers.
**Fix:** Use `maxsize` on the queue (e.g., 1000). Handle `QueueFull` by dropping old events or removing the subscriber.

### 4.4 — Fire-and-forget asyncio tasks without references

**Source:** Services F10, API F19
**Files:** `backend/openloop/services/automation_service.py`, `backend/openloop/api/routes/odin.py`
**Problem:** `asyncio.create_task()` called without storing the task reference. Exceptions are silently lost.
**Impact:** Background task failures could go unnoticed. Task could theoretically be garbage collected.
**Fix:** Store task references in a module-level set, add `task.add_done_callback` to log exceptions and remove from set.

### 4.5 — Double context assembly per message

**Source:** Agent System F8
**Files:** `backend/openloop/agents/agent_runner.py`
**Problem:** `_estimate_conversation_context` calls `context_assembler.assemble_context()` before every message for size estimation. Then the actual SDK call assembles it again.
**Impact:** Every interactive message incurs double the DB queries and context assembly cost.
**Fix:** Cache the system prompt size from the most recent assembly, or use a lighter estimation (message count + last known system prompt size). Only re-assemble when the cached estimate suggests we're near the threshold.

### 4.6 — Context assembly has commit side effects

**Source:** Agent System F9
**Files:** `backend/openloop/agents/context_assembler.py`
**Problem:** `_build_behavioral_rules_section` increments `apply_count` and commits during context assembly. Since assembly happens twice per message (estimation + real), counts are inflated.
**Impact:** Auto-demotion threshold (`apply_count >= 10`) reached faster than expected. Rules deactivated prematurely.
**Fix:** Move the `apply_count` increment out of context assembly. Only increment when the context is actually used (after the SDK call succeeds), not during estimation.

### 4.7 — LLM utility calls create abandoned SDK sessions

**Source:** Agent System F30
**Files:** `backend/openloop/services/llm_utils.py`, `backend/openloop/services/consolidation_service.py`
**Problem:** Every `llm_compare_facts` and `llm_consolidate_facts` call creates a new SDK session (JSONL file on disk) that's never cleaned up.
**Impact:** Disk space slowly grows with abandoned session files.
**Fix:** Either reuse a shared "utility" session for LLM calls, or add periodic cleanup of old session files (e.g., delete JSONL files older than 7 days in the sessions directory).

### 4.8 — No stream_end SSE event for Odin (causes split messages)

**Source:** Review Round 2, Frontend F3 (pre-existing)
**Files:** `backend/openloop/api/routes/odin.py` (or wherever Odin SSE events are emitted), `backend/openloop/services/event_bus.py` (event types), `frontend/src/components/layout/odin-bar.tsx`, `frontend/src/hooks/use-sse.ts` (SSE event types)
**Problem:** The backend doesn't emit a "stream finished" SSE event when an agent completes its response. The Odin bar relies on a 2-second silence timeout to detect completion, which misfires if the LLM pauses for tool use (>2 seconds between tokens). This produces split message bubbles — the first part finalizes prematurely, then remaining tokens start a new bubble.
**Impact:** Any Odin interaction involving tool calls or slow LLM responses shows broken message display.
**Fix:**
1. Backend: emit a `stream_end` SSE event (with `conversation_id`) when the agent's response is complete — after the last token but before the session yields `ResultMessage`.
2. Frontend: add `stream_end` to the SSE event type union. In `odin-bar.tsx`, listen for `stream_end` and call `finalizeStreaming()` immediately instead of relying on the timeout. Keep the timeout as a fallback safety net (increase from 2s to 10s).
3. The main conversation panel (`conversation-panel.tsx`) can also benefit from this event, but it already has a working mechanism (message count change detection), so updating it is optional.

---

## Phase 5: Frontend Fixes (8 items)

### 5.1 — New conversation modal agent dropdown always empty

**Source:** Frontend F4
**Files:** `frontend/src/components/space/new-conversation-modal.tsx`
**Problem:** `agentsData?.data ?? []` accesses `.data` on the response, but the API returns a flat array. `data.data` is `undefined`, so the dropdown is always empty.
**Impact:** Users cannot create new conversations from within a space — a core workflow is broken.
**Fix:** Change `agentsData?.data ?? []` to `agentsData ?? []`.

### 5.2 — Conversation streaming has no timeout fallback

**Source:** Frontend F5
**Files:** `frontend/src/components/conversation/conversation-panel.tsx`
**Problem:** If streaming tokens stop arriving (backend slow, SSE drops mid-stream), there's no fallback to finalize the streaming state. The cursor stays stuck.
**Impact:** User sees an infinite loading/streaming state with no way to recover except refreshing.
**Fix:** Add a safety timeout (e.g., 10 seconds of no new tokens) that calls `finalizeStreaming()` as a fallback.

### 5.3 — Conversation sidebar overlay lacks accessibility

**Source:** Frontend F9
**Files:** `frontend/src/components/space/conversation-sidebar.tsx`
**Problem:** The full-screen overlay that opens when clicking a conversation has no `role="dialog"`, no `aria-modal`, no focus trap, no Escape key handling, and no body scroll locking. The existing `Panel` component handles all of these correctly.
**Impact:** Keyboard and screen reader users can't properly interact with conversations.
**Fix:** Use the existing `Panel` component instead of the custom overlay div, or add the missing accessibility attributes and focus management.

### 5.4 — Document panel uses `alert()` instead of toast

**Source:** Frontend F10
**Files:** `frontend/src/components/space/document-panel.tsx`
**Problem:** Upload failures and Drive refresh failures show blocking `alert()` dialogs.
**Impact:** Blocks the main thread, jarring UX, not styled.
**Fix:** Replace with `useToastStore.getState().addToast(...)` which already exists in the codebase.

### 5.5 — BackgroundTaskCard uses `as never` type casts

**Source:** Frontend F6
**Files:** `frontend/src/components/home/background-task-card.tsx`
**Problem:** The steer endpoint is called with `as never` casts that completely bypass type safety. Same pattern in Automations page and notification panel.
**Impact:** Silent breakage if the API changes. No compile-time safety.
**Fix:** Add the steer, trigger, and mark-all-read endpoints to the OpenAPI spec so they get proper type generation. Then remove the `as never` casts.

### 5.6 — Table view forces unnecessary API call on column toggle

**Source:** Frontend F7
**Files:** `frontend/src/components/space/table-view.tsx`
**Problem:** `toggleColumn` invalidates the `field-schema` query to force a re-render, even though column visibility is stored in localStorage. This causes an unnecessary network request.
**Impact:** Unnecessary API call and visible delay on every column toggle.
**Fix:** Use a local state variable or counter to trigger re-renders when column config changes, removing the query invalidation.

### 5.7 — Panel missing `aria-labelledby` when title exists

**Source:** Frontend F8
**Files:** `frontend/src/components/ui/panel.tsx`
**Problem:** Panel uses `aria-label={title}` but the title is also rendered as a visible `<h3>`. Should use `aria-labelledby` pointing to the heading. When title is undefined, no accessible name at all.
**Impact:** Screen readers may not properly announce the panel.
**Fix:** Add `useId()` hook, set `aria-labelledby` when title present, `aria-label="Panel"` as fallback.

### 5.8 — Tag filtering crashes on special characters

**Source:** Services F14
**Files:** `backend/openloop/services/document_service.py`
**Problem:** Tag filtering uses `tag.replace('-', '_')` to create bind parameter names. Tags with dots, spaces, or other special characters produce invalid parameter names.
**Impact:** Filtering documents by tags containing special characters throws a SQLAlchemy error.
**Fix:** Use numeric index for bind parameter names (e.g., `tag_0`, `tag_1`) instead of deriving from tag content.

---

## Phase 6: API Surface & Conventions (11 items)

### 6.1 — Missing response_model on steer endpoint

**Source:** API F6
**Files:** `backend/openloop/api/routes/conversations.py`
**Fix:** Create `SteerResponse` schema, add `response_model=SteerResponse`.

### 6.2 — Missing response_model on field-schema endpoint

**Source:** API F16
**Files:** `backend/openloop/api/routes/spaces.py`
**Fix:** Add `response_model=list[dict]` or create a proper schema.

### 6.3 — Missing response_model on running sessions endpoint

**Source:** API F17
**Files:** `backend/openloop/api/routes/running.py`
**Fix:** Create `RunningSessionResponse` Pydantic schema, use as response_model.

### 6.4 — No pagination on `get_messages`

**Source:** API F7
**Files:** `backend/openloop/api/routes/conversations.py`, `backend/openloop/services/conversation_service.py`
**Fix:** Add `limit` and `offset` query parameters to the route. Add pagination to service function.

### 6.5 — No API routes for behavioral rules

**Source:** API F26
**Files:** New file `backend/openloop/api/routes/behavioral_rules.py`
**Fix:** Create CRUD endpoints using existing service and schemas. Register router in main.py.

### 6.6 — `DashboardResponse` defined inline in route file

**Source:** API F10
**Files:** `backend/openloop/api/routes/home.py` → `backend/openloop/api/schemas/home.py`
**Fix:** Move schema to proper location, re-export from `schemas/__init__.py`.

### 6.7 — Memory routes use inline paths instead of router prefix

**Source:** API F4
**Files:** `backend/openloop/api/routes/memory.py`
**Fix:** Split into two routers or add prefix and adjust paths. Add comment if keeping inline due to dual prefix.

### 6.8 — Route calls private service function `_is_text_file`

**Source:** API F11
**Files:** `backend/openloop/api/routes/documents.py`, `backend/openloop/services/document_service.py`
**Fix:** Remove underscore prefix to make the function public, or move the logic into a public method.

### 6.9 — `ItemLinkCreate.link_type` uses string instead of enum

**Source:** API F25
**Files:** `backend/openloop/api/schemas/items.py`
**Fix:** Change `link_type: str = "related_to"` to `link_type: LinkType = LinkType.RELATED_TO`.

### 6.10 — Weakly typed `list | None` in multiple schemas

**Source:** API F30
**Files:** `backend/openloop/api/schemas/agents.py`, `conversations.py`, `spaces.py`
**Fix:** Change `list | None` to `list[str] | None` (or appropriate element type) on: `AgentResponse.tools`, `AgentResponse.mcp_tools`, `SummaryResponse.decisions`, `SummaryResponse.open_questions`.

### 6.11 — Conversation `status` query parameter untyped

**Source:** API F9
**Files:** `backend/openloop/api/routes/conversations.py`
**Fix:** Change `status: str | None = Query(None)` to `status: ConversationStatus | None = Query(None)`.

---

## Phase 7: Minor Cleanup (44 items)

Grouped by area. Low risk, batch all at once.

### Backend Models & Migrations
- 7.1 — `board_columns` model allows null despite "never null" convention. Add `nullable=False`. *(Services F1)*
- 7.2 — Enum-backed fields stored as plain String in models (widespread, low priority). *(Services F2)*
- 7.3 — `Notification.type` shadows Python builtin. Document, don't change. *(Services F4)*
- 7.4 — No indexes on `notifications.created_at`, `conversation_messages.created_at`, `items.stage`, `background_tasks.status`. Add in a migration. *(Services F29)*
- 7.5 — 4c1 migration toggles `PRAGMA foreign_keys=OFF` without try/finally safety. Wrap in try/finally. *(Services F28)*

### Backend Services
- 7.6 — `upload_document` has dead `..` check after `Path().name` already strips dirs. Remove misleading check. *(Services F16)*
- 7.7 — `list_documents` tag filter has no-op `Document.title.is_not(None)`. Remove. *(Services F15)*
- 7.8 — `update_conversation` allows setting status to arbitrary strings. Add validation or document. *(Services F18)*
- 7.9 — `create_agent` silently ignores invalid space_ids. Consider raising 404. *(Services F19)*
- 7.10 — `list_background_tasks` orders by `started_at` which is null for queued tasks. Use `created_at`. *(Services F20)*
- 7.11 — `save_fact_with_dedup` redundantly sets `target.updated_at`. Remove. *(Services F13)*
- 7.12 — `create_notification` doesn't validate type against enum. Add validation. *(Services F24)*
- 7.13 — `get_db()` always calls `rollback()` even on success. Consider only on exception. *(Services F25)*
- 7.14 — `generate_meta_summary` blocks event loop with sync DB inside async. Document. *(Services F22)*
- 7.15 — `search_service.rebuild_fts_indexes` f-strings missing noqa annotation. Add for consistency. *(Services F17)*
- 7.16 — `create_item` stage validation uses truthiness (`if stage`) instead of `if stage is not None`. Fix. *(Services F7)*
- 7.17 — `_check_missed_runs` swallows all exceptions silently. Already logs at ERROR — acceptable. *(Agent System F23)*

### API Routes & Schemas
- 7.18 — Memory list endpoint doesn't expose `include_archived` parameter. Add if needed. *(API F5)*
- 7.19 — `get_summaries` endpoint has no pagination. Add `limit`/`offset`. *(API F8)*
- 7.20 — `AgentResponse` missing `skill_path` field. Add if it should be visible. *(API F14)*
- 7.21 — `AgentResponse.tools` typed as `list` not `list[str]`. Fix. *(API F15)*
- 7.22 — `get_document_content` has no response_model. Add response documentation. *(API F12)*
- 7.23 — `DocumentCreate.local_path` not validated for path traversal on manual create. Validate. *(API F13)*
- 7.24 — Search endpoint has no `offset` parameter. Add if pagination needed. *(API F18)*
- 7.25 — `AutomationCreate`/`Update` have unnecessary `from_attributes=True`. Remove. *(API F22)*
- 7.26 — `SummaryResponse.decisions` typed as `list` not `list[str]`. Fix. *(API F23)*
- 7.27 — No UUID format validation on path parameters. Low priority. *(API F29)*
- 7.28 — OpenAPI spec may be stale. Regenerate before final review. *(API F28)*
- 7.29 — No API routes for background tasks. Add if frontend needs direct access. *(API F27)*
- 7.30 — Router ordering fragility (`/agents/running` vs `/{agent_id}`). Add UUID regex. *(API F1)*
- 7.31 — Lifespan creates multiple manual DB sessions. Refactor if desired. *(API F2)*

### Agent System
- 7.32 — `_clear_active_sessions` doesn't clear `_steering_queues`. *(Agent System F6)* *Superseded: agent_runner refactor removed `_active_sessions` dict; DB is now single source of truth.*
- 7.33 — `_build_odin_attention_items` loads ALL non-archived items. Add limit. *(Agent System F11)*
- 7.34 — `get_board_state` MCP tool uses `limit=10000`. Document or reduce. *(Agent System F17)*
- 7.35 — Unknown tools default to "execute" operation (secure default — document). *(Agent System F21)*
- 7.36 — Scheduler and task_monitor don't coordinate 60s intervals. Acceptable. *(Agent System F26)*
- 7.37 — `ODIN_MCP_TOOLS` list may not match actual tool set. Audit and sync. *(Agent System F28)*
- 7.38 — `update_background_task` called as no-op on line 762. Remove call. *(Agent System F29)*
- 7.39 — Session file accumulation from consolidation LLM calls. Same as 4.7. *(Agent System F32)*
- 7.40 — Odin singleton race at startup. Add asyncio.Lock. *(Agent System F27 — moved here since single-user)*

### Frontend
- 7.41 — Odin bar streaming timeout too short (2s). Increase to 5-10s. *(Frontend F11)*
- 7.42 — Odin messages use array index as key. Generate unique IDs. *(Frontend F12)*
- 7.43 — localStorage palette/theme casts without validation. Validate. *(Frontend F13)*
- 7.44 — `useDocumentTitle` polls when tab is hidden. Set `refetchIntervalInBackground: false`. *(Frontend F14)*
- 7.45 — Multiple components duplicate `as never` pattern. Consolidate. *(Frontend F15)*
- 7.46 — `PaletteMockup.tsx` dev page in production source. Move or add dev route. *(Frontend F16)*
- 7.47 — `document-viewer.tsx` effect has incomplete dependency array. Fix. *(Frontend F17)*
- 7.48 — Home page backup status query has no error handling. Add. *(Frontend F18)*
- 7.49 — Several select elements lack accessible labels. Add `aria-label`. *(Frontend F19)*
- 7.50 — Toast timer set in store action, not React effect. Acceptable. *(Frontend F20)*
- 7.51 — `Space.tsx` grid row key could theoretically collide. Acceptable with UUIDs. *(Frontend F21)*
- 7.52 — SSE handler Set recreation on subscribe (fragile but works). Document. *(Frontend F3)*

---

## Execution Process

For each phase:
1. **Fix** — spawn agents to implement the fixes
2. **Review** — review the fixes for correctness
3. **Test** — run `make test` + relevant E2E tests
4. **Report** — summarize what was fixed and any issues encountered
5. **Move on** — proceed to the next phase only after tests pass

Phases are sequential. Within each phase, independent fixes can be parallelized.
