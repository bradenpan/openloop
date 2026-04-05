# OpenLoop: Integration Capabilities (v1)

**Status:** Approved — Phase 12 (Calendar), Phase 13 (Gmail), and Phase 14 (Integration Builder) all built. Implementation plan in [IMPLEMENTATION-PLAN-PHASE12.md](IMPLEMENTATION-PLAN-PHASE12.md).
**Companion documents:** CAPABILITIES.md (core capabilities), ARCHITECTURE-PROPOSAL.md (system architecture), FUTURE-CAPABILITIES.md (long-term roadmap)

---

## Overview

This document specifies three integration capabilities for OpenLoop:

1. **Google Calendar integration** — agents read/write calendar events, create invites, surface schedule awareness
2. **Gmail integration** — agents read/triage inbox, draft replies, surface items needing attention
3. **Integration Builder agent** — conversational agent that helps users connect arbitrary APIs to spaces

Calendar and Gmail are **direct implementations** using the existing Google OAuth infrastructure (same `credentials.json`/`token.json` as Drive). The Integration Builder is an **agent** built via the Agent Builder, handling simpler REST API integrations that don't require OAuth server-side flows.

---

## Design Principles

1. **Agent capabilities are the priority.** The value is in agents that understand your schedule and inbox — not in rebuilding Google's UIs.
2. **Simple widgets, click-through for detail.** OpenLoop shows summaries and actionable items. Clicking opens the real thing in Google Calendar or Gmail.
3. **Cross-space data sources.** Calendar and email are system-level — not bound to any single space. Any space can access them (default: opted in). Configurable per-space.
4. **Same OAuth infrastructure.** Calendar and Gmail use the same Google OAuth app as Drive. Adding scopes, not adding auth systems.
5. **Permission-controlled actions.** Destructive actions (send email, create event with invites) start as "requires approval." Users adjust per-agent as trust builds.

---

## 1. Google Calendar Integration

### What Agents Can Do

Full read/write access to Google Calendar via MCP tools:

| Tool | Operation | Default Permission |
|---|---|---|
| `list_calendar_events(start, end, calendar_id?)` | Read upcoming/past events | Always allowed |
| `get_calendar_event(event_id)` | Read event detail (attendees, description, location, conferencing) | Always allowed |
| `create_calendar_event(title, start, end, attendees?, description?, location?)` | Create event, optionally send invites | Requires approval |
| `update_calendar_event(event_id, **fields)` | Modify event (reschedule, add attendees, update description) | Requires approval |
| `delete_calendar_event(event_id)` | Delete/cancel event | Requires approval |
| `find_free_time(start, end, duration_minutes)` | Find available slots in a date range | Always allowed |
| `list_calendars()` | List all calendars the user has access to | Always allowed |

**Invite behavior:** When `create_calendar_event` includes `attendees`, Google Calendar handles the invite emails automatically. The agent doesn't send emails directly — it creates the event with attendees and Google does the rest. This is important: the "send invite" action is really "create event with attendees," which is why it requires approval.

**Recurring events:** Read support for recurring events (expand instances in a date range). Write support creates single events only — modifying recurring event series is too error-prone for agent use initially.

### Data Model

Calendar is a **cross-space data source** — system-level, not bound to a space.

```
DataSource (new record):
  source_type: "google_calendar"
  name: "Google Calendar"
  config: {
    "calendar_ids": ["primary", ...],  # which calendars to include
    "sync_window_days": 30,            # how far ahead to cache
    "default_calendar_id": "primary"   # where agents create events
  }
  space_id: null                       # cross-space — not bound to a space
```

