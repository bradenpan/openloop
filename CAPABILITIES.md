# OpenLoop: Capability Specification (DRAFT v5)

**Status:** Under review — not yet approved for implementation.

---

## What OpenLoop Is

OpenLoop is a personal AI command center. It's where you manage all your work — human tasks, AI-delegated tasks, knowledge domains, and CRM-style tracking — across multiple spaces, from one interface. You interact with AI agents organized by domain, delegate work, track progress, and maintain context across everything you're doing.

The system has four core jobs:

1. **Track all work** — to-dos, board tasks, CRM-style pipeline items. One place, not scattered across Trello, Excel, Notion, and terminal windows.
2. **Manage AI agents** — start conversations, delegate tasks, monitor progress, maintain context across sessions. Organized by space, not by terminal window.
3. **Keep you prepared** — proactive briefings, meeting prep, follow-up reminders. The system looks at your calendar, email, and task board and makes sure nothing falls through the cracks.
4. **Catch what you're missing** — scan email, board, and records for dropped balls, overdue follow-ups, unanswered threads, and items that need attention. Surface them proactively — don't wait to be asked. Eventually, this becomes a personal assistant that makes sure everything you need to get done for the day actually gets done.

## What OpenLoop Is Not (Today)

- Not a commercial SaaS product — single-user, local-first for now. Architecture should not preclude multi-user or cloud deployment later.
- Not a general-purpose chat UI — conversations are space-scoped and work-oriented.
- **Human-in-the-loop by default** — agents surface recommendations and take action only when approved. Autonomy increases over time as agents prove reliable. The architecture supports configurable autonomy levels per agent, up to and including fully autonomous operation for trusted agents.

---

## Core Concepts

### Home

Home is the top-level view above spaces. It provides (in priority order, top to bottom):

1. **Odin chat** — always visible at top. The universal AI entry point. Ask questions, give instructions, start conversations. Odin routes you where you need to go.
2. **Attention items** — the "act now" section. Pending approval requests, board tasks due today/overdue, agent results to review, automation failures. These are things that need you right now.
3. **Active agents** — background agents currently running, with status indicators. The "what's happening" section.
4. **Space list** — quick access to all spaces with activity indicators. The "go somewhere" section.
5. **Cross-space to-do list** — all to-dos from all spaces, grouped by space. The reference section — scrollable, below the fold is fine.

Home is the screen you open in the morning. "What needs my attention?" Then you drill into specific spaces.

**First-run experience:** When a user opens OpenLoop for the first time, Home shows:
- An Odin welcome message with suggested first actions ("Try: 'add a to-do: call dentist'" or "Create your first space")
- A "Create your first space" card with template picker (Project, CRM, Knowledge Base, Simple)
- Odin works immediately for basic to-dos — no agent setup needed on day one

### Spaces

A space is a domain — a container for related data, work, and AI conversations. Not every space is a "project." Some are knowledge bases, some are CRM systems, some are traditional projects.

Examples:
- **Recruiting** (CRM) — candidate records, pipeline tracking, interview notes, follow-up tasks
- **OpenLoop** (project) — task board, code agent conversations, feature planning
- **Health** (knowledge base) — bloodwork PDFs, Garmin data, doctor visit notes, health agent conversations
- **Personal** (simple) — to-do list, personal tasks, no board needed
- **Client X** (project) — deliverables, meeting notes, communication tracking

Each space has:

- **To-dos** (always) — lightweight checklist items. Every space has these. Title + done/not done. "Call dentist." "Upload bloodwork." "Email Sarah."
- **Board** (optional) — Kanban columns or table view for heavier work items that move through stages. Not every space needs this.
- **Data sources** — connected data: Google Drive folders, git repos, API integrations (Garmin, bank feeds, calendar), manual uploads. Agents can read from connected sources.
- **Agent conversations** — named, persistent chat threads with AI agents. Multiple can be active. Older ones can be closed and reopened. Agents always have context of what happened before.
- **Memory** — facts, conversation summaries, and preferences specific to this space.
- **Configuration** — which data sources are connected, which agents are available, space-specific settings

