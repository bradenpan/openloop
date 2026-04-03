# OpenLoop: Architecture Proposal (DRAFT v5)

**Status:** Under review — not yet approved for implementation.
**Companion document:** CAPABILITIES.md (defines what the system does; this document defines how it's built)

---

## System Overview

OpenLoop is a coordination layer between a human, a web UI, and multiple Claude Max sessions. It doesn't do AI work — it manages the plumbing: routing messages, storing state, assembling context, enforcing permissions, and tracking what agents are doing.

**Key terminology change:** "Projects" are now **Spaces** — a broader abstraction that can be a project, a knowledge base, a CRM, or a simple task list. All tracked work is an **item** (task or record) in a single unified model — views (list, kanban, table) are presentation, not data model. **Odin** is the always-visible AI front door at the bottom of the screen (Haiku-powered), replacing the separate command bar.

```
┌─────────────────────────────────────────────────────────┐
│                      Web UI (React)                     │
│  Home Dashboard │ Space Views │ Conversation Panels   │
└────────────┬───────────────────────────┬────────────────┘
             │ SSE (streaming responses) │ HTTP (commands)
             ▼                           ▼
┌─────────────────────────────────────────────────────────┐
│                   FastAPI Backend                        │
│                                                         │
│  ┌──────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │ REST API │  │ SSE Endpoint │  │ Odin Endpoint    │  │
│  │ (CRUD)   │  │ (streaming)  │  │ (Haiku front door)│  │
│  └────┬─────┘  └──────┬───────┘  └────────┬─────────┘  │
│       │               │                    │            │
│  ┌────▼───────────────▼────────────────────▼─────────┐  │
│  │              Service Layer                         │  │
│  │  Spaces│Items│Links│Conversations│Memory│Perms│Odin│  │
│  └────────────────────┬──────────────────────────────┘  │
│                       │                                 │
│  ┌────────────────────▼──────────────────────────────┐  │
│  │           Agent Runner                              │  │
│  │  Thin wrapper around Claude SDK query(). DB is     │  │
│  │  single source of truth (no in-memory state).      │  │
│  └────────────────────┬──────────────────────────────┘  │
│                       │                                 │
│  ┌────────────────────▼──────────────────────────────┐  │
│  │           Permission Enforcer                      │  │
│  │  Intercepts tool calls, checks grant level,        │  │
│  │  holds for approval or denies                      │  │
│  └────────────────────┬──────────────────────────────┘  │
│                       │                                 │
│  ┌────────────────────▼──────────────────────────────┐  │
│  │           Context Assembler                        │  │
│  │  Builds prompt context from four memory tiers,     │  │
│  │  scores by importance/recency/access, manages     │  │
│  │  token budget, orders for attention optimization   │  │
│  └───────────────────────────────────────────────────┘  │
│                                                         │
│  ┌───────────────────────────────────────────────────┐  │
│  │                  Data Layer                        │  │
│  │  SQLite (structured data) │ Local files (artifacts)│  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────┬───────────────────────────────┘
                          │
            Claude Agent SDK (spawns CLI sessions)
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│                Claude Max (Anthropic)                    │
│         The AI. Runs on Anthropic's servers.             │
│         Accessed via Max subscription.                   │
└─────────────────────────────────────────────────────────┘
                          │
            ┌─────────────┼─────────────┐
            ▼             ▼             ▼
      Google Drive    Git Repos     Web/APIs
      (documents)     (code)        (search, email)
```

### How OpenLoop Relates to Claude Code

OpenLoop runs on top of the Claude Agent SDK, which is a programmatic interface to Claude Code. Each `query()` call spawns or resumes a Claude Code CLI process under a Claude Max subscription. The SDK manages conversation history as local JSONL files and handles session resume transparently.

This means every OpenLoop agent is, at the infrastructure level, a Claude Code session. Claude Code already provides file access, bash execution, MCP tool support, and conversation persistence. A reasonable question is: what does OpenLoop add?

**What Claude Code provides (and OpenLoop inherits):**
- LLM reasoning (Claude models via Max subscription)
- File read/write, bash execution, tool use
- Conversation persistence via JSONL session files
- Session resume via `query(resume=session_id)`

**What OpenLoop adds on top:**
- **Multi-agent identity** — Claude Code is one agent in one terminal. OpenLoop runs multiple agents simultaneously, each with a distinct system prompt, tool set, and permission boundary, organized by domain (recruiting, code, health, etc.).
- **Structured context injection** — Claude Code gets CLAUDE.md files and whatever it reads during a conversation. OpenLoop assembles ~8,000 tokens of curated context before every first message: behavioral rules, conversation summaries, scored facts, and live board state — ranked by importance and ordered for maximum model attention.
- **Persistent memory across conversations** — Claude Code's memory is per-project markdown files. OpenLoop has four-tier memory (semantic facts, episodic summaries, procedural rules, working state) with write-time dedup, temporal tracking, scored retrieval, and lifecycle management. An agent on conversation #30 knows decisions from conversation #2.
- **Work tracking** — items (tasks, records), boards, spaces, CRM pipelines. Agents read and write structured data, not just files.
- **Permission enforcement** — every tool call goes through a permission layer with per-agent, per-resource, per-operation grants. Claude Code has its own permission model, but OpenLoop adds domain-specific controls (e.g., "this agent can read Drive files but needs approval to edit them").
- **Orchestration** — background delegation with managed turn loops, mid-task steering, progress tracking, automation scheduling. Claude Code runs one conversation at a time in a terminal. OpenLoop coordinates multiple concurrent agents working autonomously.
- **Resilience** — stale session recovery (if an SDK session expires, retry with fresh context automatically), rate limit retry with exponential backoff, crash recovery, proactive context compression.
- **Web UI** — everything is accessible through a browser instead of a terminal. Streaming responses, real-time updates, cross-space dashboards.

The Agent Runner (`agent_runner.py`) is intentionally thin (~800 lines). It doesn't reimpose lifecycle management or duplicate state the SDK already tracks. Its job is to bridge OpenLoop's conversation model to the SDK's `query()` function: assemble context on first message, pass `resume` on subsequent messages, handle errors, and coordinate background work. The heavy lifting — context assembly, memory management, permission enforcement — happens in the layers around it.

---

## Layer Architecture

### Layer 1: Frontend (React)

The web UI. Displays data, sends user actions, receives streamed responses.

**Technology:** React 19, Tailwind CSS v4, Vite. Same stack as current system.

**Communication with backend:**
- **HTTP REST** — CRUD operations (create task, update space, list conversations, manage permissions). Same pattern as current system.
- **Server-Sent Events (SSE)** — streaming agent responses. When a conversation is active, the frontend opens an SSE connection to receive the agent's response token-by-token. SSE is one-directional (server → client) which is sufficient — user messages are sent via HTTP POST, responses stream back via SSE.

**Key UI surfaces:**
- Home dashboard (cross-space)
- Space view (widget-based layout: kanban, table, task list, conversations, charts, data feeds — configurable per space)
- Conversation panel (chat interface with streaming)
- Agent monitoring (status indicators, expandable logs)
- Settings (agents, permissions, spaces)

**State management:** Zustand for UI state (current space, selected item, panel state). React Query for server state (tasks, conversations, agents). SSE for real-time streaming.

### Layer 2: API (FastAPI)

The REST API and SSE endpoints. Thin layer — validates input, calls services, returns responses.

**Endpoints (grouped by domain):**

```
# Spaces
POST   /api/v1/spaces                      Create space (with template: project, crm, knowledge_base, simple)
GET    /api/v1/spaces                      List spaces
GET    /api/v1/spaces/{id}                 Get space detail + config
PATCH  /api/v1/spaces/{id}                 Update space config

# Space layouts (widget-based, configurable per space)
GET    /api/v1/spaces/{id}/layout          Get ordered list of widgets for space
POST   /api/v1/spaces/{id}/layout/widgets  Add widget to layout
PATCH  /api/v1/spaces/{id}/layout/widgets/{widget_id}  Update widget config/position/size
DELETE /api/v1/spaces/{id}/layout/widgets/{widget_id}  Remove widget from layout
PUT    /api/v1/spaces/{id}/layout          Bulk replace layout (for agent-generated layouts)

# Items (unified — tasks and records)
POST   /api/v1/items                       Create item (lightweight: just title + space_id, or full)
GET    /api/v1/items                       List items (filters: space_id, stage, type, is_done, archived, linked_to, view)
GET    /api/v1/items/{id}                  Get item detail
PATCH  /api/v1/items/{id}                  Update item (is_done toggle triggers stage sync)
POST   /api/v1/items/{id}/move             Move item to stage (triggers is_done sync)
POST   /api/v1/items/{id}/archive          Archive item

# Item links (many-to-many associations between items)
POST   /api/v1/items/{id}/links            Create link to another item
GET    /api/v1/items/{id}/links            List links for an item
DELETE /api/v1/items/{id}/links/{link_id}  Remove link

# Conversations
POST   /api/v1/conversations               Start new conversation (with agent_id, space_id, model override)
GET    /api/v1/conversations               List conversations (filters: space, status, cross-space)
GET    /api/v1/conversations/{id}          Get conversation detail + message history
POST   /api/v1/conversations/{id}/messages Send message (response streams via SSE)
POST   /api/v1/conversations/{id}/close    Close conversation (triggers summary generation)
POST   /api/v1/conversations/{id}/reopen   Reopen closed conversation

# Odin (front door — system-level agent, always Haiku)
POST   /api/v1/odin/message                Send message to Odin, response streams via SSE

# Streaming (single multiplexed endpoint)
GET    /api/v1/events                      SSE endpoint — all events (conversation responses, background
                                           task updates, permission requests, notifications) tagged by
                                           source ID. Frontend demultiplexes.

# Agents
POST   /api/v1/agents                      Create agent
GET    /api/v1/agents                      List agents
GET    /api/v1/agents/{id}                 Get agent detail + permissions
PATCH  /api/v1/agents/{id}                 Update agent config
GET    /api/v1/agents/{id}/status          Get agent running status across all conversations

# Permissions
GET    /api/v1/permissions/pending         List pending approval requests
POST   /api/v1/permissions/{id}/approve    Approve
POST   /api/v1/permissions/{id}/deny       Deny

# Memory
POST   /api/v1/memory                      Create memory entry
GET    /api/v1/memory                      List/search memory entries
PATCH  /api/v1/memory/{id}                 Update entry
DELETE /api/v1/memory/{id}                 Delete entry

# Documents
GET    /api/v1/documents                   List documents (space filter, search)
GET    /api/v1/documents/{id}              Get document metadata
POST   /api/v1/documents                   Index a document (local or Drive link)

# Data sources
POST   /api/v1/data-sources                Register a data source (Drive folder, repo, API integration)
GET    /api/v1/data-sources                List data sources (space filter)
PATCH  /api/v1/data-sources/{id}           Update data source config/status
DELETE /api/v1/data-sources/{id}           Remove data source

# Automations
POST   /api/v1/automations                 Create automation
GET    /api/v1/automations                 List automations (filter: space, enabled, trigger_type)
GET    /api/v1/automations/{id}            Get automation detail + recent runs
PATCH  /api/v1/automations/{id}            Update automation config
DELETE /api/v1/automations/{id}            Delete automation
POST   /api/v1/automations/{id}/run        Trigger automation manually
GET    /api/v1/automations/{id}/runs       List run history

# Home
GET    /api/v1/home/dashboard              Cross-space summary (all open tasks, attention items, active agents)

# Notifications
GET    /api/v1/notifications               List notifications (read/unread filter)
POST   /api/v1/notifications/{id}/read     Mark notification as read

# Background agents
GET    /api/v1/agents/running              List all running/queued agent sessions
```

### Layer 3: Service Layer

Business logic. Stateless functions that operate on the database and coordinate between components. No direct DB access from API routes — everything goes through services.

**Services:**

- **SpaceService** — CRUD, configuration, templates, linked data sources, board enable/disable
- **ItemService** — unified item (task and record) CRUD, is_done toggle with bidirectional stage sync, stage transitions, lightweight creation (title + space_id minimum), custom fields for records, archive, cross-space task listing, default stage assignment for board-enabled spaces
- **ItemLinkService** — create, delete, list associations between items (many-to-many via `item_links` table)
- **ConversationService** — create, list, get history, close (trigger summary), reopen. Manages the mapping between conversations and SDK sessions.
- **OdinService** — system-level agent session management. Routes Odin messages to a persistent Haiku session. Handles routing instructions (open conversation, create task, navigate) and delegates complex requests.
- **DataSourceService** — manage connected data sources per space (Drive folders, repos, API integrations). Config storage, status tracking, refresh scheduling.
- **NotificationService** — create, list, mark read. Stores notifications for background task completion, permission requests, proactive alerts. Feeds the Home dashboard and SSE event stream.
- **AgentRunner** — a thin wrapper around the Claude SDK's `query()` function. No in-memory session state — the DB is the single source of truth for `sdk_session_id`. Functions:
  - `run_interactive(db, conversation_id, message)` → sends a message (handles both first message and continuation). First message assembles context and passes it as `system_prompt` in `ClaudeAgentOptions`; subsequent messages use `resume=sdk_session_id`. Returns an async stream of response chunks.
  - `close_conversation(db, conversation_id)` → triggers summary generation, memory flush, consolidation check, and closes the conversation in the DB
  - `delegate_background(db, agent_id, instruction, ...)` → runs autonomous agent work in a managed turn loop
  - `steer(conversation_id, message)` → mid-task course correction for background tasks
  - `launch_autonomous(db, agent_id, space_id, goal, constraints, token_budget, time_budget)` → goal-driven autonomous run with compaction loop, self-directed task list, approval queue integration
  - `narrow_permissions(parent_agent_id, delegation_depth)` → compute restricted permission set for sub-agents
  - `list_running(db)` → returns all running/queued agent sessions (DB query, not in-memory state)
- **ContextAssembler** — builds the prompt context for a new session:
  - Reads space memory (facts tier)
  - Reads conversation summaries (summary tier)
  - Reads current item state — open tasks, board stages, deadlines (state tier)
  - Ranks by relevance, manages token budget
  - Returns assembled context string for system prompt injection
  - Special mode for Odin: cross-space context (all spaces, all agents, cross-space task summary, attention items)
- **PermissionEnforcer** — checks tool calls against the agent's permission matrix:
  - `check_permission(agent_id, resource, operation)` → Always/Approval/Never
  - For "Approval": creates a pending request, notifies frontend, waits for resolution
  - For in-conversation approvals: routes the approval request to the conversation's SSE stream
  - For out-of-conversation: routes to the notification system
- **MemoryService** — CRUD for facts. Write/read across namespaces. Search. Token-budgeted retrieval.
- **DocumentService** — index local files and Drive files. Metadata storage. Search. Coordinate with Google Drive API.
- **AgentService** — agent CRUD. Configuration management. Permission matrix storage.
- **~~ToolRegistryService~~** — *Deferred. Agent tool configurations live in the `agents` table (`tools` and `mcp_tools` JSON fields). A dedicated registry is not needed for P0/P1.*
- **AutomationService** — CRUD for automation definitions. Runs the cron scheduler (checks every minute for matching automations). Fires matching automations as background tasks. Tracks run history. Event listener for event-based automations (P2).
- **AutomationScheduler** — background loop within the FastAPI process. Every 60 seconds, checks all enabled cron-based automations against the current time. When matched, creates a background task with the automation's agent + instruction. Lightweight — no external dependencies (no Celery, no Redis). On startup, checks for missed runs during downtime and surfaces notifications. Max concurrent automation sessions configurable (default 3). Automations run in their own concurrency lane, independent of interactive sessions (see Lane-Isolated Concurrency).

### Layer 4: Agent Runner (Detail)

This is the most architecturally significant component. It bridges OpenLoop's conversation model with Claude SDK sessions.

```
┌─────────────────────────────────────────────────┐
│                Agent Runner                      │
│                                                 │
│  No in-memory state. sdk_session_id lives on    │
│  the Conversation DB record only. The DB is the │
│  single source of truth for all session state.  │
│                                                 │
│  Operations:                                    │
│  ├── run_interactive(db, conversation_id, msg)  │
│  │   Handles both first message and continuation│
│  │   — no separate start step.                  │
│  │                                              │
│  │   First message (sdk_session_id is null):    │
│  │   1. Load agent config                       │
│  │   2. Assemble context (ContextAssembler)     │
│  │   3. Load tool config from agent record      │
│  │   4. Build MCP tools (builtin OpenLoop tools │
│  │      from agent's mcp_tools config)          │
│  │   5. Register permission hooks               │
│  │   6. Call SDK query(prompt=msg, options=      │
│  │      {system_prompt: context})               │
│  │   7. Store sdk_session_id on conversation    │
│  │      record in DB                            │
│  │                                              │
│  │   Subsequent messages (sdk_session_id set):  │
│  │   1. PROACTIVE BUDGET CHECK (before LLM call)│
│  │      Estimate total context (system prompt + │
│  │      memory + history + pending message).    │
│  │      If >70%:                                │
│  │      a. Run flush_memory() first             │
│  │      b. Compress older turns (observation    │
│  │         masking: keep recent 7 exchanges      │
│  │         verbatim, summarize the rest)         │
│  │      c. Post-compaction verification: check  │
│  │         key facts from compressed section    │
│  │         exist in persistent memory           │
│  │      d. Compress at turn boundaries only —   │
│  │         never split tool-call sequences      │
│  │      Note: this is distinct from the reactive│
│  │      monitor_context_usage() which runs AFTER│
│  │      the response and creates a checkpoint   │
│  │      (not compress). Two-tier enforcement:   │
│  │      proactive = flush + compress before call│
│  │      reactive = flush + checkpoint after call│
│  │   2. Call SDK query(prompt=msg, options=      │
│  │      {resume: sdk_session_id})               │
│  │      Stale-session fallback: if resume fails │
│  │      (SDK session expired/invalid), clear    │
│  │      sdk_session_id, reassemble fresh context│
│  │      + inject conversation summary, retry as │
│  │      first message. User sees seamless       │
│  │      continuation.                           │
│  │   3. Stream response chunks to SSE           │
│  │   4. Process tool calls through Permission   │
│  │      Enforcer                                │
│  │   5. Store message + response in DB          │
│  │                                              │
│  ├── close_conversation(db, conversation_id)    │
│  │   Called directly by the close route.         │
│  │   1. Run flush_memory() — agent saves any    │
│  │      unsaved facts to persistent memory      │
│  │   2. Send "summarize this conversation" msg  │
│  │   3. Store summary as conversation summary   │
│  │   4. Check summary consolidation threshold   │
│  │      (if space has 20+ unconsolidated         │
│  │      summaries, generate meta-summary)        │
│  │   5. Close conversation in DB                │
│  │      (status="closed", closed_at=now)        │
│  │                                              │
│  ├── flush_memory(db, conversation_id)          │
│  │   Mandatory pre-compaction safety step.       │
│  │   1. Inject instruction: "Review this convo  │
│  │      for important facts, decisions, or       │
│  │      preferences not yet saved to memory.     │
│  │      Save them now using your memory tools."  │
│  │   2. Agent calls save_fact() as needed        │
│  │   3. Return — normal flow continues           │
│  │   Called by: close_conversation() and          │
│  │   run_interactive() before compression.        │
│  │                                              │
│  Internal helpers (called by the above):         │
│  │                                              │
│  ├── verify_compaction(compressed_content)       │
│  │   Post-compaction safety check.               │
│  │   Called by: _compress_conversation()          │
│  │   1. Scan compressed content for fact-like    │
│  │      statements (decisions, preferences,      │
│  │      specific values)                         │
│  │   2. Check each against persistent memory     │
│  │   3. If gaps found: log warning, optionally   │
│  │      trigger a targeted save for missed facts │
│  │   Lightweight — not a full re-extraction,     │
│  │   just a spot check for obvious gaps.         │
│  │                                              │
│  ├── steer(conversation_id, message)            │
│  │   Mid-task course correction.                │
│  │   1. Add message to conversation's steering  │
│  │      queue (max 10 pending messages)          │
│  │   2. The managed turn loop (in                │
│  │      delegate_background) checks this queue   │
│  │      between turns. At the next turn          │
│  │      boundary:                                │
│  │      a. Current turn completes normally       │
│  │      b. Steering message used as the next     │
│  │         user message in query(resume=...)     │
│  │      c. Agent processes and adjusts course    │
│  │   Works within SDK's existing query/resume    │
│  │   mechanism — no mid-tool-call injection.     │
│  │   Background steering via message input on    │
│  │   the task monitoring panel.                  │
│  │                                              │
│  ├── delegate_background()                      │
│  │   Managed turn loop — agent works in         │
│  │   discrete turns with steering checkpoints.  │
│  │   Soft budgets replace hard turn cap:        │
│  │   token budget + time budget + GOAL_COMPLETE │
│  │   signal (or TASK_COMPLETE for simple tasks).│
│  │   Existing background tasks still work with  │
│  │   default soft budgets.                      │
│  │                                              │
│  │   1. Create background_task, assemble context│
│  │      call SDK query() with system_prompt     │
│  │   2. Enter turn loop:                        │
│  │      a. query(resume=session_id, message=    │
│  │         steering_queue.pop() or smart        │
│  │         continuation prompt — context-aware  │
│  │         with progress, budget remaining,     │
│  │         completed items, queued approvals)   │
│  │      b. Agent completes one turn of work     │
│  │      c. Log activity, update step progress   │
│  │         (current_step, step_results on task) │
│  │      d. Stream activity to SSE for monitoring│
│  │      e. Check: agent reported completion?    │
│  │         → exit loop                          │
│  │      f. Check: token or time budget exceeded?│
│  │         → exit loop with progress report     │
│  │      g. COMPACTION CYCLE: at 70% context →   │
│  │         extract persistent instructions      │
│  │         (goal, constraints, task list,        │
│  │         permission boundaries) → flush       │
│  │         memory → summarize → verify          │
│  │         persistent instructions survived →   │
│  │         if verification fails: HALT →        │
│  │         if passes: continue with compressed  │
│  │         context (persistent instructions +   │
│  │         summary + recent turns)              │
│  │      h. Check steering queue for user msgs   │
│  │      i. Loop back to (a)                     │
│  │   3. On completion: write results to task,   │
│  │      notify via SSE event                    │
│  │   Agent system prompts include: "Work        │
│  │   incrementally. Complete one meaningful step │
│  │   per turn. Report what you did and what you │
│  │   plan to do next."                          │
│  │                                              │
│  ├── monitor_context_usage()                    │
│  │   Reactive safety net — runs after each      │
│  │   agent response. Distinct from the proactive│
│  │   check in run_interactive() (see below).    │
│  │   Called by: run_interactive() post-response  │
│  │   1. Check context window usage from SDK     │
│  │      session metadata                        │
│  │   2. If usage > 70% of window:               │
│  │      a. Run flush_memory() first              │
│  │      b. Create checkpoint summary             │
│  │         (NOT compress — that's the proactive │
│  │         path's job)                           │
│  │      c. Store as conversation_summary with   │
│  │         is_checkpoint=true                   │
│  │      d. Conversation continues normally —    │
│  │         the CLI handles its own compression  │
│  │      e. But the checkpoint ensures state is  │
│  │         captured in the DB before any CLI    │
│  │         compression degrades quality         │
│  │   3. If usage > 90%: surface a notification  │
│  │      suggesting the user close and start a   │
│  │      new conversation                        │
│  │                                              │
│  └── recover_from_crash(db)                     │
│      Simplified — no in-memory state to clear.  │
│      1. Scan conversations table for            │
│         status='active'                         │
│      2. Mark all as 'interrupted'               │
│      3. Create notification: "N conversations   │
│         were interrupted by a restart"          │
│      4. Mark orphaned background tasks (running/ │
│         queued at crash time) as failed          │
│      5. When user reopens an interrupted convo: │
│         a. Attempt resume=sdk_session_id with   │
│            fresh MCP tools and hooks            │
│         b. If resume fails: start fresh with    │
│            conversation summary + recent msgs   │
│            injected as context                  │
│                                                 │
│  ├── list_running(db)                           │
│  │   DB query replacing old in-memory dict.     │
│  │   Returns active conversations (status=      │
│  │   'active' with sdk_session_id set) plus     │
│  │   running background tasks. Survives server  │
│  │   restarts — no in-memory state to lose.     │
│  │                                              │
│  Concurrency Control (lane-isolated):           │
│  - Per-conversation asyncio lock prevents       │
│    concurrent sends to the same conversation    │
│    (_conversation_locks dict). Cleaned up on    │
│    conversation close.                          │
│  - Interactive lane: cap 5                      │
│  - Autonomous lane: cap 2                       │
│  - Automation lane: cap 3                       │
│  - Sub-agent lane: cap 8                        │
│  - MAX_TOTAL_BACKGROUND: 8 (hard cap across    │
│    all non-interactive lanes)                   │
│  - Lanes are independent — interactive sessions │
│    don't block background work. No yield-to-    │
│    interactive model.                           │
│  - When lane limit hit: 429 with notification   │
│                                                 │
│  Rate Limit Retry:                              │
│  - All SDK query() calls wrapped in             │
│    _query_with_retry() with exponential backoff │
│    (30s, 60s, 120s). Max 3 retries.            │
│  - On rate limit: creates notification, publishes│
│    rate_limited SSE event, then retries.        │
│  - No retry if partial events already streamed.  │
└─────────────────────────────────────────────────┘
```

**MCP Tools available to every agent session:**

These are the tools agents use to interact with OpenLoop's data. Defined as MCP tool closures (same pattern as current orchestrator, but broader):

```
# Item operations (unified — tasks and records)
create_item(title, type, space_id, stage?, description?, due_date?, fields?)
update_item(item_id, fields...)
complete_item(item_id)                                    # convenience: sets is_done=true with stage sync
move_item(item_id, stage)
get_item(item_id)
list_items(space_id?, stage?, type?, is_done?, limit?)

# Item link operations
link_items(source_item_id, target_item_id, link_type?)    # create association between items
unlink_items(link_id)                                      # remove an association
get_linked_items(item_id, link_type?)                      # get all items linked to this item (queries both source and target — links are effectively undirected)

# Item lifecycle
archive_item(item_id)                                      # archive item (hidden from active views, still searchable)

# Memory operations
save_fact(content, importance?, category?)             # write-time dedup: compares against existing, decides ADD/UPDATE/DELETE/NOOP
update_fact(fact_id, new_content)                      # explicit update of existing fact
recall_facts(query?, namespace?, category?, date_range?) # scored retrieval (importance x decay x access)
delete_fact(fact_id, reason)                            # marks as superseded with valid_until timestamp

# Behavioral rule operations
save_rule(rule, source_type?, source_context?)           # creates procedural memory entry with confidence 0.5; source_type: "correction" | "validation"
confirm_rule(rule_id)                                    # increases confidence by +0.1 (capped at 1.0) — agent calls when user confirms a rule was correct
override_rule(rule_id)                                   # decreases confidence by -0.2 (asymmetric) — agent calls when user overrides a rule
list_rules(agent_id?)                                  # returns active rules for the agent

# Document operations
read_document(document_id)
list_documents(space_id?, search?)
create_document(title, content, space_id, tags?)

# Context operations
get_board_state(space_id)
get_task_list(space_id?, is_done?)
get_conversation_summaries(space_id, limit?)
search_conversations(query?, space_id?, date_range?, agent_id?)  # space_id optional — omit for cross-space search
search_summaries(query, space_id?)                               # FTS5 search on summary content, cross-space capable
get_conversation_messages(conversation_id, limit?)

# Layout operations (for agent-designed spaces)
get_space_layout(space_id)                                    # returns ordered widget list with configs
add_widget(space_id, widget_type, position?, size?, config?)  # adds widget to space layout
update_widget(widget_id, size?, config?, position?)           # modifies existing widget
remove_widget(widget_id)                                      # removes widget from layout
set_space_layout(space_id, widgets)                           # bulk replace — for full redesigns

# Agent operations (for sub-agent delegation, P1)
delegate_task(agent_name, instruction, space_id)
```

Plus the standard Claude Code tools the agent already has: Read, Write, Edit, Glob, Grep, WebSearch, WebFetch, Bash (subject to permissions).

**Odin-specific MCP tools** (in addition to the standard set above):

```
# Odin routing and system-level operations
list_spaces()
list_agents(space_id?)
open_conversation(space_id, agent_id, initial_message?, model?)
navigate_to_space(space_id)
get_attention_items()
get_cross_space_tasks(is_done?)
```

These tools are only available to Odin's session, not to space agents.

### Layer 4b: Odin — The Front Door (Detail)

Odin is a system-level agent that runs on Haiku. It is always visible at the bottom of the screen and serves as the universal entry point.

```
┌──────────────────────────────────────────────────┐
│                     Odin                          │
│                                                  │
│  Model: Haiku (fast, cheap)                      │
│  Scope: cross-space (no single space binding)    │
│  Session: persistent conversation record          │
│           (space_id=null in conversations table)  │
│                                                  │
│  Conversation Flow:                              │
│  1. On app load: resume existing Odin            │
│     conversation (or create one if none exists)  │
│  2. Each user message → query(resume=session_id) │
│  3. Odin handles simple actions directly via     │
│     MCP tools (create_item, list_spaces, etc.)   │
│  4. For complex requests: Odin calls             │
│     open_conversation() to route user to a       │
│     space agent. Frontend receives routing       │
│     action via SSE → navigates to space.         │
│  5. Odin's chat collapses to input-only when     │
│     user is in a space conversation.             │
│  6. Periodically (or when context is heavy):     │
│     close Odin session with summary, start fresh.│
│     Same auto-checkpoint rules as other convos.  │
│                                                  │
│  Context Assembly (special mode):                │
│  - List of all spaces (names, templates, desc)   │
│  - List of all agents (names, spaces, status)    │
│  - Cross-space task summary (open count by        │
│    space, overdue items)                         │
│  - Attention items summary                       │
│  - Odin's own prior conversation summaries       │
│  - Global memory facts                           │
│  Budget: ~4000 tokens (lighter than space agents │
│  because Odin routes, doesn't do deep work)      │
│                                                  │
│  Routing Flow:                                   │
│  User: "Help me plan the recruiting pipeline"    │
│  1. Odin determines this needs Recruiting Agent  │
│     in Recruiting space                          │
│  2. Odin calls open_conversation(                │
│       space_id="recruiting",                     │
│       agent_id="recruiting-agent",               │
│       initial_message="Help me plan the          │
│         recruiting pipeline"                     │
│     )                                            │
│  3. Backend creates conversation record           │
│     (no SDK session yet — that starts on first   │
│     message via AgentRunner.run_interactive())    │
│  4. Odin responds: "Opening a conversation with  │
│     your Recruiting Agent..."                    │
│  5. SSE event to frontend:                       │
│     { type: "route", space_id, conversation_id } │
│  6. Frontend navigates to Recruiting space,      │
│     opens the new conversation panel             │
│  7. Initial message forwarded as first user      │
│     message → run_interactive() assembles        │
│     context and starts SDK session               │
│  8. Odin's chat collapses to input-only          │
│                                                  │
│  Memory:                                         │
│  - Odin has its own memory namespace ("odin")    │
│  - Learns user preferences: "When I say          │
│    'recruiting', I mean the Recruiting space"    │
│  - Conversation summaries persist across         │
│    Odin session restarts                         │
│                                                  │
│  Error Handling:                                 │
│  - Ambiguous request: Odin asks clarifying       │
│    questions ("Which space is this for?")        │
│  - No matching agent: Odin suggests creating one │
│    ("You don't have a health agent yet. Want me  │
│    to help set one up?" → routes to Agent        │
│    Builder when available)                       │
│  - Can't handle request: Odin explains and       │
│    suggests alternatives                         │
└──────────────────────────────────────────────────┘
```

### Layer 5: Permission Enforcer (Detail)

```
┌──────────────────────────────────────────────┐
│             Permission Enforcer               │
│                                              │
│  Permission Matrix (per agent):              │
│  ┌────────────────────────────────────────┐  │
│  │ Resource        │ R │ C │ E │ D │ X   │  │
│  │─────────────────┼───┼───┼───┼───┼─────│  │
│  │ /recruiting/*   │ A │ A │ P │ N │ -   │  │
│  │ /openloop-repo  │ A │ A │ A │ N │ P   │  │
│  │ gmail           │ A │ A │ - │ N │ P   │  │
│  │ web             │ A │ - │ - │ - │ A   │  │
│  │ (default)       │ N │ N │ N │ N │ N   │  │
│  └────────────────────────────────────────┘  │
│  A=Always, P=approval required, N=Never      │
│                                              │
│  Flow:                                       │
│  1. SDK hook intercepts tool call            │
│  2. Map tool call to (resource, operation)   │
│  3. Look up grant level in matrix            │
│  4. If Always → allow immediately            │
│  5. If Never → deny immediately              │
│  6. If Approval:                             │
│     a. Create PendingApproval record in DB   │
│     b. If conversation is active (user is    │
│        watching): push approval request      │
│        inline via SSE                        │
│     c. If background: push to notification   │
│        system (Home dashboard)               │
│     d. Poll DB for resolution (2s interval)  │
│     e. NO timeout. Agent pauses until the     │
│        user approves or denies. Request       │
│        sits in Attention Items on Home        │
│        dashboard indefinitely. The agent      │
│        session remains in "running" state     │
│        but is blocked — does not consume      │
│        active processing, just holds the      │
│        session slot.                          │
│                                              │
│  System guardrails (non-overridable):        │
│  - Block: .env, credentials.json, ~/.ssh,    │
│    ~/.aws, ~/.claude, openloop.db,           │
│    agent config files                        │
│  - Block: self-permission-escalation         │
│  - Block: modifying other agents             │
└──────────────────────────────────────────────┘
```

**Tool-to-resource mapping examples:**

| Tool Call | Resource | Operation |
|-----------|----------|-----------|
| `Read("C:/dev/recruiting/candidates.md")` | `/recruiting/*` | Read |
| `Write("C:/dev/recruiting/notes/sarah.md", ...)` | `/recruiting/*` | Create |
| `Edit("C:/dev/recruiting/tracker.csv", ...)` | `/recruiting/*` | Edit |
| `Bash("git push")` | `/openloop-repo` | Execute |
| `mcp__gmail__send_email(...)` | `gmail` | Execute |
| `WebSearch("competitor analysis")` | `web` | Execute |
| `mcp__openloop__create_item(...)` | `openloop-board` | Create |

### Layer 6: Context Assembler (Detail)

Builds the system prompt context injected into new sessions. Manages token budgets so context doesn't overwhelm the conversation. **Content is ordered to exploit the U-shaped attention curve** — models attend strongly to the beginning and end of context, poorly to the middle (Liu et al., "Lost in the Middle", confirmed architecturally by MIT/Google). High-priority content (identity, rules, tools) goes at the beginning; immediately relevant content (board state) goes at the end closest to the user's message; reference material (facts, summaries) goes in the middle.

```
┌───────────────────────────────────────────────┐
│             Context Assembler                  │
│                                               │
│  Input: space_id, agent_id, conversation_id   │
│  Output: assembled context string             │
│                                               │
│  Assembly order (attention-optimized):        │
│                                               │
│  ┌─ BEGINNING (high model attention) ────────┐│
│  │                                           ││
│  │  1. Agent identity + role prompt (always)  ││
│  │     "You are the Recruiting Agent..."      ││
│  │     Budget: up to 1500 tokens              ││
│  │                                           ││
│  │  2. Procedural memory (behavioral rules)   ││
│  │     Active rules for this agent, ranked    ││
│  │     by confidence score. Injected as part  ││
│  │     of the system prompt — highest priority.││
│  │     "Always check CRM before drafting      ││
│  │     follow-up emails." (confidence: 0.9)   ││
│  │     Budget: up to 500 tokens               ││
│  │                                           ││
│  │  3. Available tools documentation          ││
│  │     MCP tools the agent can use            ││
│  │     Budget: up to 1000 tokens              ││
│  │                                           ││
│  └───────────────────────────────────────────┘│
│                                               │
│  ┌─ MIDDLE (lower model attention) ──────────┐│
│  │                                           ││
│  │  4. Conversation summaries                 ││
│  │     Meta-summary first (if exists), then   ││
│  │     most recent unconsolidated summaries.  ││
│  │     Budget: up to 2000 tokens              ││
│  │                                           ││
│  │  5. Space facts (scored retrieval)         ││
│  │     Active facts in space namespace,       ││
│  │     ranked by:                             ││
│  │       score = importance                   ││
│  │             × e^(-λ × days_since_access)   ││
│  │             × (1 + access_count × 0.2)     ││
│  │     where λ = 0.16 × (1 - importance×0.8) ││
│  │     Higher importance = slower decay.       ││
│  │     Budget: up to 1000 tokens              ││
│  │                                           ││
│  │  6. Global facts (scored retrieval)        ││
│  │     System-wide knowledge entries,         ││
│  │     same scoring formula.                  ││
│  │     Budget: up to 500 tokens               ││
│  │                                           ││
│  └───────────────────────────────────────────┘│
│                                               │
│  ┌─ END (high model attention) ──────────────┐│
│  │                                           ││
│  │  7. Item state (fresh from DB)              ││
│  │     Open tasks, board items by stage,      ││
│  │     upcoming deadlines, recent changes.    ││
│  │     Closest to user's message for maximum  ││
│  │     relevance.                             ││
│  │     Budget: up to 1500 tokens              ││
│  │                                           ││
│  └───────────────────────────────────────────┘│
│                                               │
│  Total budget: ~8000 tokens                   │
│  (leaves room for user message + response)    │
│                                               │
│  Scoring fields on memory_entries:            │
│  - importance (float, 0.0-1.0, default 0.5)  │
│  - access_count (int, incremented on retrieval)│
│  - last_accessed (datetime, updated on use)   │
│  Updated automatically during assembly.       │
│                                               │
│  Overflow handling: within each tier, lowest- │
│  scored entries are dropped first. Never      │
│  truncate agent identity, procedural rules,   │
│  or tool documentation.                       │
└───────────────────────────────────────────────┘
```

### Layer 7: Data Layer

**SQLite database** — structured data (items, spaces, conversations, agents, memory, permissions).

**SQLite FTS5 virtual tables** (P1) — full-text search indexes shadowing conversation_messages, conversation_summaries, memory_entries, and documents tables. Kept in sync via SQLite triggers. Enables the `search_conversations` MCP tool and global search. Not required for P0 launch.

**Local filesystem** — agent-generated artifacts, verbose logs.

**Google Drive** (P1) — primary document storage. Accessed via Google Drive API. Indexed in SQLite for search.

---

## Data Model

Fresh schema. No migration from current system.

### Core Tables

```
spaces
├── id (UUID, PK)
├── parent_space_id (FK → spaces, nullable — for future subspaces)
├── name (unique)
├── description
├── template ("project" | "crm" | "knowledge_base" | "simple")
├── board_enabled (boolean, default true)
├── default_view ("list" | "board" | "table" | null)
├── board_columns (JSON array, default: ["idea","scoping","todo","in_progress","done"])
├── created_at
└── updated_at

space_widgets (configurable layout — each row is one widget in a space's view)
├── id (UUID, PK)
├── space_id (FK → spaces, indexed)
├── widget_type (string — "todo_panel" | "kanban_board" | "data_table" | "conversations" |
│                          "chart" | "stat_card" | "markdown" | "data_feed")
├── position (integer — ordering within layout, 0-indexed)
├── size (string — "small" | "medium" | "large" | "full")
├── config (JSON — widget-specific: columns for kanban, data source ref for charts, field list for tables, etc.)
├── created_at
└── updated_at

items (unified — tasks and records)
├── id (UUID, PK)
├── space_id (FK → spaces, indexed)
├── item_type ("task" | "record")
├── is_agent_task (boolean, default false)
├── title
├── description
├── is_done (boolean, default false — canonical completion flag, syncs bidirectionally with stage for tasks only; records ignore sync)
├── stage (string, nullable — must be in space's board_columns when set; null for simple spaces)
├── priority (integer, nullable)
├── sort_position (float)
├── custom_fields (JSON, for records)
├── parent_item_id (FK → items, nullable — structural hierarchy: sub-tasks, sub-records)
├── assigned_agent_id (FK → agents, nullable)
├── due_date (datetime, nullable)
├── created_by (string — "user" | "agent:{name}" | "odin")
├── source_conversation_id (FK → conversations, nullable — which conversation created this)
├── archived (boolean, default false)
├── created_at
└── updated_at

item_links (many-to-many associations between items — links are effectively undirected)
├── id (UUID, PK)
├── source_item_id (FK → items, indexed)
├── target_item_id (FK → items, indexed)
├── link_type (string — "related_to", extensible)
├── created_at
└── UNIQUE(source_item_id, target_item_id, link_type)

item_events (activity tracking for stale detection and audit)
├── id (UUID, PK)
├── item_id (FK → items, indexed)
├── event_type (string — "created" | "stage_changed" | "assigned" | "updated" | "archived")
├── old_value (string, nullable)
├── new_value (string, nullable)
├── triggered_by (string — "user" | "agent:{name}" | "odin")
├── created_at

agents
├── id (UUID, PK)
├── name (unique)
├── description
├── system_prompt (text)
├── default_model (string, default "sonnet")
├── skill_path (string, nullable — path to agent skill file for Agent Builder-created agents)
├── tools (JSON array — which Claude tools are enabled)
├── mcp_tools (JSON array — which OpenLoop MCP tools are enabled)
├── max_spawn_depth (integer, default 1 — how deep sub-agent delegation can go; 1 = no nesting)
├── heartbeat_enabled (boolean, default false — whether this agent runs periodic check-ins)
├── heartbeat_cron (string, nullable — cron expression for heartbeat schedule, e.g., "*/30 * * * *")
├── status ("active" | "inactive")
├── created_at
└── updated_at

agent_spaces (join table — which spaces an agent can access)
├── agent_id (FK → agents)
├── space_id (FK → spaces)
└── PRIMARY KEY (agent_id, space_id)

agent_permissions (granular permission matrix — replaces JSON blob)
├── id (UUID, PK)
├── agent_id (FK → agents, indexed)
├── resource_pattern (string — e.g., "/recruiting/*", "gmail", "web")
├── operation (string — "read" | "create" | "edit" | "delete" | "execute")
├── grant_level (string — "always" | "approval" | "never")

data_sources (connected data per space)
├── id (UUID, PK)
├── space_id (FK → spaces, indexed)
├── source_type ("drive_folder" | "git_repo" | "api_integration" | "local_folder")
├── name (string)
├── config (JSON — folder ID, repo path, API endpoint, credentials reference, etc.)
├── refresh_schedule (string, nullable — cron expression for API integrations)
├── status ("active" | "inactive" | "needs_configuration")
├── created_at
└── updated_at

conversations
├── id (UUID, PK)
├── space_id (FK → spaces, indexed, nullable — null for system-level/Odin conversations)
├── agent_id (FK → agents)
├── name (string)
├── status ("active" | "closed" | "interrupted")
├── model_override (string, nullable — overrides agent's default_model for this conversation)
├── sdk_session_id (string, nullable — for SDK resume)
├── created_at
├── updated_at
└── closed_at (nullable)

conversation_messages
├── id (UUID, PK)
├── conversation_id (FK → conversations, indexed)
├── role ("user" | "assistant" | "tool")
├── content (text)
├── tool_calls (JSON, nullable)
├── input_tokens (integer, nullable — extracted from SDK response metadata)
├── output_tokens (integer, nullable — extracted from SDK response metadata)
├── created_at

conversation_summaries
├── id (UUID, PK)
├── conversation_id (FK → conversations, indexed)
├── space_id (FK → spaces, indexed, nullable)
├── summary (text)
├── decisions (JSON array)
├── open_questions (JSON array)
├── is_checkpoint (boolean, default false)
├── is_meta_summary (boolean, default false — true for consolidated meta-summaries)
├── consolidated_into (FK → conversation_summaries, nullable — points to meta-summary that absorbed this entry)
├── created_at

memory_entries
├── id (UUID, PK)
├── namespace (string — "global", "space:{name}", "agent:{name}")
├── key (string)
├── value (text)
├── tags (JSON array)
├── category (string, nullable — for filtering, e.g., "architecture", "preference", "contact")
├── importance (float, default 0.5 — 0.0 to 1.0, set by agent on save)
├── access_count (integer, default 0 — incremented each time retrieved during context assembly)
├── last_accessed (datetime, nullable — updated each time retrieved during context assembly)
├── valid_from (datetime, default created_at — when this fact became true)
├── valid_until (datetime, nullable — null means "still true"; set when superseded)
├── archived_at (datetime, nullable — null means active; set when evicted by cap or auto-archival)
├── source (string — "user" | "agent:{name}" | "odin" | "system")
├── created_at
└── updated_at
└── UNIQUE(namespace, key)

documents
├── id (UUID, PK)
├── space_id (FK → spaces, indexed)
├── title
├── source ("local" | "drive")
├── local_path (string, nullable)
├── drive_file_id (string, nullable)
├── drive_folder_id (string, nullable)
├── tags (JSON array)
├── indexed_at
├── created_at
└── updated_at

document_items (join table — documents linked to board items)
├── document_id (FK → documents)
├── item_id (FK → items)
└── PRIMARY KEY (document_id, item_id)

permission_requests
├── id (UUID, PK)
├── agent_id (FK → agents)
├── conversation_id (FK → conversations, nullable)
├── tool_name (string)
├── resource (string)
├── operation (string)
├── tool_input (JSON)
├── status ("pending" | "approved" | "denied")
├── resolved_by ("user" | "system")
├── created_at
└── resolved_at (nullable)

notifications
├── id (UUID, PK)
├── type (string — "task_complete" | "approval_needed" | "proactive_alert" | "agent_error")
├── title (string)
├── body (text, nullable)
├── space_id (FK → spaces, nullable)
├── conversation_id (FK → conversations, nullable)
├── is_read (boolean, default false)
├── created_at

automations
├── id (UUID, PK)
├── name (string — user-visible, e.g., "Morning Briefing")
├── description
├── space_id (FK → spaces, nullable — null for cross-space automations)
├── agent_id (FK → agents)
├── instruction (text — what the agent should do)
├── trigger_type ("cron" | "event" | "manual")
├── cron_expression (string, nullable — e.g., "0 7 * * *")
├── event_source (string, nullable — e.g., "calendar:new_event")
├── event_filter (JSON, nullable — conditions for event triggers)
├── model_override (string, nullable)
├── enabled (boolean, default true)
├── last_run_at (datetime, nullable)
├── last_run_status (string, nullable — "success" | "failed" | "running")
├── created_at
└── updated_at

automation_runs
├── id (UUID, PK)
├── automation_id (FK → automations, indexed)
├── background_task_id (FK → background_tasks, nullable)
├── status ("running" | "completed" | "failed" | "skipped")
├── result_summary (text, nullable)
├── error (text, nullable)
├── started_at
└── completed_at (nullable)

background_tasks
├── id (UUID, PK)
├── conversation_id (FK → conversations, nullable)
├── automation_id (FK → automations, nullable — set if triggered by automation)
├── agent_id (FK → agents)
├── space_id (FK → spaces, nullable — null for cross-space automations)
├── item_id (FK → items, nullable)
├── parent_task_id (FK → background_tasks, nullable — for sub-task hierarchies)
├── instruction (text)
├── goal (text, nullable — original goal text and success criteria for autonomous runs)
├── task_list (JSON, nullable — agent-managed work queue: [{id, title, status, notes}])
├── task_list_version (integer, default 0 — incremented on each modification, for UI diffing)
├── completed_count (integer, default 0 — completed items in task_list, for progress display)
├── total_count (integer, default 0 — total items in task_list, for progress display)
├── queued_approvals_count (integer, default 0 — actions waiting for user approval)
├── run_type ("task" | "autonomous" | "heartbeat", default "task")
├── time_budget (integer, nullable — maximum wall-clock seconds for this run)
├── token_budget (integer, nullable — maximum total tokens for this run)
├── run_summary (text, nullable — generated summary of what the run accomplished)
├── status ("queued" | "running" | "completed" | "failed" | "cancelled")
├── current_step (integer, nullable — for multi-step tracking)
├── total_steps (integer, nullable)
├── step_results (JSON array, nullable — [{step, status, summary}] for completed steps)
├── result_summary (text, nullable)
├── started_at
├── completed_at (nullable)
└── error (text, nullable)

behavioral_rules (procedural memory — learned from corrections and validated approaches)
├── id (UUID, PK)
├── agent_id (FK → agents, indexed)
├── rule (text — the behavioral instruction, e.g., "Always check CRM before drafting follow-ups")
├── source_type (string — "correction" | "validation" — whether this came from fixing a mistake or confirming a good approach)
├── source (string — "agent_inferred" | "user_confirmed" | "system", default "agent_inferred")
├── source_conversation_id (FK → conversations, nullable — where this rule was learned)
├── confidence (float, default 0.5 — asymmetric updates: +0.1 on confirmation, -0.2 on override)
├── apply_count (integer, default 0 — how many times injected into context)
├── last_applied (datetime, nullable — last time injected into a session)
├── is_active (boolean, default true — false when demoted due to low confidence/usage)
├── created_at
└── updated_at

audit_log (tool call audit trail for autonomous/background runs)
├── id (UUID, PK)
├── agent_id (FK → agents, indexed)
├── conversation_id (FK → conversations, indexed)
├── background_task_id (FK → background_tasks, nullable, indexed)
├── tool_name (string)
├── action (string)
├── resource_id (string, nullable)
├── input_summary (text)
├── timestamp (datetime)

approval_queue (actions queued by autonomous agents pending user sign-off)
├── id (UUID, PK)
├── background_task_id (FK → background_tasks, indexed)
├── agent_id (FK → agents, indexed)
├── action_type (string)
├── action_detail (JSON)
├── reason (text)
├── status ("pending" | "approved" | "denied" | "expired")
├── resolved_at (datetime, nullable)
├── resolved_by (string, nullable)
├── created_at

system_state (global key-value store for system-wide flags and configuration)
├── key (string, PK)
├── value (JSON)
├── updated_at

```

### FTS5 Virtual Tables (P1)

Full-text search indexes for agent search tools. Kept in sync via SQLite triggers on INSERT/UPDATE/DELETE of the shadowed tables.

```
memory_entries_fts    — shadows memory_entries.value (only active, non-archived entries)
messages_fts          — shadows conversation_messages.content
summaries_fts         — shadows conversation_summaries.summary
documents_fts         — shadows documents.title (extend to content when document indexing is built)
```

### Relationships

```
Space ──1:N──> SpaceWidgets (configurable layout)
Space ──1:N──> Items (tasks and records)
Space ──1:N──> Conversations
Space ──1:N──> Documents
Space ──1:N──> Data Sources
Space ──1:N──> Conversation Summaries
Space ──0:1──> Space (parent, for future subspaces)

Item ──N:1──> Space
Item ──N:1──> Agent (assigned, nullable)
Item ──N:1──> Item (parent_item_id — structural hierarchy: sub-tasks, sub-records)
Item ──N:N──> Item (via item_links — associative: "related_to", etc.)
Item ──1:N──> Item Events

Conversation ──N:1──> Space (nullable for system-level)
Conversation ──N:1──> Agent
Conversation ──1:N──> Messages
Conversation ──1:N──> Summaries (final + checkpoints)

Agent ──N:N──> Spaces (via agent_spaces)
Agent ──1:N──> Agent Permissions
Agent ──1:N──> Conversations
Agent ──1:N──> Background Tasks
Agent ──1:N──> Behavioral Rules
Document ──N:1──> Space
Document ──N:N──> Items (via document_items)

Automation ──N:1──> Space (nullable for cross-space)
Automation ──N:1──> Agent
Automation ──1:N──> Automation Runs
Automation Run ──N:1──> Background Task (nullable)

Background Task ──N:1──> Background Task (parent, nullable — for sub-task hierarchies)

Behavioral Rule ──N:1──> Agent
Behavioral Rule ──N:1──> Conversation (source, nullable)

Conversation Summary ──N:1──> Conversation Summary (consolidated_into, nullable)

Audit Log ──N:1──> Agent
Audit Log ──N:1──> Conversation
Audit Log ──N:1──> Background Task (nullable)

Approval Queue ──N:1──> Background Task
Approval Queue ──N:1──> Agent

System State: standalone key-value store (kill switch flag, global config)

Memory Entry: standalone, keyed by (namespace, key). Temporal: valid_from/valid_until track when facts were true.
Notification: standalone, optionally linked to space/conversation
```

---

## Key Flows

### Flow 1: Interactive Conversation

```
User opens conversation panel for "Recruiting Agent" in "Recruiting" space
  │
  ▼
Frontend: POST /api/v1/conversations
  { space_id, agent_id, name: "Candidate review" }
  │
  ▼
Backend: ConversationService.create()
  → Creates conversation record in DB (no SDK call yet)
  → Returns conversation_id
  │
  ▼
Frontend: Connected to multiplexed SSE endpoint GET /api/v1/events (demuxes by conversation_id)
  │
  ▼
User types: "What candidates need follow-up this week?"
  │
  ▼
Frontend: POST /api/v1/conversations/{id}/messages
  { content: "What candidates need follow-up this week?" }
  │
  ▼
Backend: AgentRunner.run_interactive()
  → First message: assembles context (ContextAssembler.build), builds MCP tools,
    registers permission hooks, calls query(prompt=message, options={system_prompt: context})
    → SDK creates session, stores sdk_session_id on conversation record
  → Subsequent messages: calls query(prompt=message, options={resume: sdk_session_id})
    → If resume fails (SDK session expired/invalid):
      a. Clear stale sdk_session_id
      b. Reassemble fresh context + inject conversation summary
      c. Retry as first message (user sees seamless continuation)
  → Streams response chunks to SSE endpoint
  → Agent may call MCP tools:
    → list_items(space_id, type="record") → PermissionEnforcer: Read on board → Always → allow
    → Agent sees records, formulates response
  → Store user message + agent response in conversation_messages
  │
  ▼
Frontend: renders streamed response in chat panel
```

### Flow 2: Background Delegation

```
During a conversation, user says: "Go research Sarah Chen's company background"
  │
  ▼
Agent decides to delegate (or user explicitly triggers via "delegate this")
  │
  ▼
Backend: AgentRunner.delegate_background()
  → Concurrency check (max 2 background sessions)
  → Creates background_task record (status="running")
  → Creates a dedicated conversation record for the task
     (name="Background: {instruction[:50]}", linked to background_task)
  → Fires managed turn loop as asyncio task (fire-and-forget)
  │
  ▼
Managed Turn Loop (_run_background_task):
  → Assembles context via ContextAssembler
  → Turn 1: sends task instruction with system prompt including
    "Work incrementally. Complete one meaningful step per turn.
     Report what you did. Say TASK_COMPLETE when finished."
  → Each subsequent turn (up to MAX_TURNS=20):
    a. Check steering queue for user corrections
    b. If steering message found → use it as next prompt
    c. If empty → send CONTINUATION_PROMPT ("Continue working...")
    d. Agent completes one turn of work
    e. Update step progress (current_step, step_results on task)
    f. Publish background_progress SSE event for monitoring
    g. Check for TASK_COMPLETE signal in response → exit loop
  │
  ▼
Frontend: Home dashboard shows "Research Agent working on 'Company background for Sarah Chen' — 2m elapsed"
  Click to expand → SSE stream of agent activity log
  │
  ▼
Agent signals TASK_COMPLETE (or MAX_TURNS reached):
  → Writes results to document (create_document MCP tool)
  → Updates item if applicable (update_item MCP tool)
  → Writes to memory if applicable
  → background_task.status = "completed", result_summary stored
  → Notification created
  → Background tracking cleaned up (_background_conversations, _steering_queues)
  │
  ▼
Frontend: notification "Background task complete: Company background for Sarah Chen"
  Results visible in space documents and/or on the item
```

### Flow 3: Permission Approval (In-Conversation)

```
Agent in active conversation tries to edit a Google Drive document
  │
  ▼
SDK hook intercepts Edit tool call
  → PermissionEnforcer.check(agent_id, "recruiting-drive", "edit")
  → Grant level = "Approval"
  │
  ▼
Create PendingApproval record in DB
  → Conversation is active (user is watching)
  → Push approval request inline via SSE:
    { type: "approval_request", id: "...", tool: "Edit", resource: "recruiting-drive/tracker.csv", operation: "edit" }
  │
  ▼
Frontend: renders inline in conversation:
  "Agent wants to edit recruiting-drive/tracker.csv. [Approve] [Deny]"
  │
  ▼
User clicks Approve → POST /api/v1/permissions/{id}/approve
  → PermissionEnforcer unblocks the hook
  → Agent continues with the edit
```

### Flow 4: Permission Approval (Background)

```
Background agent tries to send an email
  │
  ▼
SDK hook intercepts gmail_send tool call
  → PermissionEnforcer.check(agent_id, "gmail", "execute")
  → Grant level = "Approval"
  │
  ▼
Create PendingApproval record in DB
  → No active conversation (background task)
  → Push to notification system:
    Home dashboard shows: "Email Agent wants to send email to john@example.com [Approve] [Deny]"
  │
  ▼
User navigates to Home, approves
  → Agent continues with the send
  │
  ▼
(No timeout — agent waits indefinitely. Request visible in Home Attention Items until resolved.)
```

### Flow 5: Conversation Close and Context Transfer

```
User clicks "Close conversation" on a long-running thread
  │
  ▼
Frontend: POST /api/v1/conversations/{id}/close
  │
  ▼
Backend: AgentRunner.close_conversation()
  → flush_memory(): "Save any important unsaved facts to memory now"
  → Agent calls save_fact() as needed (write-time dedup runs on each)
  → Sends final message: "Summarize this conversation: key decisions, outcomes, open questions"
  → Agent responds with summary
  → Store summary in conversation_summaries table (via conversation_service.add_summary())
  → Check consolidation threshold: if space has 20+ unconsolidated summaries,
    generate meta-summary and mark individual summaries as consolidated
  → conversation.status = "closed", conversation.closed_at = now()
  → Clean up per-conversation lock (_conversation_locks.pop)
  │
  ▼
Later: User starts new conversation with same agent in same space
  │
  ▼
Backend: AgentRunner.run_interactive() (first message in new conversation)
  → ContextAssembler.build()
    → Loads conversation summaries (including the one just created)
    → New agent sees: "Previous conversation (March 28): discussed X, decided Y, open question Z"
    → Does NOT load the full message history of the closed conversation
  │
  ▼
New agent has full context of what happened before, without the raw history bloating the context window
```

### Flow 6: Agent Creation via Agent Builder

```
User tells Odin: "I need an agent for managing my recruiting pipeline"
  │
  ▼
Odin (via conversation): recognizes agent creation request
  → Starts conversation with Agent Builder agent
  │
  ▼
Agent Builder engages in requirements gathering:
  "What space will this agent work with?"
  "What data sources does it need access to? (repos, Drive folders, APIs)"
  "What should it be able to do? (read candidates, draft emails, update records)"
  "What should it NOT be able to do?"
  "Should it need your approval for any specific actions?"
  │
  ▼
User answers questions interactively
  │
  ▼
Agent Builder produces agent configuration:
  → Calls MCP tool: create_agent(name, description, system_prompt, tools, permissions, space_ids)
  → Agent registered in DB
  → "I've created the Recruiting Agent. It can read and create files in your recruiting Drive folder,
     but will ask permission before editing. It has access to Gmail for drafting emails (sending requires
     your approval). Want to adjust anything?"
  │
  ▼
User can refine, or accept
  Agent appears in space's agent list, ready to start conversations
```

### Flow 7: Write-Time Fact Management

```
Agent calls save_fact("Bob now owns the hiring budget", importance=0.8)
  │
  ▼
Backend: MemoryService.save_fact_with_dedup()
  → Load all active facts in same namespace (max 50 due to cap)
  → LLM comparison: "Given these existing facts, classify this new fact:
    ADD (new info), UPDATE (modify existing), DELETE (supersedes existing), NOOP (already captured)"
  │
  ├── ADD → Create new memory_entry with valid_from=now, valid_until=null
  │
  ├── UPDATE → Modify existing entry's value, update updated_at
  │
  ├── DELETE → Set valid_until=now on the superseded fact ("Alice owns budget"),
  │            create new entry ("Bob owns budget") with valid_from=now
  │
  └── NOOP → No action, fact already captured
  │
  ▼
If namespace is at cap (50 entries):
  → Calculate scores for all active entries
  → Archive lowest-scored entry (set archived_at=now)
  → Archived entry excluded from future dedup comparisons and context assembly
  → Still searchable via recall_facts tool
```

### Flow 8: Mid-Task Steering (Managed Turn Loop)

```
User delegates: "Research competitor X's pricing strategy"
  → Background task created, agent starts working in managed turn loop
  │
  ▼
Turn 1: Agent receives instruction, plans approach, starts research
  → query() returns after turn completes
  → Agent Runner: steering queue empty → auto-continue
  │
  ▼
Turn 2: Agent executes WebSearch("competitor X pricing"), reads results
  → query(resume=session_id) returns after turn completes
  → Agent Runner: steering queue empty → auto-continue
  │
  ▼
User sees activity log, realizes agent is researching wrong company
  → User types in background task message input: "Wrong company — I mean X Corp, the SaaS one"
  │
  ▼
Frontend: POST /api/v1/conversations/{id}/steer
  → Message added to conversation's steering queue
  │
  ▼
Turn 3 completes (agent finishes current turn of work normally):
  → Agent Runner checks steering queue → message found
  → query(resume=session_id, message="Wrong company — I mean X Corp, the SaaS one")
  │
  ▼
Turn 4: Agent receives correction, adjusts course, continues with correct target
  → All prior results preserved (they're in session history)
  → Agent Runner: steering queue empty → auto-continue
  → Agent works to completion


Note: The user experiences this as seamless background work with an optional correction.
The auto-continuation between turns is invisible — no user interaction unless they
choose to steer. Latency between turns is minimal (the next query() fires immediately).
```

### Flow 9: Two-Tier Context Budget Enforcement

```
User sends message in a long-running conversation
  │
  ▼
Backend: AgentRunner.run_interactive()

TIER 1 — Proactive (before LLM call):
  → Estimate total context: system_prompt + memory + conversation_history + pending_message
  │
  ├── Under 70% of context window → proceed normally with query()
  │
  └── Over 70% → compression needed before LLM call:
      │
      ▼
      1. flush_memory(): agent saves unsaved facts to persistent memory
      2. Observation masking: keep recent 7 exchanges verbatim
      3. Summarize older exchanges (cut at turn boundaries only)
      4. Post-compaction verification: spot-check that key facts survived
      │
      ▼
      Proceed with query() using compressed context
      (user sees no interruption — this is transparent)

TIER 2 — Reactive (after LLM response):
  → monitor_context_usage() checks actual token counts from SDK usage metadata
  │
  ├── Under 70% → no action
  │
  ├── Over 70% → safety-net checkpoint:
  │   1. flush_memory(): save unsaved facts
  │   2. Create checkpoint summary (NOT compress — that's proactive's job)
  │   3. Store as conversation_summary with is_checkpoint=true
  │   The checkpoint captures state in the DB before any CLI-side
  │   compression degrades quality.
  │
  └── Over 90% → notification: suggest closing and starting fresh
```

### Flow 10: Autonomous Launch

```
User gives agent a goal: "Process all new recruiting candidates and prepare briefs"
  │
  ▼
Frontend: POST /api/v1/agents/{id}/autonomous
  { space_id, goal, constraints, token_budget?, time_budget? }
  │
  ▼
Backend: AgentRunner.launch_autonomous()
  → Creates BackgroundTask (run_type="autonomous") + Conversation
  → Agent receives goal + space state (via ContextAssembler)
  │
  ▼
Agent generates task list:
  → Surveys space (board state, items, memory)
  → Builds structured work queue: [{id, title, status}]
  → Stored on BackgroundTask.task_list (survives compaction, visible to UI)
  │
  ▼
Enters managed turn loop with smart continuation:
  → Each turn: pick next item → execute → update progress → adapt plan
  → Continuation prompts include: progress, budget remaining,
    completed items, queued approvals
  → At 70% context: compaction cycle preserves goal + constraints +
    task list + permission boundaries through compression
  → If action outside permissions: queue_approval() → continue with next item
  │
  ▼
Agent signals GOAL_COMPLETE (or budget exhausted):
  → Run summary generated and stored on BackgroundTask.run_summary
  → Notification created with summary
  → Task status updated to "completed"
```

### Flow 11: Compaction Cycle (within autonomous/background runs)

Follows the OpenClaw pattern: instructions are stored externally (on the
BackgroundTask record) and re-injected each turn via continuation prompts.
Compaction only affects conversation history, not instructions — the goal
is never at risk because it comes from the DB, not the context window.

```
Context utilization hits 70%
  │
  ▼
flush_memory():
  → Agent saves important working context to persistent memory
  → Existing flush_memory() infrastructure
  │
  ▼
Generate conversation summary:
  → Summarize turns so far (existing summary infrastructure)
  → Compresses the WORK (what the agent did, what it found)
  │
  ▼
Resume with compressed context:
  → Goal re-injected from BackgroundTask.goal on next continuation prompt
  → Summary of prior work included in continuation prompt
  → Recent turns preserved in context
  → Cycle repeats as needed — no hard turn limit

No post-compaction verification needed: the goal lives in the DB and is
re-injected every turn by _build_continuation_prompt(). The conversation
history can be freely summarized because it contains results, not instructions.
```

### Flow 12: Approval Queue

```
Autonomous agent attempts action outside permissions
  │
  ▼
PermissionEnforcer.check() returns approval_queued
  → Agent calls queue_approval() MCP tool
  → Creates approval_queue entry:
    { action_type, action_detail, reason: "want to send follow-up email
      to Alice Chen because research indicates strong fit" }
  → BackgroundTask.queued_approvals_count incremented
  │
  ▼
SSE event pushed to dashboard:
  → { type: "approval_queued", agent, action, reason, goal_context }
  → Appears in Pending Approvals section on Home dashboard
  │
  ▼
Agent continues with next task list item:
  → Does not block — moves on to other work
  → Queued action noted in task log
  │
  ▼
User reviews from dashboard:
  → Sees action + reason + goal context
  → Approves or denies (batch approve/deny supported)
  │
  ▼
If approved and run still active:
  → Approval result re-injected as steering message
  → Agent retries the action on next turn boundary
If denied:
  → Agent notified via steering message, skips the action
If run already completed:
  → Approval expires, action not taken
```

### Flow 13: Parallel Sub-Agent Fan-Out

```
Coordinator agent processing 30 candidates decides to parallelize
  │
  ▼
Coordinator calls delegate_task() N times:
  → delegate_task("research-alice", "Research + brief for Alice Chen", space_id)
  → delegate_task("research-bob", "Research + brief for Bob Park", space_id)
  → delegate_task("research-carol", "Research + brief for Carol Davis", space_id)
  │
  ▼
Each delegation:
  → narrow_permissions(parent_agent_id, depth+1) computes restricted permission set
  → Sub-agent spawned with narrowed permissions
  → Runs in sub-agent concurrency lane (cap 8)
  → Each sub-agent gets bounded task, not the full goal
  │
  ▼
Sub-agents execute independently:
  → Write results to items/documents (briefs, status updates, notes)
  → Operate within narrowed permission set
  → Cannot delegate further if at max_spawn_depth
  │
  ▼
Coordinator polls for completion:
  → Calls check_delegated_tasks() to check sub-agent status
  → When all complete: coordinator continues with collected results
  → Coordinator picks next batch of items to parallelize
  │
  ▼
Lifecycle:
  → Stopping coordinator cascade-terminates all children
  → Sub-agent failure → coordinator marks item as failed, continues with others
  → Sub-agent failures don't kill the parent run
```

### Flow 14: Heartbeat

```
Agent has heartbeat_enabled=True, heartbeat_cron="*/30 9-17 * * 1-5"
  │
  ▼
AutomationScheduler detects due heartbeat (every 60s check cycle)
  │
  ▼
Creates BackgroundTask (run_type="heartbeat")
  → Agent receives survey prompt:
    "HEARTBEAT — 2026-04-03 14:30
     You have been woken for a periodic check-in.
     Review the current state of your spaces. Consider:
     - Are there overdue items that need attention?
     - Has anything changed since your last check-in?
     - Are there items you've been assigned that are stale?
     - Is there anything the user should know about?"
  │
  ▼
Agent evaluates state and responds:
  │
  ├── HEARTBEAT_OK (nothing needs attention):
  │   → Silent — no notification created
  │   → Task marked complete
  │   → Logged in audit_log
  │
  └── Takes action (updates items, creates notifications, flags issues):
      → Actions logged in audit_log
      → Notification created: "Recruiting Agent flagged 3 overdue candidates"
      → Task marked complete with result summary
```

---

## Context Pruning and Memory Lifecycle Strategy

Context grows over time. Without pruning, agents in a busy space would drown in 5 months of accumulated history. The strategy is layered: each tier has its own mechanisms, and a cross-cutting lifecycle management system prevents long-term bloat.

### Tier 1: Semantic Memory — Facts (memory_entries)

Facts are the highest-signal, most persistent entries. Agents actively curate them via `save_fact`, `update_fact`, and `delete_fact` MCP tools.

**Write-time quality control:**
- **Dedup on write (ADD/UPDATE/DELETE/NOOP):** Every new fact triggers an LLM comparison against existing active facts in the same namespace. The LLM decides: ADD (genuinely new), UPDATE (modify existing to incorporate new info), DELETE (mark existing as superseded via `valid_until`), or NOOP (already captured). This prevents bloat at the source. Per Mem0 pattern — 26% quality improvement over append-only storage.
- **Temporal supersession:** When a fact is superseded, it gets `valid_until = now`. The old fact is not deleted — it's preserved for historical queries. Context assembly only loads facts where `valid_until IS NULL`.
- **Key-based overwrite:** Agents can also overwrite entries by writing to the same (namespace, key). "Uses React 18" gets overwritten by "Uses React 19" — same key, new value. No growth.

**Retrieval scoring:**
- Context assembly ranks active facts by: `score = importance × e^(-λ × days_since_access) × (1 + access_count × 0.2)` where `λ = 0.16 × (1 - importance × 0.8)`. Higher importance = slower decay. Frequently accessed facts resist fading.
- Token budget: 1000 tokens for space facts, 500 for global. Lowest-scored entries within budget are dropped from context but remain queryable via `recall_facts` tool.

**Lifecycle management:**
- **Per-namespace cap:** 50 active entries per space namespace, 20 per agent namespace. When the cap is hit during a write, the lowest-scored active entry is archived (`archived_at = now`). Archived entries are excluded from context assembly and write-time dedup comparisons, but remain searchable via tools.
- **Auto-archival of superseded facts:** Facts with `valid_until` set more than 90 days ago are automatically archived on a weekly check.
- **Periodic consolidation (monthly or manual):** LLM reviews all active facts for a space. Merges related entries (3 facts about tech stack → 1 comprehensive fact), flags contradictions, suggests archival for entries with zero access in 60+ days. Results surfaced to user as a notification requiring approval — the system never deletes or merges without confirmation.
- **Stale detection:** Entries not accessed in 90+ days are flagged. The system surfaces them periodically: "These memory entries haven't been used in 3 months. Keep, archive, or delete?"

### Tier 2: Episodic Memory — Conversation Summaries (conversation_summaries)

Summaries grow linearly — one per closed conversation, plus mid-conversation checkpoints. A space with 3 conversations per week = ~60 summaries in 5 months.

**Pruning mechanisms:**
- **Recency window:** Context assembly injects the meta-summary first (if exists), then the most recent unconsolidated summaries that fit the budget.
- **Threshold-triggered consolidation:** When a space accumulates 20+ unconsolidated summaries, the system automatically generates a meta-summary during the next conversation close. The meta-summary condenses all unconsolidated summaries into one compact block. Example: "From January to March: shipped the API redesign, hired two candidates, resolved the auth issue. Key decisions: moved to JWT tokens, chose Tailwind v4." Individual summaries that were consolidated are marked with `consolidated_into` pointing to the meta-summary — they remain in the DB and are searchable via `search_summaries`, but excluded from context assembly.
- **Successive consolidation:** When a second round of 20 summaries accumulates, the new meta-summary covers both the old meta-summary and new individual summaries. Always one current meta-summary covering full history.
- **Manual trigger:** User can trigger consolidation from space settings at any time, regardless of threshold.
- **Checkpoint pruning:** Mid-conversation checkpoint summaries (`is_checkpoint=true`) are superseded by the final close summary. After a conversation closes, its checkpoints are excluded from context assembly (kept in DB for search).
- **Token budget:** Fixed allocation of 2000 tokens.

### Tier 3: Working Memory — Item State (generated at assembly time)

Item state is always fresh — generated from the database, not stored. But a space with 200 items would produce a large dump.

**Pruning mechanisms:**
- **Active items only:** Exclude archived items and done items (unless recently completed).
- **Recency filter:** Only include items updated in the last 30 days, plus anything with an upcoming due date.
- **Summarize, don't enumerate:** "12 tasks in To Do, 3 in In Progress, 2 completed this week" rather than listing all 200 items. Agents have `get_item` and `list_items` MCP tools for on-demand detail.
- **Token budget:** Fixed allocation of 1500 tokens. Placed at the end of context (closest to user's message) for maximum model attention.

### Tier 4: Procedural Memory — Behavioral Rules (behavioral_rules)

Behavioral rules accumulate from two sources: user corrections ("don't do X", "always check Y first") and validated approaches (user confirms a non-obvious choice worked well, or accepts an unusual approach without pushback). Growth is slow (~5-10 per agent over months) but without lifecycle management, agents could accumulate contradictory rules.

**Lifecycle mechanisms:**
- **Per-agent cap:** 30 active rules per agent. When cap is hit, lowest-confidence rule is deactivated.
- **Asymmetric confidence tracking:** Rules start at confidence 0.5. Confirmed by user → confidence increases by a standard increment (e.g., +0.1, capped at 1.0). Overridden by user → confidence decreases at **2x the rate** (e.g., -0.2). This asymmetry ensures that stale or wrong rules erode quickly while good rules build trust gradually. Rules below confidence 0.3 after 10+ sessions are auto-deactivated (`is_active = false`).
- **Source tracking:** Rules carry a `source_type` ("correction" or "validation") so the system knows whether the rule came from fixing a mistake or confirming a good approach.
- **Application tracking:** `apply_count` and `last_applied` track how often and how recently a rule was used. Rules not applied in 10+ sessions with low confidence are auto-deactivated.
- **Token budget:** Fixed allocation of 500 tokens within the system prompt section (beginning of context, highest attention).

### Tier 5: In-Session Conversation History

This is the raw message history within an active SDK session.

**Pruning mechanisms:**
- **Proactive budget enforcement:** Before each LLM call, the Agent Runner estimates total context size. If it exceeds 70% of the context window, compression is triggered before the call — not as error recovery after the fact.
- **Mandatory pre-compaction flush:** Before any compression, the `flush_memory()` operation runs: the agent is prompted to save unsaved facts to persistent memory. This prevents information loss during the inherently lossy summarization step.
- **Observation masking:** During compression, the most recent 7 complete exchanges (user message + agent response) are kept verbatim (`RECENT_TURNS_VERBATIM = 7`). Only older exchanges are summarized. This preserves the immediate working context. JetBrains research found that ~7-10 turns gave the best balance — a 2.6% task completion improvement while being 52% cheaper than full summarization.
- **Post-compaction verification:** After compression, spot-check that key facts from the compressed section exist in persistent memory. If gaps are found, log a warning and optionally trigger a targeted save. This catches cases where the flush missed something critical.
- **Turn-boundary compression:** Compression always cuts at user-message boundaries — never in the middle of a tool-call sequence. This preserves conversation coherence.
- **User-initiated close:** When context becomes unwieldy, the user closes the conversation. Flush + final summary is generated. New conversation starts with summary context.
- **Notification at 90%:** System suggests closing and starting fresh when context is nearly full.

### On-Demand Search (Beyond Context Window)

Not everything needs to be in the initial context injection. Agents have MCP tools to pull historical context on demand, backed by FTS5 full-text search indexes:

- `search_conversations(query?, space_id?, date_range?, agent_id?)` — FTS5 search on conversation message content. `space_id` is optional — omit for cross-space search scoped to the agent's permitted spaces.
- `search_summaries(query, space_id?)` — FTS5 search on conversation summary content. Cross-space capable.
- `get_conversation_messages(conversation_id, limit?)` — pull specific messages from a closed conversation. For when the summary isn't enough and the agent needs the actual exchange.
- `recall_facts(query?, namespace?, category?, date_range?)` — search facts with optional filters. Omitting namespace searches all namespaces. Results scored by the same retrieval formula used in context assembly.

Cross-space search is permission-scoped: agents only see results from spaces they have access to via the `agent_spaces` join table. Odin (system-level) can search all spaces.

This means an agent that needs context from 3 months ago can find it without that context being pre-loaded into every session. The initial context injection covers "what's likely needed." On-demand search covers "what might be needed."

### Overall Context Budget

```
Context assembly total: ~8000 tokens (~4% of 200k context window)

BEGINNING (high model attention):
  Agent identity + role prompt:     ~1500 tokens (fixed, never truncated)
  Procedural rules:                  ~500 tokens (active rules, ranked by confidence)
  Tool documentation:               ~1000 tokens (fixed, never truncated)

MIDDLE (lower model attention):
  Conversation summaries:           ~2000 tokens (meta-summary + recent unconsolidated)
  Space facts:                      ~1000 tokens (scored: importance × decay × access)
  Global facts:                      ~500 tokens (scored: importance × decay × access)

END (high model attention):
  Item state:                       ~1500 tokens (fresh, pruned by recency)
```

The vast majority of the context window remains available for the actual conversation. The 8000-token injection is a starting point — tunable per space or per agent if needed. Content ordering exploits the U-shaped attention curve documented in "Lost in the Middle" (Liu et al., 2023).

---

## Backup Strategy

### What Gets Backed Up

The SQLite database file contains all structured data: items, spaces, conversations, messages, memory, summaries, agents, permissions. This is the single critical file.

Documents in Google Drive are already remote — they don't need backing up from OpenLoop. Local artifacts (agent-generated files, verbose logs) are transient and low-value — not worth backing up.

### Existing Infrastructure

The current codebase includes a working Google Drive backup script (`backend/scripts/backup_gdrive.py`) that:
1. Creates a safe SQLite copy via `sqlite3 .backup`
2. Compresses artifacts into a tar.gz
3. Uploads both to a configured Google Drive folder
4. Enforces retention (max 30 backups, deletes oldest)

Google OAuth is already configured. This script carries forward to the new architecture unchanged — the SQLite file is still the thing that matters.

### Backup Triggers

- **Manual daily backup (P0):** `make backup-gdrive`. Run it as part of your daily routine.  The system could display a reminder on the Home dashboard if no backup has run in 24+ hours.
- **Automated daily backup (P1):** Scheduled task (Windows Task Scheduler or background timer) runs the Drive backup once daily. Configurable time.
- **Backup on conversation close (recommended):** When a conversation closes and a summary is written, trigger a backup. This is when the most valuable new data is committed. The SQLite file is small — backing up takes seconds.

### Recovery

Restore = replace the SQLite file with a backup copy and restart the backend. Conversations in progress at the time of failure are lost, but their checkpoints and summaries (if any were generated) survive in the backup.

---

## Technology Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| AI execution | Claude Agent SDK → Claude Max | No API costs. SDK is Anthropic's official programmatic interface to Claude Code CLI. Spawns CLI sessions under Max subscription. |
| Real-time streaming | Server-Sent Events (SSE) | Simpler than WebSockets. One-directional (server→client) is sufficient — user messages sent via HTTP POST. Native browser support. Easy to implement in FastAPI. |
| Database | SQLite | Local-first, zero config, sufficient for single-user. Schema designed for clean Postgres migration later if needed. |
| Backend framework | FastAPI (Python) | Already in use. Async support for SSE streaming. Good SDK integration (SDK is Python). |
| Frontend framework | React 19 + Vite | Already in use. React Query for server state. Zustand for UI state. EventSource API for SSE. |
| CSS | Tailwind CSS v4 | Already in use. Utility-first, fast iteration on UI. |
| Process model | Single process (initial) | Simpler. AgentRunner runs SDK sessions as async tasks within the FastAPI process. Architecture designed so worker separation is a clean refactor if needed. |
| Session model | Long-lived SDK sessions with resume | SDK manages conversation history. OpenLoop manages context injection for new sessions. Conversation close/summarize handles context pruning. Upgrade SDK to v0.1.51+ to fix hook timeout bug (#554/#730). Use `query()` with resume, not `ClaudeSDKClient`. |
| Model stack | Haiku (Odin) + Sonnet (default agents) + Opus (on demand) | Haiku for fast routing/simple actions. Sonnet for most agent work. Opus for complex reasoning. Per-conversation model override. |
| Odin | System-level Haiku agent, always visible at bottom of screen | Replaces command bar. One interaction model. Routes to space agents for complex work. |
| Document storage | Google Drive (primary) + local (fallback) | User's existing storage. Accessible from anywhere. Agents interact via Drive API (P1). |
| Contract / types | Pydantic → OpenAPI → TypeScript (same as current) | Type safety across the stack. Auto-generated frontend types. |

---

## What This Architecture Enables

1. **Streaming conversations** — SSE gives real-time, token-by-token agent responses. Same feel as Claude CLI.
2. **Multiple concurrent sessions** — AgentRunner manages multiple SDK sessions. Up to 5 concurrent (per user's estimate).
3. **Context that survives** — four-tier memory (semantic, episodic, working, procedural) + scored retrieval + attention-optimized assembly. New agents in a space automatically know what happened before, how to behave, and what's important.
4. **Granular permissions** — every tool call goes through the PermissionEnforcer. Per-agent, per-resource, per-operation. In-conversation and background approval flows.
5. **Odin front door** — always-visible Haiku-powered chat at the bottom of the screen. Handles simple actions directly (~1-2s), routes complex work to space agents.
6. **Background delegation** — agents work asynchronously via managed turn loop (agent runner auto-continues between turns, checks steering queue at each boundary). Results flow back to the board/conversation. Progress monitoring via SSE. User can steer mid-task without restart.
7. **Progressive autonomy** — permission matrix supports Always/Approval/Never per operation. Flip gates as trust increases.
8. **Future remote access** — API-first design. Every operation is an API call. Discord/Slack/mobile clients plug in without rearchitecting.
9. **Clean agent creation** — Agent Builder designs agents through conversation. Permission matrix set at creation time.
10. **Automations** — cron-based scheduled agent runs with full run history. Same agents, permissions, and tools as manual conversations. Automation dashboard for visibility.
11. **CRM and task views** — same data, different views. Board for tasks, table for records. Per-space defaults.
12. **Tasks everywhere** — lightweight checklist (list view) in every space plus cross-space aggregation on Home.
13. **Flexible spaces** — not everything is a "project." Knowledge bases, CRM systems, simple task lists. Template-based creation with widget-based layouts.
14. **Agent-designed layouts** — agents can read, modify, and fully redesign space layouts via MCP tools. "Redesign my health space with Garmin charts" is a tool call, not a feature request. Templates provide defaults; agents and users customize from there.
15. **Autonomous goal pursuit** — agents work independently for hours with context compaction, self-directed task lists, and adaptive planning. Token and time budgets prevent runaway usage.
16. **Permission narrowing** — sub-agents safely inherit restricted permissions at each delegation level. Permissions only narrow, never widen. Enforced through a single codepath.
17. **Lane-isolated concurrency** — background work (autonomous runs, automations, sub-agents) doesn't block interactive conversations. Independent lane caps with a shared hard ceiling.
18. **Observable operations** — audit logging for every tool call during background/autonomous runs, token tracking per message, activity feeds, and approval queues. Full visibility into what agents did overnight.

---

## Migration Strategy

Fresh database. No data migration from current system.

The current codebase has reusable pieces:
- **Frontend components** — board UI, drag-and-drop, task cards, styling, design system. Significant rework needed but the component patterns are useful.
- **Service layer patterns** — CRUD patterns, validation logic. Will be rewritten but the structure informs the new services.
- **SDK integration knowledge** — understanding of ClaudeSDKClient, query(), hooks, MCP tools. Directly applicable.
- **Contract system** — Pydantic → OpenAPI → TypeScript pipeline. Kept as-is.

What gets rebuilt:
- Data model (new schema)
- API routes (new endpoints for conversations, items, permissions)
- Agent runner (new — the core of the new architecture)
- Context assembly (new — four-tier system with scored retrieval, attention-optimized ordering, and lifecycle management)
- Permission enforcement (new — granular matrix)
- Frontend (significant rework — conversation panels, home dashboard, table view)

This is closer to a rebuild than a modify. The knowledge, patterns, and some components carry over, but the core architecture is different enough that trying to incrementally modify the current system would be more work than starting fresh with the current code as reference.

**SDK upgrade required:** Upgrade `claude-agent-sdk` from v0.1.50 to v0.1.51+ before starting. This fixes the hook timeout bug (#554/#730) and removes the need for the `CLAUDE_CODE_STREAM_CLOSE_TIMEOUT` workaround. Use `query()` with `resume`, not `ClaudeSDKClient` (session isolation bug #560 is still open, and `ClaudeSDKClient` has untested Windows compatibility at current versions).