**Event cache table** (new):
```sql
CREATE TABLE calendar_events (
    id TEXT PRIMARY KEY,               -- UUID
    google_event_id TEXT UNIQUE,       -- Google's event ID
    calendar_id TEXT NOT NULL,         -- which calendar
    title TEXT NOT NULL,
    description TEXT,
    location TEXT,
    start_time DATETIME NOT NULL,
    end_time DATETIME NOT NULL,
    all_day BOOLEAN DEFAULT FALSE,
    attendees JSON,                    -- [{email, name, response_status}]
    organizer JSON,                    -- {email, name, self}
    conference_data JSON,              -- Meet/Zoom link info
    status TEXT DEFAULT 'confirmed',   -- confirmed, tentative, cancelled
    recurrence_rule TEXT,              -- RRULE string if recurring
    html_link TEXT,                    -- click-through URL to Google Calendar
    etag TEXT,                         -- for sync conflict detection
    synced_at DATETIME,
    created_at DATETIME,
    updated_at DATETIME
);
```

**Why cache?** Agents need event data in context assembly. Hitting the Google Calendar API on every context assembly call would be slow and rate-limited. The cache syncs periodically (every 15 minutes via automation) and on-demand when an agent explicitly calls `list_calendar_events`.

**Cross-space access:** The `DataSource` record has `space_id=null`. A new `system_data_sources` concept — data sources not bound to any space. Any agent with calendar permission can access calendar MCP tools. Per-space opt-out is a space setting (`excluded_system_sources: ["google_calendar"]`).

### Context Assembly

Calendar data feeds into the **working memory tier** (end section, high attention):

```
── CALENDAR (next 48 hours) ──────────────
Today:
  09:00-09:30  Recruiting sync (Alice, Bob) [Meet link]
  11:00-12:00  Product review — OpenLoop Phase 12
  14:00-14:30  1:1 with Sarah Chen [Meeting brief: /recruiting/conv/23]
Tomorrow:
  10:00-11:00  Candidate interview: James Park [No meeting brief yet]
  15:00-16:00  Sprint planning
──────────────────────────────────────────
```

Budget: ~500 tokens from the existing ~1500 token working memory allocation. Only included when the space has calendar access (default: yes).

Meeting briefs are linked by convention: if a document or conversation summary exists with the event title or attendee names as keywords, the context assembler includes a pointer.

### Backend

**New files:**
- `backend/openloop/services/gcalendar_client.py` — Google Calendar API client (same pattern as `gdrive_client.py`). Uses existing `credentials.json`/`token.json`. Adds scopes: `calendar.readonly` + `calendar.events`.
- `backend/openloop/services/calendar_integration_service.py` — sync logic, event CRUD, free time calculation.
- `backend/openloop/api/routes/calendar.py` — API endpoints.

**New API endpoints:**
```
GET  /api/v1/calendar/auth-status          → {"authenticated": bool, "scopes": [...]}
GET  /api/v1/calendar/events               → paginated event list (query params: start, end, calendar_id)
GET  /api/v1/calendar/events/{id}          → event detail
POST /api/v1/calendar/events               → create event
PATCH /api/v1/calendar/events/{id}         → update event
DELETE /api/v1/calendar/events/{id}        → delete event
POST /api/v1/calendar/sync                 → trigger manual sync
GET  /api/v1/calendar/free-time            → find available slots (query params: start, end, duration)
GET  /api/v1/calendar/calendars            → list available calendars
```

**OAuth scope addition:** The existing Google OAuth flow (`gdrive_client.py`) requests Drive scopes. Calendar integration adds `https://www.googleapis.com/auth/calendar.events` (read/write events) and `https://www.googleapis.com/auth/calendar.readonly` (list calendars). The user re-authenticates once to grant the new scopes. Token refresh handles the rest.

**Sync automation:** A system automation (not user-configured) syncs calendar events every 15 minutes. Runs as a lightweight background task — no agent session needed, just API calls. On startup, does an initial full sync of the configured window (default: 30 days ahead, 7 days behind).

### Frontend

**Two UI surfaces:**

#### 1. Home Dashboard — Calendar Widget

A new widget type in the Home dashboard (alongside attention items, active agents, space list):