Spaces are the primary organizational unit. When you open a space, you see its to-dos, its board (if enabled), its conversations, and its data.

**Space templates** for quick creation:
- **Project** — board enabled with default columns (Idea → Scoping → To Do → In Progress → Done), standard agent tools
- **CRM** — board enabled with table view default, record-oriented, custom fields
- **Knowledge Base** — no board, data-focused, document-heavy, conversations for Q&A
- **Simple** — no board, just to-dos and conversations

Templates are starting points — you can add/remove features after creation.

**Subspaces (future):** Spaces can optionally contain subspaces for finer organization. A "Personal" space might have subspaces for Health, Finances, and Email. A "Client X" space might have subspaces per workstream. Subspaces inherit parent context — agents in a subspace can see parent-level data and memory. Not in v1, but the architecture supports adding this later.

### Items

There are two weights of tracked work:

**To-dos** — lightweight, checkbox-style. Every space has these. A to-do has a title, a done/not-done state, and an optional due date. That's it. If a to-do turns out to be more complex than expected, it can be "promoted" to a board item. **Default everything to to-dos.** When you add something, it's a to-do. No decision needed. If it needs more structure later, promote it.

**Board items** — heavier, multi-stage work that moves through a pipeline. Board items live on a space's Kanban board or table view. They have descriptions, stages, assigned agents, due dates, and attached conversations. Board items come in two kinds:

- **Tasks** — work to be done. Can be human tasks or agent tasks.
- **Records** — tracked entities (a person, a lead, a bug). Records have custom fields, attached notes, and linked to-dos/tasks.

Agents can create and manage both to-dos and board items through their MCP tools.

### Space Views

Spaces adapt their display to what's enabled:

- **To-do list** (always present) — checkbox list of lightweight items. Visible in every space.
- **Board view** (optional) — Kanban columns. Items grouped by stage, drag-and-drop. Default for project-type spaces.
- **Table view** (optional) — rows and columns. Each row is a record or task. Sortable, filterable. Default for CRM-type spaces.

Both board and table views show the same underlying board items. You can switch between them. The to-do list is always available alongside either view.

Default board columns: **Idea → Scoping → To Do → In Progress → Done**.

### Odin — The Front Door

Odin is a system-level AI agent that serves as the universal entry point. There is no separate "command bar" — Odin's chat input is always visible at the top of the screen.

You type whatever you want in natural language:
- "Add a to-do: call dentist" → Odin creates it in the current space
- "What's on my plate today?" → Odin summarizes your to-dos and attention items across all spaces
- "Open recruiting agent" → Odin opens a conversation with the Recruiting Agent
- "I need to research competitor X for the product space" → Odin opens a conversation with an appropriate agent in the Product space
- "Create an agent that can manage my health data" → Odin delegates to the Agent Builder

Odin runs on **Haiku** by default for fast responses (~1-2 seconds). It handles simple actions directly (creating to-dos, answering board state questions, routing to conversations) and delegates complex work to space-scoped agents.

When you want to interact directly with a more capable model, you either:
1. **Open a conversation** in a space (click New Conversation, pick agent, pick model) — one click, no Odin needed
2. **Click an existing conversation** in the sidebar — instant, already in the model you chose
3. **Tell Odin** "open a conversation with Opus in OpenLoop" — Odin routes you there

### Agents and Conversations

An agent is a configured AI with a specific role, prompt, and set of tools. Examples:

- **Recruiting Agent** — knows the recruiting data, can update candidate tracking, draft follow-up emails, build meeting briefs
- **Code Agent** — knows a specific codebase, can read/write code, run tests
- **Research Agent** — can search the web, summarize findings, write reports
- **Health Agent** — can read health data, search medical literature, track trends
- **Email Agent** — can draft emails, sort inbox, flag items needing response

A conversation is a persistent, named chat thread with an agent, scoped to a space. Conversations:

- Are interactive (back-and-forth, like Claude CLI)
- Maintain full history within the conversation
- Can be closed when context becomes unwieldy — the system generates a conversation summary capturing decisions, outcomes, and open questions. This summary is stored as space context.
- Can be reopened or new conversations started — the agent gets the summary from prior conversations, not the full raw history. Full history remains accessible if the agent needs to look something up.
- Can delegate work to sub-agents (e.g., the recruiting agent spins up a research sub-agent to build a candidate brief)
- Can create/update to-dos and board items as a side effect of the conversation
- Multiple conversations can be active simultaneously within a space

**Model selection:** Each agent has a default model (typically Sonnet). You can override the model per conversation (e.g., use Opus for a complex planning session). Odin may suggest upgrading when a task would benefit from a more capable model, but you always decide.

The key insight: **conversations are where most work happens**. The board and to-do list track the state of work. Conversations are where work gets planned, discussed, and driven forward.

### Permissions and Security

Agents operate under a granular permission system. Permissions are defined along three dimensions:

**Resource** — what the agent can access:
- A specific folder or Drive folder
- A repo
- A data source or API integration
- An external API (email, calendar, web)

**Operation** — what the agent can do with that resource:
- **Read** — view contents
- **Create** — make new files/documents/records
- **Edit** — modify existing files/documents/records
- **Delete** — remove files/documents/records
- **Execute** — run commands, send emails, make API calls

Each operation is independently grantable.

**Grant level** — how much oversight is required:
- **Always allowed** — agent can do this without asking.
- **Requires approval** — action is held until the human approves. Where approvals appear:
  - **In active conversations:** inline in the chat — "Agent wants to edit tracker.csv. [Approve] [Deny]"
  - **For background tasks / automations:** in the Attention Items section on Home, and as a notification. No timeout — the request waits indefinitely until you act. The agent pauses, not fails.
  - **Approval count badge** on the Home navigation so you always know if something is waiting.
- **Never allowed** — agent cannot do this under any circumstances.

Permissions are set during agent creation (the Agent Builder asks about this) and editable in the UI. Progressive autonomy: agents start with more "Requires approval" gates, earn trust over time.

System-level guardrails (non-overridable):
- No access to credential files (.env, credentials.json, SSH keys, API tokens)
- No access to OpenLoop's own configuration or database files
- No ability to grant themselves additional permissions

### Agent Creation

Creating a new agent is a conversational process. You tell Odin what you need ("I need an agent that can manage my recruiting pipeline"). Odin delegates to the **Agent Builder** — a specialized agent whose job is to design other agents. The Agent Builder:

- Asks the right questions to scope the agent: what domain, what data sources, what tools, what repos, what it should and shouldn't do
- Iterates with you on the design (like a requirements-gathering conversation)
- Produces the agent configuration: name, system prompt, tool permissions, space access, default model
- Writes the config files and registers the agent in the system

You can also view and edit agent configurations directly in the UI after creation, or go back and forth with the Agent Builder to refine.

### Memory and Documents

Each space has a knowledge base. Memory operates in three tiers:

1. **Facts** — persistent key-value entries. "Sarah prefers morning meetings." "The auth module uses JWT tokens." Long-lived, curated by agents and humans. These are the institutional knowledge of the space.

2. **Conversation summaries** — auto-generated when conversations are closed, or checkpointed mid-conversation when context usage is high. "On March 28, we discussed restructuring the API. Decided on approach X. Open question: how to handle migration." This is how context survives across conversations.

3. **Board/to-do state** — current state of items, recent changes, upcoming deadlines. Auto-generated from the database. Always fresh.

**Context assembly** pulls from all three tiers when an agent starts a conversation or picks up a task. The system manages the token budget so context doesn't overwhelm. Agents can also search prior conversations on demand — summaries are auto-loaded, but full message history from closed conversations is queryable via tools.

**Documents and data** are stored externally:
- **Google Drive** (primary) — spaces link to Drive folders. Accessible from anywhere.
- **Local files** (secondary) — agent-generated artifacts, repo files.
- **API integrations** — connected services (Garmin, calendar, email) that agents can query.

The system indexes documents regardless of where they live for agent and search access.

### Automations

Automations are scheduled or event-triggered agent runs. An automation is: **a trigger + an agent + an instruction.**

