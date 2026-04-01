# OpenLoop: Capability Specification (DRAFT v5)

**Status:** Under review — not yet approved for implementation.

---

## What OpenLoop Is

OpenLoop is a personal AI command center. It's where you manage all your work — human tasks, AI-delegated tasks, knowledge domains, and CRM-style tracking — across multiple spaces, from one interface. You interact with AI agents organized by domain, delegate work, track progress, and maintain context across everything you're doing.

The system has four core jobs:

1. **Track all work** — tasks, CRM-style pipeline items, records. One place, not scattered across Trello, Excel, Notion, and terminal windows.
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
5. **Cross-space task list** — all open tasks from all spaces, grouped by space. The reference section — scrollable, below the fold is fine.

Home is the screen you open in the morning. "What needs my attention?" Then you drill into specific spaces.

**First-run experience:** When a user opens OpenLoop for the first time, Home shows:
- An Odin welcome message with suggested first actions ("Try: 'add a task: call dentist'" or "Create your first space")
- A "Create your first space" card with template picker (Project, CRM, Knowledge Base, Simple)
- Odin works immediately for basic tasks — no agent setup needed on day one

### Spaces

A space is a domain — a container for related data, work, and AI conversations. Not every space is a "project." Some are knowledge bases, some are CRM systems, some are traditional projects.

Examples:
- **Recruiting** (CRM) — candidate records, pipeline tracking, interview notes, follow-up tasks
- **OpenLoop** (project) — task board, code agent conversations, feature planning
- **Health** (knowledge base) — bloodwork PDFs, Garmin data, doctor visit notes, health agent conversations
- **Personal** (simple) — task list, personal tasks, no board needed
- **Client X** (project) — deliverables, meeting notes, communication tracking

Each space has:

- **Items** (always) — all tracked work lives here. Items can be viewed as a simple checklist (list view), a Kanban board, or a table. Every space has items. The view determines presentation, not the data model.
- **Board** (optional) — Kanban columns for items that move through stages. Not every space needs this — items in simple spaces work as a checklist without stages.
- **Data sources** — connected data: Google Drive folders, git repos, API integrations (Garmin, bank feeds, calendar), manual uploads. Agents can read from connected sources.
- **Agent conversations** — named, persistent chat threads with AI agents. Multiple can be active. Older ones can be closed and reopened. Agents always have context of what happened before.
- **Memory** — facts, conversation summaries, and preferences specific to this space.
- **Configuration** — which data sources are connected, which agents are available, space-specific settings

Spaces are the primary organizational unit. When you open a space, you see its items (as list, kanban, or table), its conversations, and its data.

**Space templates** for quick creation:
- **Project** — board enabled with default columns (Idea → Scoping → To Do → In Progress → Done), default Kanban view, standard agent tools
- **CRM** — board enabled with table view default, record-oriented, custom fields
- **Knowledge Base** — no board, data-focused, document-heavy, conversations for Q&A
- **Simple** — no board, items shown in list view (checklist style), conversations

Templates are starting points — you can add/remove features after creation.

**Subspaces (future):** Spaces can optionally contain subspaces for finer organization. A "Personal" space might have subspaces for Health, Finances, and Email. A "Client X" space might have subspaces per workstream. Subspaces inherit parent context — agents in a subspace can see parent-level data and memory. Not in v1, but the architecture supports adding this later.

### Items

All tracked work is an **item**. Items have two types:

- **Tasks** — work to be done. Can be human tasks or agent tasks. Tasks have a title, done/not-done state, optional description, optional stage, optional due date, priority, and assigned agent. A task can be as lightweight as "Call dentist" (just a title and a checkbox) or as structured as a multi-stage deliverable with description, priority, and agent assignment. The same data, viewed differently depending on context.
- **Records** — tracked entities (a person, a lead, a bug). Records have custom fields, attached notes, and linked tasks.

**Views** determine how items are presented — the underlying data model is the same:
- **List view** (to-do style) — shows tasks as a checklist: checkbox, title, stage dropdown (editable), due date. Done items hidden by default with toggle to show. Clicking a row opens the full item detail panel. This is the default for Simple spaces.
- **Kanban view** — groups tasks by stage in draggable columns. "Done" column hideable. This is the default for Project spaces.
- **Table view** — configurable columns, sortable/filterable rows. This is the default for CRM spaces.