```
┌─ Today's Schedule ──────────────────────────┐
│                                              │
│  09:00  Recruiting sync                      │
│         Alice, Bob · Google Meet             │
│         [📋 Brief ready]                     │
│                                              │
│  11:00  Product review — OpenLoop Phase 12   │
│         No brief                             │
│                                              │
│  14:00  1:1 with Sarah Chen                  │
│         [📋 Brief ready]                     │
│                                              │
│  ─── Tomorrow ───                            │
│                                              │
│  10:00  Candidate interview: James Park      │
│         [⚠ No brief — prepare?]              │
│                                              │
│  3 more events this week →                   │
│                                              │
└──────────────────────────────────────────────┘
```

**Behavior:**
- Shows today's events + tomorrow's events by default
- "This week" expandable section
- Each event: time, title, attendees (abbreviated), conference link
- Meeting brief indicator: links to the conversation/document if one exists, "prepare?" prompt if not (clicking could trigger a meeting prep agent)
- Clicking the event title opens it in Google Calendar (`html_link`)
- Compact — designed to sit alongside existing Home widgets, not dominate

#### 2. Space Widget — Calendar Events

A new widget type (`calendar_events`) available in the space layout editor:

```
┌─ Upcoming Events ────────────────────────┐
│  Filter: This space's agents/topics       │
│                                           │
│  Today 14:00  1:1 with Sarah Chen        │
│  Tomorrow 10:00  Interview: James Park   │
│  Thu 15:00  Sprint planning              │
│                                           │
│  Show all calendar →                     │
└───────────────────────────────────────────┘
```

**Behavior:**
- Optional per-space — added via layout editor like any other widget
- Can be filtered: all events, or events relevant to the space (keyword match on event titles/attendees against space items and agent names)
- Compact list view. Click opens in Google Calendar.
- "Brief ready" / "No brief" indicators same as Home widget

**No calendar grid view in v1.** A `@fullcalendar/react` calendar grid widget is a planned future enhancement — it's feasible with the library but not in the initial build.

#### 3. Sidebar Navigation

New top-level sidebar item: **Calendar**

Clicking opens a dedicated Calendar page (`/calendar`) showing:
- Full event list (scrollable, grouped by day)
- Week view (7-day column layout — simpler than a full calendar grid)
- Filter by calendar
- Each event expandable to show attendees, description, conference link, meeting brief link
- "Sync now" button

This is the "full view" that the compact Home/Space widgets link to. Still not Google Calendar — it's a structured list/week view built with OpenLoop's design system. Click-through to Google Calendar for editing.

---

## 2. Gmail Integration

### What Agents Can Do

Read + triage + draft via MCP tools. Send requires approval.

| Tool | Operation | Default Permission |
|---|---|---|
| `list_emails(query?, label?, max_results?)` | Search inbox (Gmail search syntax) | Always allowed |
| `get_email(message_id)` | Read full email thread | Always allowed |
| `get_email_headers(message_id)` | Read headers only (faster, for triage) | Always allowed |
| `label_email(message_id, add_labels?, remove_labels?)` | Add/remove labels (for sorting) | Always allowed |
| `archive_email(message_id)` | Archive (remove from inbox) | Always allowed |
| `mark_email_read(message_id)` | Mark as read | Always allowed |
| `draft_email(to, subject, body, reply_to?, cc?, bcc?)` | Create draft (does NOT send) | Always allowed |
| `send_email(draft_id)` | Send an existing draft | Requires approval |
| `send_reply(message_id, body)` | Reply to a thread | Requires approval |
| `get_inbox_stats()` | Unread count, label counts, oldest unread | Always allowed |

**Draft workflow:** Agents create drafts, never send directly. The user reviews the draft (in the conversation panel where the agent shows what it wrote, or in Gmail) and either approves the send via OpenLoop's approval system or sends manually from Gmail. As trust builds, the user can change `send_email` and `send_reply` to "always allowed."

**Label-based triage:** The primary agent workflow for email is triage — reading new emails, categorizing them (needs response, FYI, newsletter, spam), labeling them, and surfacing the important ones. OpenLoop creates a set of triage labels in Gmail (prefixed `OL/` to avoid conflicts): `OL/Needs Response`, `OL/FYI`, `OL/Follow Up`, `OL/Waiting`, `OL/Agent Processed`. Agents apply these labels. The email widget groups by these labels.

