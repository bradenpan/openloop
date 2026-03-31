# OpenLoop: Architecture Proposal (DRAFT v4)

**Status:** Under review — not yet approved for implementation.
**Companion document:** CAPABILITIES.md (defines what the system does; this document defines how it's built)

---

## System Overview

OpenLoop is a coordination layer between a human, a web UI, and multiple Claude Max sessions. It doesn't do AI work — it manages the plumbing: routing messages, storing state, assembling context, enforcing permissions, and tracking what agents are doing.

**Key terminology change:** "Projects" are now **Spaces** — a broader abstraction that can be a project, a knowledge base, a CRM, or a simple to-do list. "Items" split into **to-dos** (lightweight, checkbox-style, every space) and **board items** (heavier, multi-stage, optional per space). **Odin** is the always-visible AI front door (Haiku-powered), replacing the separate command bar.

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
│  │  Spaces│Todos│Items│Conversations│Memory│Perms│Odin│  │
│  └────────────────────┬──────────────────────────────┘  │
│                       │                                 │
│  ┌────────────────────▼──────────────────────────────┐  │
│  │           Session Manager                          │  │
│  │  Tracks active SDK sessions, routes messages,      │  │
│  │  manages lifecycle (start/resume/close/summarize)  │  │
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
- Space view (widget-based layout: kanban, table, to-dos, conversations, charts, data feeds — configurable per space)
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

# To-dos (lightweight, every space)
POST   /api/v1/todos                       Create to-do
GET    /api/v1/todos                       List to-dos (filters: space_id, is_done, cross-space)
PATCH  /api/v1/todos/{id}                  Update to-do (title, is_done)
POST   /api/v1/todos/{id}/promote          Promote to-do to board item
DELETE /api/v1/todos/{id}                  Delete to-do

# Board items (tasks and records, optional per space)
POST   /api/v1/items                       Create board item
GET    /api/v1/items                       List board items (filters: space, stage, type)
GET    /api/v1/items/{id}                  Get board item detail
PATCH  /api/v1/items/{id}                  Update board item
POST   /api/v1/items/{id}/move             Move board item to stage
POST   /api/v1/items/{id}/archive          Archive board item

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
GET    /api/v1/home/dashboard              Cross-space summary (all to-dos, attention items, active agents)

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
- **TodoService** — lightweight to-do CRUD, done/not-done toggle, cross-space listing, promote-to-board-item
- **ItemService** — board item (task and record) CRUD, stage transitions, custom fields for records, archive
- **ConversationService** — create, list, get history, close (trigger summary), reopen. Manages the mapping between conversations and SDK sessions.
- **OdinService** — system-level agent session management. Routes Odin messages to a persistent Haiku session. Handles routing instructions (open conversation, create to-do, navigate) and delegates complex requests.
- **DataSourceService** — manage connected data sources per space (Drive folders, repos, API integrations). Config storage, status tracking, refresh scheduling.
- **NotificationService** — create, list, mark read. Stores notifications for background task completion, permission requests, proactive alerts. Feeds the Home dashboard and SSE event stream.
- **SessionManager** — the core orchestration piece. Manages active Claude SDK sessions:
  - `start_session(conversation_id, agent_id)` → spawns a new SDK session with assembled context
  - `send_message(conversation_id, message)` → routes message to the right SDK session, returns an async stream of response chunks
  - `close_session(conversation_id)` → asks the agent to summarize, then terminates the SDK session
  - `list_active()` → returns all running sessions with status
  - Handles session lifecycle: start, message routing, streaming, error recovery, cleanup
- **ContextAssembler** — builds the prompt context for a new session:
  - Reads space memory (facts tier)
  - Reads conversation summaries (summary tier)
  - Reads current to-do + board state (state tier)
  - Ranks by relevance, manages token budget
  - Returns assembled context string for system prompt injection
  - Special mode for Odin: cross-space context (all spaces, all agents, cross-space to-do summary, attention items)
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
- **AutomationScheduler** — background loop within the FastAPI process. Every 60 seconds, checks all enabled cron-based automations against the current time. When matched, creates a background task with the automation's agent + instruction. Lightweight — no external dependencies (no Celery, no Redis). On startup, checks for missed runs during downtime and surfaces notifications. Max concurrent automation sessions configurable (default 2); user conversations always take priority.
- **SummaryService** — generates conversation summaries. Called when conversations close. Uses the agent's own SDK session (asks it to summarize before closing) or a lightweight summary call.

### Layer 4: Session Manager (Detail)

This is the most architecturally significant component. It bridges OpenLoop's conversation model with Claude SDK sessions.

```
┌─────────────────────────────────────────────────┐
│                Session Manager                   │
│                                                 │
│  Active Sessions (dict: conversation_id → state)│
│                                                 │
│  Each session state:                            │
│  ├── sdk_session_id: str                        │
│  ├── agent_id: str                              │
│  ├── conversation_id: str                       │
│  ├── space_id: str (nullable for Odin)          │
│  ├── status: active | background | closing      │
│  ├── started_at: datetime                       │
│  ├── last_activity: datetime                    │
│  └── mcp_server: SDK MCP server instance        │
│                                                 │
│  Operations:                                    │
│  ├── start_session()                            │
│  │   1. Load agent config                       │
│  │   2. Assemble context (ContextAssembler)     │
│  │   3. Load tool config from agent record        │
│  │   4. Build MCP tools (builtin OpenLoop tools │
│  │      from agent's mcp_tools config)          │
│  │   5. Register permission hooks               │
│  │   6. Call SDK query() with assembled prompt   │
│  │   7. Store session state                     │
│  │                                              │
│  ├── send_message()                             │
│  │   1. Look up active session                  │
│  │   2. PROACTIVE BUDGET CHECK: estimate total  │
│  │      context (system prompt + memory +        │
│  │      history + pending message). If >70%:    │
│  │      a. Run flush_memory() first             │
│  │      b. Compress older turns (observation    │
│  │         masking: keep recent 5-10 exchanges  │
│  │         verbatim, summarize the rest)         │
│  │      c. Post-compaction verification: check  │
│  │         key facts from compressed section    │
│  │         exist in persistent memory           │
│  │      d. Compress at turn boundaries only —   │
│  │         never split tool-call sequences      │
│  │   3. Call SDK query(resume=session_id)        │
│  │   4. Stream response chunks to SSE           │
│  │   5. Process tool calls through Permission   │
│  │      Enforcer                                │
│  │   6. Store message + response in DB          │
│  │                                              │
│  ├── close_session()                            │
│  │   1. Run flush_memory() — agent saves any    │
│  │      unsaved facts to persistent memory      │
│  │   2. Send "summarize this conversation" msg  │
│  │   3. Store summary as conversation summary   │
│  │   4. Check summary consolidation threshold   │
│  │      (if space has 20+ unconsolidated         │
│  │      summaries, generate meta-summary)        │
│  │   5. Terminate SDK session                   │
│  │   6. Clean up session state                  │
│  │                                              │
│  ├── flush_memory()                             │
│  │   Mandatory pre-compaction safety step.       │
│  │   1. Inject instruction: "Review this convo  │
│  │      for important facts, decisions, or       │
│  │      preferences not yet saved to memory.     │
│  │      Save them now using your memory tools."  │
│  │   2. Agent calls save_fact() as needed        │
│  │   3. Return — normal flow continues           │
│  │   Called by: close_session() and              │
│  │   send_message() before compression.          │
│  │                                              │
│  ├── verify_compaction(compressed_content)       │
│  │   Post-compaction safety check.               │
│  │   1. Scan compressed content for fact-like    │
│  │      statements (decisions, preferences,      │
│  │      specific values)                         │
│  │   2. Check each against persistent memory     │
│  │   3. If gaps found: log warning, optionally   │
│  │      trigger a targeted save for missed facts │
│  │   Lightweight — not a full re-extraction,     │
│  │   just a spot check for obvious gaps.         │
│  │   Called by: send_message() after compression.│
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
│  │   1. Start session, create background_task   │
│  │   2. Enter turn loop:                        │
│  │      a. query(resume=session_id, message=    │
│  │         steering_queue.pop() or "continue")  │
│  │      b. Agent completes one turn of work     │
│  │      c. Log activity, update step progress   │
│  │         (current_step, step_results on task) │
│  │      d. Stream activity to SSE for monitoring│
│  │      e. Check: agent reported completion?    │
│  │         → exit loop                          │
│  │      f. Check steering queue for user msgs   │
│  │      g. Loop back to (a)                     │
│  │   3. On completion: write results to task,   │
│  │      notify via SSE event                    │
│  │   Agent system prompts include: "Work        │
│  │   incrementally. Complete one meaningful step │
│  │   per turn. Report what you did and what you │
│  │   plan to do next."                          │
│  │                                              │
│  └── monitor_context_usage()                    │
│      Runs after each agent response as backup.  │
│      (Primary budget enforcement is proactive   │
│      in send_message(), this is the safety net.)│
│      1. Check context window usage from SDK     │
│         session metadata                        │
│      2. If usage > 70% of window:               │
│         a. Run flush_memory() first              │
│         b. Create checkpoint summary             │
│         c. Store as conversation_summary with   │
│            is_checkpoint=true                   │
│         d. Conversation continues normally —    │
│            the CLI handles its own compression  │
│         e. But the checkpoint ensures state is  │
│            captured in the DB before any CLI    │
│            compression degrades quality         │
│      3. If usage > 90%: surface a notification  │
│         suggesting the user close and start a   │
│         new conversation                        │
│                                                 │
│  Crash Recovery (on startup):                   │
│  1. Scan conversations table for status='active'│
│  2. Mark all as 'interrupted'                   │
│  3. Create notification: "N conversations were  │
│     interrupted by a restart"                   │
│  4. When user reopens an interrupted convo:     │
│     a. Attempt resume=sdk_session_id with fresh │
│        MCP tools and hooks                      │
│     b. If resume fails: start new session with  │
│        conversation summary + recent messages   │
│        injected as context                      │
│  5. Clean up any orphaned CLI processes         │
│                                                 │
│  Concurrency Control:                           │
│  - Max concurrent sessions configurable         │
│    (default 5)                                  │
│  - Interactive conversations have priority over │
│    background tasks and automations             │
│  - Max concurrent automation sessions: 2        │
│  - When limit hit: queue with notification      │
└─────────────────────────────────────────────────┘
```

**MCP Tools available to every agent session:**

These are the tools agents use to interact with OpenLoop's data. Defined as MCP tool closures (same pattern as current orchestrator, but broader):

```
# To-do operations
create_todo(title, space_id, due_date?)
complete_todo(todo_id)
list_todos(space_id?, is_done?)

# Board operations
create_item(title, type, space_id, stage?, description?, fields?)
update_item(item_id, fields...)
move_item(item_id, stage)
get_item(item_id)
list_items(space_id?, stage?, type?, limit?)

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
get_todo_state(space_id?)
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
get_cross_space_todos(is_done?)
```

These tools are only available to Odin's session, not to space agents.

### Layer 4b: Odin — The Front Door (Detail)

Odin is a system-level agent that runs on Haiku. It is always visible in the UI and serves as the universal entry point.

```
┌──────────────────────────────────────────────────┐
│                     Odin                          │
│                                                  │
│  Model: Haiku (fast, cheap)                      │
│  Scope: cross-space (no single space binding)    │
│  Session: persistent conversation record          │
│           (space_id=null in conversations table)  │
│                                                  │
│  Session Lifecycle:                              │
│  1. On app load: resume existing Odin session    │
│     (or create a new one if none exists)         │
│  2. Each user message → query(resume=session_id) │
│  3. Odin handles simple actions directly via     │
│     MCP tools (create_todo, list_spaces, etc.)   │
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
│  - Cross-space to-do summary (open count by      │
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
│  3. Backend creates conversation record,          │
│     starts SDK session for Recruiting Agent      │
│  4. Odin responds: "Opening a conversation with  │
│     your Recruiting Agent..."                    │
│  5. SSE event to frontend:                       │
│     { type: "route", space_id, conversation_id } │
│  6. Frontend navigates to Recruiting space,      │
│     opens the new conversation panel             │
│  7. Initial message is forwarded as first user   │
│     message in the new conversation              │
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
│  │  7. To-do + board state (fresh from DB)    ││
│  │     Open to-dos, current board items,      ││
│  │     stages, upcoming deadlines, recent     ││
│  │     changes. Closest to user's message     ││
│  │     for maximum relevance.                 ││
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
├── default_view ("board" | "table" | null)
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

todos
├── id (UUID, PK)
├── space_id (FK → spaces, indexed)
├── title
├── is_done (boolean, default false)
├── due_date (datetime, nullable)
├── sort_position (float)
├── created_by (string — "user" | "agent:{name}" | "odin")
├── source_conversation_id (FK → conversations, nullable — which conversation created this)
├── promoted_to_item_id (FK → items, nullable — set when promoted to board item, hidden from to-do list)
├── created_at
└── updated_at

items (board items — tasks and records)
├── id (UUID, PK)
├── space_id (FK → spaces, indexed)
├── item_type ("task" | "record")
├── is_agent_task (boolean, default false)
├── title
├── description
├── stage (string, must be in space's board_columns)
├── priority (integer, nullable)
├── sort_position (float)
├── custom_fields (JSON, for records)
├── parent_record_id (FK → items, nullable, for tasks linked to records)
├── assigned_agent_id (FK → agents, nullable)
├── due_date (datetime, nullable)
├── created_by (string — "user" | "agent:{name}" | "odin")
├── source_conversation_id (FK → conversations, nullable — which conversation created this)
├── archived (boolean, default false)
├── created_at
└── updated_at

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
├── tools (JSON array — which Claude tools are enabled)
├── mcp_tools (JSON array — which OpenLoop MCP tools are enabled)
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
├── role ("user" | "agent")
├── content (text)
├── tool_calls (JSON, nullable)
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
├── source_conversation_id (FK → conversations, nullable — where this rule was learned)
├── confidence (float, default 0.5 — asymmetric updates: +0.1 on confirmation, -0.2 on override)
├── apply_count (integer, default 0 — how many times injected into context)
├── last_applied (datetime, nullable — last time injected into a session)
├── is_active (boolean, default true — false when demoted due to low confidence/usage)
├── created_at
└── updated_at

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
Space ──1:N──> Todos
Space ──1:N──> Items (board items)
Space ──1:N──> Conversations
Space ──1:N──> Documents
Space ──1:N──> Data Sources
Space ──1:N──> Conversation Summaries
Space ──0:1──> Space (parent, for future subspaces)

Todo ──N:1──> Space

Item ──N:1──> Space
Item ──N:1──> Agent (assigned, nullable)
Item ──N:1──> Item (parent record, nullable)
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
  → Creates conversation record in DB
  → SessionManager.start_session()
    → ContextAssembler.build(space_id, agent_id)
      → Loads: agent prompt, board state, conversation summaries, space facts, global facts, tool docs
    → Builds MCP tools (board ops, memory ops, doc ops)
    → Registers permission hooks via PermissionEnforcer
    → Calls SDK query() with assembled system prompt
    → Stores sdk_session_id
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
Backend: SessionManager.send_message()
  → SDK query(prompt=message, options={resume: session_id})
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
Backend: SessionManager.delegate_background()
  → Creates background_task record
  → Starts new SDK session (no SSE streaming to user)
  → Agent works: WebSearch, reads Drive docs, etc.
  → Activity logged to background_task record
  │
  ▼
Frontend: Home dashboard shows "Research Agent working on 'Company background for Sarah Chen' — 2m elapsed"
  Click to expand → SSE stream of agent activity log
  │
  ▼
Agent completes:
  → Writes results to document (create_document MCP tool)
  → Updates item if applicable (update_item MCP tool)
  → Writes to memory if applicable
  → background_task.status = "completed"
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
Backend: ConversationService.close()
  → SessionManager.close_session()
    → flush_memory(): "Save any important unsaved facts to memory now"
    → Agent calls save_fact() as needed (write-time dedup runs on each)
    → Sends final message: "Summarize this conversation: key decisions, outcomes, open questions"
    → Agent responds with summary
    → Store summary in conversation_summaries table
    → Store summary text on conversation record
    → Check consolidation threshold: if space has 20+ unconsolidated summaries,
      generate meta-summary and mark individual summaries as consolidated
    → Terminate SDK session
    → conversation.status = "closed", conversation.closed_at = now()
  │
  ▼
Later: User starts new conversation with same agent in same space
  │
  ▼
Backend: SessionManager.start_session()
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
  → Session Manager: steering queue empty → auto-continue
  │
  ▼
Turn 2: Agent executes WebSearch("competitor X pricing"), reads results
  → query(resume=session_id) returns after turn completes
  → Session Manager: steering queue empty → auto-continue
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
  → Session Manager checks steering queue → message found
  → query(resume=session_id, message="Wrong company — I mean X Corp, the SaaS one")
  │
  ▼
Turn 4: Agent receives correction, adjusts course, continues with correct target
  → All prior results preserved (they're in session history)
  → Session Manager: steering queue empty → auto-continue
  → Agent works to completion


Note: The user experiences this as seamless background work with an optional correction.
The auto-continuation between turns is invisible — no user interaction unless they
choose to steer. Latency between turns is minimal (the next query() fires immediately).
```

### Flow 9: Proactive Budget Enforcement (during send_message)

```
User sends message in a long-running conversation
  │
  ▼
Backend: SessionManager.send_message()
  → Estimate total context: system_prompt + memory + conversation_history + pending_message
  │
  ├── Under 70% of context window → proceed normally with query()
  │
  └── Over 70% → compression needed before LLM call:
      │
      ▼
      1. flush_memory(): agent saves unsaved facts to persistent memory
      2. Observation masking: keep recent 5-10 exchanges verbatim
      3. Summarize older exchanges (cut at turn boundaries only)
      4. Post-compaction verification: spot-check that key facts survived
      5. Store checkpoint summary in conversation_summaries
      │
      ▼
      Proceed with query() using compressed context
      (user sees no interruption — this is transparent)
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

### Tier 3: Working Memory — Board State (generated at assembly time)

Board state is always fresh — generated from the database, not stored. But a space with 200 items would produce a large dump.

**Pruning mechanisms:**
- **Active items only:** Exclude archived items.
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
- **Proactive budget enforcement:** Before each LLM call, the Session Manager estimates total context size. If it exceeds 70% of the context window, compression is triggered before the call — not as error recovery after the fact.
- **Mandatory pre-compaction flush:** Before any compression, the `flush_memory()` operation runs: the agent is prompted to save unsaved facts to persistent memory. This prevents information loss during the inherently lossy summarization step.
- **Observation masking:** During compression, the most recent 5-10 complete exchanges (user message + agent response, configurable — default 7) are kept verbatim. Only older exchanges are summarized. This preserves the immediate working context. JetBrains research found that 10 turns gave the best balance — a 2.6% task completion improvement while being 52% cheaper than full summarization. Shorter windows (5) may be used for simple Q&A; longer windows (10) for complex multi-step work.
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
  Board/to-do state:                ~1500 tokens (fresh, pruned by recency)
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
| Process model | Single process (initial) | Simpler. SessionManager runs SDK sessions as async tasks within the FastAPI process. Architecture designed so worker separation is a clean refactor if needed. |
| Session model | Long-lived SDK sessions with resume | SDK manages conversation history. OpenLoop manages context injection for new sessions. Conversation close/summarize handles context pruning. Upgrade SDK to v0.1.51+ to fix hook timeout bug (#554/#730). Use `query()` with resume, not `ClaudeSDKClient`. |
| Model stack | Haiku (Odin) + Sonnet (default agents) + Opus (on demand) | Haiku for fast routing/simple actions. Sonnet for most agent work. Opus for complex reasoning. Per-conversation model override. |
| Odin | System-level Haiku agent, always visible | Replaces command bar. One interaction model. Routes to space agents for complex work. |
| Document storage | Google Drive (primary) + local (fallback) | User's existing storage. Accessible from anywhere. Agents interact via Drive API (P1). |
| Contract / types | Pydantic → OpenAPI → TypeScript (same as current) | Type safety across the stack. Auto-generated frontend types. |

---

## What This Architecture Enables

1. **Streaming conversations** — SSE gives real-time, token-by-token agent responses. Same feel as Claude CLI.
2. **Multiple concurrent sessions** — SessionManager tracks multiple SDK sessions. Up to 5 concurrent (per user's estimate).
3. **Context that survives** — four-tier memory (semantic, episodic, working, procedural) + scored retrieval + attention-optimized assembly. New agents in a space automatically know what happened before, how to behave, and what's important.
4. **Granular permissions** — every tool call goes through the PermissionEnforcer. Per-agent, per-resource, per-operation. In-conversation and background approval flows.
5. **Odin front door** — always-visible Haiku-powered chat. Handles simple actions directly (~1-2s), routes complex work to space agents.
6. **Background delegation** — agents work asynchronously via managed turn loop (session manager auto-continues between turns, checks steering queue at each boundary). Results flow back to the board/conversation. Progress monitoring via SSE. User can steer mid-task without restart.
7. **Progressive autonomy** — permission matrix supports Always/Approval/Never per operation. Flip gates as trust increases.
8. **Future remote access** — API-first design. Every operation is an API call. Discord/Slack/mobile clients plug in without rearchitecting.
9. **Clean agent creation** — Agent Builder designs agents through conversation. Permission matrix set at creation time.
10. **Automations** — cron-based scheduled agent runs with full run history. Same agents, permissions, and tools as manual conversations. Automation dashboard for visibility.
11. **CRM and task views** — same data, different views. Board for tasks, table for records. Per-space defaults.
12. **To-dos everywhere** — lightweight checklist in every space plus cross-space aggregation on Home.
13. **Flexible spaces** — not everything is a "project." Knowledge bases, CRM systems, simple to-do lists. Template-based creation with widget-based layouts.
14. **Agent-designed layouts** — agents can read, modify, and fully redesign space layouts via MCP tools. "Redesign my health space with Garmin charts" is a tool call, not a feature request. Templates provide defaults; agents and users customize from there.

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
- Session management (new — the core of the new architecture)
- Context assembly (new — four-tier system with scored retrieval, attention-optimized ordering, and lifecycle management)
- Permission enforcement (new — granular matrix)
- Frontend (significant rework — conversation panels, home dashboard, table view)

This is closer to a rebuild than a modify. The knowledge, patterns, and some components carry over, but the core architecture is different enough that trying to incrementally modify the current system would be more work than starting fresh with the current code as reference.

**SDK upgrade required:** Upgrade `claude-agent-sdk` from v0.1.50 to v0.1.51+ before starting. This fixes the hook timeout bug (#554/#730) and removes the need for the `CLAUDE_CODE_STREAM_CLOSE_TIMEOUT` workaround. Use `query()` with `resume`, not `ClaudeSDKClient` (session isolation bug #560 is still open, and `ClaudeSDKClient` has untested Windows compatibility at current versions).
