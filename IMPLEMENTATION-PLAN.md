# OpenLoop: Implementation Plan (v2)

**Status:** Ready for execution
**Companion docs:** CAPABILITIES.md (v5), ARCHITECTURE-PROPOSAL.md (v4)
**Decision:** Build from scratch (Option 1)

---

## Build Principles

1. **Each phase produces a working increment.** You can use the system after each phase, even if incomplete.
2. **Backend before frontend within each phase.** API endpoints are testable without UI. UI is built against a working API.
3. **Tests after each phase.** Backend tests (pytest) + frontend tests (Playwright via webapp-testing skill) per phase.
4. **Design-forward frontend.** Use the frontend-design skill for UI creation. Distinctive, snappy, responsive feel. Desktop-first.
5. **Agents build in swarms.** Phases with independent tasks can be built by multiple agents concurrently (6+ agents viable).
6. **Document authority:** When CAPABILITIES.md and ARCHITECTURE-PROPOSAL.md contradict, CAPABILITIES.md wins. This plan is authoritative over both for task scope.
7. **Skills used during build:**
   - `frontend-design` — all UI component creation
   - `webapp-testing` — frontend testing with Playwright
   - `skill-creator` — creating new OpenLoop-specific skills if needed during build
   - `file-editor` — documentation, config files
   - `research-web` — researching libraries, patterns, APIs as needed

---

## Known Contradictions (Resolved Here)

These items differ between the architecture doc and capabilities doc. This plan resolves them:

1. **Permission timeout:** Architecture doc Flow 4 mentions "5 minutes → auto-deny." Capabilities doc says "no timeout." **Resolution: No timeout. Agents wait indefinitely for approval.** The `resolved_by` field in `permission_requests` should have values: "user" or "system" (not "timeout").
2. **Command Bar / Flow 6:** Architecture doc still contains Flow 6 (Command Bar fast path) and a `CommandBarService`. Capabilities doc lists both as "Removed." **Resolution: No command bar. Odin is the front door. Do not build CommandBarService or `POST /api/v1/command`.**
3. **ToolRegistryService:** Architecture doc defines it. Not needed for P0. **Resolution: Deferred. Agent tool configs live in the `agents` table (`tools` and `mcp_tools` JSON fields).**

---

## Phase 0: SDK Spike + Project Scaffold

**Goal:** Validate SDK assumptions and set up the project skeleton with canonical patterns.
**Prerequisite for everything else.**

### Task 0.1: SDK Spike — Validate Core Assumptions
**Agent:** 1 agent, sequential tests
**Complexity:** Medium

