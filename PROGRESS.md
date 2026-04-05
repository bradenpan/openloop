# OpenLoop Build Progress

**Reference:** [IMPLEMENTATION-PLAN.md](IMPLEMENTATION-PLAN.md) for full task descriptions and acceptance criteria.

---

## Phase 0: SDK Spike + Project Scaffold — COMPLETE

All 5 tasks done. SDK validated (zero blockers), scaffold built, 19-table schema created, reference implementation reviewed and fixed. Seed data script created.

**Key outcome from spike:** `resume=session_id` works reliably with no TTL. Sessions persist as local JSONL files. Blocking hooks validated for the permission system. Full findings in `spike/results.md`.

**Review fixes after 0.4:** Update pattern changed to `exclude_unset=True`, schemas split into per-domain files, template dict keys fixed, delete endpoint added to reference.

## Phase 1: Core Backend Services + API — COMPLETE

All tasks done. 8 service modules, 10 route files, 52 API endpoints across 34 paths. SSE event contract defined, OpenAPI schema exported, TypeScript type generation wired.

**Deviation from plan:** Tasks 1.4a/1.4b (routes) and 1.5 (type gen) were done partly by orchestrator before switching to subagents. Task 1.6 (tests) produced 257 tests covering all services and routes.

## Phase 2: Session Manager + Agent Conversations — COMPLETE

All 9 tasks done. Context assembler, 25 MCP tools, session manager (core + extended), SSE streaming, Odin service, permission hooks, structured logging.

**Deviations from plan:**
- Tasks 2.8/2.9 (tests + integration) were combined into a single integration check agent.
- `background_task_service.py` was created as a new service (not in the original plan) to support `delegate_background`.

## Post-Build Code Review — COMPLETE

Full code review of Phases 1 and 2 identified 17 issues. All fixed:

**Critical fixes:**
1. Double user message save — removed duplicate save from session_manager
2. Permission hooks not wired — integrated into all 6 `query()` calls
3. MCP tool name prefix mismatch — dynamic prefix extraction added
4. Background tasks using closed DB sessions — each creates its own session now
5. `/agents/running` route shadowed by `/{agent_id}` — fixed via router ordering
6. No cascade deletes — added `cascade="all, delete-orphan"` on all parent relationships
7. FK enforcement off — added `PRAGMA foreign_keys=ON`

**Other fixes:** Dashboard COUNT query, pagination on all list endpoints (limit/offset), LIKE wildcard escaping, broken test assertion, missing timestamps on BackgroundTask/AgentPermission, per-conversation SSE filtering, approval polling timeout (5min default), `datetime.utcnow()` deprecation, asyncio lock per conversation.

## Phase 3: Frontend Foundation — COMPLETE

All 7 tasks done. Full frontend built: design system, app shell, dashboard, space view with kanban, conversation panel with streaming, agent management with permissions.

**Task 3.1:** Design system (3 palettes × 2 themes via CSS variables, Tailwind v4 `@theme inline`), 6 UI components (Button, Input, Badge, Card, Modal, Panel), app shell (collapsible sidebar, Odin bar at bottom, React Router), API client (openapi-fetch + openapi-react-query + generated types), SSE connection manager with auto-reconnect, Zustand stores with localStorage persistence.

**Task 3.2:** Home dashboard — attention items, active agents, space list with create-space modal (4 templates), cross-space todo list with checkbox toggle, conversation list. First-run welcome card.

**Task 3.3:** Space view — 3-column collapsible layout (todos / kanban board / conversations). Kanban drag-drop with @dnd-kit. Board item detail slide-over panel. Create item and new conversation modals.

**Task 3.4:** Conversation panel — block-style messages (Claude.ai style), streaming tokens via SSE, tool call collapsible accordions, inline approval request UI, model selector, conversation close.

**Task 3.5:** Agent management — agent list with CRUD, create/edit modal (name, description, system prompt, model), delete confirmation, permission matrix (resource × operation grid with grant level dropdowns).

**Task 3.6:** Playwright tests — 39/39 pass. App shell, navigation, theme/palette toggle with persistence, dashboard sections, create space modal, agent CRUD modal, Odin bar expand/collapse.

**Task 3.7:** Pending — full frontend↔backend↔SSE integration. Blocked on starting the correct OpenLoop backend (old dispatch app was running on port 8000 during testing).

**Deviations from plan:**
- User chose all 3 color palettes (Slate+Cyan default, Warm Stone+Amber, Neutral+Indigo) with a Settings toggle instead of picking one.
- Odin bar moved to bottom of screen (user preference) instead of fixed top.
- `frontend-design` and `webapp-testing` skills used by subagents as specified in plan.
- 4 page agents ran in parallel (3.2–3.5), then 3 code review agents ran in parallel to catch issues.

**Code review fixes applied:**
1. SSE subscribe race condition — switched to Zustand updater pattern
2. Conversation panel render-phase state update — moved to useEffect
3. Panel missing focus trap — added matching Modal's implementation
4. Conversation sidebar — wired to open ConversationPanel on click
5. API data access — removed incorrect `.data` unwrap in 8 components (API returns arrays/objects directly, not wrapped)
6. Odin bar — wired to send messages via POST /api/v1/odin/message with SSE streaming

**Resolved:** The `PATCH /api/v1/agents/permission-requests/{id}` endpoint exists (agents.py:93-103). Frontend approval UI and backend are wired.

## Phase 3b: Memory Architecture + Context Safety — COMPLETE

All 6 tasks done per IMPLEMENTATION-PLAN.md. Memory system upgraded from basic key-value CRUD to four-tier cognitive architecture. All backend — no frontend changes.

**Task 3b.1:** Schema migration — 7 new columns on `memory_entries`, 2 on `conversation_summaries`, 4 on `background_tasks`, new `behavioral_rules` table. New enums: `RuleSourceType`, `DedupDecision`.

**Task 3b.2:** Memory service rewrite + behavioral rule service. Write-time LLM dedup (Haiku-powered ADD/UPDATE/DELETE/NOOP via `llm_utils.py`), scored retrieval (Ebbinghaus-inspired decay formula), namespace caps (50 space, 20 agent) with lowest-scored eviction, temporal supersession. Behavioral rules: asymmetric confidence (+0.1/-0.2), auto-deactivation.

**Task 3b.3:** 8 new MCP tools (save_fact, update_fact, recall_facts, delete_fact, save_rule, confirm_rule, override_rule, list_rules). Old read_memory/write_memory kept for backward compat.

**Task 3b.4:** Context assembler rewritten — attention-optimized ordering (beginning: identity+rules+tools; middle: summaries+facts; end: board/todos), scored retrieval replaces basic list_entries, procedural memory injection, meta-summary handling, memory management instructions in agent prompts.

**Task 3b.5:** Agent runner safety — `flush_memory()` (mandatory pre-compaction), proactive budget enforcement (checks before SDK call), observation masking (7 recent turns verbatim), `verify_compaction()` (post-compression gap detection).

**Task 3b.6:** 95 new tests + 3 real-LLM integration tests (`pytest -m llm`).

**Bug fix (from Phase 2 review):** Permission enforcer timeout removed — was 5-min auto-deny, now infinite polling per spec.

**Additional bug fixes from code review (8 issues found and fixed):**
1. save_rule/list_rules passed agent name where UUID FK required — added `_agent_id` injection via tool builder
2. `_slugify` key collision — append UUID suffix
3. `_poll_for_approval` infinite loop on deleted request — guard added
4. `llm_utils.py` missing ExceptionGroup catch
5. `_estimate_conversation_context` inflated access/apply counters — added `read_only` flag
6. `list_entries` didn't exclude superseded facts — added `valid_until` filter
7. `delete_fact` bypassed service layer — created `supersede_entry()` in memory_service
8. `source_type` accepted arbitrary strings — added enum validation

**Deviations from plan:**
- Plan called for `save_fact_with_dedup` as a sync function. Had to make it `async` because it calls the LLM. The MCP tool layer (already async) handles this fine, but it's a convention break at the service layer.
- `llm_utils.py` was not in the original plan — created as a shared utility for LLM system calls (dedup, flush, etc.).
- Plan described compression as effective for the current SDK session. In practice, the SDK retains full JSONL history and has no truncation API. Compression creates DB checkpoints useful for future reopens but doesn't reduce current session context. Documented as a known limitation.

## Phase 4: Records, Table View, Documents, Search — COMPLETE

All 7 tasks done per IMPLEMENTATION-PLAN.md. CRM-style records, table view, document management with Drive, and FTS5 full-text search.

**Pre-flight (Task 3.7 resolved):** Integration check confirmed frontend↔backend↔SSE all working. Fixed cascade delete bug (all 37 ForeignKeys missing `ondelete`), changed default port from 8000 to 8010 (avoids clash with dispatch app), added `credentials.json`/`token.json` to `.gitignore`.

**Task 4.1 (Records Backend):** Added `custom_field_schema` (JSON) to Space model. Added `record_id` FK on Todo for linking todos to records. Extended item service with sorting (`sort_by`/`sort_order`), parent-child filtering, custom field validation, `get_record_with_children`, `link_todo_to_record`. New endpoints: `GET /spaces/{id}/field-schema`, `GET /items/{id}/children`, `POST /items/{id}/link-todo`.

**Task 4.2 (Table View Frontend):** Table component with sortable column headers, stage filter, inline cell editing (text/number/date/select), column show/hide popover with localStorage persistence. Three-way view toggle (Board | Table | Documents) in Space view. Record creation modal. Item detail panel enhanced with custom fields, child records, and linked todos sections.

**Task 4.3 (Document Management):** Added `file_size`, `mime_type`, `content_text` to Document model. Upload endpoint (multipart), directory scanning, content streaming endpoint. Text extraction for 16 file types. Frontend: document panel with drag-and-drop upload, document viewer slide-over with inline tag editing.

**Task 4.4 (Google Drive Integration):** OAuth client using `credentials.json`/`token.json`. Drive folder linking via data_sources, file indexing with text extraction, refresh (add/update/remove detection). API routes at `/api/v1/drive`. Three new MCP tools (`read_drive_file`, `list_drive_files`, `create_drive_file`). Frontend: Link Drive button, Drive badge on documents, refresh button.

**Task 4.5a (FTS5 Search Infrastructure):** FTS5 virtual tables for conversation_messages, conversation_summaries, memory_entries, documents (title + content_text). SQLite triggers for INSERT/UPDATE/DELETE sync. Memory triggers exclude archived and superseded entries. Search service with BM25 ranking and `snippet()` excerpts. `GET /api/v1/search` endpoint. Frontend: global search modal with Ctrl+K shortcut, debounced search, results grouped by type.

