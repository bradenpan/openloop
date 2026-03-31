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

## Current State

- **498 tests passing**, lint clean
- **90 source files**
- Backend fully functional: CRUD for all entities, agent session management, SSE streaming, permission enforcement, Odin front door
- Frontend not started

## Phases 3–7: Not Started

See IMPLEMENTATION-PLAN.md for full breakdown. Phase 3 (Frontend Foundation) is next.

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