**Item linking:** Items can be associated with each other via a many-to-many link system. A task can be linked to a contact record ("Call Sarah" linked to Sarah's record), linked to other related tasks, or both. Links are separate from hierarchy — an item can be a sub-task of a parent item (`parent_item_id`) AND linked to a contact record simultaneously.

**Hierarchy:** Items support parent-child nesting via `parent_item_id`. Sub-tasks nest under parent tasks. Contact records can be children of company records. This is structural — it defines where items appear in tree views.

**is_done ↔ stage sync (tasks only):** Checking a task done in list view moves it to the "done" stage on the kanban (if the space has a board). Dragging to the "done" column sets `is_done=true`. Moving out of "done" sets `is_done=false`. Unchecking `is_done` reverts stage to `"todo"` (the default stage). In simple spaces (no board), `is_done` toggles without affecting stage (which stays `null`). The sync applies only to tasks — records use stages for pipeline tracking (e.g., Lead → Qualified → Closed/Won) without `is_done` sync.

**Default behavior:** When you add something, it's a task with minimal fields. No decision needed. If it needs more structure, add a description, set a stage, link it to a record. No "promotion" step — the data model supports the full range from the start.

Agents can create and manage items through their MCP tools.

### Space Layouts

Each space has a configurable layout — an arrangement of widgets that defines what the space shows and how. A widget is a self-contained UI component: a kanban board, a data table, a task list panel, a conversation sidebar, a chart, a stat card, a notes panel, or a data feed.

Space templates provide sensible default layouts:
- **Project** — task list panel (left), kanban board (center), conversations (right)
- **CRM** — task list panel (left), data table (center), conversations (right)
- **Knowledge Base** — notes panel (center), conversations (right)
- **Simple** — task list panel (center), conversations (right)

These defaults match the current fixed-view behavior. But layouts are editable — you can add, remove, rearrange, and configure widgets through a layout editor in space settings, or ask an agent to do it for you.

**Agent-designed layouts:** Tell an agent "redesign this space to show my health data with charts and a bloodwork tracker" and the agent writes a new layout config — adding chart widgets connected to your Garmin data source, a table widget for bloodwork entries, and removing the kanban board you don't need. Agents have MCP tools to read and modify space layouts just like they have tools to create items or move tasks between stages.

**Core widget types:** task list panel, kanban board, data table, conversation sidebar. These are available at launch. **Extended widget types** (charts, stat cards, markdown notes, data feeds) are added later and depend on data source integrations to be meaningful.

Default board columns: **Idea → Scoping → To Do → In Progress → Done**.

### Odin — The Front Door

Odin is a system-level AI agent that serves as the universal entry point. There is no separate "command bar" — Odin's chat input is always visible at the top of the screen.

You type whatever you want in natural language:
- "Add a task: call dentist" → Odin creates it in the current space
- "What's on my plate today?" → Odin summarizes your tasks and attention items across all spaces
- "Open recruiting agent" → Odin opens a conversation with the Recruiting Agent
- "I need to research competitor X for the product space" → Odin opens a conversation with an appropriate agent in the Product space
- "Create an agent that can manage my health data" → Odin delegates to the Agent Builder

Odin runs on **Haiku** by default for fast responses (~1-2 seconds). It handles simple actions directly (creating tasks, answering board state questions, routing to conversations) and delegates complex work to space-scoped agents.

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
- Can be steered mid-task — if an agent is working in the background and going down the wrong path, you can send a correction that gets picked up at the next turn boundary without restarting the entire task
- Can create/update items (tasks, records) as a side effect of the conversation
- Multiple conversations can be active simultaneously within a space

**Model selection:** Each agent has a default model (typically Sonnet). You can override the model per conversation (e.g., use Opus for a complex planning session). Odin may suggest upgrading when a task would benefit from a more capable model, but you always decide.

The key insight: **conversations are where most work happens**. Items (list view, board, table) track the state of work. Conversations are where work gets planned, discussed, and driven forward.

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

Each space has a knowledge base. Memory operates in four tiers, mapped from established cognitive memory types:

1. **Semantic memory (facts)** — persistent entries representing knowledge about the world. "Sarah prefers morning meetings." "The auth module uses JWT tokens." "Deploy target is AWS us-east-1." Facts are curated by agents and humans. Agents have explicit tools to save, update, and delete facts — they actively manage what they know, not just passively receive context.

   Facts are temporally aware: each fact tracks when it became true (`valid_from`) and when it was superseded (`valid_until`). When a new fact contradicts an existing one ("Bob now owns the budget" replacing "Alice owns the budget"), the old fact is marked as superseded — not deleted. This preserves history while keeping current facts clean. Agents can query historical facts ("who owned the budget in January?") via date-range search.

   Facts are deduplicated at write time. Every new fact is compared against existing facts in the same namespace. The system decides: ADD (new information), UPDATE (modify existing fact), DELETE (mark as superseded), or NOOP (already captured). This prevents bloat at the source rather than relying on periodic cleanup.

2. **Episodic memory (conversation summaries)** — auto-generated when conversations are closed, or checkpointed mid-conversation when context usage is high. "On March 28, we discussed restructuring the API. Decided on approach X. Open question: how to handle migration." This is how context survives across conversations.

   When a space accumulates 20+ unconsolidated summaries, the system automatically generates a meta-summary — a condensed overview covering months of history in one compact block. The individual summaries remain searchable but are replaced in context assembly by the meta-summary. This prevents agents from losing awareness of long-term project trajectory as history grows.

3. **Working memory (item state)** — current state of items, recent changes, upcoming deadlines. Auto-generated from the database. Always fresh.

4. **Procedural memory (behavioral rules)** — learned rules about how the agent should behave, captured from two sources: user corrections ("don't do X", "always check Y first") and validated approaches (user confirms a non-obvious choice worked well). "Always check the CRM before drafting follow-up emails." "User prefers bullet points over long paragraphs." "When formatting reports, include a summary section at the top." These rules are injected into the agent's context with high priority at the start of every conversation. Confidence updates are asymmetric: confirmations increase confidence by a standard increment, but contradictions decrease confidence at 2x the rate — it takes multiple confirmations to build trust, but a single clear override should significantly erode it. Rules below a confidence threshold after sustained non-use are deactivated. This is how agents improve over time — both corrections and validated successes stick across sessions.

**Context assembly** pulls from all four tiers when an agent starts a conversation or picks up a task. The system manages a token budget (~8000 tokens) so context doesn't overwhelm. Content is ordered to exploit how models pay attention: high-priority information (identity, behavioral rules, tool definitions) at the beginning, reference material (facts, summaries) in the middle, and immediately relevant context (board state, current task) at the end closest to the user's message.

Before any context compression (at 70% context usage or on conversation close), the system runs a mandatory memory flush: the agent is prompted to save any important unsaved facts to persistent memory before the summary is generated. This prevents information loss during the inherently lossy summarization step. During compression, the most recent conversation exchanges are kept verbatim (configurable window, default 5-10) — only older history is summarized.

Facts are scored for retrieval by a blend of importance, recency, and access frequency — not just "most recent entries." A frequently-referenced architectural decision from 3 months ago ranks higher than yesterday's meeting note. Each namespace has a hard cap (50 facts per space, 20 per agent, 30 procedural rules per agent). When the cap is hit, the lowest-scored entry is archived. A periodic consolidation job reviews facts, merges related entries, flags contradictions, and suggests archival — surfacing results for user approval.

Agents can also search beyond what's in their context window. Conversation messages, summaries, and facts are searchable via FTS5 full-text indexes. Search works across spaces (scoped to spaces the agent has access to), enabling agents to find relevant information from other domains when needed.

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

- **Morning briefing** — scheduled automation: Briefing Agent summarizes your day across all spaces (meetings, deadlines, open tasks, stale items).
- **Meeting prep** — event-triggered automation: when a meeting is detected without a prep brief, dispatch a Prep Agent.
- **Follow-up tracking** — scheduled automation: scan tasks and records for overdue follow-ups, surface to Home.
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
5. **Cross-space tasks** — all open tasks from all spaces, grouped by space. Reference view, below the fold is fine.

### Space View

When you open a space:

1. **Items** — always present. Shown as list view (checklist), kanban, or table depending on space template and user preference.
2. **Board** (if enabled) — Kanban stage columns for items that move through a pipeline.
3. **Conversations** — list of active/recent agent conversations. Click to open. Start a new one.
4. **Data** — documents, connected sources, uploaded files.

### Agent Interaction

Conversations are opened from spaces or via Odin. When you're in a conversation:

- **Chat mode (default):** Interactive back-and-forth. Streaming responses. Agent has space context pre-loaded.
- **Delegation mode:** "Go do X" — agent works in background. Notification when done.
- **Steering mode:** Send a message to a running background agent, which gets picked up at the next turn boundary. The current turn finishes, your message is processed next, and the agent adjusts course without restarting.
- **Sub-agents:** Agent spins up focused sub-agents for specific sub-tasks. Results flow back.
- **Model selection:** Switchable per conversation. Default is the agent's configured model.

### Background Agent Monitoring

Compact status indicator: "Code Agent working on 'Refactor auth module' — 2 min elapsed." Click to expand into a streaming log. Low-density by default, high-density on demand. For multi-step tasks, shows current step and step history ("Step 3/5: Analyzing competitor C"). Failed tasks show exactly where they stopped and what was completed, enabling resume from the failure point rather than full restart.

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

1. **Home dashboard** — cross-space task list, attention items, active agents, space list, Odin chat
2. **Space management** — create spaces from templates (Project, CRM, Knowledge Base, Simple), configure data sources
3. **Unified items** — all tracked work (tasks and records) in a single data model. List view (checklist style), Kanban view, and Table view of the same data. Cross-space task aggregation on Home. is_done/stage bidirectional sync.
4. **Board with stages** — create, move, edit, archive items. Kanban drag-and-drop. Optional per space. Default columns: Idea → Scoping → To Do → In Progress → Done. "Done" column hideable.
5. **Odin (front door)** — always-visible chat input running on Haiku. Handles simple actions directly, routes complex work to space agents. Natural language, no memorized commands.
6. **Agent conversations** — start a named conversation with an agent in a space context. Interactive chat with streaming responses. Agent has access to space data, memory, and board state. Can create/update items (tasks, records) and manage item links. Model selectable per conversation (default Sonnet, option for Opus).
7. **Agent delegation** — tell an agent to go work on a task in the background. Status indicator with expandable log. Results flow back.
8. **Context management** — conversations maintain history. Closing generates a summary. Mandatory pre-compaction memory flush before any summarization (agent saves unsaved facts to persistent memory before context is compressed), followed by post-compaction verification (check that key facts from the compressed section exist in persistent memory). Proactive budget enforcement checks context size before each LLM call and compresses at clean turn boundaries when needed. Recent exchanges kept verbatim during compression (configurable window, default 5-10 exchanges) — only older history is summarized. Auto-checkpoint when context usage exceeds 70%. New conversations get summaries + facts + behavioral rules + board state. Context ordered for maximum model attention: high-priority at beginning/end, reference material in middle.
9. **Agent memory tools** — agents have explicit tools to save, update, and delete facts. Agents actively curate their knowledge rather than passively receiving context. System prompts instruct agents to use these proactively. Write-time dedup prevents contradictory or duplicate entries.
10. **Permissions layer** — per-agent, per-resource, per-operation permissions with three grant levels. Inline approval in conversations, pending approvals visible in Home Attention Items. No timeout — agents wait indefinitely for approval. System guardrails non-overridable.

### P1 — Important, build soon after launch

11. **Agent Builder** — specialized agent for creating new agents through conversational requirements gathering. Writes config and registers in system. Accessible via Odin. (At P0 launch, agents created via UI form. Agent Builder adds the conversational creation flow.)
12. **Records (CRM-style items)** — tracked entities with custom fields and pipelines. Linked tasks via item_links (many-to-many). Table view.
13. **Table view** — alternative to Kanban for CRM-style spaces. Rows = records, columns = configurable fields.
14. **Google Drive integration** — link Drive folders to spaces. Agents read/write documents. Indexed and searchable.
15. **Documents/data management** — per-space document management with metadata, tags, search.
16. **Sub-agent delegation** — agents can spin up sub-agents for focused work within a conversation.
17. **Conversation management** — list all conversations across spaces, sort by recency, close stale ones, search history.
18. **Multiple active conversations** — 2-3 open simultaneously, flip between them.
19. **Proactive surfacing** — agents scan board and data for dropped balls, stale items, overdue follow-ups.
20. **Automated daily backup** — scheduled Google Drive backup of SQLite database.
21. **Cron-based automations** — scheduled agent runs (daily briefing, hourly email check, weekly health summary). Automation CRUD, run history, dashboard. Manual trigger button.
22. **Procedural memory** — behavioral rules learned from user corrections and validated approaches, captured with confidence scores (asymmetric: contradictions decrease confidence at 2x the rate of confirmations), injected into agent context at start of every conversation. Agents improve over time — corrections and confirmed successes both stick across sessions.
23. **Temporal fact management** — facts track when they became true and when they were superseded. Historical facts preserved for querying. Write-time comparison detects contradictions and supersedes old facts automatically.
24. **Cross-space and deep search** — FTS5 full-text indexes on memory, messages, and summaries. Conversation and summary search across spaces (scoped to agent permissions). Replaces basic substring matching with ranked results.
25. **Mid-task steering** — send a message to a running background agent to redirect it. Background delegation uses a managed turn loop: the session manager auto-continues between agent turns, checking a steering queue at each turn boundary. User corrections are picked up at the next turn boundary — no restart needed. Works within the Claude Agent SDK's existing `query()` + `resume` mechanism.
26. **Widget-based space layouts** — spaces use a configurable widget layout instead of hardcoded views. Templates provide defaults. Layouts editable via settings panel and agent MCP tools. Core widgets: task list panel, kanban board, data table, conversation sidebar. Agents can read, modify, and fully redesign space layouts.

### P2 — Valuable, build when core is solid

26. **Calendar integration** — read calendar, surface upcoming meetings.
27. **Email integration** — read/draft emails, sort inbox, flag items needing response.
28. **Event-based automations** — triggered by calendar events, new emails, data source updates. Requires event bus.
29. **Morning briefing** — pre-configured automation: daily summary across all spaces.
30. **Meeting prep automation** — event-triggered: detect meetings without briefs, auto-dispatch prep agents.
31. **Follow-up tracking** — scheduled automation: time-based reminders on items and records.
32. **Stale work detection** — scheduled automation: surface items that haven't moved.
33. **API data source integrations** — connect Garmin, bank feeds, and other APIs to spaces.
34. **Configurable autonomy** — per-agent autonomy levels for specific operation types.
35. **Subspaces** — nested spaces with context inheritance.
36. **Memory lifecycle management** — hard caps per namespace with lowest-scored eviction. Auto-archival of superseded facts after 90 days. Periodic LLM-driven consolidation: merges related facts, flags contradictions, suggests archival — surfaces to user for approval.
37. **Summary consolidation** — automated meta-summary generation when a space exceeds 20 unconsolidated summaries. Condensed overview replaces individual summaries in context assembly. Manual trigger available. Successive consolidation keeps one current meta-summary covering full history.
38. **Retrieval scoring** — context assembly scores facts by importance, recency, and access frequency (Ebbinghaus-inspired decay). Frequently-used, high-importance facts stay prominent regardless of age.
39. **Multi-step workflow tracking** — background tasks track current step, total steps, and step results. Parent-child task hierarchies for sub-agent delegation. Failed tasks show exactly where they stopped, enabling resume from failure point.
40. **Extended widget library** — chart/graph widgets (connected to data sources), stat cards, markdown/notes panels, data feed widgets. Depends on API data source integrations. Enables agent-designed spaces like a health dashboard with Garmin charts and bloodwork tracking.

### P3 — Future

41. **Remote access** — interact via Discord, Slack, or web interface from any device.
42. **Mobile access** — view tasks, board, and conversations from phone.
43. **Multi-user** — share spaces, assign tasks to people.
44. **Hybrid memory search** — vector embeddings + FTS5 keyword search with temporal decay and diversity reranking. Requires embedding infrastructure.

---

## What Changes From Current System

### Kept
- FastAPI backend + React frontend + SQLite (local-first stack)
- Kanban board UI with drag-and-drop
- Agent execution via Claude SDK
- Memory system (expanded from current key-value to four-tier: semantic, episodic, working, procedural)
- CLI for power-user operations

### Changed
- **Projects → Spaces** — broader concept. A space can be a project, a knowledge base, a CRM, or a simple task list. Not everything is a "project."
- **Task types eliminated** — no more manual/quick/standard distinction. All tracked work is an item (task or record). Views (list, kanban, table) are presentation of the same data — no separate "to-do" entity.
- **Odin becomes the front door** — always-visible AI chat input running on Haiku. Replaces the command bar and the old orchestrator. One interaction model, no memorized commands.
- **Items are universal** — every space has items, viewable as checklist (list view), kanban, or table. Board (stages) is optional. Cross-space task aggregation on Home.
- **Board is optional per space** — knowledge-base and simple spaces show items in list view without stages.
- **Model selection** — Haiku for Odin, Sonnet default for agents, Opus on demand. Per-agent defaults, per-conversation overrides.
- **Conversations become first-class** — lifecycle management (open, close with summary, checkpoint, reopen with context).
- **Data sources** — spaces connect to Google Drive, repos, and API integrations. Not just local files.
- **Permission model rebuilt** — granular per-agent, per-resource, per-operation with three grant levels. Inline and notification approval flows.
- **Home redesigned** — cross-space task list, attention items, Odin chat, active agents.

### Removed
- Manual/Quick/Standard task type distinction
- Separate to-do entity (unified into items with views)
- Command bar (replaced by Odin chat)
- Fast path regex pattern matching (replaced by Odin on Haiku)
- Structured output parsing (TaskResult JSON schema)
- MCP registry as a separate surface
- Morning briefing scheduler (rebuilt properly in P2)
- Discord integration (replaced by P3 remote access)

---

## Resolved Decisions

1. **Spaces, not projects** — broader abstraction. Templates for quick creation (Project, CRM, Knowledge Base, Simple).
2. **Unified item model** — all tracked work is an item (task or record) in a single table. Views (list/kanban/table) are presentation, not data model. Items can be as lightweight as a checkbox title or as structured as a multi-stage deliverable. No separate "to-do" entity, no promotion step. Item linking via many-to-many `item_links` table for associating tasks with records, tasks with tasks, etc. Structural hierarchy via `parent_item_id` for sub-tasks and sub-records.
3. **Odin as front door** — always-visible Haiku-powered chat. No separate command bar. One interaction model. Has its own memory namespace and session lifecycle.
4. **Model stack** — Haiku for Odin, Sonnet for agents (default), Opus on demand. Per-conversation override.
5. **Board is optional** — per-space setting. Knowledge bases don't need Kanban.
6. **Agent creation** — UI form at P0. Agent Builder (conversational creation via Odin) at P1.
7. **Document storage** — Google Drive as primary (P1), local as fallback. Metadata indexing for search. FTS5 for full-text search (P1).
8. **Background monitoring** — status indicator + expandable log stream.
9. **Cross-space visibility** — Home shows attention items first, then active agents, then space list, then open tasks. First-run experience with onboarding prompts.
10. **Remote access** — P3. Architecture is API-first.
11. **Permissions model** — granular (resource x operation x grant level). Inline approval in active conversations, Attention Items on Home for background/automation. No timeout anywhere — agents wait indefinitely. Pending approvals always visible on Home dashboard with badge count.
12. **Execution model** — Claude Max subscription via Claude Agent SDK. Upgrade to v0.1.51+. Use `query()` with `resume`, not `ClaudeSDKClient`.
13. **Subspaces** — deferred (P2). Schema includes `parent_space_id` for future use.
14. **Manual daily backup** for P0. Automated daily backup is P1.
15. **Automations** — cron-based (P1), event-based (P2). Proactive system is a set of pre-configured automations, not a separate layer. Automation dashboard for visibility. Max 2 concurrent automation sessions; user conversations take priority. Missed-run detection on startup.
16. **Crash recovery** — on startup, interrupted conversations are detected and surfaced. User can reopen (attempts SDK resume) or close them.
17. **Item provenance** — items track `source_conversation_id` so users can trace where work came from.
18. **SSE architecture** — single multiplexed endpoint (`/api/v1/events`) for all streaming. Frontend demultiplexes by source ID.
19. **Four-tier memory** — semantic (facts), episodic (summaries), working (board state), procedural (behavioral rules). Procedural memory is injected into the system prompt section with high priority. Based on the CoALA cognitive memory framework adopted independently by Letta/MemGPT, LangMem, and CrewAI.
20. **Agent-managed memory** — agents have explicit tools to save, update, and delete facts. System prompts instruct agents to use these proactively. Pre-compaction flush makes fact saving mandatory before any context compression.
21. **Temporal fact management** — facts carry `valid_from`/`valid_until`. Superseded facts are not deleted; they're timestamped and archived after 90 days. Write-time comparison uses the LLM for semantic matching (ADD/UPDATE/DELETE/NOOP operations per Mem0 pattern).
22. **Memory lifecycle** — hard caps per namespace (50 space, 20 agent, 30 procedural rules). Lowest-scored entries archived on overflow using Ebbinghaus-inspired scoring (importance x decay x access boost). Monthly LLM-driven consolidation with user approval.
23. **Context safety** — pre-compaction flush (mandatory before any summarization) with post-compaction verification, proactive budget enforcement (before LLM calls, not after), observation masking (recent 5-10 turns verbatim during compression, configurable per agent/conversation type), context ordering (high-priority at beginning/end, reference material in middle per "Lost in the Middle" findings).
24. **Summary consolidation** — automated, threshold-triggered at 20 unconsolidated summaries per space. Piggybacks on conversation close. Manual trigger available. Successive consolidation produces one current meta-summary covering full history.
25. **Cross-space search** — conversation and summary search tools accept optional `space_id`. Omitting it searches all spaces the agent has access to (scoped by `agent_spaces`). FTS5 replaces LIKE matching for all text search.
26. **Mid-task steering** — background delegation uses a managed turn loop where the session manager auto-continues between agent turns. A steering queue accepts user corrections, which are injected at the next turn boundary via the SDK's `query(resume=session_id)` mechanism. No mid-tool-call injection required (the SDK doesn't support this). Agent system prompts instruct incremental work, creating natural turn boundaries for steering and progress tracking.
27. **Workflow tracking** — background tasks track step-level progress with parent-child hierarchies. Failed tasks show where they stopped. Audit detects stale (>10min queued) and stuck (>30min running) tasks.
28. **Space layouts** — widget-based, config-driven. Layout stored per space as an ordered list of widget configurations in a `space_widgets` table. Templates provide defaults that match the current fixed layouts. Agents have MCP tools to modify layouts. Core widgets (kanban, table, task list, conversations) in P1. Extended widgets (charts, data feeds, stat cards) in P2 alongside data source integrations. Settings-panel layout editor first; drag-and-drop widget repositioning within the space view is a later enhancement.

---

## Architecture Principles

1. **API-first** — every capability is accessible via API. Future clients plug in without rearchitecting.
2. **Conversations are the core abstraction** — the system is built around persistent, context-rich conversations that produce work as a side effect.
3. **Context is assembled, not manually fed** — agents get what they need automatically. Token budgets, relevance ranking, summarization, and on-demand search for historical context.
4. **One interaction model** — Odin chat is the universal entry point. No memorized commands, no mode switching. Conversations for deep work. Items (list, board, table) for tracking.
5. **Progressive autonomy** — agents start supervised, earn trust, get more autonomy.
6. **Storage is external** — Google Drive for documents, SQLite for structured data, repos for code, APIs for live data. OpenLoop is the orchestration layer.
7. **Claude Max, not API** — all agent execution via Claude Agent SDK under Max subscription. Haiku for Odin, Sonnet/Opus for agents.
8. **Granular security by default** — per-agent, per-resource, per-operation permissions. No agent gets broad access by default.
9. **Agents improve over time** — procedural memory captures corrections, write-time dedup keeps knowledge clean, lifecycle management prevents bloat, and retrieval scoring surfaces the right context. The system gets smarter with use, not just bigger.
