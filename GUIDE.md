# OpenLoop User Guide

OpenLoop is a personal AI command center. You manage all your work — tasks, CRM pipelines, knowledge bases, and AI agent conversations — from one interface. Agents work for you: they track your projects, manage your data, handle research, and run on schedules while you focus on what matters.

This guide has two parts. **Part 1** gets you working in the system in 10 minutes. **Part 2** explains how everything works under the hood.

---

# Part 1: Getting Started

## Starting the App

```bash
make dev
```

This starts the backend (port 8010) and frontend (port 5173). Open `http://localhost:5173` in your browser.

If this is your first time, you'll also need to run the database migrations and optionally seed demo data:

```bash
make migrate      # set up the database
python scripts/seed.py   # optional — creates sample spaces, agents, items
```

## The Home Screen

Home is your morning dashboard. From top to bottom:

1. **Odin** — the chat bar at the bottom of the screen. Type anything in natural language. Odin handles simple requests directly and routes complex work to the right agent.
2. **Attention items** — things that need you right now: pending approvals, overdue tasks, automation failures.
3. **Active agents** — background tasks currently running, with live status.
4. **Space list** — all your spaces with quick access.
5. **Cross-space tasks** — every open task across all spaces.

If there are pending approvals or unread notifications, you'll see a count in the browser tab title: `(3) OpenLoop`.

## Spaces

A space is a container for related work. Think of it as a workspace for a specific domain — a project, a set of clients, a knowledge base, or just a personal task list.

Create a space from the Home screen. Pick a template:

| Template | Best for | Default view | Has board? |
|----------|----------|-------------|------------|
| **Project** | Work with stages (Idea → Done) | Kanban | Yes |
| **CRM** | Tracking people, leads, records | Table | Yes |
| **Knowledge Base** | Documents, notes, research | Documents | No |
| **Simple** | Personal tasks, checklists | List | No |

Templates are starting points — you can add or remove features later through the Space Settings panel (gear icon in the space header).

### What's inside a space

- **Items** — all tracked work. Tasks (things to do) and records (things to track, like contacts or leads). Viewable as a list, kanban board, or table.
- **Conversations** — persistent chat threads with AI agents. This is where most work actually happens.
- **Documents** — files, uploaded or linked from Google Drive.
- **Memory** — facts and knowledge the agents have learned about this space.

## Items: Tasks and Records

Everything you track is an **item**. There are two types:

**Tasks** are work to be done. They can be as simple as "Call dentist" (just a title and a checkbox) or as structured as a multi-stage deliverable with description, priority, due date, and agent assignment.

**Records** are entities you track — a person, a company, a lead, a bug. Records have custom fields and can be linked to tasks.

### Views

The same data, shown differently:

- **List view** — checklist. Checkbox, title, stage dropdown. Done items hidden by default (toggle to show). This is the default for Simple spaces.
- **Kanban view** — drag items through stage columns. Default for Project spaces.
- **Table view** — sortable/filterable columns. Default for CRM spaces.

You can switch views using the toggle in the space header.

### Done/stage sync

Checking a task "done" in list view automatically moves it to the Done stage on the kanban. Dragging to Done on the kanban checks the box. Moving out of Done unchecks it. This sync only applies to tasks — records use stages for pipeline tracking without done/not-done semantics.

### Item linking