**Task 4.5b (Cross-Space Search Tools):** Upgraded `search_conversations` and `recall_facts` MCP tools from LIKE to FTS5. New `search_summaries` tool. All cross-space capable with permission scoping via `agent_spaces` join table. Odin searches all spaces.

**Task 4.6 (Tests):** 41 integration tests covering records, documents, search, Drive, and end-to-end workflows.

**Code review (8 issues found and fixed):**
1. Path traversal in file upload — sanitized filenames with `Path.name`
2. XSS in search snippets — HTML-escaped excerpts with safe `<mark>` restoration
3. Migration ordering — chained 3 parallel heads into linear sequence
4. `nullslast()` unsupported on SQLite — replaced with `func.coalesce`
5. Drive datetime comparison — string compare replaced with proper datetime parsing
6. `update_document` missing field allowlist — added explicit `_DOC_UPDATABLE_FIELDS`
7. Upload/refresh errors silently swallowed in frontend — added error feedback
8. FTS5 documents index only had `title` — extended to include `content_text`

**Deviations from plan:**
- Port changed from 8000 to 8010 to avoid conflict with the old dispatch app
- Cascade delete bug (pre-existing from Phase 2) fixed as part of pre-flight — all FKs now have `ondelete="CASCADE"` or `ondelete="SET NULL"`, `passive_deletes=True` removed

## Phase 4b: Flexible Space Layouts — COMPLETE

All 5 tasks done per IMPLEMENTATION-PLAN.md. Widget-based space layouts replacing the hardcoded 3-column view.

**Task 4b.1 (Schema + Backend):** New `space_widgets` table with `WidgetType` and `WidgetSize` enums. Layout service (6 functions: get, add, update, remove, set, create_default_widgets). 5 API endpoints under `/api/v1/spaces/{id}/layout`. Alembic migration creates default widgets for all existing spaces based on template. Space creation auto-generates default widgets.

**Task 4b.2 (Widget Renderer):** Space.tsx refactored from hardcoded flex layout to CSS Grid driven by layout API. Widget registry maps types to components. Self-contained widget wrappers (TodoPanel, KanbanBoard, DataTable, ConversationSidebar, DocumentPanel). Board/Table toggle preserved when both exist. Placeholder for future widget types (chart, stat_card, markdown, data_feed).

**Task 4b.3 (Layout Editor UI):** Slide-over panel from gear icon in space header. Widget cards with up/down reorder arrows, inline size dropdown, expandable config accordion, remove with click-twice confirmation. Grid picker for adding widgets. All changes live (immediate API calls). Design inspired by Notion/Linear/Grafana.

**Task 4b.4 (Agent Layout MCP Tools):** 5 new MCP tools (29-33): `get_space_layout`, `add_widget`, `update_widget`, `remove_widget`, `set_space_layout`. Registered as standard tools available to all agents.

**Task 4b.5 (Tests):** 31 new tests across service (15), API (10), and MCP (6) layers.

**Code review (3 issues found and fixed):**
1. `set_layout` NOT NULL crash when bulk-replacing without explicit positions — enforced sequential position assignment
2. Grid row React keys used array indices — switched to stable widget ID composites
3. Layout editor query invalidation key missing params — added explicit space params for reliable cache busting

**Deviations from plan:**
- None — executed as specified in IMPLEMENTATION-PLAN.md

## Phase 4c: Unified Item Model — COMPLETE

All 5 tasks done per IMPLEMENTATION-PLAN.md. Todos collapsed into items; views (list/kanban/table) are presentation, not data model.

**Task 4c.1 (Schema Migration):** Alembic migration adds `is_done` to items, renames `parent_record_id` → `parent_item_id`, creates `item_links` table (many-to-many with unique constraint). Backfills `board_columns` on Simple/Knowledge spaces. Migrates all todos → items (type='task'), converts todo record_id links → item_links rows, drops `todos` table. New `LinkType` enum, `ItemLink` ORM model.

**Task 4c.2 (Backend Refactor):** Deleted `todo_service.py`, todo routes, todo schemas. Updated `item_service`: lightweight creation (title + space_id minimum), `toggle_done()` with bidirectional stage sync (tasks only — records excluded), `is_done` filter on `list_items`, `get_record_with_children` returns linked items via `ItemLink` joins. New `item_link_service.py` (create/delete/list, bidirectional queries). Home dashboard queries items instead of todos.

**Task 4c.3 (MCP Tools + Context Assembler):** Removed 3 todo tools. Added 7 new tools: `create_task`, `complete_task`, `list_tasks`, `link_items`, `unlink_items`, `get_linked_items`, `archive_item`. Renamed `get_todo_state` → `get_task_state`, `get_cross_space_todos` → `get_cross_space_tasks`. Context assembler and Odin service updated. Permission enforcer updated.

**Task 4c.4 (Frontend):** Types regenerated. TodoPanel → TaskListPanel with inline stage dropdown and done-item toggle. Kanban "Done" column hideable. Home dashboard uses `open_task_count`. Seed script creates tasks via `item_service`. All todo references removed from frontend.

**Task 4c.5 (Tests):** Deleted todo test files. Added tests for is_done toggle, stage sync, lightweight creation, link CRUD, new MCP tools. 776 tests passing.

**Code review (2 pre-existing issues found and fixed):**
1. `search_summaries` missing from `ODIN_MCP_TOOLS` — added
2. `search_summaries` missing from `_MCP_TOOL_MAP` in permission enforcer — added

**Design decision:** All spaces now have `board_columns` (never null). Simple/Knowledge templates get `["todo", "in_progress", "done"]` with `board_enabled=True`, `default_view="list"`. Eliminated all conditional null-checking for board_columns.

**Deviations from plan:**
- Plan called for removing todo tools and adding `complete_item`. Instead, created `create_task`/`complete_task`/`list_tasks` as convenience wrappers (clearer agent UX) alongside the generic item tools. `complete_item` functionality covered by `complete_task`.

## Phase 5: Agent Builder + Sub-agents + Steering — COMPLETE

All 5 tasks done per IMPLEMENTATION-PLAN.md (with architectural revisions agreed during planning). Conversational agent creation, sub-agent delegation with managed turn loop, and mid-task steering.

**Pre-flight (Schema):** Alembic migration adds `skill_path` column to `agents` table. Step tracking columns (`current_step`, `total_steps`, `step_results`, `parent_task_id`) already existed from Phase 3b schema. Updated `background_task_service` updatable set to include step fields.

**Task 5.2a (Delegation + Workflow Tracking):** Implemented `delegate_task` MCP tool (replaced Phase 2 placeholder). New `update_task_progress` MCP tool for agents to report step-by-step progress. Added `get_agent_by_name()` to agent service. Parent-child task linking via `parent_task_id` with `list_child_tasks()` query. New `task_monitor.py` — asyncio background loop (60s interval) detecting stale (queued >10min) and stuck (running >30min) tasks, creates notifications. Wired into app lifespan startup/shutdown. Dedup logic prevents repeated notifications for the same task.

**Task 5.1 (Agent Builder + Skill Registration):** Hybrid agent definition model — DB stores runtime config (permissions, spaces, model), system prompt loaded from SKILL.md on disk when `skill_path` is set, falls back to `system_prompt` column. `_load_skill_prompt()` in context assembler reads SKILL.md, strips YAML frontmatter. Agent Builder skill created at `agents/skills/agent-builder/SKILL.md` — follows skill-creator methodology: interview user → draft SKILL.md → test via delegation → iterate → register. Two exclusive MCP tools: `register_agent` (creates/updates DB record with skill_path), `test_agent` (delegates a test conversation to the draft agent). `build_agent_builder_tools()` creates Agent Builder's tool server (standard + exclusive tools). SessionManager detects Agent Builder by name and uses the dedicated tool builder. Odin system prompt updated to route agent creation requests to Agent Builder. `scripts/register_skills.py` scans `agents/skills/` and registers all existing skills as agents.

**Task 5.2b (Mid-Task Steering):** Rewrote `_run_background_task` from single fire-and-forget `query()` call into a managed turn loop. Agent works in discrete turns (max 20), checks steering queue between turns, signals completion with `TASK_COMPLETE`. In-memory steering queue (`_steering_queues` dict, max 10 messages per conversation). `steer()` function queues messages and publishes `steering_received` SSE event. New `POST /api/v1/conversations/{id}/steer` endpoint with `SteerRequest` schema. Background agent system prompts include incremental-work instructions. Step progress updated and SSE `background_progress` event published after each turn.

**Task 5.2c (Delegation UI):** New `BackgroundTaskCard` component — compact card with status dot (green=running with ping animation, yellow=stale, red=failed, blue=completed), agent name, step label, slim progress bar, elapsed time. Expanded view shows numbered step history with timestamps and steering text input. Recursive rendering for child tasks (indented). New `BackgroundTaskPanel` — polls running endpoint every 5s, subscribes to SSE `background_progress` events for real-time step updates, caches progress in module-level Map. Integrated into Home.tsx replacing the static ActiveAgents component. Added `SSEBackgroundProgressEvent` interface and `background_progress` to SSE event types.

**Task 5.3 (Tests):** 24 new tests covering: step tracking accumulation, parent-child task creation and querying, stale/stuck detection (with backdated timestamps), no false positives on completed/fresh tasks, agent get-by-name, skill_path on create/update, steer endpoint (404 for missing session, 422 for bad schema), MCP tool update_task_progress (success + bad input), delegate_task (agent not found), skill_path resolution (_load_skill_prompt reads SKILL.md, strips frontmatter, returns None for missing), context assembler identity (skill_path takes priority over system_prompt column, fallback works).