### Data Model

Gmail is a **cross-space data source**, same as calendar.

```
DataSource (new record):
  source_type: "gmail"
  name: "Gmail"
  config: {
    "triage_labels": ["OL/Needs Response", "OL/FYI", "OL/Follow Up", "OL/Waiting"],
    "sync_max_results": 50,
    "exclude_labels": ["SPAM", "TRASH"]
  }
  space_id: null
```

**Email cache table** (new):
```sql
CREATE TABLE email_cache (
    id TEXT PRIMARY KEY,               -- UUID
    gmail_message_id TEXT UNIQUE,      -- Gmail's message ID
    gmail_thread_id TEXT,              -- Gmail's thread ID
    subject TEXT,
    from_address TEXT,
    from_name TEXT,
    to_addresses JSON,                 -- [{email, name}]
    cc_addresses JSON,
    snippet TEXT,                       -- Gmail's preview snippet (plain text)
    labels JSON,                       -- ["INBOX", "UNREAD", "OL/Needs Response"]
    is_unread BOOLEAN DEFAULT TRUE,
    received_at DATETIME NOT NULL,
    gmail_link TEXT,                    -- https://mail.google.com/mail/#inbox/{id}
    synced_at DATETIME,
    created_at DATETIME,
    updated_at DATETIME
);
```

**Why cache headers only?** Email bodies can be huge (HTML, attachments). The cache stores headers + snippet for the widget and triage. When an agent needs the full email body, it calls `get_email(message_id)` which hits the Gmail API directly. No body storage in OpenLoop's DB.

**Sync:** Every 15 minutes (same system automation as calendar). Syncs recent inbox messages (last 50 by default). On-demand when agent calls `list_emails` or `get_inbox_stats`.

### Context Assembly

Email awareness feeds into working memory tier:

```
── EMAIL (inbox summary) ─────────────────
Unread: 12 | Needs Response: 3 | Follow Up: 2
Recent requiring attention:
  • Sarah Chen (2h ago): "Re: Interview schedule for James Park" [Needs Response]
  • Mike Torres (5h ago): "Budget approval needed" [Needs Response]
  • Alice Wang (1d ago): "Q2 planning doc — review?" [Needs Response]
──────────────────────────────────────────
```

Budget: ~300 tokens from the working memory allocation. Summary only — not full emails. Included when the agent has email permission.

### Backend

**New files:**
- `backend/openloop/services/gmail_client.py` — Gmail API client. Adds scopes: `gmail.modify` (read + label + archive + draft + send). Same OAuth flow as Drive/Calendar.
- `backend/openloop/services/email_integration_service.py` — sync logic, triage label management, draft creation.
- `backend/openloop/api/routes/email.py` — API endpoints.

**New API endpoints:**
```
GET  /api/v1/email/auth-status             → {"authenticated": bool}
GET  /api/v1/email/messages                → paginated message list (query params: label, query, unread_only)
GET  /api/v1/email/messages/{id}           → message detail (headers + body)
POST /api/v1/email/messages/{id}/label     → add/remove labels
POST /api/v1/email/messages/{id}/archive   → archive
POST /api/v1/email/messages/{id}/read      → mark read
POST /api/v1/email/drafts                  → create draft
POST /api/v1/email/drafts/{id}/send        → send draft
POST /api/v1/email/sync                    → trigger manual sync
GET  /api/v1/email/stats                   → inbox stats (unread counts by label)
POST /api/v1/email/setup-labels            → create OL/ triage labels in Gmail
```

### Frontend

**Two UI surfaces:**

#### 1. Home Dashboard — Email Widget

```
┌─ Email ──────────────────────��──────────────┐
│                                              │
│  12 unread · 3 need response                 │
│                                              │
│  ── Needs Response ──                        │
│  Sarah Chen · Re: Interview schedule...  2h  │
│  Mike Torres · Budget approval needed    5h  │
│  Alice Wang · Q2 planning doc — revi...  1d  │
│                                              │
│  ── Follow Up ──                             │
│  James Park · Thanks for the info       3d   │
│  Recruiter · Application received       5d   │
│                                              │
│  View all in Gmail →                         │
│                                              │
└──────────────────────────────────────────────┘
```