Examples:
- Every morning at 7am, run the Briefing Agent to summarize the day across all spaces
- Every hour, run the Email Agent to check for new emails and flag items needing response
- Every Monday, run the Health Agent to pull Garmin data and generate a weekly summary
- When a new calendar event is created, run the Meeting Prep Agent
- Every evening, run the Finance Agent to categorize today's transactions

Automations are visible in a dedicated dashboard: what's scheduled, what ran, what succeeded/failed, what's running now. You can enable/disable, edit, manually trigger, and review run history.

Automations use the same agents, permissions, and MCP tools as manual conversations. The only difference is the trigger — cron schedule or event instead of you typing a message. If an automation's agent hits an "Approval required" permission gate, it surfaces a notification just like any background task.

### Proactive System

The proactive system is built on top of automations. Proactive behaviors are pre-configured automations that ship with the system:

- **Morning briefing** — scheduled automation: Briefing Agent summarizes your day across all spaces (meetings, deadlines, to-dos, stale items).
- **Meeting prep** — event-triggered automation: when a meeting is detected without a prep brief, dispatch a Prep Agent.
- **Follow-up tracking** — scheduled automation: scan to-dos and records for overdue follow-ups, surface to Home.
- **Stale work detection** — scheduled automation: flag board items that haven't moved in X days.
- **Dropped ball detection** — scheduled automation: scan email and records for unanswered items.

These are regular automations with pre-built configurations. You can edit, disable, or replace them. The proactive system is not a separate layer — it's a set of default automations.

---

## Interaction Model

This section describes the intended interaction patterns. The specific UI layout will evolve through use.

### Home View

When you open OpenLoop:

1. **Odin chat** — always visible at top. Type anything.
2. **Attention items** — pending approvals, due-today tasks, agent results to review, automation failures. Act now.
3. **Active agents** — background agents currently running, with status.
4. **Space list** — quick access to all spaces with activity indicators.
5. **Cross-space to-dos** — all to-dos from all spaces, grouped by space. Reference view, below the fold is fine.

### Space View

When you open a space:

1. **To-dos** — always present. Lightweight checklist.
2. **Board** (if enabled) — Kanban or table view for heavier items.
3. **Conversations** — list of active/recent agent conversations. Click to open. Start a new one.
4. **Data** — documents, connected sources, uploaded files.

### Agent Interaction

Conversations are opened from spaces or via Odin. When you're in a conversation:

- **Chat mode (default):** Interactive back-and-forth. Streaming responses. Agent has space context pre-loaded.
- **Delegation mode:** "Go do X" — agent works in background. Notification when done.
- **Sub-agents:** Agent spins up focused sub-agents for specific sub-tasks. Results flow back.
- **Model selection:** Switchable per conversation. Default is the agent's configured model.

### Background Agent Monitoring

Compact status indicator: "Code Agent working on 'Refactor auth module' — 2 min elapsed." Click to expand into a streaming log. Low-density by default, high-density on demand.

### Automation Dashboard

Accessible from Home or Settings. Shows:
- All automations with status (enabled/disabled, last run time, last result)
- Run history per automation (when, what happened, success/failure)
- Currently running automations
- Enable/disable toggle, "Run now" button, edit configuration
- Upcoming scheduled runs

### Response Time Expectations

- **Odin (simple actions):** ~1-2 seconds (Haiku)
- **Agent conversations:** Same as Claude CLI. Streaming, first tokens in 1-2 seconds (Sonnet) or 2-4 seconds (Opus).
- **Background delegation:** Progress indicator. Results when done.

---

## Capabilities by Priority

### P0 — Must work at launch

