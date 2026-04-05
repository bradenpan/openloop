# OpenLoop: Implementation Plan — Phase 12-14 (DRAFT v2)

**Status:** Under review — not yet approved for implementation.
**Companion docs:** INTEGRATION-CAPABILITIES.md (capability spec), CAPABILITIES.md (master capability list), IMPLEMENTATION-PLAN-PHASE8.md (Phases 8-11)
**Scope:** External integrations — Google Calendar, Gmail, and Integration Builder agent.

---

## Build Principles

Carries forward all principles from IMPLEMENTATION-PLAN.md and IMPLEMENTATION-PLAN-PHASE8.md, plus:

1. **Same OAuth, new scopes.** Calendar and Gmail reuse the existing Google OAuth infrastructure (`gdrive_client.py` pattern). No new auth systems. Scope expansion requires a full re-consent flow — token refresh does NOT add scopes.
2. **Cache for speed, API for truth.** Cached data powers widgets and context assembly. Writes always go through the Google API. Stale cache is acceptable; stale writes are not. Use etag-based conflict detection on updates.
3. **Cross-space data sources are new infrastructure.** The `DataSource.space_id` nullability change affects the ORM relationship cascade, service layer, and schemas. Every reference to `space_id` must handle null.
4. **Agent capabilities before UI.** MCP tools and context assembly are the high-value work. Widgets are built after the backend is solid.
5. **Sync is not agent work.** Calendar/email sync is API-to-DB — no LLM reasoning needed. Run sync as direct function calls in the scheduler loop, not via `delegate_background`.
6. **Skills used during build:**
   - `frontend-design` — all UI component creation
   - `webapp-testing` — frontend testing with Playwright
   - `research-web` — Google API documentation, library research

## Explicitly Deferred

These capabilities are NOT built in Phases 12-14 and remain [NOT BUILT]:

- **Event-based automations (Capability #29)** — requires a webhook receiver for Google Calendar push notifications and Gmail watch API. The 15-minute cron sync is the v1 approach. Event-driven triggers are a separate infrastructure phase.
- **Meeting prep as event-triggered automation (Capability #31)** — requires event-based automations. However, Phase 12 does include a cron-based meeting prep template (see Task 12.4b).
- **Calendar grid widget** — a `@fullcalendar/react` month/week/day view is a future enhancement. Phase 12 builds list-style widgets only.
- **Task management integrations (Asana, Trello, Linear)** — require the Task Adapter pattern from FUTURE-CAPABILITIES.md. The Integration Builder explicitly does NOT handle these.

---

## Phase 12: Google Calendar Integration

**Goal:** Agents can read/write Google Calendar events. Calendar data appears in context assembly. Users see schedule on Home and in spaces.
**Prerequisite:** Phases 1-11 complete.

### Task 12.1: Cross-Space Data Source Infrastructure
**Agent:** 1 agent
**Complexity:** Medium-Large
**Dependencies:** None (foundational for all integration work)

The cross-space data source model — system-level data sources not bound to any space. This task has the highest migration risk in the plan because it changes an existing FK constraint and ORM relationship.

**Schema changes:**
- Make `DataSource.space_id` nullable (currently NOT NULL with `ondelete="CASCADE"`). Alembic migration.
- **ORM relationship fix (critical):** `Space.data_sources` currently has `cascade="all, delete-orphan"`. System-level DataSources with `space_id=None` would be treated as orphans by SQLAlchemy. Change to: `relationship("DataSource", back_populates="space", cascade="all, delete", passive_deletes=True)` — remove `delete-orphan`. Add a filter on the relationship to only include `space_id IS NOT NULL` records, or query system sources separately.
- **Schema fixes:** Update `DataSourceCreate.space_id` from `str` to `str | None = None`. Update `DataSourceResponse.space_id` from `str` to `str | None`.
- New `space_data_source_exclusions` table: `space_id` (FK, CASCADE), `data_source_id` (FK, CASCADE), composite PK. For per-space opt-out of system data sources.
- Add source type string constants to `contract/enums.py`: `SOURCE_TYPE_GOOGLE_DRIVE = "google_drive"`, `SOURCE_TYPE_GOOGLE_CALENDAR = "google_calendar"`, `SOURCE_TYPE_GMAIL = "gmail"`, `SOURCE_TYPE_API = "api"`. These are constants, NOT a database enum — `source_type` remains a plain String column to avoid migration complexity on existing data.
- Add `is_system` boolean (default false) to `Automation` model. System automations are hidden from `list_automations()` by default (add `include_system` query param). Users cannot delete system automations via the API (guard in delete endpoint).
- Add `data_source_id` FK (nullable, `ondelete="CASCADE"`) to both `calendar_events` and `email_cache` tables (created in later tasks but the FK target is defined here). When a DataSource is deleted, its cached data is cascade-deleted.

**Service changes:**
- `data_source_service.py`: update `create_data_source()` to handle `space_id=None` (skip space lookup when null). Update `list_data_sources()` to support `space_id=None` filter. New `list_system_data_sources()`, `is_excluded(space_id, data_source_id)`, `exclude_from_space()`, `include_in_space()`.
- `mcp_tools.py`: Calendar/email MCP tools are statically defined functions (like all other tools), NOT dynamically loaded from DataSource records. The DataSource record gates whether the tools are included in a session's tool registry: if no calendar DataSource exists, calendar tools are not registered. Add conditional tool loading in the tool builder based on system data source existence and per-space exclusion checks. Skip `_validate_space_access()` for system-level resource tools (calendar, email) — these tools are not space-scoped.
- `automation_service.py`: filter system automations from `list_automations()` unless `include_system=True`. Guard `delete_automation()` against system automations.

**API changes:**
- `GET /api/v1/data-sources` — add `system=true` query param to list system-level sources
- `POST /api/v1/data-sources/{id}/exclude` — exclude from a space
- `DELETE /api/v1/data-sources/{id}/exclude` — re-include in a space
- `GET /api/v1/automations` — add `include_system` query param (default false)
- `DELETE /api/v1/automations/{id}` — reject with 403 if `is_system=True`

**Files modified:** `backend/openloop/db/models.py`, `backend/openloop/services/data_source_service.py`, `backend/openloop/services/automation_service.py`, `backend/openloop/agents/mcp_tools.py`, `backend/openloop/api/routes/data_sources.py`, `backend/openloop/api/routes/automations.py`, `backend/openloop/api/schemas/data_sources.py`, `contract/enums.py`
**Migration:** Alter `data_sources.space_id` to nullable, alter Space.data_sources relationship cascade, add `is_system` to `automations`, create `space_data_source_exclusions` table. This is the **sole migration revision for Phase 12** — Tasks 12.3 and 13.2 add their tables in this same revision to avoid sequencing issues.

**⚠️ Human review gate:** This changes an existing FK constraint and ORM cascade. Review the migration and ORM relationship changes before proceeding. Verify existing Drive data sources are unaffected. Run existing data_source tests.

**Acceptance criteria:**
- DataSource can be created with `space_id=None`
- System data sources returned by `list_system_data_sources()`
- Space-level DataSources still cascade-delete when their Space is deleted
- System-level DataSources are NOT deleted when any Space is deleted
- Per-space exclusion works (excluded source's tools not loaded for that space)
- System automations hidden from dashboard by default
- System automations cannot be deleted via API
- `DataSourceCreate` and `DataSourceResponse` schemas accept/return `space_id: str | None`
- All existing tests pass

### Task 12.2: Shared OAuth Infrastructure + Google Calendar API Client
**Agent:** 1 agent
**Complexity:** Large
**Can run in parallel with 12.1**

Build the shared OAuth infrastructure and Calendar API client. **This task resolves the OAuth re-auth design upfront** — it is on the critical path for all integration work.

**New file: `backend/openloop/services/google_auth.py`** (shared OAuth utility)

The current `gdrive_client.py` has OAuth logic inline (hardcoded scopes, `InstalledAppFlow.run_local_server()`). Extract into a shared module:

- `INTEGRATION_SCOPES` registry: dict mapping integration name → required scopes. Each integration registers its scopes on import. Drive: `drive.readonly`, `drive.file`. Calendar: `calendar.events`, `calendar.readonly`. Gmail: `gmail.modify`.
- `get_all_required_scopes() -> list[str]` — union of all registered integration scopes
- `get_credentials() -> Credentials | None` — load token.json, return Credentials if valid
- `get_missing_scopes() -> list[str]` — compare token's granted scopes against required scopes
- `get_auth_url(scopes?) -> str` — generate OAuth consent URL using `InstalledAppFlow`. Uses `include_granted_scopes=True` for incremental authorization (Google preserves existing grants when adding new scopes). If `scopes` not provided, uses `get_all_required_scopes()`.
- `complete_auth(auth_code: str)` — exchange authorization code for token, save to `token.json`. This replaces the `run_local_server()` approach.
- `is_authenticated(required_scopes: list[str]) -> bool` — check if token exists and includes the specified scopes
- `refresh_if_needed(credentials) -> Credentials` — refresh expired token (does NOT add new scopes — only re-auth adds scopes)

**OAuth re-auth flow (resolved design):**
1. Frontend calls `GET /api/v1/integrations/auth-status` → returns `{authenticated: bool, granted_scopes: [...], missing_scopes: [...]}`
2. If scopes are missing, frontend shows "Grant access" button
3. Button calls `GET /api/v1/integrations/auth-url?scopes=calendar.events,calendar.readonly` → returns `{url: "https://accounts.google.com/o/oauth2/..."}`
4. Frontend opens the URL in a new browser tab. User completes Google consent.
5. Google redirects to `http://localhost:{port}/oauth/callback` (using `InstalledAppFlow.run_local_server()` running temporarily)
6. Backend receives the callback, exchanges code for token, saves to `token.json`
7. Frontend polls `GET /api/v1/integrations/auth-status` until scopes are granted, then enables the integration

**OAuth flow mechanics:** When the frontend calls `GET /api/v1/integrations/auth-url`, the backend starts `InstalledAppFlow.run_local_server()` in a **background thread**. This opens a temporary local HTTP server, generates the consent URL, and waits for Google's redirect callback. The endpoint returns the consent URL immediately. The frontend opens it in a new tab. After the user consents, Google redirects to the local server, which exchanges the code for a token and saves it. The frontend polls `GET /api/v1/integrations/auth-status` until the new scopes appear. This matches the existing Drive auth pattern and works for local-first. For future remote deployment, replace with a FastAPI OAuth callback route.

**New API endpoints (in a new `integrations.py` route file):**
- `GET /api/v1/integrations/auth-status` → auth status with scope breakdown
- `GET /api/v1/integrations/auth-url` → generate OAuth consent URL for missing scopes

**New file: `backend/openloop/services/gcalendar_client.py`**

- Imports shared auth from `google_auth.py`
- Registers calendar scopes on import
- Functions:
  - `is_authenticated() -> bool` — check token validity with calendar scopes
  - `get_calendar_service()` — build Google Calendar API v3 service
  - `list_calendars() -> list[dict]` — all calendars user has access to
  - `list_events(calendar_id, time_min, time_max, max_results?) -> list[dict]` — events in date range, handles pagination. Uses `singleEvents=True` to expand recurring events into individual instances.
  - `get_event(calendar_id, event_id) -> dict` — single event detail
  - `create_event(calendar_id, event_body) -> dict` — create event (with optional attendees for invites). Uses `sendUpdates="all"` to send invite emails.
  - `update_event(calendar_id, event_id, event_body, etag?) -> dict` — update event fields. Includes etag for conflict detection (Google returns 412 Precondition Failed on stale etag).
  - `delete_event(calendar_id, event_id)` — delete/cancel event
  - `find_free_busy(calendar_ids, time_min, time_max) -> list[dict]` — free/busy query
- **Retry with backoff:** Wrap Google API calls with exponential backoff (same pattern as SDK `_query_with_retry`). Handle `HttpError` 429 (rate limit) and 5xx (server errors).

**Files created:** `backend/openloop/services/google_auth.py`, `backend/openloop/services/gcalendar_client.py`, `backend/openloop/api/routes/integrations.py`, `backend/openloop/api/schemas/integrations.py`
**Files modified:** `backend/openloop/services/gdrive_client.py` (replace inline OAuth with imports from `google_auth.py`), `backend/openloop/main.py` (register integrations router)

**⚠️ Human review gate:** OAuth refactor touches existing Drive auth. Verify Drive still works after extracting shared auth. Test: delete `token.json`, re-auth with all scopes, verify Drive + Calendar both work.

**Acceptance criteria:**
- `google_auth.py` manages scopes for all Google integrations
- `get_missing_scopes()` correctly detects when calendar scopes are needed
- `get_auth_url()` generates a consent URL with `include_granted_scopes=True`
- Re-auth grants new scopes without losing existing Drive grants
- Existing Drive operations still work after refactor — all tests in `test_services/test_drive_integration_service.py` and `test_api/test_drive.py` pass without modification
- `list_calendars()` returns user's calendars
- `list_events()` returns events with recurring instances expanded
- `create_event()` with attendees sends invite via Google Calendar
- `update_event()` with stale etag returns conflict error
- Google API errors retried with exponential backoff

### Task 12.3: Calendar Event Cache + Sync Service
**Agent:** 1 agent
**Complexity:** Medium
**Dependencies:** 12.1 (cross-space data source), 12.2 (calendar client)

**Schema:**
- New `calendar_events` table: `id` (UUID PK), `google_event_id` (UNIQUE), `calendar_id`, `title`, `description`, `location`, `start_time` (DATETIME, NOT NULL), `end_time` (DATETIME, NOT NULL), `all_day` (BOOLEAN), `attendees` (JSON), `organizer` (JSON), `conference_data` (JSON), `status` (confirmed/tentative/cancelled), `recurrence_rule`, `html_link`, `etag`, `synced_at`, `created_at`, `updated_at`
- FTS5 virtual table on `calendar_events` (title + description) for search

**New file: `backend/openloop/services/calendar_integration_service.py`**

- `setup_calendar(calendar_ids?) -> DataSource` — create system-level DataSource, run initial sync
- `sync_events(data_source_id) -> dict` — full sync: fetch events for configured window (default: 7 days back, 30 days ahead), upsert by `google_event_id`, detect deletes via etag comparison. Returns `{added, updated, removed}`.
- `get_cached_events(start, end, calendar_id?) -> list` — query local cache
- `get_upcoming_events(hours=48) -> list` — convenience for context assembly
- `create_event(calendar_id, title, start, end, **kwargs) -> CalendarEvent` — create via API, cache locally
- `update_event(event_id, **kwargs) -> CalendarEvent` — update via API, update cache
- `delete_event(event_id)` — delete via API, remove from cache
- `find_free_time(start, end, duration_minutes) -> list[dict]` — find available slots using free/busy API
- `get_event_with_brief(event_id) -> dict` — event + linked meeting brief (if exists). Brief linking: search conversation_summaries and documents for keyword match on event title or attendee names.

**Sync mechanism:** Calendar sync runs as a **direct function call in the automation scheduler loop**, NOT as a `delegate_background` agent session. Sync is API-to-DB work — no LLM reasoning needed. Add a `_run_integration_syncs()` function to `automation_scheduler.py` that runs every 15 minutes alongside the existing cron evaluation. On Google API failure: retry once with backoff. On persistent failure (3 consecutive failures): create a notification "Calendar sync failed — check Google auth" and skip until next cycle. On token expiry (401 Unauthorized): create a notification "Google Calendar disconnected — re-authentication needed", disable sync until re-auth.

**Files created:** `backend/openloop/services/calendar_integration_service.py`
**Files modified:** `backend/openloop/agents/automation_scheduler.py` (add integration sync loop)
**Migration:** `calendar_events` table and FTS5 virtual table + triggers are included in the **Phase 12 migration revision** created by Task 12.1. The `data_source_id` FK (nullable, CASCADE) on `calendar_events` points to `data_sources.id`.

**Acceptance criteria:**
- `setup_calendar()` creates system DataSource and runs initial sync
- `sync_events()` correctly adds/updates/removes cached events
- `create_event()` creates in Google and caches locally
- `find_free_time()` returns available slots
- Brief linking finds relevant conversations/documents for events
- Sync runs every 15 minutes via scheduler (not an agent session)
- Sync failure creates notification after 3 consecutive failures
- Token expiry disables sync and surfaces re-auth prompt
- Deleting the calendar DataSource cascade-deletes cached events

### Task 12.4: Calendar MCP Tools + Context Assembly
**Agent:** 1 agent
**Complexity:** Medium
**Dependencies:** 12.3 (sync service)

**7 new MCP tools:**

| Tool | Description |
|---|---|
| `list_calendar_events(start, end, calendar_id?)` | List events in date range from cache (triggers sync if stale >30min) |
| `get_calendar_event(event_id)` | Get event detail including attendees, conference link, meeting brief |
| `create_calendar_event(title, start, end, attendees?, description?, location?)` | Create event via API (invites sent automatically if attendees provided) |
| `update_calendar_event(event_id, **fields)` | Update event fields via API |
| `delete_calendar_event(event_id)` | Delete/cancel event via API |
| `find_free_time(start, end, duration_minutes)` | Find available time slots |
| `list_calendars()` | List available calendars |

**Permission enforcer mappings:**
- `list_calendar_events`, `get_calendar_event`, `find_free_time`, `list_calendars` → resource: `google_calendar`, operation: `read`
- `create_calendar_event` → resource: `google_calendar`, operation: `create`
- `update_calendar_event` → resource: `google_calendar`, operation: `edit`
- `delete_calendar_event` → resource: `google_calendar`, operation: `delete`

Default permissions for new agents: read = always allowed, create/edit/delete = requires approval.

**Context assembly changes:**
- Add new `_build_calendar_section()` in `context_assembler.py` as a **separate END section** with its own budget — NOT carved from the existing board/todo budget.
- **Total context budget increases from ~8,000 to ~8,800 tokens.** New breakdown: existing 8,000 + 500 (calendar) + 300 (email, added in Phase 13). The 8,000 total was a design choice, not a hard limit. Adding 800 tokens for integrations that provide high-value daily awareness is justified.
- **Odin budget increases from ~4,000 to ~4,800 tokens.** Calendar and email are cross-space awareness — exactly what Odin needs.
- New constants: `BUDGET_CALENDAR = 500`, `BUDGET_EMAIL = 300` (used by Phase 13).
- Format: time, title, attendees (abbreviated), conference link, meeting brief pointer if exists.
- Only included when calendar data source exists and isn't excluded for this space.
- Odin context: always includes calendar (cross-space by nature).
- **Tool loading:** Calendar MCP tools are conditionally included in the tool registry based on whether a `google_calendar` system DataSource exists and isn't excluded for the agent's space. Skip `_validate_space_access()` for calendar tools — they are system-level, not space-scoped.
- **Agent runner dispatch:** Add `"integration builder"` / `"integration-builder"` name check to `_build_mcp_server()` (same pattern as Agent Builder dispatch). Include `background_task_id` for the `queue_approval` tool.

**Files modified:** `backend/openloop/agents/mcp_tools.py`, `backend/openloop/agents/permission_enforcer.py`, `backend/openloop/agents/context_assembler.py`, `backend/openloop/agents/agent_runner.py` (tool builder dispatch)

**Acceptance criteria:**
- All 7 MCP tools functional
- Permission enforcer correctly maps calendar tools to resource/operation
- Context assembly includes upcoming events as a separate END section (not stealing from board budget)
- Total context budget is ~8,800 tokens (8,000 existing + 500 calendar + 300 email placeholder)
- Odin sees calendar data in its context (budget ~4,800)
- Agent without calendar permission does not see calendar tools or context
- Space with calendar excluded does not get calendar in context
- Calendar tools skip space access validation (system-level resource)

### Task 12.4b: Automation Templates — Meeting Prep + Updated Briefing
**Agent:** 1 agent
**Complexity:** Small
**Dependencies:** 12.4 (calendar MCP tools available)

Create/update automation templates that leverage calendar data:

**1. Meeting Prep template** (new):
- Cron: daily at 7am (same as Daily Task Review)
- Instruction: "Check calendar for meetings in the next 24 hours. For each meeting without a prepared brief: look up attendees in CRM/items, check recent conversation summaries for context, draft a brief with attendee info, agenda, and context. Save the brief as a document linked to the space. Flag meetings with no context as 'needs manual prep' via notification."
- Agent: shared "Automation Agent" (existing)
- Disabled by default (like other templates)

**2. Update existing Daily Task Review template:**
- Modify instruction to include: "Also check today's calendar events and flag any that need preparation. Include a schedule summary at the top of the review."

**3. Update existing Stale Work Check template:**
- Modify instruction to include: "Also check for follow-up items linked to calendar events that have passed without action."

**Registration:** Add to `scripts/register_automation_templates.py` (idempotent). Run as `make register-automations`.

**Files modified:** `scripts/register_automation_templates.py`

**Acceptance criteria:**
- Meeting Prep automation template registered (disabled by default)
- Daily Task Review instruction references calendar
- Templates are idempotent (re-running registration doesn't duplicate)

### Task 12.5: Calendar API Routes
**Agent:** 1 agent
**Complexity:** Small
**Can run in parallel with 12.4**

**New file: `backend/openloop/api/routes/calendar.py`**

```
GET  /api/v1/calendar/auth-status          → CalendarAuthStatusResponse
GET  /api/v1/calendar/events               → paginated CalendarEventResponse list
                                             (query: start, end, calendar_id)
GET  /api/v1/calendar/events/{id}          → CalendarEventResponse (with brief info)
POST /api/v1/calendar/events               → CalendarEventResponse
PATCH /api/v1/calendar/events/{id}         → CalendarEventResponse
DELETE /api/v1/calendar/events/{id}        → 204
POST /api/v1/calendar/sync                 → CalendarSyncResponse ({added, updated, removed})
GET  /api/v1/calendar/free-time            → list of available slots
                                             (query: start, end, duration_minutes)
GET  /api/v1/calendar/calendars            → list of calendar info
POST /api/v1/calendar/setup                → DataSourceResponse (initial setup)
```

**New file: `backend/openloop/api/schemas/calendar.py`**

Schemas: `CalendarEventCreate`, `CalendarEventUpdate`, `CalendarEventResponse`, `CalendarSyncResponse`, `CalendarAuthStatusResponse`, `FreeTimeSlot`, `CalendarSetupRequest`. Re-export from `schemas/__init__.py`.

**Files created:** `backend/openloop/api/routes/calendar.py`, `backend/openloop/api/schemas/calendar.py`
**Files modified:** `backend/openloop/main.py` (register router), `backend/openloop/api/schemas/__init__.py`

**Acceptance criteria:** All endpoints return correct responses. Auth status reflects actual Google OAuth state. Setup endpoint creates system data source and triggers initial sync. OpenAPI spec includes calendar endpoints.

### Task 12.5b: Type Generation + OpenAPI Spec
**Agent:** Same agent as 12.5 (or any agent)
**Complexity:** Small
**Dependencies:** 12.5 (API routes registered)

Run `make generate-types` to regenerate TypeScript types from the updated OpenAPI spec. Frontend tasks (12.6) depend on these types being current.

**Acceptance criteria:** `frontend/src/api/` contains generated types for all calendar endpoints. No TypeScript compilation errors.

### Task 12.6: Calendar Frontend — Home Widget + Calendar Page
**Agent:** 1 agent (uses frontend-design skill)
**Complexity:** Large
**Dependencies:** 12.5b (generated types available)

**Three UI surfaces:**

**1. Home dashboard calendar widget** (`frontend/src/components/home/calendar-widget.tsx`):
- Compact: today's events + tomorrow's events
- Each event: time, title, attendees (first names, abbreviated if >3), conference link icon
- Meeting brief indicator: link icon if brief exists, "prepare?" prompt if not
- Clicking event title → opens in Google Calendar (`html_link`)
- "This week" expandable section
- Only renders when calendar data source exists (query `/api/v1/data-sources?system=true`)
- Loading skeleton while fetching

**2. Calendar page** (`frontend/src/pages/Calendar.tsx`):
- New sidebar nav item "Calendar" (only visible when connected)
- Full event list grouped by day, scrollable
- Week view: 7-day column layout with time slots (simple CSS grid, not a full calendar library)
- Each event expandable: attendees, description, conference link, meeting brief link
- Filter by calendar (if multiple)
- "Sync now" button → `POST /api/v1/calendar/sync`
- Auto-refresh every 60 seconds

**3. Space calendar widget** (`calendar_events` widget type):
- New entry in widget registry
- Compact event list filtered to space-relevant events (keyword match on titles/attendees vs space items)
- Added via layout editor like any other widget
- Add `CALENDAR_EVENTS` to `WidgetType` enum

**Sidebar changes:**
- Add "Calendar" nav item in sidebar, positioned between Home and Spaces
- Conditionally rendered: only when system data source with `source_type=google_calendar` exists
- Use calendar icon

**Files created:** `frontend/src/components/home/calendar-widget.tsx`, `frontend/src/pages/Calendar.tsx`, `frontend/src/components/space/calendar-events-widget.tsx`
**Files modified:** `frontend/src/components/layout/sidebar.tsx`, `frontend/src/components/space/widget-registry.tsx`, `frontend/src/App.tsx` (route), `contract/enums.py` (WidgetType)

**Acceptance criteria:**
- Home widget shows today's and tomorrow's events
- Calendar page shows full week view with expandable events
- Space widget shows space-relevant events
- Clicking events opens Google Calendar
- Meeting brief links navigate to the right conversation/document
- Calendar sidebar item only visible when connected
- Skeleton loading states

### Task 12.7: Calendar Tests
**Agent:** 1 agent
**Complexity:** Medium
**Dependencies:** 12.3, 12.4, 12.5, 12.6

**Backend tests:**
- `test_services/test_calendar_integration_service.py`: sync logic (add/update/remove), create/update/delete events, free time calculation, brief linking, cache staleness detection
- `test_api/test_calendar.py`: all API endpoints, auth status, setup flow, pagination
- `test_agents/test_calendar_mcp.py`: MCP tool execution, permission mapping, context assembly with calendar data
- `test_services/test_data_source_service.py` (extend): cross-space data source CRUD, exclusion logic

**Frontend E2E tests:**
- Calendar widget on Home (mocked API data)
- Calendar page navigation and event display
- Space calendar widget rendering
- Sidebar conditional visibility

**Target:** ~50 backend tests, ~10 E2E tests

**Wave 1 review deferred items (must be covered in 12.7):**
- Test system data source exclusion endpoints (POST/DELETE `/{id}/exclude`)
- Test `system` query param on `GET /api/v1/data-sources`
- Test `list_system_data_sources()`, `is_excluded()`, `exclude_from_space()`, `include_in_space()` service functions
- Test `include_system` filtering on `GET /api/v1/automations`
- Test 403 on `DELETE /api/v1/automations/{id}` for system automations
- Test 403 on PATCH with `is_system` field in automation updates
- Test only system data sources can be excluded (422 for space-level)
- Test `include_in_space()` validates existence of space and data source

**Schema deferred items (nice-to-have, add if time permits):**
- Add index on `calendar_events.calendar_id` (frequent sync queries)
- Add index on `email_cache.gmail_thread_id` (thread grouping queries)
- Add `data_source` back-relationship on CalendarEvent and EmailCache models

**Acceptance criteria:** All tests pass. Calendar integration covered across service, API, MCP, context assembly, and frontend layers.

### Task 12.8: Documentation Update
**Agent:** 1 agent
**Complexity:** Small
**Dependencies:** 12.7 (all calendar work complete)

Update project documents to reflect Phase 12 changes:
- **ARCHITECTURE-PROPOSAL.md:** Add calendar API endpoints to Layer 2, `calendar_integration_service` and `google_auth` to Layer 3, calendar MCP tools to Layer 4, `calendar_events` table to Layer 7. Add system-level data source concept. Update context assembly budget numbers.
- **CAPABILITIES.md:** Update item #27 from [NOT BUILT] to [BUILT]. Update #30 (morning briefing) and #31 (meeting prep) status notes. Add note to #29 about deferral.
- **INTEGRATION-CAPABILITIES.md:** Add `/setup` endpoints and auth-status scope breakdown to the spec. Note resolved OAuth design.
- **Regenerate OpenAPI spec** from current routes.

**Acceptance criteria:** All documents reflect current state. OpenAPI spec is fresh.

---

## Phase 13: Gmail Integration

**Goal:** Agents can read/triage email, draft replies, and surface inbox status. Users see email dashboard on Home and in spaces.
**Prerequisite:** Phase 12 complete (shared OAuth infrastructure, cross-space data source model).

### Task 13.1: Gmail API Client
**Agent:** 1 agent
**Complexity:** Medium
**Dependencies:** 12.2 (shared OAuth utilities from calendar client refactor)

**New file: `backend/openloop/services/gmail_client.py`**

- Reuse shared OAuth infrastructure from 12.2
- Add scope: `https://www.googleapis.com/auth/gmail.modify` (read, label, archive, draft, send)
- Functions:
  - `is_authenticated() -> bool` — check token validity with gmail scope
  - `get_gmail_service()` — build Gmail API v1 service
  - `list_messages(query?, label_ids?, max_results?) -> list[dict]` — list messages with Gmail search syntax support
  - `get_message(message_id) -> dict` — full message (headers + body + attachments metadata)
  - `get_message_headers(message_id) -> dict` — headers only (faster, for triage)
  - `modify_labels(message_id, add_labels?, remove_labels?)` — add/remove labels
  - `archive_message(message_id)` — remove INBOX label
  - `mark_as_read(message_id)` — remove UNREAD label
  - `create_draft(to, subject, body, reply_to?, cc?, bcc?) -> dict` — create draft message
  - `send_draft(draft_id) -> dict` — send an existing draft
  - `send_reply(message_id, body) -> dict` — reply to thread
  - `get_labels() -> list[dict]` — list all labels
  - `create_label(name) -> dict` — create a label
  - `get_inbox_stats() -> dict` — unread count, label counts

**MIME handling:**
- Parse multipart messages to extract plain text body (prefer text/plain, fall back to text/html with tag stripping)
- Attachment metadata only (filename, mime_type, size) — no attachment download in v1
- Proper encoding handling (base64url decode for Gmail API)

**Files created:** `backend/openloop/services/gmail_client.py`

**Acceptance criteria:**
- `list_messages()` returns inbox messages with Gmail search syntax
- `get_message()` returns parsed message with plain text body
- `modify_labels()` adds/removes labels in Gmail
- `create_draft()` creates a draft visible in Gmail
- `send_draft()` sends the draft (for testing: use a test draft to yourself)
- MIME parsing handles multipart messages correctly

### Task 13.2: Email Cache + Triage Label System
**Agent:** 1 agent
**Complexity:** Medium
**Dependencies:** 13.1 (Gmail client), 12.1 (cross-space data source)

**Schema:**
- New `email_cache` table: `id` (UUID PK), `gmail_message_id` (UNIQUE), `gmail_thread_id`, `subject`, `from_address`, `from_name`, `to_addresses` (JSON), `cc_addresses` (JSON), `snippet` (plain text preview), `labels` (JSON array), `is_unread` (BOOLEAN), `received_at` (DATETIME, NOT NULL), `gmail_link` (URL), `synced_at`, `created_at`, `updated_at`
- FTS5 virtual table on `email_cache` (subject + from_name + snippet) for search
- No email body storage — bodies fetched live from Gmail API when agents need them

**New file: `backend/openloop/services/email_integration_service.py`**

- `setup_email(triage_labels?) -> DataSource` — create system-level DataSource, create OL/ labels in Gmail, run initial sync
- `ensure_triage_labels()` — create `OL/Needs Response`, `OL/FYI`, `OL/Follow Up`, `OL/Waiting`, `OL/Agent Processed` labels in Gmail if they don't exist. Prefix avoids conflicts with user labels.
- `sync_inbox(data_source_id, max_results=50) -> dict` — sync recent inbox messages. Upsert by `gmail_message_id`. Update labels and read status. Returns `{added, updated}`.
- `get_cached_messages(label?, query?, unread_only?, limit?, offset?) -> list` — query local cache
- `get_inbox_stats() -> dict` — unread count, count by OL/ label, oldest unread timestamp
- `label_message(message_id, add?, remove?)` — label via API, update cache
- `archive_message(message_id)` — archive via API, update cache
- `mark_read(message_id)` — mark read via API, update cache
- `create_draft(to, subject, body, **kwargs) -> dict` — create via API
- `send_draft(draft_id) -> dict` — send via API
- `send_reply(message_id, body) -> dict` — reply via API

**Gmail link format:** `https://mail.google.com/mail/u/0/#inbox/{gmail_message_id}`. Note: Gmail API message IDs may need URL-safe encoding. Verify during build and adjust the link template if needed.

**Sync mechanism:** Same pattern as calendar — **direct function call in the automation scheduler loop**, NOT an agent session. Add email sync to the existing `_run_integration_syncs()` in `automation_scheduler.py`. Same failure handling as calendar: retry once, notification after 3 consecutive failures, disable on token expiry.

**Files created:** `backend/openloop/services/email_integration_service.py`
**Files modified:** `backend/openloop/agents/automation_scheduler.py` (add email sync alongside calendar sync)
**Migration:** `email_cache` table and FTS5 virtual table + triggers are included in the **Phase 12 migration revision** created by Task 12.1. The `data_source_id` FK (nullable, CASCADE) on `email_cache` points to `data_sources.id`. Deleting the gmail DataSource cascade-deletes cached emails.

**Acceptance criteria:**
- `setup_email()` creates DataSource, triage labels, and runs initial sync
- `sync_inbox()` correctly upserts cached messages
- Triage labels created in Gmail with `OL/` prefix
- `label_message()` updates both Gmail and local cache
- `get_inbox_stats()` returns accurate counts
- Gmail links open the correct message in Gmail
- Sync runs as direct function call (not agent session)
- Sync failure handling: notifications, token expiry detection
- Deleting gmail DataSource cascade-deletes cached emails

### Task 13.3: Email MCP Tools + Context Assembly
**Agent:** 1 agent
**Complexity:** Medium
**Dependencies:** 13.2 (email service)

**10 new MCP tools:**

| Tool | Description |
|---|---|
| `list_emails(query?, label?, max_results?)` | Search inbox (Gmail search syntax), returns from cache (triggers sync if stale) |
| `get_email(message_id)` | Read full email thread (fetches body live from Gmail API) |
| `get_email_headers(message_id)` | Read headers only from cache (faster, for triage) |
| `label_email(message_id, add_labels?, remove_labels?)` | Add/remove labels |
| `archive_email(message_id)` | Archive (remove from inbox) |
| `mark_email_read(message_id)` | Mark as read |
| `draft_email(to, subject, body, reply_to?, cc?, bcc?)` | Create draft (does NOT send) |
| `send_email(draft_id)` | Send existing draft |
| `send_reply(message_id, body)` | Reply to thread |
| `get_inbox_stats()` | Unread count, label counts, oldest unread |

**Permission enforcer mappings:**
- `list_emails`, `get_email`, `get_email_headers`, `get_inbox_stats` → resource: `gmail`, operation: `read`
- `label_email`, `archive_email`, `mark_email_read` → resource: `gmail`, operation: `edit`
- `draft_email` → resource: `gmail`, operation: `create`
- `send_email`, `send_reply` → resource: `gmail`, operation: `execute`

Default permissions: read = always allowed, edit = always allowed (labeling/archiving is low-risk), create = always allowed (drafts don't send), execute = requires approval (sending email).

**Context assembly changes:**
- New `_build_email_section()` in context assembler as a **separate END section** with its own budget (`BUDGET_EMAIL = 300`, constant defined in Task 12.4).
- Format: unread count, needs-response count, top 3 emails needing response (sender, subject, age).
- Only included when gmail data source exists and isn't excluded for this space.
- Odin context: always includes email summary.

**Files modified:** `backend/openloop/agents/mcp_tools.py`, `backend/openloop/agents/permission_enforcer.py`, `backend/openloop/agents/context_assembler.py`

**Acceptance criteria:**
- All 10 MCP tools functional
- `get_email()` fetches body live from Gmail (not from cache)
- `send_email()` and `send_reply()` require approval by default
- Context assembly includes inbox summary when email is connected
- Space with email excluded does not get email in context

### Task 13.4: Email API Routes
**Agent:** 1 agent
**Complexity:** Small
**Can run in parallel with 13.3**

**New file: `backend/openloop/api/routes/email.py`**

```
GET  /api/v1/email/auth-status             → EmailAuthStatusResponse
GET  /api/v1/email/messages                → paginated EmailMessageResponse list
                                             (query: label, query, unread_only)
GET  /api/v1/email/messages/{id}           → EmailMessageResponse (with body)
POST /api/v1/email/messages/{id}/label     → EmailMessageResponse
POST /api/v1/email/messages/{id}/archive   → 204
POST /api/v1/email/messages/{id}/read      → 204
POST /api/v1/email/messages/{id}/reply     → EmailMessageResponse (send reply to thread)
POST /api/v1/email/drafts                  → DraftResponse
POST /api/v1/email/drafts/{id}/send        → EmailMessageResponse
POST /api/v1/email/sync                    → EmailSyncResponse ({added, updated})
GET  /api/v1/email/stats                   → EmailStatsResponse
POST /api/v1/email/setup                   → DataSourceResponse
POST /api/v1/email/setup-labels            → {labels_created: int}
```

**New file: `backend/openloop/api/schemas/email.py`**

Schemas: `EmailMessageResponse`, `EmailLabelRequest`, `DraftCreateRequest`, `DraftResponse`, `EmailSyncResponse`, `EmailStatsResponse`, `EmailAuthStatusResponse`, `EmailSetupRequest`. Re-export from `schemas/__init__.py`.

**Files created:** `backend/openloop/api/routes/email.py`, `backend/openloop/api/schemas/email.py`
**Files modified:** `backend/openloop/main.py` (register router), `backend/openloop/api/schemas/__init__.py`

**Acceptance criteria:** All endpoints return correct responses. Setup creates data source, triage labels, and initial sync. OpenAPI spec includes email endpoints.

### Task 13.4b: Type Generation + OpenAPI Spec
**Agent:** Same agent as 13.4 (or any agent)
**Complexity:** Small
**Dependencies:** 13.4 (API routes registered)

Run `make generate-types` to regenerate TypeScript types. Frontend task (13.5) depends on these.

**Acceptance criteria:** `frontend/src/api/` contains generated types for all email endpoints. No TypeScript compilation errors.

### Task 13.5: Email Frontend — Home Widget + Email Page
**Agent:** 1 agent (uses frontend-design skill)
**Complexity:** Large
**Dependencies:** 13.4b (generated types available)

**Three UI surfaces:**

**1. Home dashboard email widget** (`frontend/src/components/home/email-widget.tsx`):
- Header: unread count, needs-response count
- Grouped by OL/ triage labels (Needs Response, Follow Up, FYI)
- Each email: sender name, subject (truncated), time ago
- Clicking email → opens in Gmail (`gmail_link`)
- "View all in Gmail" link
- Label groups collapsible, configurable order (stored in widget config)
- Only renders when gmail data source exists
- Badge count: feeds into existing browser tab badge (add unread email count)

**2. Email page** (`frontend/src/pages/Email.tsx`):
- New sidebar nav item "Email" (only visible when connected, below Calendar)
- Full inbox triage dashboard
- Grouped by OL/ labels with counts, collapsible sections
- Each message: sender, subject, snippet, time ago, label badges
- Quick actions per message: archive (with confirmation), mark read, change label (dropdown)
- Search bar — proxies to `GET /api/v1/email/messages?query=...`
- "Sync now" button
- Auto-refresh every 60 seconds
- Clicking any message opens in Gmail

**3. Space email widget** (`email_feed` widget type):
- New entry in widget registry
- Compact email list filtered to space-relevant messages (keyword match on sender/subject vs space items and agent names)
- Add `EMAIL_FEED` to `WidgetType` enum

**Sidebar changes:**
- Add "Email" nav item below Calendar
- Conditionally rendered when gmail system data source exists

**Files created:** `frontend/src/components/home/email-widget.tsx`, `frontend/src/pages/Email.tsx`, `frontend/src/components/space/email-feed-widget.tsx`
**Files modified:** `frontend/src/components/layout/sidebar.tsx`, `frontend/src/components/space/widget-registry.tsx`, `frontend/src/App.tsx` (route), `contract/enums.py` (WidgetType)

**Acceptance criteria:**
- Home widget shows emails grouped by triage label
- Email page shows full inbox with quick actions
- Space widget shows relevant emails
- All clicks open Gmail
- Email sidebar item only visible when connected
- Browser tab badge includes unread email count

### Task 13.6: Email Tests
**Agent:** 1 agent
**Complexity:** Medium
**Dependencies:** 13.2, 13.3, 13.4, 13.5

**Backend tests:**
- `test_services/test_email_integration_service.py`: sync logic, triage labels, label/archive/read operations, draft creation, inbox stats, cache queries
- `test_api/test_email.py`: all API endpoints, setup flow, search, pagination
- `test_agents/test_email_mcp.py`: MCP tool execution, permission mapping (especially send = requires approval), context assembly with email data
- `test_services/test_gmail_client.py`: MIME parsing (multipart, base64url decoding, encoding edge cases)

**Frontend E2E tests:**
- Email widget on Home (mocked API data)
- Email page navigation, label groups, quick actions
- Space email widget rendering
- Sidebar conditional visibility
- Browser tab badge count

**Target:** ~55 backend tests, ~10 E2E tests

**Acceptance criteria:** All tests pass. Email integration covered across service, API, MCP, context assembly, and frontend layers. MIME parsing tested with representative email formats.

### Task 13.7: Email Triage Automation Template + Documentation Update
**Agent:** 1 agent
**Complexity:** Small
**Dependencies:** 13.6 (all email work complete)

**Email Triage automation template** (new):
- Cron: every 2 hours during business hours (`0 8-18/2 * * 1-5`)
- Instruction: "Check inbox for unprocessed emails (without OL/ labels). For each: read the content, categorize as Needs Response / FYI / Follow Up / Waiting based on content and sender. Apply the appropriate OL/ label. For 'Needs Response' emails, create a task in the relevant space if one can be identified. Mark processed emails with OL/Agent Processed."
- Agent: shared "Automation Agent" (existing)
- Disabled by default

**Update existing morning briefing instruction** to include: "Summarize today's unread emails requiring attention. Include count by category and highlight any urgent items."

**Documentation update:**
- **ARCHITECTURE-PROPOSAL.md:** Add email API endpoints, services, MCP tools, `email_cache` table.
- **CAPABILITIES.md:** Update item #28 from [NOT BUILT] to [BUILT]. Update #30 status.
- **Regenerate OpenAPI spec.**

**Files modified:** `scripts/register_automation_templates.py`

**Acceptance criteria:** Email Triage template registered. Morning briefing references email. Documents updated. OpenAPI spec fresh.

---

## Phase 14: Integration Builder Agent

**Goal:** Users can connect arbitrary REST APIs to spaces through a conversational agent. The Integration Builder researches APIs, walks through setup, and creates data sources + automations + widgets.
**Prerequisite:** Phase 12 complete (cross-space data source infrastructure). Does not depend on Phase 13 — can run in parallel.

### Task 14.1: Integration Builder MCP Tools
**Agent:** 1 agent
**Complexity:** Medium
**Dependencies:** 12.1 (cross-space data source model)

Three exclusive MCP tools for the Integration Builder agent:

| Tool | Description |
|---|---|
| `create_api_data_source(space_id, name, source_type, config)` | Create a DataSource with API connection config (base_url, auth_headers, endpoints). Config stored as JSON — no credentials in items/memory. |
| `test_api_connection(data_source_id)` | Read the DataSource config, make a test request via `WebFetch`, return the response (status, headers, truncated body). Validate the connection works. |
| `create_sync_automation(data_source_id, cron_expression, agent_name, instruction)` | Create an automation that periodically fetches data from the API. The automation's instruction tells the agent what to fetch and where to store it. |

**Security constraints enforced in tools:**
- `config` field accepts `auth_header_name` and `auth_header_value` — stored in DataSource.config, which is NOT included in context assembly or memory. Agents can write to it but not read the auth values back (write-only for credentials).
- `test_api_connection` only returns response metadata and a truncated body preview (first 2000 chars), not raw response to prevent data exfiltration to context.

**Tool builder integration:**
- These tools are registered as exclusive to agents with name "Integration Builder" (same pattern as Agent Builder's exclusive tools in `mcp_tools.py`)
- All other agents do NOT get these tools

**Files modified:** `backend/openloop/agents/mcp_tools.py`

**Acceptance criteria:**
- `create_api_data_source` creates a DataSource with config
- `test_api_connection` makes a test HTTP request and returns result
- `create_sync_automation` creates a working automation
- Auth credentials stored in DataSource.config, not readable by other tools
- Tools only available to Integration Builder agent

### Task 14.2: Integration Builder Skill
**Agent:** 1 agent
**Complexity:** Medium
**Dependencies:** 14.1 (MCP tools)

Create the Integration Builder agent using the Agent Builder pattern.

**New file: `agents/skills/integration-builder/SKILL.md`**

System prompt covers:
- **Role:** Help users connect external REST APIs to OpenLoop spaces
- **Process:**
  1. Understand what data the user wants and from where
  2. Research the API (use WebSearch to find documentation)
  3. Identify auth requirements (API key, bearer token, basic auth)
  4. Walk the user through obtaining credentials
  5. Create the data source with `create_api_data_source`
  6. Test the connection with `test_api_connection`
  7. Iterate on the config if the test fails
  8. Set up a sync automation with `create_sync_automation`
  9. Suggest widgets to display the data
  10. Save a memory entry documenting the integration
- **Security rules:**
  - Never store API keys/tokens in items, memory, or conversation messages
  - Only store credentials via `create_api_data_source` (goes to DataSource.config)
  - Warn the user if they paste credentials in the chat (they'll be in conversation history)
- **Limitations:**
  - Cannot handle OAuth flows (redirect-based auth) — explain to user and suggest they request a direct integration
  - Cannot create new backend code or service files
  - Works within existing primitives (DataSource, Automations, WebFetch, Items, Memory)
  - **Do NOT attempt to integrate full task management tools (Asana, Trello, Linear, Jira).** These require a specialized Task Adapter pattern with bidirectional sync that is planned as a separate feature. If the user asks, explain this and suggest they use OpenLoop's built-in items for now.

**Registration:**
- Add to `scripts/register_skills.py` — registers "Integration Builder" as an agent with `skill_path="integration-builder"`
- Default spaces: all (cross-space capable)
- Default model: sonnet

**Odin routing:**
- Update Odin system prompt to route integration requests to Integration Builder: "connect my [X] data", "I want to pull data from [API]", "set up an integration for [service]"

**Files created:** `agents/skills/integration-builder/SKILL.md`
**Files modified:** `scripts/register_skills.py`, `backend/openloop/agents/odin_service.py` (routing instruction)

**Acceptance criteria:**
- Integration Builder registered as agent with skill_path
- System prompt covers the full integration workflow
- Odin routes integration requests to Integration Builder
- Integration Builder has exclusive MCP tools (standard agents don't)
- Security rules prevent credential leakage

### Task 14.3: Integration Builder Tests + Validation
**Agent:** 1 agent
**Complexity:** Small
**Dependencies:** 14.1, 14.2

**Backend tests:**
- `test_agents/test_integration_builder_mcp.py`: MCP tool execution (create data source, test connection with mocked HTTP, create automation)
- `test_services/test_data_source_service.py` (extend): API-type data source CRUD, credential storage in config
- Validation: DataSource.config schema validation for `source_type="api"` (must have `base_url`)

**Integration test (manual or semi-automated):**
- Connect to a public API (e.g., Open-Meteo weather API — no auth required)
- Verify: data source created, test connection succeeds, automation created, data flows on first sync

**Target:** ~15 backend tests

**Acceptance criteria:** All tests pass. Public API integration works end-to-end. Credential handling is secure (not in context, not in memory, only in DataSource.config).

---

## Execution Plan

### Migration Strategy

**Single migration revision for Phase 12.** Task 12.1 creates the Alembic revision containing ALL schema changes for Phases 12 and 13:
- ALTER `data_sources.space_id` to nullable
- ALTER `Space.data_sources` relationship cascade
- ADD `is_system` to `automations`
- CREATE `space_data_source_exclusions`
- CREATE `calendar_events` (with `data_source_id` FK)
- CREATE `calendar_events_fts` (FTS5 + triggers)
- CREATE `email_cache` (with `data_source_id` FK)
- CREATE `email_cache_fts` (FTS5 + triggers)

This avoids migration sequencing issues across agents. The `calendar_events` and `email_cache` tables are empty until their respective setup functions are called — creating them early costs nothing.

### Parallelism

```
Phase 12 (Calendar):
  Wave 1: [12.1] [12.2]              ← parallel (infra + OAuth/client)
  Wave 2: [12.3]                      ← depends on 12.1 + 12.2
  Wave 3: [12.4] [12.4b] [12.5]     ← parallel (MCP + templates + routes)
  Wave 4: [12.5b] then [12.6]        ← type gen then frontend
  Wave 5: [12.7]                      ← tests
  Wave 6: [12.8]                      ← documentation

Phase 13 (Email):
  Wave 1: [13.1]                      ← client (depends on 12.2 shared OAuth)
  Wave 2: [13.2]                      ← cache + triage (depends on 13.1 + 12.1)
  Wave 3: [13.3] [13.4]              ← parallel (MCP + routes)
  Wave 4: [13.4b] then [13.5]        ← type gen then frontend
  Wave 5: [13.6]                      ← tests
  Wave 6: [13.7]                      ← templates + documentation

Phase 14 (Integration Builder):   ← can start after 12.1 completes
  Wave 1: [14.1]                      ← MCP tools
  Wave 2: [14.2]                      ← skill creation
  Wave 3: [14.3]                      ← tests
```

**Phase 14 can run in parallel with Phase 13** — it only depends on 12.1 (cross-space data source infrastructure), not on the email integration.

### Estimated Agent-Tasks

| Phase | Tasks | Agents (parallel) | Sequential waves |
|---|---|---|---|
| Phase 12 | 10 tasks | up to 3 parallel | 6 waves |
| Phase 13 | 8 tasks | up to 2 parallel | 6 waves |
| Phase 14 | 3 tasks | 1 | 3 waves |
| **Total** | **21 tasks** | | |

### Human Review Gates

1. **After Task 12.1** — cross-space data source model affects existing FK, ORM cascade, and schemas. Verify backward compatibility. Run existing data_source and Drive tests before proceeding.
2. **After Task 12.2** — OAuth scope refactor touches existing Drive auth. Delete `token.json`, re-auth with all scopes, verify Drive + Calendar both work.
3. **After Task 12.8** — full calendar integration review before starting email (email builds on calendar patterns).
4. **After Task 13.3** — email send permission mapping. Verify "requires approval" default is correctly enforced.

---

## Resolved Questions (from v1 review)

1. **OAuth re-auth UX** — resolved in Task 12.2. Shared `google_auth.py` module with scope registry, `get_missing_scopes()`, and `get_auth_url()` with `include_granted_scopes=True`. Frontend shows "Grant access" button when scopes are missing, opens consent URL, polls until granted. Uses `InstalledAppFlow.run_local_server()` for local-first app (suitable for current deployment model).

2. **Sync conflict on writes** — resolved. Calendar `update_event()` includes etag. Google returns 412 on conflict. Agent retries with fresh data.

3. **Context assembly budget** — resolved. Calendar (500 tokens) and email (300 tokens) are separate END sections with their own budgets. Total context increases from 8,000 to 8,800. Odin increases from 4,000 to 4,800.

4. **System vs user automations** — resolved. `is_system` flag on Automation model (Task 12.1). System automations hidden from dashboard, non-deletable.

5. **Sync as function, not agent** — resolved. Integration syncs run as direct function calls in the scheduler loop, not `delegate_background` sessions. No LLM overhead for API-to-DB work.

6. **DataSource cascade** — resolved. `Space.data_sources` relationship changed from `cascade="all, delete-orphan"` to `cascade="all, delete"` with `passive_deletes=True`. System-level sources (space_id=null) are not affected by Space deletion.

## Remaining Open Questions

1. **Gmail message ID encoding.** Gmail API returns message IDs that may need URL-safe encoding for web links. Verify the link format `https://mail.google.com/mail/u/0/#inbox/{id}` works with the API's message ID, or if encoding is needed. Resolve during Task 13.2 build.

2. **Triage label cleanup.** If the user disconnects email, should OL/ labels be removed from Gmail? Decision: no — they're harmless and removing them could delete user-applied labels that coincidentally match. Document this behavior.

3. **Rate limits.** Google Calendar API: 1,000,000 queries/day per project. Gmail API: 250 quota units/second per user. 15-minute sync is well within limits. The retry-with-backoff pattern (Task 12.2) handles transient rate limits. If sustained rate limits become an issue, reduce sync frequency dynamically.

4. **Multiple Google accounts.** Current OAuth supports one Google account. Calendar/email don't change this. Multi-account is a future enhancement if needed.
