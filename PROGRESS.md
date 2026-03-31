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

**Known gap from Phase 2:** `PATCH /api/v1/agents/permission-requests/{id}` endpoint doesn't exist. Frontend approval UI is built but the backend endpoint for responding to approval requests needs to be added. The permission enforcer polls the DB — the endpoint just needs to update the row's status field.

## Current State

- **498 backend tests passing**, lint clean
- **39 frontend Playwright tests passing**
- **~130 source files** (90 backend + ~40 frontend)
- Backend fully functional: CRUD for all entities, agent session management, SSE streaming, permission enforcement, Odin front door
- Frontend fully built: dashboard, space view, conversation panel, agent management, design system with 3 palettes
- Integration check (3.7) pending

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
8. **Approval polling has 5-minute timeout** — auto-denies with `resolved_by="system"` to prevent indefinite blocks.
9. **All list endpoints paginated** — default limit=50, max 200. Internal callers (context assembler, crash recovery) pass limit=10000.