Run targeted tests on Windows (our platform):
1. Upgrade `claude-agent-sdk` to v0.1.51+ and verify hooks work with `query()` (Bug #554/#730 fix)
2. Test `resume=session_id` — start a session, wait 5 minutes, resume. Verify conversation continuity.
3. **Test resume after long idle** — start a session, wait 1 hour, attempt resume. Document session TTL behavior. If sessions expire after idle, document the actual TTL. This determines whether `resume` is the primary conversation continuity mechanism or an optimization for rapid exchanges (with summary-based context transfer as the primary path).
4. Test SSE streaming feasibility — bridge the SDK's async generator to a FastAPI StreamingResponse
5. Test MCP tool creation — `create_sdk_mcp_server` with 3-4 tools, verify the model calls them
6. Test concurrent sessions — run 3 `query()` calls concurrently, verify no interference
7. Test context window reporting — does `ResultMessage` expose token counts?
8. **Test blocking hook** — create a `PreToolUse` hook that blocks (simulates DB poll), verify the session waits and resumes correctly after the hook returns
9. **Test SDK error handling** — force a connection failure mid-session. Document what exceptions are raised, whether the session is recoverable, and what error information is available for logging.

**Acceptance criteria:** Written report of what works, what doesn't, and any workarounds needed. Blocks if any critical assumption fails. Session TTL behavior documented clearly — this determines whether the architecture treats `resume` as primary or as an optimization.

**Output:** `spike/results.md` documenting findings, `spike/` directory with test scripts

### Task 0.2: Project Scaffold + Conventions
**Agent:** 1 agent
**Complexity:** Medium (upgraded from Small — conventions are critical)
**Can run in parallel with 0.1**

Set up project structure:
- `pyproject.toml` (Python 3.12, FastAPI, uvicorn, SQLAlchemy, Alembic, claude-agent-sdk >=0.1.51, pydantic, pytest)
- `frontend/package.json` (pnpm, React 19, Vite, Tailwind CSS v4, @tanstack/react-query, zustand, openapi-fetch, openapi-react-query, openapi-typescript, @dnd-kit)
- `backend/` directory structure mirroring architecture doc
- `contract/enums.py` (all enums: SpaceTemplate, ItemType, ConversationStatus, GrantLevel, AutomationTriggerType, etc.)
- `Makefile` (dev, dev-backend, dev-frontend, test, lint, lint-fix, migrate, seed, generate-types, backup, backup-gdrive)
- Alembic configuration
- `.gitignore`, `start.sh` / `start.bat`

**Critical deliverable: `CLAUDE.md`** — comprehensive project instructions for all build agents. Must include:

```
Directory structure conventions:
- backend/openloop/ for all Python code
- backend/openloop/api/routes/ for API route modules
- backend/openloop/api/schemas.py for Pydantic models
- backend/openloop/services/ for service modules
- backend/openloop/db/models.py for SQLAlchemy models
- backend/openloop/agents/ for agent execution code
- contract/enums.py for shared enums
- frontend/src/ for all TypeScript/React code

Code patterns:
- Services receive `db: Session` as first parameter, return ORM model instances
- API routes use `db: Session = Depends(get_db)` dependency injection
- Routes convert ORM models to Pydantic response schemas before returning
- All enums imported from contract/enums.py, never defined inline
- API field names use snake_case in JSON
- API endpoint paths use kebab-case
- Error responses: 422 for validation, 404 for not found, 409 for conflicts
- MCP tools defined as @tool-decorated async closures capturing db session

Testing patterns:
- pytest with in-memory SQLite for unit tests
- Test fixtures in conftest.py
- One test file per service/route module

Naming conventions:
- Python: snake_case variables/functions, PascalCase classes
- TypeScript: camelCase variables/functions, PascalCase components/types
- Files: snake_case for Python, kebab-case for TypeScript/React
- DB tables: snake_case, plural
```

**Acceptance criteria:** `make dev` starts backend + frontend (empty pages, health endpoint works), `make test` runs (0 tests, passes), `make lint` passes. CLAUDE.md is comprehensive.

### Task 0.3: Database Schema + Migrations
**Agent:** 1 agent
**Complexity:** Medium
**Depends on:** 0.2

Create all SQLAlchemy models from architecture doc (19 tables):
- `spaces`, `todos`, `items`, `item_events`, `agents`, `agent_spaces`, `agent_permissions`, `data_sources`, `conversations`, `conversation_messages`, `conversation_summaries`, `memory_entries`, `documents`, `document_items`, `permission_requests`, `notifications`, `automations`, `automation_runs`, `background_tasks`

Note: `background_tasks.status` enum includes "queued" (for tasks waiting on concurrency limits) in addition to "running", "completed", "failed", "cancelled". Define in `contract/enums.py`.

Create initial Alembic migration. Create `database.py` (engine, SessionLocal, get_db).

**Database configuration (set up here, not deferred):**
- Enable WAL mode (`PRAGMA journal_mode=WAL`) on engine creation — required for concurrent read/write from multiple agent sessions
- Set busy timeout (`PRAGMA busy_timeout=5000`) — prevents `SQLITE_BUSY` errors when multiple MCP tools write concurrently
- These are two lines in `database.py` but prevent intermittent failures across all subsequent phases

**Acceptance criteria:** `make migrate` creates all tables. Models have correct relationships, foreign keys, indexes, and unique constraints. WAL mode and busy timeout are configured in `database.py`.

### Task 0.4: Reference Implementation (Vertical Slice)
**Agent:** 1 agent
**Complexity:** Medium
**Depends on:** 0.2, 0.3

Build one complete vertical slice as the canonical pattern for all Phase 1 agents:
- `SpaceService` (create, get, list, update) in `backend/openloop/services/space_service.py`
- Pydantic schemas (SpaceCreate, SpaceUpdate, SpaceResponse) in `backend/openloop/api/schemas.py`
- API routes (POST, GET list, GET detail, PATCH) in `backend/openloop/api/routes/spaces.py`
- Router registration in `main.py`
- Tests: `backend/tests/test_services/test_space_service.py` and `backend/tests/test_api/test_spaces.py`

This establishes: import paths, service patterns, schema patterns, route patterns, test patterns, error handling patterns. **Every Phase 1 agent reads this before starting.**

**Acceptance criteria:** All 4 space endpoints work. Tests pass. Code follows CLAUDE.md conventions exactly.

**⚠️ Human review gate:** Phase 1 MUST NOT start until this reference implementation is reviewed and approved by the human. Errors in these patterns propagate to every Phase 1 agent. Review the import structure, service patterns, error handling, and test patterns before giving Phase 1 agents the green light.

### Task 0.5: Seed Data Script
**Agent:** 1 agent
**Complexity:** Small
**Depends on:** 0.3, 0.4

Create `scripts/seed.py` that populates the database with representative test data for frontend development:
- 3 spaces (one Project with board, one CRM, one Simple)
- 10-15 to-dos across spaces (mix of done/not-done, some with due dates)
- 8-10 board items across stages (mix of tasks and records)
- 2 agents with different permission configurations
- 3 conversations (one active, one closed with summary, one interrupted)
- Sample messages in conversations
- Memory entries in space and global namespaces
- 2 notifications (one read, one unread)

Wire into `make seed` command.

**Acceptance criteria:** `make seed` populates the database. Frontend agents in Phase 3 have realistic data to develop against. `make seed` is idempotent (clears and re-seeds).

---

## Phase 1: Core Backend Services + API

**Goal:** Full REST API for all CRUD operations. No agent execution yet.
**All Phase 1 agents read Task 0.4's reference implementation before starting.**

### Task 1.1: Service Layer — To-dos, Items, Item Events
**Agent:** 1 agent
**Complexity:** Medium

- `TodoService` — CRUD, done/not-done toggle, cross-space listing, promote-to-item (sets `promoted_to_item_id`, creates board item)
- `ItemService` — CRUD, stage transitions (validated against space's `board_columns`), archive, custom_fields for records, `source_conversation_id` tracking
- `ItemEventService` — log stage changes, assignments, creation. Feeds stale detection.

**Acceptance criteria:** All service functions work. Stage validation rejects invalid transitions. Promotion creates item and links todo.

### Task 1.2: Service Layer — Agents, Memory, Permissions
**Agent:** 1 agent
**Complexity:** Medium
**Can run in parallel with 1.1**

- `AgentService` — CRUD, agent_spaces join management, agent_permissions CRUD
- `MemoryService` — CRUD, namespace-scoped read/write, search by key/value/tags, token-budgeted retrieval
- `PermissionEnforcer` — `check_permission(agent_id, resource, operation)` → Always/Approval/Never. Uses `agent_permissions` table (not JSON blob). DB-backed approval polling with **no timeout**.

**Acceptance criteria:** Permission matrix lookups work correctly. Memory search returns relevant results. No timeout on approvals.

### Task 1.3: Service Layer — Conversations, Documents, DataSources, Notifications
**Agent:** 1 agent
**Complexity:** Medium
**Can run in parallel with 1.1 and 1.2**

- `ConversationService` — CRUD, status transitions (active/closed/interrupted), message storage, summary storage
- `DocumentService` — CRUD, metadata indexing, tag-based search
- `DataSourceService` — CRUD for data sources (Drive folders, repos, API integrations), status tracking
- `NotificationService` — create, list, mark read, filter by type, unread count

**Acceptance criteria:** Conversation lifecycle works. Notifications persist and filter. Data sources can be linked to spaces.

### Task 1.4a: API Routes — Spaces, Todos, Items, Agents
**Agent:** 1 agent
**Complexity:** Medium
**Depends on:** 1.1, 1.2 (for agents)

- `/api/v1/spaces` (4 endpoints) — already built in 0.4, extend if needed
- `/api/v1/todos` (5 endpoints including promote)
- `/api/v1/items` (6 endpoints)
- `/api/v1/agents` (5 endpoints)

Pydantic schemas for all request/response models.

### Task 1.4b: API Routes — Permissions, Memory, Documents, DataSources, Notifications, Home
**Agent:** 1 agent
**Complexity:** Medium
**Depends on:** 1.2, 1.3
**Can run in parallel with 1.4a**

- `/api/v1/permissions` (3 endpoints)
- `/api/v1/memory` (4 endpoints)
- `/api/v1/documents` (3 endpoints)
- `/api/v1/data-sources` (4 endpoints)
- `/api/v1/notifications` (2 endpoints)
- `/api/v1/home/dashboard` (1 endpoint — aggregates attention items, active agents, to-do counts)
- `/api/v1/health` (1 endpoint)

Pydantic schemas for all request/response models.

### Task 1.5: Contract + Type Generation + SSE Event Contract
**Agent:** 1 agent
**Complexity:** Medium (upgraded — includes SSE contract)
**Depends on:** 1.4a, 1.4b

- `contract/enums.py` finalized
- OpenAPI export script
- `make generate-types` produces TypeScript types
- **SSE Event Contract:** Define the event format shared between backend and frontend:

```python
# contract/sse_events.py
SSE event types:
- "token" — streaming conversation token { conversation_id, content }
- "tool_call" — agent calling a tool { conversation_id, tool_name, status }
- "tool_result" — tool call completed { conversation_id, tool_name, result_summary }
- "approval_request" — permission needed { conversation_id, request_id, tool_name, resource, operation }
- "notification" — system notification { notification_id, type, title, body }
- "route" — Odin routing action { space_id, conversation_id }
- "background_update" — background task status { task_id, status, progress }
- "error" — error event { conversation_id, message }
```

TypeScript types generated for all SSE events alongside the REST API types.

**Acceptance criteria:** `make generate-types` produces correct types including SSE event types.

### Task 1.6: Phase 1 Tests
**Agent:** 1 agent
**Complexity:** Medium
**Depends on:** 1.4a, 1.4b

- Service layer tests (all CRUD operations, validation, edge cases)
- API endpoint tests (success paths, error paths, filters)
- Permission enforcer tests (matrix lookup, all grant levels)
- Integration: verify all routes wire to correct services

### Task 1.7: Phase 1 Merge + Integration Check
**Agent:** 1 agent
**Complexity:** Small
**Depends on:** 1.6

- Verify all imports resolve across modules built by different agents
- Verify all services wire together (routes → services → models)
- Verify `make lint` passes
- Verify `make test` passes
- Fix any integration issues from parallel agent work

---

## Phase 2: Session Manager + Agent Conversations

**Goal:** You can start a conversation with an agent and get streaming responses.

### Task 2.1: Context Assembler
**Agent:** 1 agent
**Complexity:** Medium

- Builds system prompt from: agent identity, to-do + board state, conversation summaries, space facts, global facts, tool documentation
- Special Odin mode: cross-space context (all spaces, all agents, to-do summary, attention items)
- Token budget management (concatenate, measure total, truncate from bottom)
- Reads from MemoryService, ConversationService, TodoService, ItemService

**Token counting method:** Use a character-based heuristic: **1 token ≈ 4 characters**. Claude's tokenizer is not available as a standalone library. This heuristic is well-established for English text and Claude's tokenizer. The budgets in the architecture doc (2000, 1500, 2000, 1000, 500, 1000 tokens) translate to character limits (8000, 6000, 8000, 4000, 2000, 4000 chars). Implement as a `estimate_tokens(text: str) -> int` utility function in a shared module. If the SDK exposes token counts in `ResultMessage` (tested in Task 0.1 spike #7), use actual counts to calibrate the heuristic later.

**Acceptance criteria:** Context assembly produces correctly structured prompts. Token budget respected using character-based estimation. Odin mode includes cross-space data.

**Architecture doc reference:** Layer 6: Context Assembler (Detail)

### Task 2.2: MCP Tool Definitions
**Agent:** 1 agent
**Complexity:** Medium
**Can run in parallel with 2.1**

Define all MCP tools as `@tool`-decorated async closures. Each tool creates its own short-lived DB session (not shared across tools):

Standard agent tools:
- `create_todo`, `complete_todo`, `list_todos`
- `create_item`, `update_item`, `move_item`, `get_item`, `list_items`
- `read_memory`, `write_memory`
- `read_document`, `list_documents`, `create_document`
- `get_board_state`, `get_todo_state`, `get_conversation_summaries`, `search_conversations`, `get_conversation_messages`
- `delegate_task` (placeholder for Phase 5)

Odin-only tools:
- `list_spaces`, `list_agents`, `open_conversation`, `navigate_to_space`, `get_attention_items`, `get_cross_space_todos`

Each tool has try/except, db rollback on error, returns `is_error: True` on failure.

**Deliverable:** A well-defined tool registry module that Task 2.3a and 2.5 import.

**Acceptance criteria:** All tools callable, produce correct results, handle errors gracefully. Module has clear interface for SessionManager to consume.

**Architecture doc reference:** MCP Tools section under Layer 4

### Task 2.3a: Session Manager — Core Lifecycle
**Agent:** 1 agent
**Complexity:** Large
**Depends on:** 2.1, 2.2, and spike results from 0.1

The core session lifecycle (happy path):
- `start_session(conversation_id, agent_id)` — load agent config, assemble context (via ContextAssembler), build MCP tool set, register permission hooks, call `query()` with assembled prompt, store session state in memory dict
- `send_message(conversation_id, message)` — look up active session, call `query(resume=session_id)`, yield response chunks for SSE streaming, store user message + agent response in DB
- `close_session(conversation_id)` — send "summarize this conversation" as final message, store summary in conversation_summaries, terminate SDK session, update conversation status to "closed"
- Active session tracking: `dict[conversation_id → SessionState]`

**Claude Max outage handling:** SDK calls (`query()`) can fail due to Claude Max outages, rate limits, or network errors. The SessionManager must:
- Catch SDK connection/API errors and surface them as SSE `error` events to the frontend (not silent failures)
- Mark the conversation status as `interrupted` (not `closed`) on unrecoverable SDK errors
- Create a notification: "Conversation X was interrupted: Claude is unavailable"
- The frontend should render a clear "Claude is unavailable — try again later" state in the conversation panel (not a generic error)
- Do NOT implement retry logic for outages (the user decides when to retry). Rate limit 429s can be retried with backoff (Task 7.3 handles the retry policy).

**Acceptance criteria:** Can start a session, send multiple messages with resume, close with summary generation. Session state tracked correctly. SDK errors result in clear error events and conversation marked as interrupted.

**Architecture doc reference:** Layer 4: Session Manager (Detail) — start_session, send_message, close_session operations

### Task 2.3b: Session Manager — Delegation, Recovery, Concurrency
**Agent:** 1 agent
**Complexity:** Medium
**Depends on:** 2.3a

Extended session manager capabilities:
- `delegate_background(agent_id, instruction, space_id, item_id?)` — simple fire-and-forget version: start session without SSE streaming, log activity to background_tasks, notify on completion. **Note: Task 5.2b replaces this with the managed turn loop (discrete turns with steering checkpoints). This Phase 2 version is intentionally simple — it gets background delegation working without the turn loop complexity.**
- `reopen_conversation(conversation_id)` — attempt `resume=sdk_session_id`. If resume fails, start new session with conversation summary + recent messages as context.
- Crash recovery on startup: scan for `status='active'` conversations, mark as `interrupted`, create notification
- Concurrency control: max 5 interactive sessions, max 2 automation sessions, user conversations priority over automations. Queue when limit hit.
- `monitor_context_usage()` — after each response, estimate context usage. At 70% trigger auto-checkpoint summary. At 90% surface notification suggesting close.
- `GET /api/v1/agents/running` endpoint (lists all active/queued sessions)
- Orphaned process cleanup on startup

**Acceptance criteria:** Background delegation works. Crash recovery marks interrupted conversations. Concurrency limits enforced. Reopen works for both closed and interrupted conversations.

### Task 2.4: SSE Streaming Endpoint
**Agent:** 1 agent
**Complexity:** Medium
**Depends on:** 2.3a

- Single multiplexed SSE endpoint: `GET /api/v1/events`
- Uses the SSE Event Contract from Task 1.5
- Streams: conversation tokens, tool calls, approval requests, notifications, routing actions, background updates, errors
- All events tagged with source ID (conversation_id, task_id, etc.)
- Frontend connects once, demultiplexes by source
- `POST /api/v1/conversations/{id}/messages` triggers streaming via the SSE channel
- Reconnection support (client sends last-event-id)

**Acceptance criteria:** SSE connection stays alive. Conversation responses stream token-by-token. Multiple conversations stream to the same connection. Events follow the contract types.

**Architecture doc reference:** SSE Event Contract from Task 1.5

### Task 2.5: Odin Service
**Agent:** 1 agent
**Complexity:** Medium
**Depends on:** 2.3a, 2.2 (for Odin-specific tools)

- Persistent Haiku session (conversation record with `space_id=null`)
- Uses Odin-specific MCP tools from Task 2.2
- Uses Odin-specific context assembly from Task 2.1
- `POST /api/v1/odin/message` endpoint
- Session lifecycle: start on first message (or resume existing), auto-checkpoint at high context, periodic restart
- Routing: `open_conversation` tool returns routing action → SSE event → frontend navigates
- Memory namespace: "odin" — learns user preferences across sessions
- Error handling: ambiguous requests → ask clarifying questions, no matching agent → suggest creating one

**Acceptance criteria:** Odin responds to messages. Can create to-dos, list spaces, route to space conversations. Routing actions trigger SSE route events.

**Architecture doc reference:** Layer 4b: Odin — The Front Door (Detail)

### Task 2.6: Permission Hooks Integration
**Agent:** 1 agent
**Complexity:** Medium
**Depends on:** 2.3a

- `PreToolUse` hook registration on every session
- Path validation: extract file paths from tool_input, match against agent_permissions resource patterns
- Approval flow: create permission_request in DB, poll DB (no timeout), push approval_request event to SSE
- When user approves/denies via API → hook unblocks → agent continues or receives denial
- System guardrails: always block .env, credentials.json, ~/.ssh, ~/.aws, ~/.claude, openloop.db
- Bash tool: defaults to "Requires approval" for all agents (no pattern matching on shell commands)

**Resource matching algorithm:**
The `resource_pattern` field in `agent_permissions` uses these matching rules:
1. **File paths** — glob-style matching via Python's `fnmatch`. Patterns like `/recruiting/*` match any file under `/recruiting/`. Patterns like `/recruiting/**` match recursively. The tool call's file path is normalized to forward slashes and matched against the pattern.
2. **Named resources** — exact string match. Patterns like `gmail`, `web`, `openloop-board` match the resource name extracted from the tool call. MCP tool calls (e.g., `mcp__gmail__send_email`) map to a resource name by extracting the service prefix (`gmail`).
3. **Default fallback** — if no `agent_permissions` row matches the resource, the grant level is `never` (deny by default). Every allowed resource must have an explicit permission row.

**Tool-to-resource extraction:**
- `Read`, `Write`, `Edit`, `Glob`, `Grep` → extract `file_path` / `path` from tool_input, use as resource
- `Bash` → resource is `bash` (always requires approval, no path extraction)
- `mcp__openloop__*` → resource is `openloop-board` / `openloop-memory` based on tool name
- `mcp__gmail__*` → resource is `gmail`
- `WebSearch`, `WebFetch` → resource is `web`
- Unknown tools → resource is `unknown` (defaults to deny)

**Acceptance criteria:** Blocked paths denied immediately. Approval-required operations create pending request visible via SSE. Approvals unblock agent. No timeout anywhere. Glob matching works for file path patterns. Named resource matching works for MCP tools.

**Architecture doc reference:** Layer 5: Permission Enforcer (Detail)

### Task 2.7: Structured Logging Setup
**Agent:** 1 agent
**Complexity:** Small
**Can run in parallel with 2.3b, 2.4, 2.5, 2.6**

Set up structured logging for agent session diagnostics:
- Python `logging` module with JSON formatter, output to `data/logs/openloop.log` (rotated, 10MB max, 5 backups)
- Log levels: `INFO` for session lifecycle events (start, message, close, resume), `WARNING` for permission denials and context budget overflows, `ERROR` for SDK failures and unhandled exceptions
- Key events to log:
  - Session start/resume/close (conversation_id, agent_id, model)
  - Tool calls (conversation_id, tool_name, resource, permission decision)
  - Permission requests (agent_id, resource, operation, grant_level, resolution)
  - SDK errors (conversation_id, error type, error message)
  - Context assembly (conversation_id, tokens used per tier, total)
- Utility: `get_logger(name: str)` that returns a pre-configured logger
- All log entries include timestamp, conversation_id (where applicable), and agent_id

**Acceptance criteria:** Logging configured and importable. Session Manager, Permission Enforcer, and Context Assembler use it. Logs are human-readable JSON in `data/logs/`. Log rotation works.

### Task 2.8: Phase 2 Tests
**Agent:** 1 agent
**Complexity:** Medium
**Depends on:** 2.3b, 2.4, 2.5, 2.6

- Context assembler tests (all tiers, token budgets, Odin mode)
- MCP tool tests (each tool, error paths, per-tool DB session isolation)
- Session manager tests (lifecycle, crash recovery, reopen)
- **Concurrency test: start 5 sessions, verify no interference**
- SSE streaming tests (connection, demultiplexing, event contract compliance)
- Permission hook tests (path validation, approval flow, no-timeout behavior)
- Odin tests (routing actions, cross-space context)

### Task 2.9: Phase 2 Merge + Integration Check
**Agent:** 1 agent
**Complexity:** Small
**Depends on:** 2.8

- Verify all Phase 2 modules integrate correctly
- Verify SSE events match the contract from Task 1.5
- `make lint` and `make test` pass
- Quick manual smoke test: start backend, send a message, verify streaming works

---

## Phase 3: Frontend Foundation

**Goal:** Home dashboard, space navigation, and conversation UI. Design-forward.
**Depends on:** Phase 1 API (stable) + Phase 2 streaming (working)

### Task 3.1: Design System + App Shell
**Agent:** 1 agent using `frontend-design` skill
**Complexity:** Medium

- Design system: color tokens (CSS variables, dark/light), distinctive typography selection, spacing scale, component primitives (button, input, badge, panel, modal, card)
- App shell: sidebar navigation (Home link, space list with activity indicators), main content area, Odin chat input (fixed top, always visible)
- Router setup (Home view, Space view, Settings view)
- API client setup (openapi-fetch + openapi-react-query using generated types)
- Zustand stores (UI state: current space, selected item, panel open/closed; theme state)
- SSE connection manager (connect to `GET /api/v1/events`, demultiplex by source ID, auto-reconnect on disconnect, expose as React hooks)

**Acceptance criteria:** App loads, sidebar shows navigation, Odin input at top. Theme toggle works. SSE connection established and events demultiplexed. Looks distinctive and polished, not generic.

### Task 3.2: Home Dashboard
**Agent:** 1 agent using `frontend-design` skill
**Complexity:** Medium
**Can run in parallel with 3.3**

Layout (top to bottom, priority order):
1. Odin chat panel (fixed top, expandable/collapsible, streaming responses, inline action cards for routing/creation)
2. Attention items (pending approvals with badge count, due-today items, agent results to review, automation failures)
3. Active agents (compact status indicators, expandable activity logs via SSE)
4. Space list (cards with activity indicators, click to navigate)
5. Cross-space to-do list (grouped by space, checkbox toggle, below the fold)
6. Cross-space conversation list (recent conversations across all spaces, click to navigate)

First-run state: Odin welcome message, "Create your first space" card with template picker.

**Acceptance criteria:** Dashboard renders all sections in priority order. Odin sends messages and streams responses. Action cards render for routing/creation events. To-do checkboxes toggle. Approvals show with badge. First-run state on empty database.

### Task 3.3: Space View — To-dos + Board
**Agent:** 1 agent using `frontend-design` skill
**Complexity:** Large
**Can run in parallel with 3.2**

- Space view layout: to-dos panel (left or top), board area (center), conversations sidebar (right), data tab
- To-do list (add inline, check off, delete, promote button, optional due date)
- Kanban board (columns from space's `board_columns`, drag-and-drop with @dnd-kit, distinctive card design)
- Board item cards (title, stage badge, agent assignment, due date indicator, provenance link to source conversation)
- Board item detail panel (slide-over: edit all fields, view item_events history, link to source conversation)
- "New Conversation" button with agent picker and model selector dropdown
- Create board item modal (title, type selector, stage, description)

**Acceptance criteria:** Board drag-and-drop works. To-dos created and checked off. Items created and moved between columns. Detail panel opens on click with edit capability.

### Task 3.4: Conversation Panel
**Agent:** 1 agent using `frontend-design` skill
**Complexity:** Large
**Depends on:** 3.1 (SSE connection manager)

- Chat interface (message list with auto-scroll, input area, send button)
- Streaming response rendering (tokens appear as they arrive via SSE `token` events)
- Tool call indicators ("Agent is reading files...", "Agent is searching web..." via SSE `tool_call` events)
- Inline approval requests ([Approve] [Deny] buttons rendered from SSE `approval_request` events)
- Conversation list within space view (active/closed tabs, click to switch — **supports multiple open conversations**)
- Close conversation button (triggers summary generation, shows completion)
- Model selector dropdown (per-conversation override)
- Conversation name editing (inline)

**Acceptance criteria:** Messages send and responses stream in real-time. Tool call indicators show during agent work. Approval requests render inline with working buttons. Can switch between multiple open conversations. Closing triggers summary visible in the conversation.

### Task 3.5: Agent Management UI
**Agent:** 1 agent using `frontend-design` skill
**Complexity:** Medium
**Can run in parallel with 3.4**

- Settings → Agents page
- Agent list (name, description, default model, spaces, status badge)
- Create agent form (name, description, system prompt textarea, model selector, tool checkboxes, space multi-select)
- Edit agent form (same fields, pre-populated)
- Permission matrix editor (resource × operation grid with Always/Approval/Never dropdowns)

**Acceptance criteria:** Agents can be created, edited, and viewed. Permission matrix is editable with correct grant levels. Changes persist via API.

### Task 3.6: Phase 3 Frontend Tests
**Agent:** 1 agent using `webapp-testing` skill
**Complexity:** Medium
**Depends on:** 3.2, 3.3, 3.4, 3.5

Playwright tests:
- Home dashboard renders all sections, Odin input works
- Space navigation (Home → Space → Home via sidebar)
- To-do CRUD (create, check off, delete)
- Board drag-and-drop (move item between columns)
- **End-to-end streaming test: send a real message through Session Manager, verify tokens appear in the browser** (requires Phase 2 backend running)
- Agent CRUD (create, edit, view permissions)
- Theme toggle (dark/light)
- First-run state display

### Task 3.7: Phase 3 Merge + Integration Check
**Agent:** 1 agent
**Complexity:** Small
**Depends on:** 3.6

- Full integration verification (frontend ↔ backend ↔ SSE)
- Visual consistency check across all pages
- `make lint` passes for both backend and frontend

---

## Phase 3b: Memory Architecture + Context Safety

**Goal:** Upgrade memory system to four tiers (semantic, episodic, working, procedural). Add write-time dedup, temporal fact management, scored retrieval, context safety mechanisms. All backend — no frontend changes.
**Depends on:** Phase 2 (session manager, MCP tools, context assembler) and Phase 3 (complete).
**Rationale:** Memory infrastructure is foundational. Agents using better memory tools from Phase 4 onward means higher quality from day one. These are all modifications to existing Phase 2 backend code.

### Task 3b.1: Schema Migration
**Agent:** 1 agent
**Complexity:** Small

- Add columns to `memory_entries`: `importance` (float, default 0.5), `access_count` (int, default 0), `last_accessed` (datetime, nullable), `valid_from` (datetime, default created_at), `valid_until` (datetime, nullable), `archived_at` (datetime, nullable), `category` (string, nullable)
- Add columns to `conversation_summaries`: `is_meta_summary` (boolean, default false), `consolidated_into` (FK → conversation_summaries, nullable)
- Create `behavioral_rules` table: id, agent_id (FK), rule (text), source_type (string — "correction" | "validation"), source_conversation_id (FK, nullable), confidence (float, default 0.5 — asymmetric updates: +0.1 on confirmation, -0.2 on override), apply_count (int, default 0), last_applied (datetime, nullable), is_active (boolean, default true), created_at, updated_at
- Add columns to `background_tasks`: `current_step` (int, nullable), `total_steps` (int, nullable), `step_results` (JSON, nullable), `parent_task_id` (FK → background_tasks, nullable)
- Alembic migration
- Update ORM models in `models.py`
- Update affected Pydantic schemas

**Acceptance criteria:** Migration runs cleanly. All new columns/tables exist. Existing data is preserved. ORM models reflect new schema.

**Architecture doc reference:** Data Model (memory_entries, conversation_summaries, behavioral_rules, background_tasks schemas)

### Task 3b.2: Enhanced Memory Service + Write-Time Dedup
**Agent:** 1 agent
**Complexity:** Large
**Depends on:** 3b.1

Rewrite `memory_service.py` to support the new memory architecture:

- `save_fact_with_dedup(db, namespace, content, importance?, category?, source?)` — the core write path:
  1. Load all active (non-archived, valid_until IS NULL) facts in the namespace
  2. Call LLM to compare new fact against existing facts → decide ADD/UPDATE/DELETE/NOOP
  3. ADD: create new entry with valid_from=now
  4. UPDATE: modify existing entry's value, update updated_at
  5. DELETE (supersession): set valid_until=now on old fact, create new fact with valid_from=now
  6. NOOP: return existing entry unchanged
  7. If namespace is at cap (50 space, 20 agent): archive lowest-scored active entry before adding
- Scoring function: `score = importance × e^(-λ × days_since_access) × (1 + access_count × 0.2)` where `λ = 0.16 × (1 - importance × 0.8)`
- `get_scored_entries(db, namespace, limit?)` — returns active entries ranked by score
- `archive_entry(db, entry_id)` — sets archived_at, excludes from future assembly and dedup
- Update `list_entries()` to exclude archived by default, add `include_archived` parameter
- Keep backward-compatible `upsert_entry()` for non-agent callers (seed script, API routes)

New service modules:
- `behavioral_rule_service.py` — CRUD, `confirm_rule(rule_id)` (+0.1 confidence, capped at 1.0), `override_rule(rule_id)` (-0.2 confidence, asymmetric), apply tracking (increment apply_count, set last_applied), auto-demotion (is_active=false when confidence < 0.3 after 10+ sessions), list active rules ranked by confidence
**Acceptance criteria:** Write-time dedup correctly identifies ADD/UPDATE/DELETE/NOOP. Temporal supersession preserves old fact with valid_until. Cap enforcement archives lowest-scored entry. Scoring formula returns correct rankings. Behavioral rules track confidence correctly. All existing memory service tests still pass.

**Architecture doc reference:** Context Pruning and Memory Lifecycle Strategy (Tier 1: Semantic Memory), Flow 7 (Write-Time Fact Management)

### Task 3b.3: Enhanced MCP Tools
**Agent:** 1 agent
**Complexity:** Medium
**Depends on:** 3b.2
**Can run in parallel with 3b.4**

Replace existing memory MCP tools in `mcp_tools.py`:
- Remove: `read_memory`, `write_memory`
- Add: `save_fact(content, importance?, category?)` — calls `save_fact_with_dedup()`, returns the dedup decision and resulting entry
- Add: `update_fact(fact_id, new_content)` — explicit update of a known fact
- Add: `recall_facts(query?, namespace?, category?, date_range?)` — scored retrieval, returns facts with scores. Omit namespace for cross-namespace search.
- Add: `delete_fact(fact_id, reason)` — marks as superseded (sets valid_until=now)
- Add: `save_rule(rule, source_type?, source_context?)` — creates behavioral_rule with confidence 0.5; source_type: "correction" | "validation"
- Add: `confirm_rule(rule_id)` — calls `behavioral_rule_service.confirm_rule()`, increases confidence by +0.1
- Add: `override_rule(rule_id)` — calls `behavioral_rule_service.override_rule()`, decreases confidence by -0.2
- Add: `list_rules(agent_id?)` — returns active rules for the agent
Update agent system prompts (in context assembler or agent configs) with instructions to:
- Use `save_fact` proactively when learning important information
- Use `save_rule` when the user corrects behavior (source_type="correction") or confirms a non-obvious approach worked well (source_type="validation")
- Use `confirm_rule` when the user validates a rule's recommendation was correct
- Use `override_rule` when the user contradicts an existing rule — the agent can see its active rules in context and should recognize when a user response conflicts with one

**Acceptance criteria:** All new tools callable and produce correct results. Old read_memory/write_memory removed. `confirm_rule` increases confidence by +0.1; `override_rule` decreases by -0.2. Agent system prompts include memory management instructions (including when to confirm/override rules). Error handling (try/except, db rollback, is_error on failure) follows existing patterns.

**Architecture doc reference:** MCP Tools section (Memory operations, Behavioral rule operations)

### Task 3b.4: Context Assembler Upgrade
**Agent:** 1 agent
**Complexity:** Medium
**Depends on:** 3b.2
**Can run in parallel with 3b.3**

Rewrite `context_assembler.py` to implement attention-optimized ordering and scored retrieval:

- **Ordering change** (beginning/middle/end):
  - BEGINNING (high attention): Agent identity + role prompt (~1500 tokens), procedural rules from behavioral_rules (~500 tokens), tool documentation (~1000 tokens)
  - MIDDLE (lower attention): Conversation summaries — meta-summary first if exists, then recent unconsolidated (~2000 tokens), space facts via `get_scored_entries()` (~1000 tokens), global facts via `get_scored_entries()` (~500 tokens)
  - END (high attention): Board/to-do state (~1500 tokens)

- **Scored retrieval**: Use `get_scored_entries()` from memory service instead of `list_entries()`. Update `access_count` and `last_accessed` on every fact retrieved during assembly.

- **Procedural memory injection**: Load active behavioral_rules for the agent, sorted by confidence descending. Format as a "Behavioral Rules" section within the system prompt area. Update `apply_count` and `last_applied` on each rule injected.

- **Meta-summary handling**: If a meta-summary exists for the space (is_meta_summary=true, consolidated_into IS NULL), load it first in the summaries section. Then load unconsolidated individual summaries (consolidated_into IS NULL, is_meta_summary=false) most recent first.

- **Odin mode**: Same changes but cross-space. Load Odin's own behavioral rules. Global facts scored. Cross-space summary.

**Acceptance criteria:** Context output follows beginning/middle/end ordering. Facts are scored and ranked correctly. Behavioral rules appear in system prompt section. Access tracking updates on retrieval. Meta-summaries load correctly. Total budget stays within ~8000 tokens.

**Architecture doc reference:** Layer 6: Context Assembler (Detail), Context Pruning and Memory Lifecycle Strategy (Overall Context Budget)

### Task 3b.5: Session Manager Context Safety
**Agent:** 1 agent
**Complexity:** Medium
**Depends on:** 3b.3 (needs enhanced memory tools for flush)

Add three safety mechanisms to `session_manager.py`:

1. **`flush_memory(conversation_id)`** — mandatory pre-compaction step:
   - Inject instruction to the agent: "Review this conversation for any important facts, decisions, or user preferences that haven't been saved to memory yet. Save them now using your memory tools."
   - Agent processes the instruction, calls save_fact/save_rule as needed
   - Return — normal flow continues
   - Wire into `close_session()`: call flush_memory() BEFORE generating the final summary
   - Wire into `monitor_context_usage()`: call flush_memory() BEFORE creating a checkpoint summary

2. **Proactive budget enforcement in `send_message()`**:
   - Before each `query()` call, estimate total context size (system prompt + assembled context + conversation history + pending message)
   - Use `estimate_tokens()` utility (already exists, 4 chars ≈ 1 token)
   - If >70% of context window (200K × 0.7 = 140K tokens): trigger compression before the LLM call
   - Compression: call flush_memory() first, then apply observation masking (below)

3. **Observation masking** — compression strategy:
   - Keep the most recent 5-10 complete exchanges (user message + agent response) verbatim (configurable — default 7 as a named constant in session manager)
   - Summarize older exchanges into a compact block (use the agent or a lightweight summary call)
   - Cut at turn boundaries only — never split a tool-call sequence
   - Store the compressed summary as a checkpoint in conversation_summaries

4. **`verify_compaction(compressed_content)`** — post-compaction safety check:
   - Extract key phrases from the compressed content (decisions, specific values, preferences) using keyword/pattern extraction — NOT an LLM call
   - Check each against persistent memory (memory_entries where valid_until IS NULL)
   - If gaps found: log a warning with the missed content. Optionally trigger a targeted `save_fact` for clearly missed facts
   - Non-blocking — do not hold up the conversation for verification
   - Wire into `send_message()`: call after compression completes, before proceeding with query()

**Acceptance criteria:** flush_memory() runs before every close and every checkpoint. Proactive check triggers compression before LLM call when needed. Observation masking preserves recent turns verbatim. Post-compaction verification runs after compression. Compression happens at clean turn boundaries. All existing session manager tests still pass.

**Architecture doc reference:** Session Manager operations (flush_memory, send_message proactive check), Flow 5 (updated close flow), Flow 9 (Proactive Budget Enforcement)

### Task 3b.6: Phase 3b Tests
**Agent:** 1 agent
**Complexity:** Medium
**Depends on:** 3b.3, 3b.4, 3b.5

- **Write-time dedup tests**: save fact → save contradicting fact → verify NOOP/ADD/UPDATE/DELETE decisions. Test temporal supersession (old fact gets valid_until, new fact created).
- **Cap enforcement tests**: fill namespace to cap → save one more → verify lowest-scored entry archived. Verify archived entries excluded from context assembly but still queryable.
- **Scoring formula tests**: create facts with varying importance/access/age → verify ranking order matches expected scores.
- **Context ordering tests**: assemble context → verify identity at top, rules after identity, board state at bottom, facts/summaries in middle.
- **Procedural memory tests**: save rule → assemble context → verify rule in system prompt section. Test `confirm_rule` increases confidence by +0.1 (capped at 1.0). Test `override_rule` decreases confidence by -0.2 (asymmetric). Test auto-demotion after threshold (confidence < 0.3 after 10+ sessions). Test both source_types ("correction", "validation").
- **Flush pipeline tests**: start conversation → discuss facts → trigger flush → verify facts saved to memory before summary generated. Test in both close and checkpoint paths.
- **Proactive budget tests**: create a session with large context → send message → verify compression triggered before LLM call, not after. Verify recent turns kept verbatim.
- **Post-compaction verification tests**: compress context where flush deliberately misses a fact → verify `verify_compaction()` detects the gap and logs a warning. Verify non-blocking (conversation proceeds even if gaps found).
- **Backward compatibility**: verify existing API routes for memory still work (they use the service layer, which maintains backward-compatible functions).

**Acceptance criteria:** All tests pass. No regressions in existing Phase 1-2 test suites.

---

## Phase 4: Records, Table View, Documents, Search

**Goal:** CRM-style capabilities, document management, full-text search.
**Can overlap with Phases 5 and 6 once started.**

### Task 4.1: Records Backend
**Agent:** 1 agent
**Complexity:** Medium

- Extend `ItemService` for records: `custom_fields` CRUD, `parent_record_id` linking, record-to-todo links
- API endpoints for custom field schema management per space
- Stage validation for records (same `board_columns` system)
- **Define the API contract for 4.2** before this task completes (schemas first, implementation second)

### Task 4.2: Table View Frontend
**Agent:** 1 agent using `frontend-design` skill
**Complexity:** Large
**Depends on:** 4.1 (needs API contract defined)

- Table component (sortable columns, filterable rows, configurable visible fields)
- Record row rendering (custom fields as table columns)
- Inline editing (click cell to edit, save on blur/enter)
- Column configuration panel (add/remove/reorder visible fields)
- View toggle per space (board ↔ table) with persistence
- Record detail panel (shows linked to-dos, custom fields, item events)

### Task 4.3: Document Management
**Agent:** 1 agent
**Complexity:** Medium
**Can run in parallel with 4.1 and 4.2**

- Extend `DocumentService` with local file indexing (scan directory, store metadata)
- Document list/search UI in space data tab (per-space, tag filter, text search)
- Upload UI (drag-and-drop file upload to local storage in `data/documents/{space_id}/`)
- Document viewer (inline for text/markdown, download link for other types)

### Task 4.4: Google Drive Integration
**Agent:** 1 agent
**Complexity:** Large
**Depends on:** 4.3

- Google Drive API client (OAuth flow reusing existing `credentials.json` pattern from dispatch repo)
- Link Drive folder to space via `data_sources` table
- Index Drive files (list files, store metadata in documents table, configurable refresh interval)
- Agent MCP tools: `read_drive_file`, `list_drive_files`, `create_drive_file`
- Drive document browsing in the space data tab (merged with local documents)

### Task 4.5a: FTS5 Search Infrastructure
**Agent:** 1 agent
**Complexity:** Medium
**Can run in parallel with 4.4**

- FTS5 virtual tables for: `conversation_messages`, `conversation_summaries`, `memory_entries` (active only, exclude archived), `documents`
- SQLite triggers to keep FTS5 tables in sync on INSERT/UPDATE/DELETE
- Memory entries trigger: only index rows where `archived_at IS NULL`; remove from FTS5 index when archived
- `SearchService` — combined search across all types, results ranked by FTS5 BM25 scoring and grouped by type
- `GET /api/v1/search?q=...` endpoint
- Global search UI (search icon in header → search modal with results grouped by type: conversations, documents, memory, items)

### Task 4.5b: Cross-Space Search Tools
**Agent:** 1 agent
**Complexity:** Medium
**Depends on:** 4.5a
**Can run in parallel with 4.4**

Upgrade MCP search tools to use FTS5 and support cross-space search:
- `search_conversations` — `space_id` becomes optional. Omit for cross-space search. Backed by FTS5 instead of LIKE. Results include BM25 relevance score.
- `search_summaries(query, space_id?)` — new tool. FTS5 search on conversation_summaries.summary. Cross-space capable.
- `recall_facts` — upgrade from LIKE to FTS5 on memory_entries.value. Returns scored results.
- **Permission scoping**: cross-space results filtered by agent's `agent_spaces` join table. Odin sees all spaces.
- API endpoint: `GET /api/v1/search?q=...&space_id=...` supports optional space_id for cross-space.

**Acceptance criteria:** All search tools return FTS5-ranked results. Cross-space search respects agent permissions. Odin can search all spaces. Archived memory entries excluded from search results.

**Architecture doc reference:** Context Pruning and Memory Lifecycle Strategy (On-Demand Search section), MCP Tools (Context operations)

### Task 4.6: Phase 4 Tests
**Agent:** 1 agent
**Complexity:** Medium

- Record CRUD + custom field tests
- Table view Playwright tests (sort, filter, inline edit, view toggle)
- Document indexing + search tests
- Drive integration tests (mock Google API)
- FTS5 search accuracy tests (search across types, verify ranking)
- Cross-space search tests (verify permission scoping, verify Odin sees all spaces)
- search_summaries tool tests (FTS5 on summary content, cross-space)
- Verify archived memory entries excluded from FTS5 index

---

## Phase 4b: Flexible Space Layouts

**Goal:** Replace hardcoded space views with a widget-based layout system. Agents can read and redesign space layouts.
**Depends on:** Phase 4 (table view exists as a widget candidate, core space views working).
**Can overlap with Phases 5 and 6.**

### Task 4b.1: Schema + Backend
**Agent:** 1 agent
**Complexity:** Medium

Create `space_widgets` table and Alembic migration:
- `id` (UUID, PK), `space_id` (FK → spaces), `widget_type` (string), `position` (integer), `size` (string — "small" | "medium" | "large" | "full"), `config` (JSON), `created_at`, `updated_at`
- Add `WidgetType` enum to `contract/enums.py`: `todo_panel`, `kanban_board`, `data_table`, `conversations`, `chart`, `stat_card`, `markdown`, `data_feed`
- Add `WidgetSize` enum to `contract/enums.py`: `small`, `medium`, `large`, `full`

Extend SpaceService (or create `layout_service.py`) with layout CRUD:
- `get_layout(db, space_id)` → ordered list of widgets
- `add_widget(db, space_id, widget_type, position, size, config)` → creates widget, shifts positions of subsequent widgets
- `update_widget(db, widget_id, **kwargs)` → update size, config, position
- `remove_widget(db, widget_id)` → delete widget, reorder positions
- `set_layout(db, space_id, widgets)` → bulk replace all widgets (for agent-generated full redesigns)

Pydantic schemas: `WidgetCreate`, `WidgetUpdate`, `WidgetResponse`, `LayoutResponse` (ordered list of widgets).

API endpoints:
- `GET /api/v1/spaces/{id}/layout`
- `POST /api/v1/spaces/{id}/layout/widgets`
- `PATCH /api/v1/spaces/{id}/layout/widgets/{widget_id}`
- `DELETE /api/v1/spaces/{id}/layout/widgets/{widget_id}`
- `PUT /api/v1/spaces/{id}/layout` (bulk replace)

Data migration: for all existing spaces, generate `space_widgets` rows from current `board_enabled` / `default_view` / `board_columns` values. Project spaces get [todo_panel, kanban_board, conversations]. CRM spaces get [todo_panel, data_table, conversations]. Knowledge Base and Simple spaces get appropriate defaults.

Update space template defaults in `space_service.py` to create widgets on new space creation.

**Acceptance criteria:** Widget CRUD works. Existing spaces get correct widgets via migration. New spaces from templates have correct default widgets. Bulk replace works for agent-generated layouts. `make generate-types` produces TypeScript types for widget schemas.

### Task 4b.2: Widget Renderer + Space.tsx Refactor
**Agent:** 1 agent using `frontend-design` skill
**Complexity:** Large
**Depends on:** 4b.1

Refactor `Space.tsx` to read widget layout from API instead of hardcoding the 3-column layout:

- **Widget registry**: a mapping from `widget_type` strings to React components:
  - `"todo_panel"` → `<TodoPanel />`
  - `"kanban_board"` → `<KanbanBoard />`
  - `"data_table"` → `<DataTable />`
  - `"conversations"` → `<ConversationSidebar />`
  - Extended types (`chart`, `stat_card`, `markdown`, `data_feed`) render a placeholder until implemented
- **Layout engine**: reads the ordered widget list from the API, renders each widget in a CSS Grid layout based on `position` and `size`
- **Widget interface**: each widget component receives its `config` prop and renders independently. Standard props: `spaceId`, `widgetId`, `config`, `size`
- Wrap existing components (TodoPanel, KanbanBoard, DataTable, ConversationSidebar) to conform to the widget interface
- Fallback: if a space has no widgets (shouldn't happen after migration), render the template default

**Acceptance criteria:** Existing spaces render identically to before (via migrated widget data). Adding/removing widgets via the API changes what renders in the space view. All four core widget types work. Unknown widget types render a graceful placeholder.

### Task 4b.3: Layout Editor UI
**Agent:** 1 agent using `frontend-design` skill
**Complexity:** Medium
**Depends on:** 4b.2
**Can run in parallel with 4b.4**

A layout editor accessible from space settings (gear icon or settings page):

- Visual representation of current widget layout (list of widgets with type, size, position)
- **Add widget**: picker showing available widget types with descriptions
- **Remove widget**: click to remove with confirmation
- **Reorder widgets**: up/down arrow buttons to change position
- **Configure widget**: opens widget-specific config panel (e.g., choose columns for kanban, select visible fields for table)
- **Size selector**: per-widget dropdown (small, medium, large, full)
- Changes persist via API and space view updates immediately

This is a settings panel, not drag-and-drop within the space view. Drag-and-drop repositioning is a future enhancement.

**Acceptance criteria:** Can add, remove, reorder, resize, and configure widgets. Changes persist via API. Space view reflects changes immediately. Configuration panels work for kanban (column editor) and data table (field selector).

### Task 4b.4: Agent Layout MCP Tools
**Agent:** 1 agent
**Complexity:** Medium
**Depends on:** 4b.1
**Can run in parallel with 4b.3**

New MCP tools in `mcp_tools.py`:
- `get_space_layout(space_id)` — returns ordered widget list with configs
- `add_widget(space_id, widget_type, position?, size?, config?)` — adds widget to layout
- `update_widget(widget_id, size?, config?, position?)` — modifies existing widget
- `remove_widget(widget_id)` — removes widget from layout
- `set_space_layout(space_id, widgets)` — bulk replace for full redesigns

Each tool follows existing patterns: `@tool`-decorated async closure, own DB session, try/except with rollback, `is_error: True` on failure.

Update Agent Builder (Phase 5.1, when built) instructions to include layout design as part of new space/agent setup: "After creating a space, ask the user if they want a custom layout or if the template default is fine."

**Acceptance criteria:** Agent can read a layout, add/remove individual widgets, and bulk-replace an entire layout. Agent-written layouts render correctly in the frontend. Error handling follows existing MCP tool patterns.

### Task 4b.5: Phase 4b Tests
**Agent:** 1 agent
**Complexity:** Medium
**Depends on:** 4b.3, 4b.4

- Widget CRUD API tests (create, read, update, delete, bulk replace)
- Migration test (existing spaces get correct widgets based on template/board_enabled/default_view)
- Widget renderer tests: correct components render for each type, unknown types show placeholder
- Layout editor Playwright tests (add widget, remove widget, reorder, configure, resize)
- Agent layout MCP tool tests (read layout, add/remove widgets, bulk replace)
- Template default tests (new spaces created from each template get correct widget set)
- Regression: existing space views render identically to pre-refactor

---

## Phase 5: Agent Builder + Sub-agents

**Goal:** Conversational agent creation and agent-to-agent delegation.
**Can overlap with Phases 4b and 6.**

### Task 5.1: Agent Builder Agent
**Agent:** 1 agent
**Complexity:** Large

- Agent Builder system prompt (requirements gathering conversation — asks about domain, data sources, tools, permissions, what the agent should/shouldn't do)
- MCP tools: `create_agent`, `update_agent`, `list_available_tools`, `set_agent_permission`
- Agent Builder is a special system agent: exempt from "can't modify other agents" guardrail. Only the Agent Builder has these tools.
- Integration with Odin: Odin detects agent creation requests ("I need an agent for...") and calls `open_conversation` to route to the Agent Builder
- The Agent Builder registers the new agent in the DB and confirms to the user

### Task 5.2a: Sub-agent Delegation + Workflow Tracking
**Agent:** 1 agent
**Complexity:** Large
**Can run in parallel with 5.1**

- Implement `delegate_task` MCP tool (placeholder from Phase 2)
- Backend: creates `background_task` record, starts new SDK session for the sub-agent via SessionManager
- Sub-agent gets context from: space context + parent conversation summary + delegation instruction
- Results flow back: sub-agent writes to memory/documents/items, background_task record updated
- Notification sent when sub-agent completes or fails
- **Step tracking**: update `delegate_background()` to track `current_step`/`total_steps`/`step_results` on the background_task record. Agent updates step progress via a new `update_task_progress(step, summary)` MCP tool.
- **Parent-child linking**: when a sub-agent delegates further, link via `parent_task_id`. Query all tasks for a parent to show hierarchy.
- **Task audit**: detect stale tasks (queued >10min), stuck tasks (running >30min). Surface as notifications. Run check every 60 seconds (can share the automation scheduler's loop).

**Acceptance criteria:** delegate_task creates background task, sub-agent executes, results flow back. Step tracking shows progress. Parent-child hierarchy queryable. Stale/stuck detection creates notifications.

### Task 5.2b: Mid-Task Steering (Managed Turn Loop)
**Agent:** 1 agent
**Complexity:** Large (rewrites delegate_background from Phase 2's fire-and-forget into managed turn loop, plus adds steering queue)
**Depends on:** 5.2a

- `steer(conversation_id, message)` operation on SessionManager:
  - Add message to conversation's steering queue (max 10 pending messages)
  - Managed turn loop in `delegate_background()` checks queue between turns
  - At next turn boundary: steering message used as next user input in `query(resume=session_id)`
  - Works within SDK's existing query/resume mechanism — no mid-tool-call injection
- `POST /api/v1/conversations/{id}/steer` API endpoint
- SSE event: `steering_received` confirms message was queued
- Background agent system prompts include incremental-work instructions

**Acceptance criteria:** Steering message queued via API. Managed turn loop picks up message at next turn boundary. Agent receives message as next user input via query(resume). Agent adjusts course based on steering message. Auto-continuation works when steering queue is empty (no user involvement needed).

### Task 5.2c: Delegation UI
**Agent:** 1 agent using `frontend-design` skill
**Complexity:** Medium
**Depends on:** 5.2a, 5.2b

- Background task panel in Home dashboard active agents section:
  - Step progress display: "Step 3/5: Analyzing competitor C" with step history
  - Parent-child hierarchy view for tasks with sub-agents
  - **Steering message input**: text input on active background tasks to send steering messages
  - Task status indicators: running, completed, failed, stale, stuck
- Expandable activity log via SSE (existing pattern from Phase 3, enhanced with step markers)

**Acceptance criteria:** Step progress renders correctly. Steering input sends message and agent responds. Parent-child tasks show hierarchy. Stale/stuck tasks show warning indicators.

### Task 5.3: Phase 5 Tests
**Agent:** 1 agent
**Complexity:** Medium

- Agent Builder end-to-end: create an agent through conversation, verify it appears in agent list and is usable
- Sub-agent delegation: delegate task from conversation, verify background task created, results written, notification sent
- Permission isolation: sub-agent respects its own permission matrix, not parent's
- Step tracking: delegate multi-step task, verify step progress updates, verify step_results recorded
- Steering: delegate task → send steering message → verify agent receives and adjusts
- Workflow hierarchy: parent delegates to sub-agent → verify parent-child link → verify hierarchy in UI
- Stale/stuck detection: create task, don't complete it → verify notification after threshold

---

## Phase 6: Automations

**Goal:** Scheduled agent runs with dashboard and pre-built templates.
**Can overlap with Phases 4b and 5.**

### Task 6.1: Automation Backend
**Agent:** 1 agent
**Complexity:** Medium

- `AutomationService` — CRUD, run history tracking
- `AutomationScheduler` — background loop (every 60s), cron expression matching (use `croniter` library), fires matching automations as background tasks via SessionManager
- On startup: detect missed runs during downtime, create notifications ("Morning Briefing was missed, server was down at 7:00 AM. Run now?")
- Concurrency: max 2 concurrent automation sessions, user conversations always priority
- API endpoints: POST create, GET list, GET detail + runs, PATCH update, DELETE, POST manual trigger, GET run history

### Task 6.2: Automation Dashboard Frontend
**Agent:** 1 agent using `frontend-design` skill
**Complexity:** Medium
**Depends on:** 6.1

- Automation list (name, cron schedule in human-readable form, last run time + status, enable/disable toggle)
- Automation detail view (config, run history timeline with status/duration/result summary)
- Create/edit automation form (name, description, agent picker, instruction textarea, cron expression with helper, space picker)
- "Run now" button with confirmation
- Integration: automation failures appear in Home attention items

### Task 6.3: Pre-built Automation Templates
**Agent:** 1 agent
**Complexity:** Medium (upgraded from Small — includes agent prompts that produce useful results)
**Depends on:** 6.1

- "Daily To-Do Review" — agent scans all spaces for overdue to-dos, items with past due dates, and items that haven't moved. Produces a summary notification.
- "Stale Work Check" — weekly scan for board items not updated in 7+ days. Surfaces via notification.
- "Follow-up Reminder" — scans records with custom field `next_follow_up` past due. Surfaces via notification.

Each template includes: the automation config, the agent system prompt, and the MCP tool calls needed. Templates are pre-configured but not auto-enabled.

### Task 6.4: Phase 6 Tests
**Agent:** 1 agent
**Complexity:** Medium

- Scheduler tests (cron matching, missed-run detection, concurrency limits, priority over user sessions)
- Automation CRUD tests
- Dashboard Playwright tests (list, create, edit, run now, run history)
- Pre-built template execution tests (run each template, verify useful output)

---

## Phase 7: Polish, Backup, Integration

**Goal:** Tie everything together, polish, handle edge cases.

### Task 7.1a: Memory Lifecycle Management
**Agent:** 1 agent
**Complexity:** Medium

Phase 3b built the write-time infrastructure (dedup, caps, scoring). This task adds the long-term maintenance layer:

- **Auto-archival of superseded facts**: weekly check archives facts where `valid_until` was set >90 days ago. Background job (can share the automation scheduler's 60-second loop, run archival check once per day).
- **Auto-demotion of procedural rules**: rules with confidence < 0.3 after `apply_count >= 10` sessions are set to `is_active = false`. Check runs during context assembly (lazy evaluation — no separate job needed).
- **Periodic LLM-driven fact consolidation**: monthly job (or manual trigger from space settings):
  1. Load all active facts for a space
  2. LLM reviews for: related facts that should merge, contradictions, stale entries worth archiving
  3. Produce a consolidation report: proposed merges, flagged contradictions, suggested archives
  4. Surface as notification: "Memory review for [Space]: merged 4 entries, found 2 contradictions, suggest removing 3 stale entries. [Review]"
  5. User approves, adjusts, or dismisses — system never merges/deletes without confirmation
- **Memory health UI in space settings**: view all facts (active tab + archived tab), view behavioral rules (active + inactive), filter by category, manual archive/delete/merge actions
- **Checkpoint pruning**: after conversation closes, exclude its mid-conversation checkpoint summaries from context assembly (keep in DB for search)

### Task 7.1b: Summary Consolidation
**Agent:** 1 agent
**Complexity:** Medium
**Can run in parallel with 7.1a**

- **Threshold-triggered meta-summary generation**: when a space has 20+ unconsolidated summaries (where `consolidated_into IS NULL` and `is_meta_summary = false`), generate a meta-summary
- **Trigger point**: wired into `close_session()` — after storing the new summary, check unconsolidated count. If >= 20, generate meta-summary.
- **Generation**: LLM reads all unconsolidated summaries chronologically, produces a condensed overview covering: key decisions, outcomes, trajectory, open threads.
- **Storage**: meta-summary stored as `conversation_summary` with `is_meta_summary = true`. Individual summaries marked with `consolidated_into` pointing to the meta-summary.
- **Successive consolidation**: when a second round of 20 accumulates, the new meta-summary covers both the old meta-summary and the new individuals. Old meta-summary gets `consolidated_into` pointing to the new one.
- **Manual trigger**: `POST /api/v1/spaces/{id}/consolidate` endpoint. UI button in space settings: "Consolidate conversation history."
- **Context assembly integration**: meta-summary loads first in summaries section. Then unconsolidated individuals most-recent-first. (Context assembler already handles this from Phase 3b.4.)

**Acceptance criteria:** Meta-summary generated at threshold. Individual summaries marked as consolidated. Successive consolidation works. Manual trigger works. Context assembly loads meta-summary first.

### Task 7.2: Backup System
**Agent:** 1 agent
**Complexity:** Small
**Can run in parallel with 7.1**

- Port `backup_gdrive.py` to work with new data directory (`data/openloop.db`)
- `make backup` (local SQLite copy) and `make backup-gdrive` (Drive upload with retention)
- Optional: backup on conversation close (configurable in settings)
- Home dashboard: subtle reminder if no backup in 24 hours

### Task 7.3: Error Handling + Edge Cases
**Agent:** 1 agent
**Complexity:** Medium
**Can run in parallel with 7.1 and 7.2**

- SDK session crash recovery (mid-conversation exception → mark interrupted, notify, log error)
- Rate limit handling (detect 429 from SDK, surface notification, pause session, auto-retry after cooldown)
- SSE reconnection (frontend EventSource auto-reconnects, replays missed events via last-event-id)
- Orphaned CLI process cleanup on backend startup
- Graceful shutdown on SIGTERM (close active sessions cleanly)
- SQLite busy timeout configuration (5-10 second timeout for concurrent writes)

### Task 7.4: UI Polish
**Agent:** 1 agent using `frontend-design` skill
**Complexity:** Medium

- Animations and transitions (page transitions, panel slides, toast notifications, loading → loaded transitions)
- Loading states (skeleton screens for dashboard, spinners for actions)
- Empty states (no conversations, no items, no agents — each with helpful prompts and suggested actions)
- Keyboard shortcuts (/ to focus Odin, Escape to close panels, n for new to-do, etc.)
- Notification sounds / browser tab badge for pending approvals
- Overall visual consistency pass across all pages
- Timezone-safe date handling in item-detail-panel (use UTC `T00:00:00Z` suffix for due_date fields, normalize date parsing across components)
- Accessibility pass: add `aria-invalid` and `aria-describedby` to Input component when error prop is present

### Task 7.5: End-to-End Integration Tests
**Agent:** 1 agent using `webapp-testing` skill
**Complexity:** Large

Full workflow Playwright tests:
- First-run: open app → see welcome → create space → create agent → start conversation → agent creates to-do → verify on board
- Conversation lifecycle: start → chat → close → start new → verify summary in new context
- Odin routing: type in Odin → Odin opens space conversation → verify navigation happened
- Background delegation: delegate task in conversation → verify status on Home → verify completion notification
- Permission flow: agent hits approval gate → see it on Home attention items → approve → agent continues
- Automation: create automation → manual trigger → verify run history and result
- Board workflow: create item → drag through stages → archive → verify item_events
- CRM workflow: create record → add custom fields → link to-do → switch to table view → verify display
- Search: create content across types → global search → verify results grouped correctly
- Backup: trigger backup → verify file created
- **Memory lifecycle**: create facts → exceed namespace cap → verify lowest-scored archived → verify archived facts still searchable via tools
- **Write-time dedup**: save fact → save contradicting fact → verify temporal supersession (old fact gets valid_until, new fact created)
- **Procedural memory**: correct agent behavior → verify rule saved → open new conversation → verify rule in context and agent follows it
- **Mid-task steering**: delegate background task → send steering message → verify agent receives and adjusts course
- **Summary consolidation**: close 20+ conversations in a space → verify meta-summary auto-generated → verify individual summaries marked as consolidated
- **Cross-space search**: create content in two spaces → search from one space's agent → verify cross-space results respect permissions
- **Space layout**: create space → verify default widgets → add/remove widgets via layout editor → verify space view updates → agent modifies layout via MCP tool → verify rendered correctly

---

## Phase Summary

| Phase | What You Get | Tasks | Max Parallel |
|-------|-------------|-------|-------------|
| 0 | SDK validated, scaffold, schema, reference impl, seed data | 5 | 2 |
| 1 | Full REST API + type generation + SSE contract | 8 | 3 |
| 2 | Session Manager, Odin, streaming, permissions, logging | 10 | 4 |
| 3 | Full frontend — dashboard, board, conversations | 7 | 3-4 |
| 3b | Four-tier memory, write-time dedup, temporal facts, context safety, procedural memory | 6 | 2 |
| 4 | CRM, table view, documents, Drive, search + cross-space FTS5 search | 7 | 4 |
| 4b | Widget-based space layouts, layout editor, agent layout tools | 5 | 2 |
| 5 | Agent Builder, sub-agents, mid-task steering, workflow tracking | 5 | 2-3 |
| 6 | Automations + dashboard + templates | 4 | 2 |
| 7 | Lifecycle management, summary consolidation, backup, edge cases, integration tests | 6 | 3-4 |

**Total: 63 tasks across 10 phases**

---

## Execution Notes

### How to run each task

Each task should be given to an agent with:
1. This task's full description + acceptance criteria
2. The CLAUDE.md file (project conventions)
3. The relevant architecture doc sections (see mapping table below)
4. For frontend tasks: the `frontend-design` skill
5. For test tasks: the `webapp-testing` skill
6. Access to the full codebase (agent reads existing code for patterns)
7. For Phase 1+ tasks: explicit instruction to read Task 0.4's reference implementation first

### Task-to-Documentation Mapping

| Task | Architecture Doc Sections | Capabilities Doc Sections |
|------|--------------------------|--------------------------|
| 0.1 | Technology Decisions | Architecture Principles #7 (Claude Max) |
| 0.2-0.5 | System Overview, Data Model | Core Concepts |
| 1.1-1.3 | Layer 3: Service Layer | Core Concepts (relevant entity) |
| 1.4a-1.4b | Layer 2: API endpoints list | Core Concepts (relevant entity) |
| 1.5 | Layer 2: API, SSE Event Contract | — |
| 2.1 | Layer 6: Context Assembler | Memory and Documents |
| 2.2 | Layer 4: MCP Tools list | — |
| 2.3a | Layer 4: Session Manager (start, send, close) | Agent Interaction |
| 2.3b | Layer 4: Session Manager (delegation, recovery, concurrency) | Background Agent Monitoring |
| 2.4 | Layer 2: SSE endpoint, SSE Event Contract | Response Time Expectations |
| 2.5 | Layer 4b: Odin — The Front Door | Odin — The Front Door |
| 2.6 | Layer 5: Permission Enforcer | Permissions and Security |
| 2.7 | — | — |
| 3.1 | System Overview diagram | Interaction Model |
| 3.2 | — | Home (priority order), First-run experience |
| 3.3 | — | Space View, Items (to-dos + board items) |
| 3.4 | — | Agent Interaction, Agents and Conversations |
| 3.5 | Data Model: agents, agent_permissions | Permissions and Security, Agent Creation |
| 3b.1 | Data Model: memory_entries, behavioral_rules, background_tasks, conversation_summaries | Memory and Documents, Resolved Decisions 19-27 |
| 3b.2 | Context Pruning (Tier 1: Semantic Memory), Flow 7 | Memory and Documents (temporal facts, write-time dedup) |
| 3b.3 | MCP Tools (Memory, Behavioral rule operations) | Memory and Documents (agent-managed memory) |
| 3b.4 | Layer 6: Context Assembler, Context Budget | Memory and Documents (context ordering, scored retrieval) |
| 3b.5 | Layer 4: Session Manager (flush_memory, send_message), Flow 5, Flow 9 | Context management (P0 item 8) |
| 4.1-4.2 | Data Model: items (custom_fields) | Items (Records), Space Layouts (Table view) |
| 4.3-4.4 | Layer 7: Data Layer, Data Model: documents, data_sources | Memory and Documents |
| 4.5a | Layer 7: FTS5, FTS5 Virtual Tables | — |
| 4.5b | Context Pruning (On-Demand Search), MCP Tools (Context operations) | Cross-space search (P1 item 24) |
| 4b.1 | Data Model: space_widgets, Layer 2: Layout endpoints | Space Layouts, Resolved Decision 28 |
| 4b.2 | Layer 1: Frontend (widget renderer) | Space Layouts |
| 4b.3 | — | Space Layouts (layout editor) |
| 4b.4 | MCP Tools (Layout operations) | Space Layouts (agent-designed layouts) |
| 5.1 | — | Agent Creation (Agent Builder) |
| 5.2a | Layer 4: delegate_background, Flow 8 | Agent Interaction (Sub-agents), Background Monitoring |
| 5.2b | Layer 4: Session Manager (steer), Flow 8 | Agent Interaction (Steering mode), Resolved Decision 26 |
| 5.2c | — | Background Agent Monitoring |
| 6.1-6.3 | Data Model: automations, automation_runs | Automations, Proactive System |
| 7.1a | Context Pruning (Tier 1 lifecycle, Tier 4 procedural) | Memory and Documents (lifecycle), Resolved Decision 22 |
| 7.1b | Context Pruning (Tier 2 consolidation) | Memory and Documents (summary consolidation), Resolved Decision 24 |
| 7.2 | Backup Strategy | — |
| 7.3-7.4 | Technology Decisions, Layer 4: crash recovery | — |
| 7.5 | All key flows | All interaction patterns |

### Inter-task coordination

When multiple agents build in parallel:
- They work on different files/directories (no merge conflicts)
- Merge + integration check tasks (1.7, 2.9, 3.7) validate integration
- Phase test tasks validate correctness
- All agents read CLAUDE.md and the Task 0.4 reference implementation for patterns

### Dependency graph

```
Phase 0: 0.1 (spike) || 0.2 (scaffold)
              ↓            ↓
         0.3 (schema, depends on 0.2)
              ↓
         0.4 (reference impl, depends on 0.2 + 0.3)
              ↓  ⚠️ HUMAN REVIEW GATE — approve 0.4 before proceeding
         0.5 (seed data, depends on 0.3 + 0.4)
              ↓
Phase 1: 1.1 || 1.2 || 1.3 (services, all parallel)
              ↓
         1.4a || 1.4b (routes, parallel)
              ↓
         1.5 (types + SSE contract)
              ↓
         1.6 (tests) → 1.7 (merge check)
              ↓
Phase 2: 2.1 || 2.2 || 2.7 (context + tools + logging, parallel)
              ↓
         2.3a (session manager core, depends on 2.1 + 2.2 + spike)
              ↓
         2.3b || 2.4 || 2.5 || 2.6 (all depend on 2.3a, parallel)
              ↓
         2.8 (tests) → 2.9 (merge check)
              ↓
Phase 3: 3.1 (design system + shell)
              ↓
         3.2 || 3.3 || 3.4 || 3.5 (all depend on 3.1, parallel)
              ↓
         3.6 (tests) → 3.7 (merge check)
              ↓
Phase 3b: 3b.1 (schema migration)
              ↓
         3b.2 (memory service + write-time dedup)
              ↓
         3b.3 || 3b.4 (MCP tools || context assembler, parallel)
              ↓
         3b.5 (session manager context safety, depends on 3b.3)
              ↓
         3b.6 (tests)
              ↓
Phases 4, 4b, 5, 6 can overlap:
  Phase 4:  4.1 → 4.2, 4.3 || 4.4 || 4.5a → 4.5b → 4.6
  Phase 4b: 4b.1 → 4b.2 → 4b.3 || 4b.4 → 4b.5
            (depends on Phase 4 completion; can overlap with 5/6)
  Phase 5:  5.1 || 5.2a → 5.2b → 5.2c → 5.3
  Phase 6:  6.1 → 6.2 || 6.3 → 6.4
              ↓
Phase 7: 7.1a || 7.1b || 7.2 || 7.3 (parallel) → 7.4 → 7.5
```

With 6 agents, max parallelism per phase:
- Phase 0: 2 agents (0.1 || 0.2)
- Phase 1: 3 agents (1.1 || 1.2 || 1.3), then 2 (1.4a || 1.4b)
- Phase 2: 3 agents (2.1 || 2.2 || 2.7), then 4 (2.3b || 2.4 || 2.5 || 2.6)
- Phase 3: 4 agents (3.2 || 3.3 || 3.4 || 3.5)
- Phase 3b: 2 agents (3b.3 || 3b.4), rest sequential
- Phases 4+4b+5+6 overlap: up to 6 agents across all four phases
- Phase 7: 4 agents (7.1a || 7.1b || 7.2 || 7.3)