1. **Home dashboard** — cross-space to-do list, attention items, active agents, space list, Odin chat
2. **Space management** — create spaces from templates (Project, CRM, Knowledge Base, Simple), configure data sources
3. **To-dos** — lightweight checklist in every space. Cross-space aggregation on Home. Done/not-done.
4. **Board with tasks** — create, move, edit, archive board items. Kanban drag-and-drop. Optional per space. Default columns: Idea → Scoping → To Do → In Progress → Done.
5. **Odin (front door)** — always-visible chat input running on Haiku. Handles simple actions directly, routes complex work to space agents. Natural language, no memorized commands.
6. **Agent conversations** — start a named conversation with an agent in a space context. Interactive chat with streaming responses. Agent has access to space data, memory, and board state. Can create/update to-dos and board items. Model selectable per conversation (default Sonnet, option for Opus).
7. **Agent delegation** — tell an agent to go work on a task in the background. Status indicator with expandable log. Results flow back.
8. **Context management** — conversations maintain history. Closing generates a summary. Auto-checkpoint when context usage exceeds 70%. New conversations get summaries + facts + board state. Agents can search prior conversations on demand.
9. **Permissions layer** — per-agent, per-resource, per-operation permissions with three grant levels. Inline approval in conversations, pending approvals visible in Home Attention Items. No timeout — agents wait indefinitely for approval. System guardrails non-overridable.

### P1 — Important, build soon after launch

10. **Agent Builder** — specialized agent for creating new agents through conversational requirements gathering. Writes config and registers in system. Accessible via Odin. (At P0 launch, agents created via UI form. Agent Builder adds the conversational creation flow.)
11. **Records (CRM-style items)** — tracked entities with custom fields and pipelines. Linked to-dos/tasks. Table view.
12. **Table view** — alternative to Kanban for CRM-style spaces. Rows = records, columns = configurable fields.
13. **Google Drive integration** — link Drive folders to spaces. Agents read/write documents. Indexed and searchable.
14. **Documents/data management** — per-space document management with metadata, tags, search.
15. **Sub-agent delegation** — agents can spin up sub-agents for focused work within a conversation.
16. **Conversation management** — list all conversations across spaces, sort by recency, close stale ones, search history.
17. **Multiple active conversations** — 2-3 open simultaneously, flip between them.
18. **Proactive surfacing** — agents scan board and data for dropped balls, stale items, overdue follow-ups.
19. **Automated daily backup** — scheduled Google Drive backup of SQLite database.
20. **Cron-based automations** — scheduled agent runs (daily briefing, hourly email check, weekly health summary). Automation CRUD, run history, dashboard. Manual trigger button.

### P2 — Valuable, build when core is solid

21. **Calendar integration** — read calendar, surface upcoming meetings.
22. **Email integration** — read/draft emails, sort inbox, flag items needing response.
23. **Event-based automations** — triggered by calendar events, new emails, data source updates. Requires event bus.
24. **Morning briefing** — pre-configured automation: daily summary across all spaces.
25. **Meeting prep automation** — event-triggered: detect meetings without briefs, auto-dispatch prep agents.
26. **Follow-up tracking** — scheduled automation: time-based reminders on items and records.
27. **Stale work detection** — scheduled automation: surface items that haven't moved.
28. **API data source integrations** — connect Garmin, bank feeds, and other APIs to spaces.
29. **Configurable autonomy** — per-agent autonomy levels for specific operation types.
30. **Subspaces** — nested spaces with context inheritance.

### P3 — Future

31. **Remote access** — interact via Discord, Slack, or web interface from any device.
32. **Mobile access** — view to-dos, board, and conversations from phone.
33. **Multi-user** — share spaces, assign tasks to people.

---

## What Changes From Current System

### Kept
- FastAPI backend + React frontend + SQLite (local-first stack)
- Kanban board UI with drag-and-drop
- Agent execution via Claude SDK
- Memory system (expanded from current key-value to three-tier)
- CLI for power-user operations

### Changed
- **Projects → Spaces** — broader concept. A space can be a project, a knowledge base, a CRM, or a simple to-do list. Not everything is a "project."
- **Task types eliminated** — no more manual/quick/standard distinction. Items are to-dos (lightweight) or board items (tasks/records).
- **Odin becomes the front door** — always-visible AI chat input running on Haiku. Replaces the command bar and the old orchestrator. One interaction model, no memorized commands.
- **To-dos are universal** — every space has a lightweight checklist. Board is optional. Cross-space to-do aggregation on Home.
- **Board is optional per space** — knowledge-base spaces don't need Kanban columns.
- **Model selection** — Haiku for Odin, Sonnet default for agents, Opus on demand. Per-agent defaults, per-conversation overrides.
- **Conversations become first-class** — lifecycle management (open, close with summary, checkpoint, reopen with context).
- **Data sources** — spaces connect to Google Drive, repos, and API integrations. Not just local files.
- **Permission model rebuilt** — granular per-agent, per-resource, per-operation with three grant levels. Inline and notification approval flows.
- **Home redesigned** — cross-space to-dos, attention items, Odin chat, active agents.