**Behavior:**
- Groups by OL/ triage labels (configurable — user can reorder, hide categories)
- Each email: sender, subject (truncated), time ago
- Clicking an email opens it in Gmail (`gmail_link`)
- "View all in Gmail" opens Gmail inbox
- Badge count feeds into the existing browser tab badge system

#### 2. Space Widget — Email Feed

A new widget type (`email_feed`) available in the space layout editor:

```
┌─ Related Emails ─────────────────────────┐
│  Filter: Recruiting-related              │
│                                          │
│  Sarah Chen · Interview schedule...  2h  │
│  James Park · Thanks for the info   3d   │
│                                          │
│  View all →                              │
└──────────────────────────────────────────┘
```

- Optional per-space, filterable by keywords/contacts relevant to the space
- Same click-through to Gmail behavior

#### 3. Sidebar Navigation

New top-level sidebar item: **Email**

Clicking opens a dedicated Email page (`/email`) showing:
- Full inbox triage dashboard
- Grouped by OL/ labels with counts
- Expandable threads showing snippet
- Quick actions: archive, mark read, change label (all hit Gmail API directly)
- Search bar (uses Gmail search syntax)
- "Sync now" button
- Click any email to open in Gmail

This is the dashboard view — sorted, categorized, actionable. Not a mail client. You read and reply in Gmail. OpenLoop shows you what needs attention and lets agents help you manage it.

---

## 3. Integration Builder Agent

### What It Is

A specialized agent (built via Agent Builder, registered as a skill) that helps users connect arbitrary REST APIs to OpenLoop spaces. For APIs that use API keys, webhooks, or simple auth — not OAuth flows (those need direct implementations like Calendar/Email/Drive).

### What It Does

User: "I want to pull my Garmin sleep data into my Health space and see weekly trends."

Integration Builder:
1. **Researches the API** — searches for Garmin's API docs, finds the right endpoints, identifies auth requirements
2. **Walks the user through auth** — "You'll need a Garmin Connect API key. Here's how to get one: [steps]. Paste the key here."
3. **Creates the integration:**
   - Registers a `DataSource` in the space (`source_type: "api"`, config with base URL, auth headers, endpoints)
   - Creates an automation that periodically fetches data via `WebFetch`
   - Stores results as items (structured data) or memory entries (facts/trends)
   - Suggests/creates widgets to display the data
4. **Tests it** — runs a test fetch, shows the user what came back, iterates if the format isn't right
5. **Documents it** — saves a memory entry describing what the integration does, how to troubleshoot, where the API key is stored

### Architecture

The Integration Builder doesn't write backend code or create new service files. It uses **existing primitives**:

- **DataSource records** — stores API config (URL, headers, endpoints) in the `config` JSON field
- **Automations** — creates cron automations whose instruction tells an agent to fetch from the API
- **MCP tools** — the fetching agent uses `WebFetch` (already available) to hit the API
- **Items/Memory** — results stored as items (if structured/trackable) or memory entries (if knowledge/facts)
- **Widgets** — suggests adding a `data_table` or `stat_card` widget configured to show the integration's data

This means no dynamic code execution, no runtime plugin loading, no security concerns from agent-generated code. The agent configures existing infrastructure.

### MCP Tools (Integration Builder exclusive)

| Tool | Purpose |
|---|---|
| `create_api_data_source(space_id, name, config)` | Register an API data source with connection config |
| `test_api_connection(data_source_id)` | Fetch from the API and return a sample response |
| `create_sync_automation(data_source_id, cron, instruction)` | Create an automation that syncs data from this API |

These are convenience wrappers — the agent could use existing tools (create data source, create automation), but dedicated tools make the workflow more reliable.

### What It Can Connect