Items can be linked to each other. A task can be linked to a contact record ("Call Sarah" linked to Sarah's record). Links are many-to-many and separate from parent-child hierarchy.

## Agents and Conversations

An agent is a configured AI with a specific role. Examples: a Recruiting Agent that manages your pipeline, a Code Agent that works on your codebase, a Research Agent that searches the web.

### Starting a conversation

1. Click "New Conversation" in a space
2. Pick an agent
3. Pick a model (Sonnet is default — use Opus for complex planning)
4. Start chatting

Conversations are persistent. You can close them when done (the system saves a summary), and start new ones later. The agent in the new conversation gets the summaries from prior conversations, so context carries over.

### Background delegation

Tell an agent to "go do X" and it works in the background. You'll see it in the Active Agents section on Home with a live progress indicator. Multi-step tasks show which step the agent is on.

### Mid-task steering

If a background agent is going down the wrong path, you can send it a correction. The agent finishes its current step, reads your message, and adjusts course. No restart needed.

### Odin

Odin is the system-level AI. Always available at the bottom of the screen. It runs on Haiku for fast responses (~1-2 seconds).

Use Odin for:
- Quick actions: "Add a task: call dentist"
- Questions: "What's on my plate today?"
- Navigation: "Open the recruiting agent"
- Agent creation: "I need an agent that can manage my health data" (Odin delegates to the Agent Builder)

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `/` | Focus the Odin input |
| `Escape` | Close any open panel or modal |
| `n` | New item (when in a space) |
| `Ctrl+K` | Open global search |
| `?` | Show shortcuts help overlay |

## Search

Press `Ctrl+K` to open global search. It searches across conversations, documents, memory entries, and summaries using full-text search. Results are grouped by type and ranked by relevance.

## Automations

Automations run agents on a schedule. Navigate to Automations from the sidebar.

To create one:
1. Click "New Automation"
2. Pick a schedule (Daily, Weekly, Monthly, or custom cron)
3. Pick an agent and space
4. Write the instruction the agent should follow
5. Enable it

The system comes with three pre-built templates (disabled by default):
- **Daily Task Review** — scans for overdue and stuck tasks every morning
- **Stale Work Check** — flags items untouched for 7+ days every Monday
- **Follow-up Reminder** — checks CRM records with past-due follow-ups daily

To activate templates: `make register-automations`, then enable them in the dashboard.

## Permissions

Agents operate under a permission system. Each agent has per-resource, per-operation permissions:

- **Always allowed** — agent acts without asking
- **Requires approval** — agent pauses and asks. You'll see it in Attention Items on Home.
- **Never allowed** — blocked entirely

Permissions are set during agent creation and editable in the Agents page. There's no timeout on approvals — the agent waits until you respond.

## Backups

```bash
make backup          # local copy to data/backups/
make backup-gdrive   # upload to Google Drive (first run sets up OAuth)
```

If you haven't backed up in 24 hours, the Home dashboard shows a subtle reminder.

## Settings

Navigate to Settings from the sidebar. Currently has:
- **Theme** — light/dark toggle
- **Color palette** — Slate+Cyan, Warm Stone+Amber, or Neutral+Indigo

---

# Part 2: How It Works

## Architecture Overview

```
Browser (React)  ←→  FastAPI Backend  ←→  Claude Agent SDK  ←→  Claude (Anthropic)
                          ↕
                    SQLite Database
                    Local Files
```

OpenLoop is a coordination layer. It doesn't do AI work — it manages the plumbing: routing messages, storing state, assembling context, enforcing permissions, and tracking what agents are doing. The actual intelligence comes from Claude via the Agent SDK.

**Tech stack:** Python 3.12, FastAPI, SQLAlchemy, SQLite, Alembic (migrations). React 19, Tailwind CSS v4, Vite, Zustand, React Query. Claude Agent SDK.

**Communication:** HTTP REST for CRUD operations. Server-Sent Events (SSE) for streaming agent responses and real-time updates. The frontend opens a persistent SSE connection to receive events (agent responses, background task progress, permission requests, notifications).

## Data Model

### Spaces

A space is a row in the `spaces` table. Key fields: `name`, `template` (project/crm/knowledge_base/simple), `board_enabled`, `board_columns` (JSON array of stage names), `default_view`, `custom_field_schema` (JSON — defines CRM-style fields for records).

All spaces have `board_columns` — even Simple and Knowledge Base spaces get `["todo", "in_progress", "done"]`. This eliminates null-checking throughout the codebase. The `board_enabled` flag controls whether the kanban view is meaningful.

### Items

The `items` table stores all tracked work. Key fields:

- `item_type` — "task" or "record"
- `title`, `description`, `priority` (1-4), `due_date`
- `stage` — which board column the item is in (nullable for Simple spaces)
- `is_done` — boolean, synced with stage for tasks
- `space_id` — which space this belongs to
- `parent_item_id` — for sub-task/sub-record hierarchy
- `assigned_agent_id` — which agent is responsible
- `custom_fields` — JSON blob for CRM-style data

The `item_links` table provides many-to-many associations between items (e.g., a task linked to a contact record).

### Conversations and Messages

A `conversation` belongs to a space and an agent. Has `status` (active, closed, interrupted), a `model_override`, and a `session_id` for resuming the SDK session.

`conversation_messages` stores the full history: role (user/assistant/tool), content, tool calls, timestamps.

`conversation_summaries` are generated when conversations close. These carry context forward to future conversations. Key fields: `summary` (text), `decisions` (JSON array), `open_questions` (JSON array), `is_checkpoint` (mid-conversation vs. final), `is_meta_summary` (consolidated overview), `consolidated_into` (FK to the meta-summary that consumed this one).

### Agents

The `agents` table: `name`, `system_prompt` (inline text or loaded from a skill file on disk), `model` (default: sonnet), `skill_path` (optional — points to a `SKILL.md` file).

`agent_permissions` define the permission matrix: `resource`, `operation` (read/create/edit/delete/execute), `grant_level` (always/approval/never).

### Memory

`memory_entries` stores semantic facts. Namespaced — `space:{space_id}` for space-scoped facts, `agent:{agent_id}` for agent-scoped facts. Key fields:

- `namespace`, `key`, `value`
- `importance` (0.0–1.0) — how important this fact is
- `access_count` — how often it's been retrieved
- `last_accessed` — for recency scoring
- `valid_from`, `valid_until` — temporal range (null `valid_until` means "still true")
- `archived_at` — soft archive (excluded from active retrieval)
- `category`, `tags`, `source`

`behavioral_rules` stores procedural memory: `rule` (text), `confidence` (0.0–1.0), `apply_count`, `is_active`, `source_type` (correction/validation).

### Automations

`automations` table: `name`, `cron_expression`, `agent_id`, `space_id`, `instruction`, `enabled`, `model_override`.

`automation_runs` tracks each execution: `status`, `started_at`, `completed_at`, `result`.

### Notifications

`notifications` table: `type` (enum), `title`, `body`, `read`, `space_id`, `conversation_id`, `automation_id`. Used for approval requests, automation failures, memory consolidation results, and system messages.

## Context Assembly

When an agent starts working, the **context assembler** builds its prompt from multiple sources. This is one of the most important pieces of the system — it determines what the agent knows.

The assembled context follows an attention-optimized order:

1. **Beginning (highest attention):**
   - Agent identity and system prompt (or SKILL.md content)
   - Behavioral rules (procedural memory) — highest-confidence rules first
   - Tool documentation

2. **Middle (reference material):**
   - Meta-summary (if one exists for the space)
   - Recent conversation summaries (unconsolidated, most recent first)
   - Semantic facts (scored by importance × recency × access frequency)

3. **End (closest to user's message, high attention):**
   - Current board state (items, stages, recent changes)
   - Working memory (today's tasks, upcoming deadlines)

The total budget is ~8,000 tokens. Facts are scored using an Ebbinghaus-inspired decay formula:

```
score = importance × decay_factor × (1 + access_boost)
```

Where `decay_factor` decreases with days since last access (but slower for high-importance facts) and `access_boost` increases with retrieval count. This means a frequently-referenced architectural decision from 3 months ago outranks yesterday's meeting note.

## Memory Lifecycle

Memory doesn't just accumulate — it's actively managed:

### Write-time dedup

Every time a fact is saved, the system compares it against existing facts in the same namespace using Haiku. The LLM decides: ADD (new), UPDATE (modify existing), DELETE (supersede old), or NOOP (already captured). This prevents bloat at the source.

### Temporal facts

When a new fact contradicts an existing one, the old fact's `valid_until` is set to now. Both facts remain in the database — the old one is just marked as historical. Agents can query historical facts with date-range search.

### Scored retrieval

During context assembly, facts are scored by importance, recency, and access frequency. Top-scored facts fill the token budget. Low-importance, rarely-accessed facts naturally fade from context.

### Namespace caps

Each space can have at most 50 active facts. Each agent can have 20 active facts and 30 active behavioral rules. When a cap is hit, the lowest-scored entry is archived (soft-deleted — still searchable, but excluded from context).

### Auto-archival

A daily background job archives facts that were superseded 90+ days ago (their `valid_until` was set more than 90 days in the past).

### Rule demotion

Behavioral rules with low confidence (< 0.3) after 10+ applications are automatically deactivated. This is evaluated lazily during context assembly — no separate job needed.

### Monthly consolidation

A monthly background job reviews each space's active facts using Haiku. It produces a report: proposed merges (related facts that should combine), contradictions, and stale entries (zero access in 60+ days). The report is surfaced as a notification — the system never merges or deletes without your approval. You can also trigger consolidation manually from Space Settings → Memory tab.

### Summary consolidation

When a space accumulates 20+ conversation summaries, the system auto-generates a meta-summary — a condensed overview covering the full history. Individual summaries are marked as consolidated (still searchable, but replaced in context assembly by the meta-summary). Successive rounds produce new meta-summaries that absorb the old one. You can trigger this manually from Space Settings → History tab or via the API.

## Context Safety

Long conversations risk losing information when context is compressed. Three mechanisms prevent this:

1. **Mandatory pre-compaction flush** — before any summarization, the agent is prompted to save important unsaved facts to persistent memory. Even if the summary is lossy, specific decisions survive as facts.

2. **Proactive budget enforcement** — the system checks context size *before* each LLM call (not after). If it exceeds 70%, compression happens first at a clean turn boundary. You never see a "context almost full" warning that arrives too late.

3. **Observation masking** — during compression, the most recent 5-10 exchanges are kept verbatim. Only older history is summarized. The immediate working context stays intact.

## Session Manager

The session manager bridges OpenLoop conversations with Claude SDK sessions.

**Interactive conversations:** Your message is sent via `query(resume=session_id)`. The SDK resumes the session, the agent responds, and the response streams back via SSE token by token.

**Background delegation:** Uses a managed turn loop instead of fire-and-forget. The agent works in discrete turns (max 20). Between turns, the session manager checks a steering queue for user corrections. If a correction exists, it's injected as the next message. Otherwise, the agent auto-continues. The agent signals completion with `TASK_COMPLETE`.

**Rate limit handling:** If the SDK returns a 429, the system retries with exponential backoff (30s, 60s, 120s, max 3 retries), creates a notification, and publishes an SSE event so the UI can show status.

**Crash recovery:** On startup, the system marks any conversations with status "active" that don't have a running process as "interrupted" and creates notifications.

**Graceful shutdown:** On SIGTERM, active interactive sessions are closed cleanly (summaries saved) with a 30-second timeout.

## MCP Tools

Agents interact with the system through MCP (Model Context Protocol) tools. These are async functions decorated with `@tool` that create short-lived DB sessions for each operation.

Key tool categories:

- **Item management** — `create_task`, `complete_task`, `list_tasks`, `create_item`, `update_item`, `archive_item`
- **Item linking** — `link_items`, `unlink_items`, `get_linked_items`
- **Memory** — `save_fact`, `update_fact`, `recall_facts`, `delete_fact`
- **Behavioral rules** — `save_rule`, `confirm_rule`, `override_rule`, `list_rules`
- **Search** — `search_conversations`, `search_summaries` (cross-space capable)
- **Layout** — `get_space_layout`, `add_widget`, `update_widget`, `remove_widget`, `set_space_layout`
- **Delegation** — `delegate_task`, `update_task_progress`
- **Drive** — `read_drive_file`, `list_drive_files`, `create_drive_file`

Odin gets all tools. Space-scoped agents get tools filtered to their accessible spaces.

## Space Layouts

Each space has a configurable widget-based layout stored in the `space_widgets` table. Widgets have a type, size (small/medium/large/full), position, and optional config JSON.

Core widget types: `task_list`, `kanban_board`, `data_table`, `conversation_sidebar`, `document_panel`.

Templates create sensible defaults (Project gets task list + kanban + conversations). You can reconfigure through the Space Settings → Layout tab, or tell an agent to redesign the layout.

## SSE (Server-Sent Events)

The frontend maintains a persistent SSE connection to `GET /api/v1/events`. All real-time updates flow through this:

- `conversation_message` — streaming agent response tokens
- `background_progress` — step updates from background tasks
- `permission_request` — agent needs approval
- `notification` — system notification
- `rate_limited` — SDK rate limit encountered
- `steering_received` — confirmation that a steering message was queued

Events include sequential IDs. If the connection drops, the browser auto-reconnects with `Last-Event-ID` and missed events are replayed from an in-memory buffer (last 100 events).

## Background Services

Three asyncio background loops run alongside the web server:

1. **Automation Scheduler** (60s interval) — evaluates cron expressions, fires automations as background tasks, detects missed runs on startup.
2. **Task Monitor** (60s interval) — detects stale tasks (queued >10 min) and stuck tasks (running >30 min), creates notifications.
3. **Lifecycle Scheduler** (60s interval) — daily fact archival, monthly memory consolidation.

All three use the same pattern: asyncio task started in the app lifespan, cancelled on shutdown.

## File Structure

```
backend/openloop/
├── agents/             # Session manager, context assembler, MCP tools, schedulers
├── api/
│   ├── routes/         # One file per domain (spaces, items, memory, events, etc.)
│   └── schemas/        # Pydantic models, one file per domain
├── db/
│   └── models.py       # All SQLAlchemy ORM models (single file)
├── services/           # Business logic — stateless module functions
└── main.py             # FastAPI app, lifespan, router registration

frontend/src/
├── api/                # API client, generated types
├── components/
│   ├── ui/             # Reusable components (Button, Input, Modal, Panel, etc.)
│   ├── layout/         # App shell, sidebar, connection status
│   ├── space/          # Space-specific components (kanban, table, settings, etc.)
│   └── home/           # Home page components
├── hooks/              # Custom hooks (SSE, keyboard shortcuts, document title)
├── pages/              # Page-level components (Home, Space, Agents, etc.)
├── stores/             # Zustand state stores
└── utils/              # Utilities (dates, etc.)

contract/
└── enums.py            # Shared enums (used by both backend and frontend codegen)

scripts/
├── seed.py             # Demo data
├── backup_local.py     # Local SQLite backup
├── backup_gdrive.py    # Google Drive backup
└── register_automation_templates.py

data/                   # SQLite database, artifacts, backups (gitignored)
agents/skills/          # Agent skill definitions (SKILL.md files)
```

## API Overview

All endpoints are under `/api/v1/`. The OpenAPI schema is exported to `contract/openapi.json` and TypeScript types are generated from it.

Key endpoint groups:

| Prefix | Purpose |
|--------|---------|
| `/spaces` | Space CRUD, layout, consolidation |
| `/items` | Item CRUD, move, archive, links |
| `/conversations` | Start, message, close, reopen, steer |
| `/odin/message` | Send message to Odin |
| `/events` | SSE streaming endpoint |
| `/agents` | Agent CRUD, status, permissions |
| `/automations` | Automation CRUD, trigger, run history |
| `/memory` | Memory entry CRUD, archive, health, consolidation |
| `/documents` | Document management, upload, content |
| `/drive` | Google Drive integration |
| `/search` | Global FTS5 search |
| `/notifications` | List, read, mark-all-read |
| `/system/backup-status` | Backup status |
| `/home/dashboard` | Cross-space dashboard data |

## Development Commands

```bash
make dev              # Start both backend and frontend
make dev-backend      # Start backend only (port 8010)
make dev-frontend     # Start frontend only (port 5173)
make test             # Run all backend tests (pytest)
make lint             # Check linting (ruff)
make lint-fix         # Auto-fix lint issues
make migrate          # Run Alembic database migrations
make seed             # Seed demo data
make generate-types   # Export OpenAPI schema → generate TypeScript types
make backup           # Local SQLite backup
make backup-gdrive    # Google Drive backup
make register-automations  # Register pre-built automation templates
```

## Google Drive Setup

For Drive backup and integration:

1. Go to https://console.cloud.google.com/
2. Create a project, enable the Google Drive API
3. Create OAuth 2.0 credentials (Desktop app type)
4. Download as `credentials.json` in the project root
5. Run `make backup-gdrive` — first run opens a browser for OAuth consent
6. Token is saved to `data/.gdrive-token.json` for future runs

## What's Automated vs. What Needs Setup

**Works out of the box:**
- Home dashboard, spaces, items, conversations, Odin
- Agent conversations with streaming
- Background delegation with steering
- Search (Ctrl+K)
- Memory (four tiers, write-time dedup, scored retrieval)
- Keyboard shortcuts, toasts, loading states, empty states

**Needs one-time setup:**
- `make migrate` — initialize the database
- Google Drive credentials — for Drive backup and integration
- Agent creation — create agents for your domains (via UI or Agent Builder)
- Automation templates — `make register-automations` then enable in the dashboard

**Runs automatically after setup:**
- Memory lifecycle (daily archival, monthly consolidation)
- Summary consolidation (at 20+ summaries per space)
- Task monitoring (stale/stuck detection)
- Enabled automations (on their cron schedules)
- Context assembly, dedup, scoring, compression — all transparent