### Removed
- Manual/Quick/Standard task type distinction
- Command bar (replaced by Odin chat)
- Fast path regex pattern matching (replaced by Odin on Haiku)
- Structured output parsing (TaskResult JSON schema)
- MCP registry as a separate surface
- Morning briefing scheduler (rebuilt properly in P2)
- Discord integration (replaced by P3 remote access)

---

## Resolved Decisions

1. **Spaces, not projects** — broader abstraction. Templates for quick creation (Project, CRM, Knowledge Base, Simple).
2. **Two item weights** — to-dos (lightweight, every space, default) and board items (heavier, optional board). Promotion path from to-do to board item. Default everything to to-dos.
3. **Odin as front door** — always-visible Haiku-powered chat. No separate command bar. One interaction model. Has its own memory namespace and session lifecycle.
4. **Model stack** — Haiku for Odin, Sonnet for agents (default), Opus on demand. Per-conversation override.
5. **Board is optional** — per-space setting. Knowledge bases don't need Kanban.
6. **Agent creation** — UI form at P0. Agent Builder (conversational creation via Odin) at P1.
7. **Document storage** — Google Drive as primary (P1), local as fallback. Metadata indexing for search. FTS5 for full-text search (P1).
8. **Background monitoring** — status indicator + expandable log stream.
9. **Cross-space visibility** — Home shows attention items first, then active agents, then space list, then to-dos. First-run experience with onboarding prompts.
10. **Remote access** — P3. Architecture is API-first.
11. **Permissions model** — granular (resource x operation x grant level). Inline approval in active conversations, Attention Items on Home for background/automation. No timeout anywhere — agents wait indefinitely. Pending approvals always visible on Home dashboard with badge count.
12. **Execution model** — Claude Max subscription via Claude Agent SDK. Upgrade to v0.1.51+. Use `query()` with `resume`, not `ClaudeSDKClient`.
13. **Subspaces** — deferred (P2). Schema includes `parent_space_id` for future use.
14. **Manual daily backup** for P0. Automated daily backup is P1.
15. **Automations** — cron-based (P1), event-based (P2). Proactive system is a set of pre-configured automations, not a separate layer. Automation dashboard for visibility. Max 2 concurrent automation sessions; user conversations take priority. Missed-run detection on startup.
16. **Crash recovery** — on startup, interrupted conversations are detected and surfaced. User can reopen (attempts SDK resume) or close them.
17. **Item provenance** — to-dos and board items track `source_conversation_id` so users can trace where work came from.
18. **SSE architecture** — single multiplexed endpoint (`/api/v1/events`) for all streaming. Frontend demultiplexes by source ID.

---

## Architecture Principles

1. **API-first** — every capability is accessible via API. Future clients plug in without rearchitecting.
2. **Conversations are the core abstraction** — the system is built around persistent, context-rich conversations that produce work as a side effect.
3. **Context is assembled, not manually fed** — agents get what they need automatically. Token budgets, relevance ranking, summarization, and on-demand search for historical context.
4. **One interaction model** — Odin chat is the universal entry point. No memorized commands, no mode switching. Conversations for deep work. To-dos and boards for tracking.
5. **Progressive autonomy** — agents start supervised, earn trust, get more autonomy.
6. **Storage is external** — Google Drive for documents, SQLite for structured data, repos for code, APIs for live data. OpenLoop is the orchestration layer.
7. **Claude Max, not API** — all agent execution via Claude Agent SDK under Max subscription. Haiku for Odin, Sonnet/Opus for agents.
8. **Granular security by default** — per-agent, per-resource, per-operation permissions. No agent gets broad access by default.
