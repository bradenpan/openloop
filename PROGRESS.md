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

**Task 3b.5:** Session manager safety — `flush_memory()` (mandatory pre-compaction), proactive budget enforcement (checks before SDK call), observation masking (7 recent turns verbatim), `verify_compaction()` (post-compression gap detection).

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

## Current State

- **776 backend tests passing** (781 prior − deleted todo tests + new item/link tests), lint clean
- **39 frontend Playwright tests passing**
- Backend: CRUD, agent sessions, SSE streaming, permissions, Odin, four-tier memory, context safety, records/CRM, documents, FTS5 search, Google Drive, widget layouts, unified items, item links
- Frontend: dashboard, space view (widget-based layout), conversation panel, agent management, search modal, document panel + viewer, layout editor, task list with stage dropdown, 3 palettes

## Phases 5–7: Not Started

See IMPLEMENTATION-PLAN.md for full breakdown. Phase 5 (Agent Builder, Sub-agents, Steering) is next.

---

## Key Decisions Made During Build

1. **Schemas split into per-domain files** (`backend/openloop/api/schemas/`) — prevents merge conflicts during parallel agent work.
2. **Update pattern uses `model_dump(exclude_unset=True)`** — correctly distinguishes "field not sent" from "field sent as null."
3. **Services are module-level functions**, not classes — simpler, no shared state needed.
4. **Services raise HTTPException directly** — accepted tradeoff for single-user app simplicity.
5. **SDK `resume` is the primary conversation continuity mechanism** — no TTL, sessions persist indefinitely.
6. **Permission hooks use own DB sessions** — not tied to request-scoped sessions, safe for async SDK context.
7. **MCP tool name matching uses dynamic prefix extraction** — handles `mcp__openloop_{agentName}__toolName` pattern.
8. **Approval polling has no timeout** — agents wait indefinitely per spec (5-minute auto-deny removed in Phase 3b).
9. **All list endpoints paginated** — default limit=50, max 200. Internal callers (context assembler, crash recovery) pass limit=10000.
10. **All spaces have board_columns** — Simple/Knowledge spaces get `["todo", "in_progress", "done"]`. Eliminates null-checking branches everywhere.
11. **Todos are items** — no separate table. Tasks (item_type='task') have is_done with bidirectional stage sync. Records ignore sync.
