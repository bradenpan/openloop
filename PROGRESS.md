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

## Current State

- **593 backend tests passing** (498 original + 95 new), lint clean
- **39 frontend Playwright tests passing**
- Backend: CRUD, agent sessions, SSE streaming, permissions, Odin, four-tier memory, context safety
- Frontend: dashboard, space view, conversation panel, agent management, 3 palettes
- Integration check (3.7) still pending

## Phases 4–7: Not Started

See IMPLEMENTATION-PLAN.md for full breakdown. Phase 4 (Records, Table View, Documents, Search) is next. Phases 4, 5, 6 can overlap.

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