**Good fit (API key + REST):**
- Garmin Connect (health/fitness data)
- Bank feeds / Plaid (financial data)
- Weather APIs
- News/RSS feeds
- Stock/crypto price APIs
- Todoist, Notion, Airtable (simpler APIs with API keys)
- Custom webhooks

**Bad fit (needs OAuth server-side flow):**
- Google services (Calendar, Gmail, Drive) — already have direct implementations
- Slack, Discord (OAuth + webhooks)
- GitHub (OAuth, but has fine-grained PATs that could work)

**Gray area (PAT/token auth, complex APIs):**
- GitHub (personal access tokens work)
- Linear (API keys available)
- Jira (API tokens available)

For the gray area, the Integration Builder can attempt the connection and escalate to the user if it hits complexity it can't handle.

### Skill Definition

Created via Agent Builder, registered at `agents/skills/integration-builder/SKILL.md`:

```yaml
---
name: Integration Builder
description: Helps users connect external APIs and data sources to OpenLoop spaces
model: sonnet
---
```

System prompt covers:
- How to research APIs (use WebSearch to find docs)
- How to guide users through API key acquisition
- How to create data sources, automations, and widgets
- How to test connections and iterate
- Security rules: never store credentials in items/memory, only in DataSource config (which is not agent-readable)

---

## Cross-Space Data Source Architecture

Calendar and Gmail introduce a new concept: **system-level data sources** that aren't bound to any space.

### Changes to Data Model

```sql
-- DataSource.space_id becomes nullable
ALTER TABLE data_sources ALTER COLUMN space_id DROP NOT NULL;

-- New: per-space opt-out for system data sources
CREATE TABLE space_data_source_exclusions (
    space_id TEXT REFERENCES spaces(id) ON DELETE CASCADE,
    data_source_id TEXT REFERENCES data_sources(id) ON DELETE CASCADE,
    PRIMARY KEY (space_id, data_source_id)
);
```

**Behavior:**
- `space_id = null` → system-level data source (calendar, email)
- System data sources are accessible to all agents by default
- Per-space exclusion: a space can opt out of a system data source (e.g., a "Personal" space might exclude work email)
- Space-level data sources (Drive folders, API integrations via Integration Builder) work as before

### MCP Tool Access

When building MCP tools for an agent session, the tool builder:
1. Loads tools for space-level data sources (existing behavior)
2. Loads tools for system-level data sources (new), minus any the space has excluded
3. Permission enforcer applies the agent's permission matrix to all tools regardless of source

### Context Assembly