**Code review (2 issues found and fixed):**
1. Path traversal vulnerability in `register_agent` and `_load_skill_prompt` — added skill_name validation (rejects `..`, `/`, `\`) and `os.path.realpath` check to ensure resolved path stays under project root
2. HTTPException imported inside exception handler in conversations route — moved to module-level import

**Deviations from plan:**
- Plan had Tasks 5.1 and 5.2a running in parallel. Revised dependency: 5.2a runs first (delegation is foundation), then 5.1 and 5.2b in parallel. Agent Builder needs `delegate_task` to test draft agents.
- Plan described Agent Builder as using custom MCP tools to write DB records. Revised to hybrid model: Agent Builder creates skill files (SKILL.md) on disk using standard file tools, tests via `delegate_task`, then registers in DB via `register_agent` MCP tool. This integrates the skill-creator methodology and keeps agent definitions in git.
- Plan described agent creation as possible through both web UI (quick path) and Claude Code (full path). Revised to single full-creation path only — all agent creation goes through the Agent Builder inside OpenLoop. No "quick" half-baked agents.
- Existing skills (eng-manager, frontend-design, webapp-testing, research-web, file-editor, skill-creator) designed to be registered as OpenLoop agents via `scripts/register_skills.py`.

## Phase 6: Automations — COMPLETE

All 4 tasks done per IMPLEMENTATION-PLAN.md. Scheduled agent runs with dashboard, notification panel, and pre-built templates.

**Task 6.1 (Automation Backend):** `AutomationService` — full CRUD, run history tracking (`create_run`, `complete_run`, `list_runs`), missed-run detection via `croniter` (uses `automation.created_at` as anchor, not arbitrary epoch). `AutomationScheduler` — asyncio background loop (60s interval, same pattern as `task_monitor`), cron expression matching, fires automations as background tasks via `delegate_background`. Concurrency: max 2 concurrent automation sessions, skips cycle when active user conversations exist. Missed-run detection on startup creates `AUTOMATION_MISSED` notifications with dedup (no duplicate notifications on repeated restarts). Run lifecycle fully wired: `delegate_background` accepts `automation_run_id`, `_run_background_task` calls `complete_run` on both success and failure paths. `model_override` flows through `delegate_background` → `_run_background_task` → `resolve_model`. 7 API endpoints at `/api/v1/automations` (create, list, detail+runs, update, delete, manual trigger, run history). Alembic migration adds `automation_id` FK to `notifications` table. `mark-all-read` endpoint added to notifications API.

**Task 6.2 (Automation Dashboard + Notification Panel):** Automations page — own sidebar item (same level as Agents). List view with animated status dots (same pattern as BackgroundTaskCard), schedule in plain English, last run status badge, enable/disable toggle with error handling. Detail slide-over panel with config display, run history (paginated, "View all" loads more), "Run now" with inline confirmation, edit/delete. Create/edit modal with cron presets (Daily/Weekly/Monthly/Custom), hour + minute pickers, plain-English preview, agent picker, space picker, model override. Cross-field cron validation on both Create and Update schemas. Notification panel — "Unread Notifications" in Home stat bar now clickable, opens slide-over panel with notification list. Each notification shows type badge, title, body, time-ago. Click marks read and routes: `automation_failure`/`automation_missed` → `/automations`, `pending_approval` → `/space/{space_id}`, others → space or stay on Home. "Mark all read" button. Accessible: form labels with htmlFor/id pairs, toggle aria-labels, panel has accessible name.

**Task 6.3 (Pre-built Templates):** Three automation templates registered via `scripts/register_automation_templates.py` (idempotent, wired as `make register-automations`). Shared "Automation Agent" (model: sonnet). Templates: "Daily Task Review" (daily 8am, scans overdue + stuck tasks), "Stale Work Check" (weekly Monday 9am, items untouched 7+ days), "Follow-up Reminder" (daily 8am, CRM records with past-due `next_follow_up`). All pre-configured, disabled by default. Instructions use `get_cross_space_tasks`, `list_items`, `get_linked_items`, and `write_memory` for results.

**Task 6.4 (Tests):** 60 new backend tests — 28 service tests (CRUD, run lifecycle, missed-run detection, concurrency counting), 22 API tests (all endpoints, pagination, trigger with mocked async, mark-all-read), 10 scheduler tests (`_is_due` logic, missed-run queries, running count). E2E Playwright tests in `tests/e2e/test_automations.py`.

**Code review (4 rounds — Sonnet initial, then 3 rounds of Opus):**

*Round 1 (Sonnet) — 10 issues found and fixed:*
1. `asyncio.create_task` called in sync context — made `trigger_automation` async
2. Resource leak in `_fire()` error branch — added try/finally
3. Stale concurrency counter in scheduler loop — re-query DB each iteration
4. `automation_missed` not in NotificationType enum — added to `contract/enums.py`
5. No cron expression validation — added `croniter.is_valid()` field validator
6. trigger_type/status bare strings — replaced with enum constants
7. `get_missed_runs` year-2000 epoch — changed to `automation.created_at`
8. Missing logger in `_fire()` error handler — added `logger.error` with exc_info
9. Lazy imports in scheduler hot path — moved to module level
10. Missing `ConfigDict(from_attributes=True)` on Create/Update schemas — added

*Round 2 (Opus) — 2 critical + 8 important issues found and fixed:*
1. **CRITICAL:** AutomationRun records never completed — wired `automation_run_id` through `delegate_background` → `_run_background_task` → `complete_run` on both success/failure paths
2. **CRITICAL:** Frontend sent `trigger_type: 'schedule'` (not in enum) — changed to `'cron'`
3. Notification panel navigated to non-existent `/conversations/` route — changed to `/space/{space_id}`
4. Can't clear optional fields in edit mode (`undefined` vs `null`) — PATCH body uses `null`
5. DetailPanel missing key prop — added `key={selectedId}` to force remount
6. Custom cron stale expression after preset changes — syncs from current form state
7. `model_override` field ignored — flows through delegate_background to resolve_model
8. Duplicate missed-run notifications — dedup query before creation
9. N+1 lazy loading in list endpoint — manual response construction
10. No error state for automations list query — added error card

*Round 3 (Opus) — 2 issues found and fixed:*
1. `status="success"` should be `"completed"` (matching BackgroundTaskStatus enum)
2. Dirty DB session in error handler — added `db.rollback()` before cleanup operations

*Round 4 (Opus) — 6 should-fix items found and fixed:*
1. `AutomationUpdate` missing cross-field validation for cron — added `model_validator` using `model_fields_set`
2. Tests used `"manual"` trigger_type not in enum — changed to `"event"`
3. Tests used `status="success"` — changed to `"completed"`
4. Notification panel missing accessible name — passed `title="Notifications"` to Panel
5. Time picker only showed whole hours — added minute dropdown (00/15/30/45)
6. `describeCron` produced odd text for dow=7 — added `% 7` modulo

**Deviations from plan:**
- Plan specified automation failures appearing as a dedicated section in Home attention items. Implementation uses the notification system instead — failures create notifications, and the new notification panel (clickable from the "Unread Notifications" stat) routes to the automations page. Functionally equivalent, architecturally cleaner.
- Notification panel and `mark-all-read` endpoint were not in the Phase 6 spec but were added to support the attention items integration requirement. General-purpose infrastructure, not automation-specific.
- Template instructions use `write_memory` instead of `create_notification` because no `create_notification` MCP tool exists for agents. Automation results stored as memory entries.

## Phase 7: Polish, Backup, Integration — COMPLETE

All 6 tasks done per IMPLEMENTATION-PLAN.md. Memory lifecycle management, summary consolidation, backup system, error handling/resilience, UI polish, and comprehensive E2E integration tests.

**Task 7.1a (Memory Lifecycle Management):** `auto_archive_superseded()` — daily background job archives facts where `valid_until` set 90+ days ago. Lazy rule demotion in context assembler — rules with `confidence < 0.3` and `apply_count >= 10` auto-deactivated during context assembly. LLM-driven fact consolidation — monthly background job (or manual trigger) calls Haiku to review active facts, produces consolidation report with proposed merges, contradictions, and stale entries. User approves before any changes apply. `LifecycleScheduler` — asyncio background loop (60s interval, same pattern as automation scheduler), runs daily archival and monthly consolidation. Checkpoint pruning — closed-conversation checkpoints excluded from context assembly. 3 API endpoints: `GET /spaces/{id}/memory/health`, `POST /spaces/{id}/memory/consolidate`, `POST /spaces/{id}/memory/consolidate/apply`. 6 Pydantic schemas in new `memory.py`. Space Settings panel — tabbed slide-over (Layout, Memory, History) replacing the old layout editor. Memory tab with stats bar, facts/rules sub-tabs, archive/delete actions, consolidation report display with per-item accept/dismiss. `NotificationType.MEMORY_CONSOLIDATION` added.

**Task 7.1b (Summary Consolidation):** `consolidation_service.py` — `get_unconsolidated_count()` and `generate_meta_summary()`. Threshold-triggered: when a space hits 20+ unconsolidated summaries, auto-generates a meta-summary via Haiku. Wired into `close_conversation()` (fire-and-forget, non-blocking). Successive consolidation — second round absorbs old meta-summary plus new individuals into a new meta. Manual trigger: `POST /spaces/{id}/consolidate` (returns 409 if <2 summaries). Context assembler updated: meta-summary loads first, then unconsolidated individuals (excluding checkpoints).

**Task 7.2 (Backup System):** `scripts/backup_local.py` — local SQLite backup via `.backup` command with `shutil.copy2` fallback, 10-backup retention, timestamped filenames. `make backup` and `make backup-gdrive` wired in Makefile. Backup status tracking via `data/.last_backup` timestamp file. `GET /api/v1/system/backup-status` endpoint returns `last_backup_at`, `hours_since_backup`, `needs_backup`. Home dashboard shows subtle muted reminder when no backup in 24 hours.

**Task 7.3 (Error Handling + Edge Cases):** Rate limit retry wrapper — `_query_with_retry()` wraps SDK `query()` calls with exponential backoff (30s/60s/120s, max 3 retries). Creates notification and publishes `rate_limited` SSE event on rate limit. SSE reconnection — `_ReplayBuffer` (deque, last 100 events) with sequential IDs, `Last-Event-ID` header support for replay on reconnect. `ConnectionStatus` component shows "Reconnecting..." indicator. Orphaned task cleanup on startup — marks stale running/queued tasks as failed. Graceful shutdown — closes active interactive sessions with 30s timeout, per-session DB sessions for concurrency safety. `SSEEventType.RATE_LIMITED` added. SQLite `busy_timeout` and crash recovery confirmed pre-existing.

**Task 7.4 (UI Polish):** `Skeleton` component (configurable pulsing rectangle). Toast notification system (Zustand store, bottom-right, auto-dismiss 3s, `role="status"`, `aria-live="polite"`). `FadeIn` wrapper on route transitions. Panel slide-in animation (`translate-x`). Modal fade+scale animation. Skeleton loading states on Home (stat cards, space list) and Space (widget grid). Empty states for agents, conversations, kanban, automations. Keyboard shortcuts: `/` focus Odin, `Escape` close panel/modal, `n` new item, `?` shortcuts help overlay, `Ctrl+K` search (pre-existing). `useDocumentTitle` hook — browser tab badge `(N) OpenLoop` for pending approvals + unread notifications. Date utility (`formatDate`, `formatDateTime`, `timeAgo`). Timezone-safe due dates (UTC suffix). Accessibility: `aria-invalid`/`aria-describedby` on Input, `aria-labelledby` on Modal, `aria-label` on layout editor select, focus-visible rings. Visual consistency: Settings theme toggle uses Button component.

**Task 7.5 (E2E Integration Tests):** 63 Playwright tests across 15 spec files, all using API mocking (`page.route()`) — no backend required. Comprehensive mock layer with factory functions (`makeSpace`, `makeAgent`, `makeItem`, etc.). Test scenarios: first-run experience, space navigation, item CRUD, conversation lifecycle, agent management, automation management, kanban workflow, search modal, settings persistence, Space Settings panel, keyboard shortcuts, Home dashboard, empty states, UI polish verification, app shell navigation. 3 SDK-dependent tests in `e2e/slow/` directory (skipped by default).

**Code review (2 rounds — 4 review agents total):**

*Round 1 — backend (19 issues found, 16 fixed):*
1. **CRITICAL:** Timezone mismatch in `consolidate_space_memory` — naive vs aware comparison would crash at runtime. Fixed: `datetime.now(UTC).replace(tzinfo=None)`.
2. **CRITICAL:** Graceful shutdown fails for background sessions — `close_conversation()` requires `status="active"`. Fixed: filter to `status == "active"` sessions only.
3. **CRITICAL:** Cross-space entry manipulation in `apply_consolidation_report` — no namespace validation. Fixed: added namespace check before modifying entries.
4. Long-lived DB session in lifecycle scheduler — single session across LLM calls. Fixed: per-space `SessionLocal()`.
5. Missing 404 on memory health routes — returns zeros for invalid space. Fixed: `space_service.get_space()` validation.
6. Missing `db.rollback()` in lifecycle scheduler error handler. Fixed.
7. `generate_meta_summary` fragile with 0 individuals — added `ValueError` guard.
8. Skipped: `ExceptionGroup` Python 3.11+ (project requires 3.12+), raw notification strings (pre-existing), threading.Lock in async (O(1) ops).

*Round 1 — frontend (18 issues found, 9 fixed):*
1. **CRITICAL:** SpaceList card clicks don't navigate — `CardBody` dropped `onClick`. Fixed: forward `onClick` to div.
2. **CRITICAL:** Archive button sends no-op PATCH — no archive route. Fixed: added `POST /memory/{id}/archive` backend route, updated frontend.
3. **CRITICAL:** XSS in search modal — confirmed non-issue, backend already HTML-escapes excerpts with safe `<mark>` restoration (Phase 4 fix).
4. Stale focus traps in Panel/Modal — elements cached on mount. Fixed: recompute in keydown handler.
5. Double Escape handlers — Panel/Modal + keyboard shortcuts hook. Fixed: `stopPropagation`.
6. Missing label associations in ItemDetailPanel. Fixed: `id`/`htmlFor` pairs.
7. Toast container lacks `aria-live`. Fixed: always render with `aria-live="polite"`.
8. Non-functional RulesList checkbox. Fixed: removed.
9. Uncoordinated dual mutations in handleSave. Fixed: chained (move after update succeeds).

*Round 2 — backend (16 issues found, 8 fixed):*
1. **CRITICAL:** Shared DB session across concurrent shutdown coroutines. Fixed: per-session `_close_one()` helper.
2. **CRITICAL:** `backup_gdrive.py` wrong REPO_ROOT — `.parent.parent.parent` gives `C:\dev` not `C:\dev\openloop`. Fixed: `.parent.parent`.
3. Timezone consistency — `auto_archive_superseded` used aware cutoff, `consolidate_space_memory` used deprecated `utcnow()`. Fixed: standardized on `datetime.now(UTC).replace(tzinfo=None)`.
4. `_run_daily` missing `db.rollback()`. Fixed.
5. `apply_consolidation_report` iterates `None` when client sends explicit null. Fixed: `or []` pattern.
6. `_run_monthly` closes DB then iterates ORM objects. Fixed: extract to plain tuples first.
7. Redundant `db.close()` in error path. Fixed.
8. `backup_gdrive.py` `datetime.now()` without UTC for filenames. Fixed: `datetime.now(UTC)`.

*Round 2 — frontend (20 issues found, 8 fixed):*
1. `stopPropagation` ineffective on document-level listeners. Fixed: `stopImmediatePropagation`.
2. `valid_until` filter hides all superseded entries regardless of expiry. Fixed: check `new Date(valid_until) > new Date()`.
3. `Card` component drops `onClick` (not just `CardBody`). Fixed: forward to div.
4. `Home.tsx` `allLoading` uses `&&` instead of `||`. Fixed.
5. `Space.tsx` state not reset on `spaceId` change. Fixed: `useEffect` resets `settingsOpen`, `selectedDocId`, `centerView`.
6. Layout editor size select missing `aria-label`. Fixed.
7. `connection-status.tsx` missing `role="status"`/`aria-live`. Fixed.
8. `search-modal.tsx` `as never` type casts. Fixed: uses generated types.

*Additional fixes between rounds (5 items):*
1. `ConsolidationResponse.conversation_id` typed `str` but can be `None`. Fixed: `str | None`.
2. `backup_local.py` local time for filename vs UTC for `.last_backup`. Fixed: UTC consistently.
3. `space-settings.tsx` stale `activeTab` on `spaceId` change. Fixed: `useEffect` reset.
4. `timeAgo` returns "NaN d ago" for invalid dates. Fixed: guard.
5. `ShortcutsHelp` lacks own Escape handler. Fixed: added `useEffect` listener.

**Deviations from plan:**
- Plan specified "optional: backup on conversation close" — skipped per user decision.
- Plan specified notification sounds — replaced with browser tab badge (less intrusive, more useful).
- Space Settings panel (tabbed: Layout, Memory, History) was not in the original plan — added to house memory health UI and consolidation trigger alongside the existing layout editor.
- E2E tests use full API mocking instead of requiring a running backend — faster, more reliable, with SDK-dependent tests in a separate slow/ directory.

## Post-Build Code Review (Full System) — IN PROGRESS

Full codebase review and fix process run by eng-manager agent team. 4 parallel review agents (Backend Services, API Routes, Agent System, Frontend) produced 90 findings (7 critical, 39 important, 44 minor). Fixes organized into 7 phases in `CODE-REVIEW-FIXES.md`.

### Phase 1: Critical Fixes — COMPLETE

7 critical fixes applied:

1. **Automation double-fire** — `automation_service.py`: set `last_run_at` before async fire to prevent scheduler re-triggering during long-running tasks
2. **Odin SSE token filtering** — `odin-bar.tsx`: filter SSE events by `conversationId` so Odin only shows its own tokens, not other conversations'
3. **XSS in search results** — verified: backend `_safe_snippet()` uses null-byte delimiters + `html.escape` + safe `<mark>` restoration. Added documentation comments. No code fix needed.
4. **Permission polling timeout** — `permission_enforcer.py`: 30-minute timeout with auto-deny, notification creation, and clean session cleanup (was infinite loop)
5. **Migration: explicit `is_done` column** — new migration checks and adds `is_done` to items table if missing (was working by accident via Alembic batch mode)
6. **Migration: FK cascades** — same migration recreates all FK constraints across 17 tables with correct `ondelete` clauses matching ORM models (production had no cascades)
7. **Orphaned background task cleanup** — `session_manager.py`: `recover_from_crash` now marks RUNNING/QUEUED BackgroundTask records as FAILED on server restart

### Phase 2: Security & Authorization — COMPLETE

5 security fixes applied:

1. **MCP tool space scoping** — `mcp_tools.py`: added `_validate_space_access` helper + validation in 18 tools that accept `space_id`. System agents (Odin) bypass check.
2. **Test agent space restrictions** — `mcp_tools.py`: test agents inherit Agent Builder's space restrictions instead of getting unrestricted access
3. **Widget ownership validation** — `layout_service.py` + `layout.py`: `update_widget`/`remove_widget` verify widget belongs to the URL's `space_id`
4. **Google Drive scope narrowed** — `gdrive_client.py`: from full `drive` to `drive.readonly` + `drive.file` (principle of least privilege)
5. **Windows path case sensitivity** — `permission_enforcer.py`: case-insensitive matching in `is_system_blocked` prevents bypasses like `OPENLOOP.DB`

### Phase 3: Data Correctness — COMPLETE

7 data correctness fixes applied:

1. **Memory active filter** — `memory_service.py`: `_active_filter` + 4 inline copies now include `OR valid_until > now` so future-dated entries aren't treated as expired
2. **MemoryCreate schema cleanup** — `schemas/memory.py`: removed unused `importance` and `category` fields that were silently dropped
3. **Stage in update_item** — `item_service.py`: now raises 422 "Use move_item to change stage" instead of silent ignore
4. **Automation validation** — `automation_service.py`: validates `trigger_type` enum, requires `cron_expression` when type is cron, validates with `croniter.is_valid()`
5. **move_item guard** — `item_service.py`: added `if space and space.board_columns:` guard matching other methods
6. **recall_facts read-only** — `mcp_tools.py`: removed access tracking from read path, pass `read_only=True` to scored retrieval
7. **Timezone standardization** — `memory_service.py`: all DB writes use naive UTC via `.replace(tzinfo=None)` consistently

### Review Round 2 Fixes — COMPLETE

Code review of Phases 1-3 fixes found 5 additional issues, all fixed:

1. **FTS5 search_memory bypassed active filter** — `search_service.py`: added `archived_at IS NULL` and `valid_until` filtering to FTS5 SQL query
2. **ID-based MCP tools lacked space validation** — `mcp_tools.py`: added space access checks to 11 ID-based tools (`complete_task`, `update_item`, `move_item`, `get_item`, `read_document`, `archive_item`, `link_items`, `unlink_items`, `get_linked_items`, `update_widget`, `remove_widget`)
3. **Odin first-message token race** — `odin-bar.tsx`: added `pendingSendRef` to accept tokens during the window between send and POST response
4. **test_agent existing agent scope** — `mcp_tools.py`: existing test agents now have space linkage updated to match caller's scope
5. **Minor consistency** — naive UTC in `permission_enforcer.py`, standardized enum comparison in `automation_service.py`

16 new tests written covering all Phase 1-3 behaviors: space access validation (4 tests), permission timeout (2), orphaned task cleanup (1), automation validation (5), stage rejection (1), move_item guard (1), widget ownership (2).

### Phase 4: Resource Leaks & Stability — COMPLETE

8 stability fixes applied:

1. **Conversation lock cleanup** — `session_manager.py`: locks removed from `_conversation_locks` when sessions close
2. **DB sessions across async boundaries** — `session_manager.py`: `flush_memory`, `_create_checkpoint`, `_compress_conversation` now use short-lived `SessionLocal()` for post-await DB writes
3. **Event bus queue bounds** — `event_bus.py`: queues capped at 1000 items, `put_nowait` with `QueueFull` drop + warning
4. **Fire-and-forget task references** — `automation_service.py`, `odin.py`, `session_manager.py`: all `asyncio.create_task` calls now tracked in sets with done callbacks logging exceptions
5. **Context size caching** — `session_manager.py`: cached system prompt token estimate eliminates redundant context assembly per message
6. **Context assembly read_only guard** — `context_assembler.py`: `apply_count` increment and auto-demotion guarded by `if not read_only`, prevents counter inflation during estimation
7. **Abandoned SDK session cleanup** — `llm_utils.py`, `consolidation_service.py`: JSONL session files deleted after utility LLM calls via `_cleanup_session_file()`, cleanup in `finally` block covers error paths
8. **Stream end SSE event** — `session_manager.py` emits `stream_end` event after response completes; `odin-bar.tsx` listens for it with 10-second fallback timeout (replaces fragile 2-second silence detection)

Code review of Phase 4 found 1 critical + 5 important + 6 minor issues, all addressed:
- **Critical:** `delegate_background` create_task was not tracked — fixed with task set + done callback
- **Important:** Scheduler/monitor tasks lacked done-callback logging — added; consolidation session file leaked on SDK errors — moved cleanup to `finally` block; stale context cache documented as approximate; short-lived session commit pattern documented
- Odin bar timeout stale closure — fixed with functional updater pattern

### Phase 5: Frontend Fixes — COMPLETE

8 frontend fixes applied:

1. **Agent dropdown fix** — `new-conversation-modal.tsx`: changed `agentsData?.data` to `agentsData` (API returns flat array, not wrapped)
2. **Conversation streaming safety** — `conversation-panel.tsx`: added `stream_end` SSE handler + 10-second fallback timeout + existing message-count detection (three layers of defense)
3. **Conversation sidebar accessibility** — `conversation-sidebar.tsx`: replaced custom overlay with `Panel` component (adds focus trap, Escape handling, aria attrs)
4. **Document panel toast** — `document-panel.tsx`: replaced blocking `alert()` with toast notifications
5. **Type safety cleanup** — `background-task-card.tsx`, `memory-tab.tsx`, `Automations.tsx`: removed all `as never` casts and manual error typing (endpoints were already in OpenAPI spec)
6. **Table view column toggle** — `table-view.tsx`: local `configVersion` state replaces unnecessary query invalidation
7. **Panel aria-labelledby** — `panel.tsx`: conditional `aria-labelledby` with heading ID, fallback `aria-label="Panel"`, added `noPadding` prop
8. **Tag filtering fix** — `document_service.py`: numeric bind parameter indexes (`tag_0`, `tag_1`) replace user-derived names that crashed on special characters

Code review found 0 critical, 0 important, 2 minor issues (unnecessary useCallback dep, potential double-scroll in Panel wrapper) — neither requiring action.

## Current State

### Phase 6: API Surface & Conventions — COMPLETE

11 API surface fixes applied:

1. **Steer response_model** — `conversations.py`: `SteerResponse` schema + response_model on steer endpoint
2. **Field-schema response_model** — `spaces.py`: `response_model=list` on field-schema endpoint
3. **Running sessions response_model** — `running.py`: `RunningSessionResponse` schema + response_model
4. **Messages pagination** — `conversations.py` + `conversation_service.py`: limit/offset on get_messages (default 50, max 500)
5. **Behavioral rules API** — new `behavioral_rules.py` route file with 4 CRUD endpoints, agent ownership verification, `update_rule` service function added
6. **DashboardResponse moved** — `home.py` schema moved to `schemas/home.py`, re-exported from `__init__.py`
7. **Memory router prefix** — `memory.py`: dual routers with proper prefixes replacing inline paths
8. **Public is_text_file** — `document_service.py`: renamed from `_is_text_file`, call site updated
9. **LinkType enum** — `schemas/items.py`: `ItemLinkCreate.link_type` and `ItemLinkResponse.link_type` now use `LinkType` enum; `ItemResponse.item_type` uses `ItemType` enum
10. **Stronger list typing** — `schemas/agents.py`, `conversations.py`, `spaces.py`: `list | None` → `list[str] | None` on 6 fields
11. **Typed status param** — `conversations.py`: `status` query param uses `ConversationStatus` enum

Code review found 2 important issues, both fixed:
- Behavioral rules update/delete didn't verify agent ownership — added check
- `BehavioralRuleCreate` had phantom `agent_id` field (path param is source of truth) — removed

### Phase 7: Minor Cleanup — COMPLETE

~35 fixes applied across 5 batches (17 items skipped as already done in earlier phases or acceptable as-is):

**Migrations & Models (3):** `board_columns` model set to `nullable=False`, 4 query indexes added (notifications, messages, items, background_tasks), 4c1 migration FK pragma wrapped in try/finally.

**Backend Services (9):** Removed dead `..` check and no-op tag filter in document_service, added status validation in conversation_service, 404 for invalid space_ids in agent_service, ordered background tasks by `created_at`, removed redundant `updated_at` set in memory_service, added notification type validation, added `noqa: S608` to FTS rebuild, fixed stage validation truthiness in item_service.

**API Routes & Schemas (9):** Added `include_archived` param to memory list, pagination on summaries, `skill_path` on AgentResponse, document content response documentation, path traversal validation on DocumentCreate, search offset, removed `from_attributes` from Create/Update schemas, documented router ordering.

**Agent System (6):** Cleared steering queues and background tasks in test helper, limited Odin attention items to 500, documented board_state limit, synced ODIN_MCP_TOOLS (added 17 missing tools), removed no-op update_background_task call, added asyncio.Lock to Odin singleton.

**Frontend (7):** Odin messages use unique IDs instead of array index keys, localStorage palette/theme validated before casting, `refetchIntervalInBackground: false` on document title poll, PaletteMockup documented as dev utility, document-viewer effect dependency array fixed, backup status error handling added, aria-labels on 6 unlabeled select elements.

**OpenAPI spec regenerated** from current routes.

## Post-Build Code Review (Full System) — COMPLETE

Full codebase review and fix process complete. 4 initial review agents produced 90 findings (7 critical, 39 important, 44 minor). All 7 phases of fixes applied with code review cycles after each phase. Total: ~80 fixes across ~50 files, 16 new tests, multiple review rounds catching additional issues.

## Session Manager Refactor (agent_runner) — COMPLETE

Replaced `session_manager.py` (1,728 lines) with `agent_runner.py` (~400 lines). Fixed broken first-message flow and broken close/reopen routes. Removed redundant in-memory state (`_active_sessions` dict, `_conversation_locks`, `_steering_queues`). DB is now single source of truth for `sdk_session_id`. Key API changes: `start_session()`/`send_message()` collapsed into `run_interactive()`, `close_session()` renamed to `close_conversation()`, `list_active()` replaced by `list_running(db)`.

Code review of refactor found 1 critical + 5 important issues, all fixed:
- **Critical:** `include_partial_messages` passed as top-level kwarg instead of inside `ClaudeAgentOptions` — moved to correct location (3 instances)
- **Important:** Stale `sdk_session_id` in close_conversation after flush_memory — re-read from DB; `ExceptionGroup` not caught in conversation route — added; redundant orphaned task cleanup in main.py — removed; duplicate `stream_end` — verified not a real issue (only published once internally, not yielded)
- Reopen context: summary-only approach accepted (simpler, sufficient)

## Phase 8: Security Foundation + Core Infrastructure — COMPLETE

**Reference:** [IMPLEMENTATION-PLAN-PHASE8.md](IMPLEMENTATION-PLAN-PHASE8.md) | [AUTONOMOUS-AGENTS.md](AUTONOMOUS-AGENTS.md)

All 8 tasks done across 4 waves of parallel execution. 195 new tests. Security hardening and session infrastructure for autonomous agent operations.

**Task 8.1 — Prompt Injection Delimiters:** Modified `context_assembler.py` to wrap all user-originated data in `<user-data type="...">` tags and system instructions in `<system-instruction>` tags. Anti-injection instruction added to both agent and Odin paths. Covers: board state, memory entries, summaries, behavioral rules, tool docs, agent config. 29 tests.

**Task 8.2 — Steering Validation + Audit Log:** Added 2000-char limit on steering messages with `<steering>` delimiters. Built `audit_log` table + `audit_service.py` + `GET /api/v1/audit-log` API. Wired into permission_enforcer (logs every tool call decision) and agent_runner background loop (captures individual tool use events from StreamEvent, not just ResultMessage). Secret redaction on logged tool inputs. 21 tests.

**Task 8.3 — Memory Integrity:** Added `origin` column to `behavioral_rules` (named `origin` to avoid collision with existing `source_type`). Values: `agent_inferred`, `user_confirmed`, `system`. Context assembler places user-confirmed rules in high-attention BEGINNING section, agent-inferred rules in lower-attention MIDDLE section. Added imperative pattern detection on memory writes — entries matching `/^(ignore|override|you must|...)/i` create a notification for human review. 30 tests.

**Task 8.4 — Kill Switch + Token Tracking:** Built `system_state` table + `system_service.py`. `POST /system/emergency-stop` halts all background work, `POST /system/resume` clears. Guards in agent_runner and automation_scheduler. Added `input_tokens`/`output_tokens` to conversation_messages, `token_budget` to background_tasks. Token extraction added to both interactive path (extended existing) and background loop (built new). Budget enforcement stops tasks when token limit exceeded. `GET /api/v1/stats/tokens` for aggregated usage. 38 tests.

**Task 8.5 — Lane-Isolated Concurrency:** Created `concurrency_manager.py` with 4 independent lanes: interactive (5), autonomous (2), automation (3), subagent (8). `MAX_TOTAL_BACKGROUND = 8` hard cap. Removed yield-to-interactive behavior from automation_scheduler — automations now run regardless of active conversations. Replaced inline DB queries in agent_runner with `acquire_slot()` calls. 22 tests.

**Task 8.6a — Compaction Loop:** Added context estimation to background task loop (previously only existed in interactive path). Compaction triggers at 70% context utilization: flushes memory, generates checkpoint summary, continues with compressed context. Defined `PersistentData` dataclass and `register_persistent_extractor()` for Phase 9 extension. Added `goal` and `time_budget` columns to background_tasks. 14 tests (after simplification, see below).

**Task 8.6b — Soft Budgets + Continuation Prompts:** Replaced `MAX_TURNS = 20` hard cap with soft budgets: token budget, time budget (default 4h), and `GOAL_COMPLETE`/`TASK_COMPLETE` completion signals. `MAX_TURNS` raised to 500 as absolute safety fallback. Built `_build_continuation_prompt()` with context-aware content: turn number, progress, budget remaining, compaction notes. Budget-exhausted message gives agent one final turn to summarize. 29 tests.

**Task 8.7 — Security UI:** Three frontend components: (1) System status indicator in app header — subtle dot + label ("Active" / "2 agents running" / "Paused"), expands to show stop button when background work active, resume button when paused. (2) Token usage sparkline — compact 7-day SVG sparkline with hover tooltips, "Last 24h" summary. (3) Integration into existing Home dashboard and app shell.

**Compaction simplification (post-8.6a):** Original implementation included post-compaction verification — string-matching key phrases from the original instruction against the post-compaction context. Removed after recognizing this solves a problem that doesn't exist if we follow the OpenClaw pattern: instructions are stored externally (on the BackgroundTask record's `goal` field) and re-injected each turn via continuation prompts. Compaction only affects conversation history, not instructions. The goal is never in the summarizable context — it comes from the DB. Flush memory + generate summary is sufficient. Verification was adding complexity and false-positive halt risk for no safety benefit.

**Deviations from plan:**
- Agents consistently produced plans and waited for approval before implementing (following global CLAUDE.md rule). Required a round-trip per agent to push them to implement.
- Task 8.2 agent also created merge migrations for parallel alembic heads from concurrent tasks.
- Compaction verification logic stripped post-implementation based on OpenClaw pattern analysis — simpler model, same safety properties.

## Phase 9: Autonomous Operations — COMPLETE

**Reference:** [IMPLEMENTATION-PLAN-PHASE8.md](IMPLEMENTATION-PLAN-PHASE8.md) (Phase 9 section) | [AUTONOMOUS-AGENTS.md](AUTONOMOUS-AGENTS.md)

All 6 tasks done across 3 waves of parallel execution. 86 new backend tests, 7 new frontend components. Agents can now pursue goals autonomously.

**Task 9.1 — Schema Extensions:** Added task_list, task_list_version, completed_count, total_count, queued_approvals_count, run_type, run_summary to BackgroundTask. Added max_spawn_depth, heartbeat_enabled, heartbeat_cron to Agent. Created ApprovalQueue table. Added BackgroundTaskRunType, ApprovalStatus enums, SSE event types. 10 tests.

**Task 9.2a — Approval Queue:** Built approval_service.py with create/resolve/batch_resolve/list_pending/expire_stale. Added queue_approval MCP tool. Modified permission_enforcer with autonomous_mode: when enabled, approval-required actions create ApprovalQueue entries instead of blocking. API routes for listing, resolving, and batch operations. 23 tests.

**Task 9.2b — Autonomous Launch Flow:** The core autonomous execution path. launch_autonomous() creates a pending task + clarification conversation. Agent asks clarifying questions, user approves via approve_autonomous_launch(). Agent builds a JSON task list, stores on BackgroundTask, iterates through items with compaction/budgets/progress tracking. PersistentData extractor preserves task list through compaction. update_task_list MCP tool for agent self-management. Per-agent pause/resume. One autonomous run per agent guard. 32 tests.

**Task 9.3 — Heartbeat Protocol:** Added _evaluate_heartbeats to automation_scheduler alongside existing cron evaluation. Agents with heartbeat_enabled=True and heartbeat_cron fire periodic survey prompts. HEARTBEAT_OK = silent completion (no notification). Actions logged in audit + notification. Uses automation concurrency lane. delegate_background now accepts run_type parameter. 21 tests.

**Task 9.4a — Dashboard UI:** Active Agents panel (conditional top placement when agents running, progress bars, pause controls, SSE updates). Activity Feed (audit log stream, agent/time filters, pagination). Pending Approvals (per-entry approve/deny, batch actions, badge count, hidden when empty). Enriched RunningSessionResponse with autonomous fields.

**Task 9.4b — Conversation UI:** Task list sidebar (right side, collapsible, status icons, progress summary, 5s polling + SSE refetch). Autonomous progress header (goal, budget, elapsed time, pause/resume controls). Inline autonomous launch component (goal textarea, optional constraints/budgets). Approve-launch banner (fixed bottom, transitions to autonomous execution). Integration into conversation-panel and conversation-sidebar.

**Code review fixes (post-build):**
- task-list-sidebar.tsx: `item.label` → `item.title` (field name mismatch with backend)
- task-list-sidebar.tsx: added `"done"` to status type union (MCP tool uses "done", not "completed")
- active-agents.tsx: removed misleading "Stop" button that actually called pause endpoint

**Deviations from plan:**
- Task 9.2a agent also added the autonomous_mode permission path that was spec'd for the task
- Task 9.2b is the largest single task in the plan (~130k tokens, 89 tool calls) — built the full autonomous loop, MCP tool, API routes, schemas, and PersistentData extractor in one pass
- Code review caught a frontend field name mismatch that would have made the task list sidebar non-functional — fixed before proceeding

## Phase 10: Multi-Agent Fan-Out — COMPLETE

**Reference:** [IMPLEMENTATION-PLAN-PHASE8.md](IMPLEMENTATION-PLAN-PHASE8.md) (Phase 10 section) | [AUTONOMOUS-AGENTS.md](AUTONOMOUS-AGENTS.md) (Section 5)

All 3 tasks done sequentially. 44 new backend tests. Autonomous agents can now delegate work to parallel sub-agents with permission inheritance and cascade control.

**Task 10.1 — Permission Narrowing Engine:** `PermissionSet` dataclass and `narrow_permissions()` / `validate_narrowing()` in permission_enforcer.py. Sub-agents inherit the parent's full permissions by default — no depth-based stripping. The only hard rule: permissions can never widen beyond the parent's scope (no-escalation invariant). `delegation_depth` tracked on BackgroundTask for display. `cascade_update_status()` and `get_all_descendant_task_ids()` in background_task_service. Cascade termination and cascade pause/resume in agent_runner. Sub-agent completion notifications (`SUB_TASK_COMPLETED`). 30 tests.

**Task 10.2 — Parallel Delegation + Result Collection:** `MAX_SUBAGENTS_PER_RUN = 3` per-coordinator cap. `count_active_children()` in concurrency_manager. Two new MCP tools: `check_delegated_tasks(task_ids)` (poll child status, security-scoped to caller's children) and `cancel_delegated_task(task_id)` (cancel child + descendants). Continuation prompts include "Sub-agent status:" section when child tasks exist. 14 tests.

**Task 10.3 — Fan-Out UI:** New `delegation-tree.tsx` — tree sidebar in conversation view showing coordinator → sub-agent hierarchy with status dots, depth badges, progress bars, pause/resume buttons. Self-hides when no children. Real-time SSE updates. Active Agents panel updated — sub-agents nested under coordinators with collapsible "N sub-agents" badge, recursive descendant collection with cycle detection. `max_spawn_depth` field added to agent form (select 1-5 with descriptions).

**Design change (during build):** Original plan specified depth-based permission tiers (depth 1 strips management tools, depth 2+ restricts to items/docs). Changed to inheritance model after discussion — sub-agents get the same permissions as their parent. No automatic stripping. Only the no-escalation invariant enforced. All docs (AUTONOMOUS-AGENTS.md, CAPABILITIES.md, ARCHITECTURE-PROPOSAL.md, guide.md, README.md, IMPLEMENTATION-PLAN-PHASE8.md) updated to reflect this.

**Code review fixes (3 rounds):**
- Round 1: Notification enum string → `NotificationType.SUB_TASK_COMPLETED`, SubAgentRow pause/resume (was pause-only), agent form PATCH error handling, recursive descendants in Active Agents (was direct children only)
- Round 2: Cycle detection in `collectDescendants`, query invalidation moved outside depth conditional
- Round 3 (security): Root coordinator permission anchoring — `delegate_task()` walks up parent chain to find root coordinator's permissions for the narrowed set (prevents escalation when sub-agent has broader DB permissions than inherited). Status config completeness for all backend statuses. Error toast on PATCH failure.

**Deviations from plan:**
- Permission model changed from depth-based narrowing to inheritance (all docs updated)
- `RunningSessionResponse` enriched with `parent_task_id` and `delegation_depth` (not in original plan — needed for frontend hierarchy display)
- `AgentCreate` schema doesn't include `max_spawn_depth`, so agent form uses a follow-up PATCH on create

## Phase 11: Polish + Hardening — COMPLETE

**Reference:** [IMPLEMENTATION-PLAN-PHASE8.md](IMPLEMENTATION-PLAN-PHASE8.md) (Phase 11 section)

All 4 tasks done (3 parallel + 1 sequential). ~51 new backend tests, 1 new frontend component. Production-readiness for autonomous operations.

**Task 11.1 — Crash Recovery for Autonomous Runs:** Extended `recover_from_crash()` in agent_runner.py with three-pass logic: autonomous tasks checked for resumability (task_list with remaining items + goal present → `pending_resume` status), sub-agents always marked failed (coordinator re-delegates), regular tasks unchanged. Added `PENDING_RESUME` to BackgroundTaskStatus enum. New `resume_autonomous_tasks()` restores conversations and re-fires autonomous loops after a 2-second startup delay. `_is_resumable()` helper with corruption protection (try/except for malformed task_list JSON). 17 tests.

**Task 11.2 — Approval Queue Lifecycle:** Wired existing `expire_stale()` into automation_scheduler's tick loop (runs every 60 seconds). Per-agent configurable timeout via new `approval_timeout_hours` field on Agent model (falls back to 24h default). Approval resolution steering: approved actions inject "retry this action" via steer(), denied actions inject "skip and continue", expired actions inject "timed out, skip". Guard in `resolve_approval()` rejects non-pending approvals with 409 (prevents race between expiry and manual resolve). `batch_resolve()` also skips non-pending entries. Steer failures in scheduler loop isolated per-entry (try/except). 9 tests.

**Task 11.3 — Overnight Summary Generation:** New `summary_service.py` with `generate_run_summary()` — compiles structured summary from goal, duration, progress, item breakdown, token usage (from conversation_messages), approval counts (from approval_queue), and key actions (from audit_log, queried by both conversation_id and background_task_id). Replaces simple truncated-text summary on autonomous completion. Morning brief API: `GET /api/v1/home/morning-brief` returns completed runs since last user visit grouped by agent, with pending approval and failed task counts. Dedicated `POST /api/v1/home/morning-brief/dismiss` endpoint (not a GET side-effect). New `MorningBrief` frontend component with agent-grouped cards, status badges, progress info, collapsible summary text, and dismiss button. 10 tests.

**Task 11.4 — End-to-End Integration Testing:** 15 integration tests covering the full autonomous pipeline in `test_autonomous_e2e.py`: full run lifecycle with summary generation, compaction preserving goal/task_list, approval queue full flow (create → resolve → count tracking), parallel delegation lane caps (subagent lane + per-run cap), permission inheritance no-escalation, kill switch state management, crash recovery + resume round-trip, heartbeat cron evaluation, budget exhaustion in continuation prompts, cascade termination, user task list modification mid-run, concurrent autonomous run isolation, per-agent approval expiry, and morning brief aggregation. All tests use in-memory SQLite + mocked SDK calls.

**Code review (15 findings, 8 fixed):**
- Critical: `"pending_resume"` magic string → added to BackgroundTaskStatus enum; approval resolve/expire race condition → pending-status guard added; `_is_resumable` crash on corrupted task_list → try/except protection
- Important: GET dashboard side-effect for last_seen → dedicated POST dismiss endpoint; AuditLog query missed entries by task_id → added `or_()` fallback; scheduler steer loop failure blocked remaining entries → per-entry try/except
- Consistency: `resume_autonomous_tasks` string literals → enum constants; `batch_resolve` missing pending guard → added skip for non-pending
- Won't fix (7): N+1 queries in expiry/brief (low volume), redundant task re-query in route (correct behavior), missing ConfigDict on dict-only schemas, redundant updated_at, test helper falsy check, missing edge case test

## Search Improvements: Agentic Search + Items FTS5 — COMPLETE

Spike found that vector search adds unnecessary complexity for a small personal dataset. Instead, adopted the "agentic search" pattern used by Claude Code: FTS5 keyword search + LLM-driven query reformulation. The model itself acts as the semantic layer, iterating on search terms when initial results are sparse.

**Migration:** New `fts_items` FTS5 virtual table indexing `items.title` + `items.description` with 3 sync triggers (insert/delete/update). COALESCE for nullable description. All items indexed including archived (filtered at query time).

**Service layer:**
- New `search_items()` in search_service.py — space filtering, space_ids permission scoping, item_type filtering, archived exclusion toggle. Follows exact pattern of search_documents().
- `search_all()` updated from 4-type to 5-type (includes items), budget split changed from `//4` to `//5`.
- `rebuild_fts_indexes()` and `check_and_rebuild_if_needed()` updated to include fts_items.

**MCP tools (2 new):**
- `search_items` — FTS5 search on items with space permission scoping, item_type filter. Registered in _STANDARD_TOOLS.
- `search` (unified) — calls search_all(), returns grouped results across all 5 content types. Strips HTML `<mark>` tags from excerpts (agents don't need highlighting). Designed as a first-pass discovery tool.

**Agentic search guidance:** New `_SEARCH_INSTRUCTIONS` constant in context_assembler.py, injected into agent identity section alongside memory instructions. Teaches agents to: use `search` for broad discovery, reformulate queries with synonyms/broader terms on sparse results, iterate 2-3 times, drill into specific tools for targeted follow-up.

**API route:** `GET /api/v1/search` now accepts `type=items`. Docstrings updated.

**Frontend:** Search modal (Ctrl+K) updated — items appear in results with checkbox icon, click navigates to item's space. Placeholder text updated.

**Tests:** 18 new tests across 3 files:
- test_search_service.py: 7 tests (TestSearchItems: basic, description, space filter, type filter, archived exclusion, archived inclusion, no results)
- test_mcp_search_tools.py: 7 tests (TestSearchItems: 4 tests + TestSearchAllContent: 3 tests including HTML stripping verification)
- test_phase4_integration.py: Updated 3 existing tests to include items key in assertions, added fts_items FTS5 setup SQL

**E2E testing (Playwright):** 9/9 pass — modal open/close, placeholder text, search returns results, space badges, excerpt highlights, no-results state, click-to-navigate. Confirmed items appear in search results with correct space assignment.

**Files changed:** 9 modified, 2 new
- New: `backend/alembic/versions/10_2_fts_items.py`, `backend/tests/test_e2e/test_search_e2e.py`
- Modified: search_service.py, mcp_tools.py, context_assembler.py, routes/search.py, search-modal.tsx, test_search_service.py, test_mcp_search_tools.py, test_phase4_integration.py

## Phase 12: Google Calendar Integration — COMPLETE

Full Google Calendar integration: agents read/write events, calendar data in context assembly, sync every 15 minutes, calendar UI on Home and dedicated page.

**Task 12.1 — Cross-space data source infrastructure:**
- `DataSource.space_id` made nullable (system-level sources not bound to any space)
- `Space.data_sources` cascade changed from `delete-orphan` to `delete` + `passive_deletes=True`
- `space_data_source_exclusions` table for per-space opt-out
- `is_system` flag on `Automation` model (hidden from dashboard, undeletable via API)
- `CalendarEvent` and `EmailCache` models + FTS5 virtual tables with triggers
- Source type constants in `contract/enums.py`
- Service/route/schema updates for system data sources and exclusions
- Single Alembic migration for all Phase 12-14 schema changes

**Task 12.2 — Shared OAuth + Calendar client:**
- `google_auth.py` — shared scope registry, incremental authorization, background callback server with thread cancellation
- `gcalendar_client.py` — 7 Calendar API functions with exponential backoff retry
- `gdrive_client.py` refactored to use shared OAuth (all 15 Drive tests pass unchanged)
- `/api/v1/integrations/auth-status` and `/auth-url` endpoints

**Task 12.3 — Calendar sync service:**
- `calendar_integration_service.py` — setup, sync, CRUD, free time, brief linking
- `_parse_iso()` helper handles Google's Z suffix
- Sync failure tracking with 3-strike notification threshold
- Token expiry detection with re-auth notification
- 15-minute integration sync loop in `automation_scheduler.py`

**Task 12.4 — Calendar MCP tools + context assembly:**
- 7 MCP tools: list_calendar_events, get_calendar_event, create_calendar_event, update_calendar_event, delete_calendar_event, find_free_time, list_calendars
- Permission enforcer mappings (read=always, create/edit/delete=approval)
- Conditional tool loading based on DataSource existence and space exclusion
- `_build_calendar_section()` in context assembler — 48h lookahead, grouped by day, 500-token budget
- `BUDGET_CALENDAR=500`, `BUDGET_EMAIL=300` constants; total context 8,000→8,800, Odin 4,000→4,800

**Task 12.4b — Automation templates:**
- Meeting Prep template (daily 7am, disabled by default)
- Daily Task Review updated to reference calendar
- Stale Work Check updated to reference calendar follow-ups

**Task 12.5 — Calendar API routes:**
- 10 endpoints under `/api/v1/calendar/`: auth-status, events CRUD, sync, free-time, calendars, setup
- Pydantic schemas with ORM compat
- Consistent timezone handling (strip tzinfo) with try-except for 400 on bad input

**Task 12.6 — Calendar frontend:**
- Home dashboard calendar widget (today + tomorrow, conditional on auth)
- `/calendar` page with day grouping, expandable events, sync button with error handling, auto-refresh
- Space calendar widget (compact, 5 events)
- Sidebar "Calendar" nav item (conditional on connection)
- `CALENDAR_EVENTS` widget type in registry and enum

**Task 12.7 — Tests:** 65 new tests across 6 files (calendar service, calendar API, data source exclusions, system automations, context assembler calendar section). Total: 1315 passing.

**Task 12.8 — Documentation:** ARCHITECTURE-PROPOSAL.md, CAPABILITIES.md (#27 → [BUILT]), INTEGRATION-CAPABILITIES.md updated. OpenAPI spec regenerated.

**Review findings fixed:**
- B1: `fromisoformat()` Z suffix crash → `_parse_iso()` helper
- B2: Deletion detection wrong query → proper overlap detection
- B3: All-day event end time off by 24h → subtract 1 second for inclusive end
- B4: Timezone inconsistency across routes → standardized `.replace(tzinfo=None)`
- R1: Hardcoded string in scheduler → `SOURCE_TYPE_GOOGLE_CALENDAR` constant
- R3: SQL wildcard injection in brief search → `_escape_like()` helper
- R4: Missing route error handling → try-except with HTTP 400
- R5: Missing frontend error states → error UI in all 3 calendar components
- R6: Sync mutation no error handling → onError callback with red error text
- R7: Context assembler zero test coverage → 8 dedicated tests

**Files created:** 12 new files (google_auth.py, gcalendar_client.py, calendar_integration_service.py, integrations routes/schemas, calendar routes/schemas, Alembic migration, 3 frontend components, 2 test files)
**Files modified:** ~20 files (models.py, enums.py, data_source_service.py, automation_service.py, mcp_tools.py, permission_enforcer.py, context_assembler.py, agent_runner.py, automation_scheduler.py, main.py, sidebar.tsx, App.tsx, widget-registry.tsx, register_automation_templates.py, 3 doc files)

## Phase 13: Gmail Integration — COMPLETE

Full Gmail integration: agents read/triage email, draft replies, surface inbox status. Users see email dashboard on Home and dedicated page.

**Task 13.1 — Gmail API client:**
- `gmail_client.py` — 14 public functions, MIME parsing (text/plain preference, HTML fallback with tag stripping), base64url decode, draft/reply composition
- Scope: `gmail.modify` (read + label + archive + draft + send)
- Same patterns as gcalendar_client: `_retry_api_call`, shared OAuth, module-level functions

**Task 13.2 — Email cache + triage labels:**
- `email_integration_service.py` — setup, sync, cache queries, label/archive/read operations, draft/send passthrough
- 5 triage labels: `OL/Needs Response`, `OL/FYI`, `OL/Follow Up`, `OL/Waiting`, `OL/Agent Processed`
- Sync failure tracking with 3-strike notification threshold (same as calendar)
- Stale cache reconciliation: messages no longer in inbox have INBOX label removed
- Email sync added to `automation_scheduler.py` alongside calendar sync

**Task 13.3 — Email MCP tools + context assembly:**
- 10 MCP tools: list_emails, get_email (live body fetch), get_email_headers, label_email, archive_email, mark_email_read, draft_email, send_email, send_reply, get_inbox_stats
- Permission mappings: read=always, edit=always (low-risk), create=always (drafts), execute=requires approval (send)
- `_build_email_section()` in context assembler — inbox summary, 300-token budget
- Conditional tool loading in all 4 builder functions

**Task 13.4 — Email API routes:**
- 13 endpoints under `/api/v1/email/`: auth-status, messages CRUD, label/archive/read, reply, drafts, sync, stats, setup, setup-labels
- Pydantic schemas with ORM compat

**Task 13.5 — Email frontend:**
- Home dashboard email widget (grouped by triage label, conditional on auth)
- `/email` page with search, sync button, grouped messages, quick actions (archive, mark read)
- Space email widget (compact, 5 messages)
- Sidebar "Email" nav item (conditional on connection)
- `EMAIL_FEED` widget type in registry and enum

**Task 13.6 — Tests:** 81 new tests across 4 files (email service 19, API 15, MCP 19, gmail client MIME parsing 13, integration builder 15). Total: 1432 passing.

**Task 13.7 — Templates + docs:**
- Email Triage automation template (every 2h business hours, disabled by default)
- Daily Task Review updated to reference email
- ARCHITECTURE-PROPOSAL.md, CAPABILITIES.md (#28 → [BUILT]), INTEGRATION-CAPABILITIES.md updated

**Review findings fixed (1 round):**
- C1: Frontend archive/markRead passed UUID instead of gmail_message_id — fixed
- C2: `_parse_date` missing 'Z' suffix handling — added `.replace("Z", "+00:00")`
- C3: Integration Builder tools missing from permission enforcer `_MCP_TOOL_MAP` — added
- C4: SSRF in `test_api_connection` — added private IP/localhost/metadata blocking
- I1: `get_inbox_stats` in gmail_client made N+1 API calls — simplified to INBOX label only
- I2: Hardcoded "cron" string — replaced with `AutomationTriggerType.CRON`
- I3: Stale cache messages not reconciled — added INBOX label removal for missing messages
- I4: SKILL.md referenced nonexistent web search tool — clarified instructions
- M1: Stats label key mismatch in frontend widget — fixed to use `OL/` prefix

**Files created:** 11 new files (gmail_client.py, email_integration_service.py, email routes/schemas, 3 frontend components, SKILL.md, 4 test files)
**Files modified:** ~15 files (mcp_tools.py, permission_enforcer.py, context_assembler.py, agent_runner.py, automation_scheduler.py, main.py, odin_service.py, sidebar.tsx, App.tsx, widget-registry.tsx, Home.tsx, enums.py, register_automation_templates.py, register_skills.py, 3 doc files)

## Phase 14: Integration Builder Agent — COMPLETE

Conversational agent that helps users connect arbitrary REST APIs to OpenLoop spaces using existing primitives.

**Task 14.1 — Integration Builder MCP tools:**
- 3 exclusive tools: `create_api_data_source`, `test_api_connection`, `create_sync_automation`
- SSRF protection on test_api_connection (blocks private IPs, localhost, metadata endpoints)
- Tool builder dispatch added to both `_build_mcp_server` and `_build_mcp_server_by_name`
- Permission enforcer mappings for all 3 tools

**Task 14.2 — Integration Builder skill:**
- `agents/skills/integration-builder/SKILL.md` — 9-step integration workflow, security rules, limitations
- Auto-discovered by `register_skills.py` (scans agents/skills/ directories)
- Odin routing added for integration requests

**Task 14.3 — Tests:** 15 tests covering all 3 MCP tools (create, test connection with mocked httpx, create automation) + tool registration exclusivity. All passing.

## Current State

- **~1432 backend tests passing**, lint clean on new code
- **63 Playwright E2E tests passing** (new comprehensive suite) + 39 prior component tests
- **OpenAPI spec freshly regenerated** from current routes
- Backend: CRUD, agent sessions, SSE streaming with replay buffer, permissions, Odin, four-tier memory, context safety, records/CRM, documents, FTS5 search, Google Drive, widget layouts, unified items, item links, sub-agent delegation, managed turn loop, mid-task steering, Agent Builder, skill-based agents, step tracking, stale/stuck detection, automation scheduler, cron matching, run lifecycle, missed-run detection, notification infrastructure, memory lifecycle management, summary consolidation, backup system, rate limit retry, graceful shutdown, orphaned task cleanup, space-scoped MCP tools, permission polling timeout, FK cascade enforcement, FTS5 active filtering, bounded event queues, context size caching, stream_end SSE event, SDK session cleanup, tag filtering, behavioral rules API, messages pagination, typed enums, query indexes, permission inheritance with no-escalation enforcement, parallel sub-agent delegation with per-run caps, cascade termination/pause/resume, delegation monitoring MCP tools, audit-logged sub-agent completions, autonomous crash recovery with task list resumption, approval queue lifecycle with per-agent expiry and steering re-injection, structured run summaries with morning brief dashboard, **Google Calendar integration** (shared OAuth, 7 MCP tools, 15-min sync, cross-space data sources, per-space exclusion, calendar context in working memory, meeting prep automation template), **Gmail integration** (10 MCP tools, 15-min sync, triage labels, email context in working memory, email triage automation template), **Integration Builder agent** (3 exclusive MCP tools, SKILL.md, Odin routing, SSRF protection)
- Frontend: dashboard with skeleton loading + backup reminder + morning brief, space view (widget-based layout), conversation panel with stream_end support, agent management with max_spawn_depth + approval_timeout_hours, search modal, document panel + viewer, Space Settings (tabbed: layout editor + memory health + history), task list with stage dropdown, background task monitoring with steering, automations dashboard with cron presets, notification panel, toast notifications, keyboard shortcuts + help overlay, browser tab badge, page transitions, empty states, 3 palettes × 2 themes, Odin SSE filtering with race-condition handling, accessible sidebar/panel, agent dropdown fix, type-safe API calls, local column toggle, validated localStorage, aria-labels, delegation tree sidebar, nested sub-agents in Active Agents panel, **Calendar** (home widget, /calendar page with sync + expandable events, space widget, conditional sidebar nav), **Email** (home widget with triage grouping, /email page with search + quick actions, space widget, conditional sidebar nav)

---

## Key Decisions Made During Build

1. **Schemas split into per-domain files** (`backend/openloop/api/schemas/`) — prevents merge conflicts during parallel agent work.
2. **Update pattern uses `model_dump(exclude_unset=True)`** — correctly distinguishes "field not sent" from "field sent as null."
3. **Services are module-level functions**, not classes — simpler, no shared state needed.
4. **Services raise HTTPException directly** — accepted tradeoff for single-user app simplicity.
5. **SDK `resume` is the primary conversation continuity mechanism** — no TTL, sessions persist indefinitely.
6. **Permission hooks use own DB sessions** — not tied to request-scoped sessions, safe for async SDK context.
7. **MCP tool name matching uses dynamic prefix extraction** — handles `mcp__openloop_{agentName}__toolName` pattern.
8. **Approval polling timeout is 30 minutes** — auto-deny with notification after timeout (changed from infinite polling in Phase 3b).
9. **All list endpoints paginated** — default limit=50, max 200. Internal callers (context assembler, crash recovery) pass limit=10000.
10. **All spaces have board_columns** — Simple/Knowledge spaces get `["todo", "in_progress", "done"]`. Eliminates null-checking branches everywhere.
11. **Todos are items** — no separate table. Tasks (item_type='task') have is_done with bidirectional stage sync. Records ignore sync.
12. **MCP tools enforce space scoping** — every tool that accepts a `space_id` or operates on an entity validates the agent's space access. System agents (Odin) bypass the check.
13. **Naive UTC for all SQLite datetimes** — `datetime.now(UTC).replace(tzinfo=None)` is the standard pattern. SQLite strips tzinfo anyway, but explicit naive UTC prevents comparison bugs.
14. **Agent runner replaces session manager** — `agent_runner.py` (~400 lines) replaced `session_manager.py` (1,728 lines). No in-memory session state; DB is single source of truth for `sdk_session_id`. First message creates session automatically via `ClaudeAgentOptions.system_prompt`. The SDK was always stateless per-call — the old lifecycle model was unnecessary.
15. **`system_prompt` via SDK options, not as prompt** — the assembled context (memory, rules, board state) is passed via `ClaudeAgentOptions.system_prompt`, not as the `prompt` parameter. This matches how Claude CLI works and avoids wasting an API call on session initialization.
16. **Compaction follows the OpenClaw pattern** — instructions stored externally (BackgroundTask.goal), re-injected each turn via continuation prompts. Compaction only summarizes conversation history, never instructions. No post-compaction verification needed — the goal is never at risk because it comes from the DB, not the context window.
17. **Concurrency lanes are independent** — interactive, autonomous, automation, and subagent work each have their own lane with separate caps. No lane blocks another. The old yield-to-interactive model (automations paused during user conversations) was removed.
18. **Audit logging via permission enforcer** — every tool call decision (allow/deny) is logged in the audit_log table with redacted inputs. Provides the data foundation for the activity feed and overnight summaries in Phase 9+.
19. **Autonomous launch is a conversation, not a form** — the user gives a goal, the agent asks clarifying questions, the user approves. The clarification IS the scoping mechanism. No per-run configuration UI needed.
20. **Approval queue is non-blocking** — autonomous agents queue actions outside their permissions and continue with other work. The user approves/denies from the dashboard in batch. Agents don't wait.
21. **Heartbeat cron expression controls working hours** — no separate working-hours feature needed. `*/30 9-17 * * 1-5` = business hours only.
22. **Permission inheritance, not narrowing** — sub-agents inherit the parent's full permissions by default. No depth-based stripping. The only hard rule: child can never exceed parent scope (no-escalation invariant). Delegation walks up to the root coordinator to anchor permissions, preventing escalation when a sub-agent has broader DB permissions than what it inherited. `max_spawn_depth` limits recursion depth, not permissions.
23. **Cross-space data sources use nullable space_id** — system-level DataSources (Calendar, Email) have `space_id=null`. The Space relationship cascade changed from `delete-orphan` to `delete` + `passive_deletes=True` so system sources survive space deletions. Per-space opt-out via `space_data_source_exclusions` table.
24. **Shared OAuth with incremental authorization** — `google_auth.py` manages a scope registry. Each integration registers scopes on import. `include_granted_scopes=true` preserves existing grants when adding new scopes. Single token file covers Drive + Calendar + Gmail.
25. **Integration sync is not agent work** — Calendar/email sync runs as a direct function call in the automation scheduler loop (every 15 minutes), not via `delegate_background`. No LLM reasoning needed for API-to-DB sync. Failure counter with 3-strike notification threshold.
26. **Context budget increased for integrations** — Total context 8,000→8,800 tokens (500 calendar + 300 email). Odin 4,000→4,800. Calendar and email are separate END sections, not carved from existing board/todo budget.
27. **Email bodies not cached** — Only headers + snippet cached in `email_cache` table. Full email bodies fetched live from Gmail API via `get_email()` MCP tool. Avoids storing sensitive email content in SQLite.
28. **Email send requires approval** — `send_email` and `send_reply` mapped to `("gmail", "execute")` permission. Default: requires approval. Users can upgrade to "always allowed" per-agent as trust builds. Drafts don't require approval.
29. **Integration Builder uses existing primitives** — No dynamic code execution, no runtime plugin loading. Configures DataSource + Automation + WebFetch + Items/Memory. SSRF protection blocks private IPs, localhost, and metadata endpoints in `test_api_connection`.