System data source state (calendar events, email stats) is included in the working memory tier of context assembly. The context assembler:
1. Checks which system data sources exist and aren't excluded for this space
2. For each: pulls summary data (today's events, inbox stats) from cache tables
3. Fits within the existing ~1500 token working memory budget

---

## UI: Sidebar Navigation Changes

Current sidebar:
```
Home
Spaces
  Space 1
  Space 2
  ...
Agents
Automations
Settings
```

With integrations:
```
Home
Calendar          ← new (only shows when calendar is connected)
Email             ← new (only shows when email is connected)
Spaces
  Space 1
  Space 2
  ...
Agents
Automations
Settings
```

Calendar and Email are top-level nav items because they're cross-space. They only appear after the user connects the integration (via agent-driven setup: "connect my calendar").

---

## Setup Flow

### Calendar Setup

User tells Odin: "Connect my Google Calendar"

1. Odin checks if Google OAuth is already authenticated (Drive may have done this)
2. If not authenticated: Odin explains the OAuth flow, provides the auth URL, user completes in browser
3. If authenticated but missing calendar scopes: re-auth with expanded scopes
4. Once authenticated: system creates the `google_calendar` DataSource, runs initial sync
5. Calendar widget appears on Home, Calendar sidebar item appears
6. Odin confirms: "Calendar connected. I can see 15 events this week. Your agents can now access your schedule."

### Email Setup

Same flow, but with Gmail scopes. Additional step: system creates OL/ triage labels in Gmail.

### Integration Builder Setup

User tells Odin: "I want to connect my Garmin data to my Health space"

1. Odin routes to the Integration Builder agent in the Health space
2. Integration Builder researches Garmin's API, walks user through setup
3. Creates data source, automation, and widget
4. Tests the connection, shows sample data
5. Done — data syncs on the configured schedule

---

## Phasing

### Phase A: Calendar Integration (build first)
1. `gcalendar_client.py` — API client with OAuth scope addition
2. `calendar_events` table + `calendar_integration_service.py` — sync, CRUD, free time
3. Calendar MCP tools (7 tools) + permission enforcer mappings
4. API routes (`/api/v1/calendar/*`)
5. Context assembler — calendar data in working memory
6. System sync automation (15-minute cycle)
7. Frontend: Home calendar widget, Calendar page, sidebar nav item, space calendar widget
8. Tests

### Phase B: Gmail Integration (build second)
1. `gmail_client.py` — API client with OAuth scope addition
2. `email_cache` table + `email_integration_service.py` — sync, triage labels, drafts
3. Email MCP tools (10 tools) + permission enforcer mappings
4. API routes (`/api/v1/email/*`)
5. Context assembler — email stats in working memory
6. System sync automation (15-minute cycle)
7. Frontend: Home email widget, Email page, sidebar nav item, space email widget
8. Tests

### Phase C: Integration Builder Agent (build third)
1. Create skill via Agent Builder (`agents/skills/integration-builder/SKILL.md`)
2. Exclusive MCP tools (create_api_data_source, test_api_connection, create_sync_automation)
3. Register agent via `scripts/register_skills.py`
4. Test with a real integration (e.g., a weather API)

### Phase D: Calendar Grid Widget (future enhancement)
1. Add `@fullcalendar/react` dependency
2. New `calendar_grid` widget type — month/week/day views
3. Wire to calendar API, read-only display
4. Add to widget registry and layout editor

---

## Implementation Notes (Phase 12 Build)

Resolved during implementation — deviations from the original spec:

1. **OAuth flow:** Shared `google_auth.py` module with incremental authorization. Adding calendar scopes does not invalidate existing Drive tokens. Both `gcalendar_client.py` and `gdrive_client.py` use the same auth module.
2. **Setup endpoint added:** `GET /api/v1/calendar/setup` — returns setup status (auth state, sync state, next steps). Not in the original spec; needed for the frontend setup flow to guide users through OAuth + first sync.
3. **Integrations auth endpoints added:** `GET /api/v1/integrations/auth-status` (OAuth status for all integrations) and `GET /api/v1/integrations/auth-url` (get OAuth URL with requested scopes). These are shared across Calendar/Drive/future Gmail — not calendar-specific.
4. **Calendar-specific auth endpoints removed:** The original spec had `GET /api/v1/calendar/auth-status`. This was replaced by the shared integrations auth endpoints above to avoid per-integration auth duplication.
5. **FTS5 index for items:** `items_fts` virtual table added alongside `calendar_events_fts` during Phase 12 to enable unified search across items, calendar events, conversations, and memory.
6. **Sync implementation:** Uses Google Calendar's incremental sync (syncToken) rather than full re-fetch. Initial sync fetches the configured window; subsequent syncs use the stored syncToken for efficient delta updates.
7. **Gmail deferred to Phase 13.** `email_cache` table schema defined but not created. Gmail MCP tools, sync service, and frontend deferred.

## Implementation Notes (Phase 13 Build)

Resolved during implementation — deviations from the original spec:

1. **Gmail API client** (`gmail_client.py`) built with full MIME parsing (plain text + HTML extraction), draft creation with proper MIME encoding, label management (add/remove/create), and send/reply operations. Uses shared `google_auth.py` for OAuth with `gmail.modify` scope.
2. **Email cache with headers-only storage.** `email_cache` table stores message metadata, headers, snippet, and labels. Full email bodies are fetched live via `get_email` MCP tool — never stored in the database. This avoids storing sensitive email content in SQLite.
3. **10 MCP tools with permission mappings.** `list_emails`, `get_email`, `get_email_headers`, `label_email`, `archive_email`, `mark_email_read`, `draft_email` are always-allowed. `send_email` and `send_reply` require approval. `get_inbox_stats` is always-allowed. Permission enforcer updated with email resource mappings.
4. **Email triage label system.** OL/ prefix labels (`OL/Needs Response`, `OL/FYI`, `OL/Follow Up`, `OL/Waiting`, `OL/Agent Processed`) created in Gmail via `POST /api/v1/email/setup-labels`. Agents apply labels during triage. Email widget groups by these labels.
5. **Email context in working memory.** ~300 token budget in the working memory tier (end section, high attention). Shows unread count, needs-response count, and recent emails requiring attention. Included when gmail data source is active and not excluded for the space.
6. **Frontend surfaces:** Home dashboard email widget (grouped by OL/ triage labels), dedicated `/email` page with full inbox triage dashboard, space email feed widget (`email_feed` widget type). All click-through to Gmail for reading/replying.
7. **Email Triage automation template.** Cron: `0 8-18/2 * * 1-5` (every 2 hours during business hours, weekdays). Disabled by default. Processes unread emails, categorizes, applies OL/ labels, creates tasks for urgent items.
8. **Daily Task Review updated** to include email inbox summary alongside calendar and task data.

## Implementation Notes (Phase 14 Build)

Resolved during implementation:

1. **Integration Builder agent** built as a skill via Agent Builder. Registered at `agents/skills/integration-builder/SKILL.md`. Uses Sonnet model. System prompt covers API research, auth guidance, data source creation, testing, and documentation.
2. **3 exclusive MCP tools:** `create_api_data_source` (registers API data source with connection config), `test_api_connection` (fetches from API and returns sample response), `create_sync_automation` (creates cron automation for periodic data sync). These are convenience wrappers over existing primitives.
3. **Odin routing.** Odin recognizes API connection requests and routes to the Integration Builder agent in the relevant space. No new Odin MCP tools needed — uses existing `open_conversation` with the Integration Builder agent.

---

## Resolved Decisions

1. **No iframes.** Google blocks embedding Calendar and Gmail via X-Frame-Options. All data rendered natively in OpenLoop components.
2. **Cross-space data sources** with per-space opt-out (default: opted in). System data sources have `space_id=null`.
3. **Cache + sync model.** Events and email headers cached locally, synced every 15 minutes. Full email bodies fetched on-demand from Gmail API (not cached).
4. **Triage labels** prefixed `OL/` in Gmail to avoid conflicts with user labels.
5. **Send requires approval** initially. Configurable per-agent via existing permission system. User upgrades to "always allowed" when ready.
6. **No email body storage.** Snippets cached for display, full body fetched live. Avoids storing potentially sensitive email content in SQLite.
7. **Integration Builder uses existing primitives** (DataSource, Automations, WebFetch, Items/Memory). No dynamic code execution.
8. **OAuth scope expansion** — single re-auth when connecting Calendar or Email. Existing Drive token stays valid.
9. **Calendar and Email appear in sidebar** only after connected. Not visible on fresh install.
10. **Email send approval is a permission setting**, not a system constraint. Adjustable per-agent like any other permission.

---

## Open Questions

1. **Calendar sync frequency.** 15 minutes is proposed. Should it be configurable? More frequent risks rate limits (Google Calendar API: 1,000,000 queries/day for a project, but per-user limits are lower).
2. **Email triage agent.** Should a pre-built "Email Triage" automation template ship with the email integration (like the existing Daily Task Review template)? Or let users create their own?
3. **Meeting brief linking.** How to automatically link a meeting brief (conversation/document) to a calendar event? By title keyword match? By explicit agent action (MCP tool: `link_brief_to_event`)? Both?
4. **Draft review UX.** Agent creates a draft. Where does the user review it? Options: (a) in the conversation panel where the agent shows the draft text, (b) "View in Gmail" link to the draft, (c) a dedicated draft review widget. Probably (a) + (b).
5. **Multiple Google accounts.** The current OAuth flow supports one Google account. Should calendar/email support multiple accounts? Probably not in v1 — adds significant complexity.
