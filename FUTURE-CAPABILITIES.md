# OpenLoop: Future Capabilities (DRAFT v1)

**Status:** Vision / roadmap — not approved for implementation.
**Context:** Based on analysis of Paperclip (paperclip.ing), Asana, and OpenLoop's current architecture. This document extends CAPABILITIES.md with future directions. It does not override or replace any current specs.

---

## Guiding Principle

OpenLoop's core differentiator is its **cognitive layer** — four-tier memory, context assembly with attention optimization, permission enforcement at the tool level, and proactive surfacing. These are things no external tool provides. Future capabilities should extend this cognitive core, not replace it with orchestration complexity that doesn't serve a single-user tool.

External tools (Asana, Trello, Linear, Google Calendar, Gmail) are better at collaboration, mobile access, and mature UI for their specific domains. OpenLoop should integrate with them rather than rebuild what they do well. OpenLoop's job is to be the AI command layer on top of those tools — the intelligence, context, and automation that makes them more useful.

---

## 1. External Task Management Integration

### The Problem

OpenLoop has a built-in item system (tasks + records, list/kanban/table views). This is the right default for spaces that don't need external tooling — knowledge bases, simple personal lists, lightweight project tracking. But for spaces where serious task management matters (recruiting pipelines, client projects, product development), dedicated tools like Asana, Trello, or Linear do it better: dependency graphs, timeline views, mobile apps, collaboration, activity history.

Building a second Asana is wasted work. Instead, a space should be able to **bind to an external task management source**, making that source authoritative for task state in that space.

### How It Works

A space can optionally connect an **external task source** as a special data source type. When connected:

- The external system is the **source of truth** for tasks in that space
- OpenLoop's item views (list, kanban, table) render tasks from the external system, not the local DB
- Agent MCP tools for task operations in that space write to the external system
- The built-in item system is still available for spaces without an external source (the default)
- A space can have both: external tasks from Asana AND local items (records, notes, lightweight tasks that don't belong in the external system)

### Integration Architecture

```
┌─────────────────────────────────────────────────┐
│                  Space                           │
│                                                  │
│  ┌──────────────┐    ┌────────────────────────┐  │
│  │ Local Items   │    │ External Task Source    │  │
│  │ (built-in DB) │    │ (Asana / Trello / etc) │  │
│  └──────┬───────┘    └──────────┬─────────────┘  │
│         │                       │                │
│         ▼                       ▼                │
│  ┌──────────────────────────────────────────┐    │
│  │         Task Adapter Interface            │    │
│  │  list_tasks() / create_task() / update()  │    │
│  │  move_to_stage() / complete() / search()  │    │
│  └──────────────────────────────────────────┘    │
│         │                       │                │
│         ▼                       ▼                │
│  ┌──────────────┐    ┌────────────────────────┐  │
│  │ item_service  │    │ asana_adapter /         │  │
│  │ (local DB)    │    │ trello_adapter / etc    │  │
│  └──────────────┘    └────────────────────────┘  │
└─────────────────────────────────────────────────┘
```

The key abstraction is a **task adapter interface** — a normalized set of operations that both the local item_service and external adapters implement. Agent MCP tools call the adapter, not the service directly. This means:

- Adding a new external source (Linear, Jira, GitHub Issues) is an adapter implementation, not a tool rewrite
- Agents don't know or care whether tasks are local or external
- The UI renders from the same normalized task model regardless of source

### Adapter Interface (Sketch)

```python
class TaskAdapter(Protocol):
    async def list_tasks(self, filters: TaskFilters) -> list[NormalizedTask]: ...
    async def get_task(self, task_id: str) -> NormalizedTask: ...
    async def create_task(self, title: str, **kwargs) -> NormalizedTask: ...
    async def update_task(self, task_id: str, **kwargs) -> NormalizedTask: ...
    async def complete_task(self, task_id: str) -> NormalizedTask: ...
    async def move_to_stage(self, task_id: str, stage: str) -> NormalizedTask: ...
    async def search_tasks(self, query: str) -> list[NormalizedTask]: ...
```

`NormalizedTask` maps external fields to OpenLoop's display model: title, description, stage, is_done, due_date, assignee, priority, custom_fields, external_url. The adapter handles the translation — Asana sections become stages, Trello lists become stages, Linear states become stages.

### What This Enables

- "Connect this space to my Asana project" → space shows Asana tasks in kanban/list/table views
- Agents can create, update, move, and complete Asana tasks through their normal MCP tools
- Morning briefing automation pulls tasks from Asana alongside local items
- Context assembly includes external task state — agents know what's on the board regardless of where it lives
- You use Asana's mobile app to check tasks on the go; agents use OpenLoop's cognitive layer to work on them

### Supported Sources (Prioritized)

1. **Asana** — mature API (47 resource types), good Python client, existing MCP server (roychri/mcp-server-asana with 41 tools). Requires paid plan for search API and custom fields ($10.99/user/month Starter tier). Rate limit: 1,500 req/min on paid.
2. **Trello** — simpler model (boards/lists/cards), free tier is more capable, good for lightweight project tracking.
3. **Linear** — modern API, good for software development workflows. GraphQL API.
4. **GitHub Issues** — for code-focused spaces. Already close to the development workflow.

### What OpenLoop Does NOT Replicate

Even with external integration, OpenLoop does not try to rebuild:
- Dependency graphs and timeline views (use Asana's UI for those)
- Multi-user collaboration and permissions (use the external tool)
- Mobile task management (use the external tool's mobile app)
- Activity history / audit trail (the external tool already tracks this)

OpenLoop adds: AI agents that understand context, proactive briefings, memory that persists across conversations, automated task triage, and a unified view across all your spaces.

### Migration Path

The built-in item system stays indefinitely. External task sources are additive — you opt in per space. If you disconnect an external source, the space falls back to local items. No data migration needed because external tasks were never stored locally (or if cached, the cache is just a read-through layer).

### Prerequisites

- Data source infrastructure (already in architecture as P1)
- Webhook receiver for bidirectional sync (new — external tools push changes to OpenLoop)
- Task adapter interface (new abstraction layer between MCP tools and item_service)
- Normalized task model for display (new — maps external schemas to OpenLoop's view layer)

---

## 2. Operational Patterns for Background Agents

These patterns are drawn from Paperclip's architecture. They address operational concerns — cost, concurrency, reliability — that become important as OpenLoop runs more background agents and automations.

### 2a. Heartbeat Protocol for Automations

**Problem:** As automations grow (morning briefing, email check, follow-up scan, stale work detection), each one is currently a bespoke "run this agent with this instruction." There's no standardized contract for how background agents behave, which makes monitoring, debugging, and extending automations harder over time.

**Solution:** A standardized protocol that all background agents follow when woken by an automation trigger:

```
1. IDENTIFY    — who am I, what space am I in, why was I woken (cron / event / manual)
2. ORIENT      — fetch current state: open tasks, recent changes, pending items
3. PRIORITIZE  — if multiple things need attention, pick highest priority
4. EXECUTE     — do the work (one discrete unit per cycle)
5. REPORT      — update task status, add comments, log what was done
6. SURFACE     — create notifications for anything that needs human attention
```

This is injected into the agent's system prompt as behavioral guidance, not enforced by code. Agents that follow the protocol produce consistent, auditable output. The agent runner's `delegate_background()` already provides the turn loop — this adds structure to what happens within each turn.

**Not adopted from Paperclip:** The org chart / reporting hierarchy, CEO/manager/IC roles, agent "hiring" with board approval. These are organizational metaphors that don't serve a single-user tool.

### 2b. Token and Cost Tracking

**Problem:** OpenLoop's architecture doesn't track how much each agent or automation costs. With Claude Max, you're not paying per token, but you are consuming a shared quota. A runaway automation could burn through your daily allowance without you knowing.

**Solution:** Log token usage per interaction.

- Add `input_tokens` and `output_tokens` columns to `conversation_messages`
- Extract from SDK response metadata (the SDK spike confirmed token counts are available in ResultMessage)
- Aggregate by agent, by space, by conversation, by time period
- Surface in a simple dashboard: "This agent has used X tokens this month" / "This automation averages Y tokens per run"
- Optional: configurable alert threshold ("notify me if an automation uses more than Z tokens in one run")

This is lightweight — a few columns and an aggregation query. No budget enforcement, no hard stops. Just visibility.

**Not adopted from Paperclip:** Per-agent monthly budgets with hard stops and auto-pause. That's the "AI company managing employee spend" pattern. A personal tool just needs visibility.

### 2c. Atomic Task Checkout

**Problem:** If two agents run simultaneously (e.g., two automations fire at the same time, or a user conversation and a background agent both target the same task), they could conflict — both trying to update the same task, producing contradictory results.

**Solution:** When an agent starts working on a specific task, it checks it out. Checkout is atomic — if another agent already has it, the second agent gets a conflict and picks different work.

```python
# item_service addition
def checkout_item(db, item_id: str, agent_id: str, run_id: str) -> Item:
    """Atomically claim an item for work. Returns 409 if already checked out."""

def release_item(db, item_id: str, run_id: str) -> Item:
    """Release checkout when work is done or agent session ends."""
```

On the item model: `checked_out_by` (agent_id, nullable), `checkout_run_id` (for stale detection), `checked_out_at` (timestamp). Session cleanup releases stale checkouts (e.g., if an agent crashes mid-work).

**When this matters:** Only when concurrent agents are a real scenario — multiple automations running simultaneously, or automations running alongside user conversations that modify the same items. Not needed until P2 automations are active.

### 2d. Model Adapter Interface

**Problem:** OpenLoop currently assumes Claude SDK everywhere. If you want Odin on Haiku, a research agent using Gemini's grounding for web search, or a coding agent using a local model, there's no clean abstraction for swapping the underlying model.

**Solution:** A model adapter interface between the agent runner and the execution layer.

```python
class ModelAdapter(Protocol):
    async def run_interactive(self, config: SessionConfig, message: str) -> AsyncIterator[Chunk]: ...
    async def close_conversation(self, session: SessionHandle) -> None: ...
```

The Claude SDK adapter is the default and primary implementation. Others (Gemini, OpenAI, local models) are added as needed. The agent runner calls the adapter, not the SDK directly.

**When this matters:** Not until you want non-Claude models for specific agents. The current architecture (Claude SDK everywhere) is correct for now. This is an extraction refactor when the need arises, not an upfront abstraction.

**Learned from Paperclip:** Their adapter system (7 adapters: Claude, Codex, Cursor, Gemini, OpenClaw, OpenCode, Pi) is genuinely runtime-agnostic and well-designed. The pattern of adapter as a self-contained package with execution, parsing, and configuration is clean. OpenLoop's version would be simpler (no CLI process spawning, no org chart integration) but the interface shape is similar.

---

## 3. Multi-Agent Orchestration (Future)

OpenLoop's current architecture handles one agent per conversation, with sub-agent delegation planned for P1. This section describes how to extend to coordinated multi-agent work when the need arises.

### What Multi-Agent Means for a Personal Tool

Not an org chart. Not AI employees. The use cases are:

- **Parallel research:** "Research these 5 candidates" → one coordinating agent spawns 5 research sub-agents, collects results, synthesizes
- **Cross-space work:** morning briefing agent reads from Recruiting, Product, and Personal spaces, synthesizes into one brief
- **Pipeline automation:** email agent detects a new lead → creates a record in the CRM space → recruiting agent picks it up and starts outreach prep
- **Delegation chains:** you tell your recruiting agent to "prepare for tomorrow's interviews" → it delegates background research to a sub-agent, prep doc drafting to another, and coordinates the outputs

### Architecture Extensions Needed

The current agent runner + delegate_background() handles single-agent background work. Multi-agent coordination adds:

1. **Agent-to-agent task assignment:** An agent creates a task and assigns it to another agent. The assigned agent is woken (same as automation trigger). Results flow back through the task system (status updates, comments, linked artifacts).

2. **Coordination primitives:**
   - `delegate_to_agent(agent_id, instruction, space_id)` — creates a task, assigns it, wakes the target agent
   - `wait_for_task(task_id)` — coordinating agent checks task status at each turn boundary
   - `collect_results(task_ids)` — gather outputs from multiple delegated tasks

3. **Concurrency controls:**
   - Max concurrent agent sessions (already in architecture, default 5)
   - Priority: interactive > delegated > automated
   - Atomic checkout prevents double-work (see 2c above)
   - Queue with notification when limit hit

4. **Result aggregation:** When a coordinating agent delegates to N sub-agents, it needs to collect and synthesize results. This happens through the task system — sub-agents write results to their assigned tasks, the coordinator reads them. No special message bus needed.

### What's NOT Needed (Learned from Paperclip)

- **Org chart / reporting hierarchy:** Paperclip's core metaphor. Agents have managers, report to a CEO, escalate up the chain. This is organizational overhead that doesn't help one person.
- **Agent hiring with governance:** Paperclip requires board approval to create new agents. OpenLoop has agent creation via UI form or Agent Builder — no governance layer needed for a personal tool.
- **Company-scoped budgets:** Per-company, per-project, per-agent financial controls. Unnecessary. Simple token tracking (2b) is sufficient.
- **Plugin SDK with RPC protocol:** Paperclip has a full plugin system with worker-based isolation, UI extension points, job scheduling. OpenLoop's extensibility is MCP tools — any capability can be added as a tool. No plugin framework needed.

---

## 4. What Paperclip Gets Right (Reference)

Paperclip (paperclip.ing, ~43k GitHub stars) is an open-source "control plane for multi-agent companies." It's solving a fundamentally different problem than OpenLoop — managing teams of agents as employees with organizational structure — but several of its engineering decisions are worth understanding.

### Architecture Summary

- **67 PostgreSQL tables**, 66 service modules, 25 API route modules
- **7 agent adapters**: Claude Code, Codex, Cursor, Gemini, OpenClaw, OpenCode, Pi
- **Adapter-agnostic execution**: agents are runtime-agnostic, connected through a standardized adapter interface
- **Heartbeat protocol**: 9-step contract (identity → approvals → inbox → pick work → checkout → context → execute → update → delegate)
- **Financial controls**: per-agent monthly budgets with soft warn (80%) and hard stop (100%), auto-pause/resume
- **Task system**: issues with atomic checkout, status lifecycle (backlog → todo → in_progress → in_review → done), hierarchical delegation
- **Session management**: per-adapter compaction thresholds (max runs, max tokens, max age), session ID persistence across heartbeats
- **Plugin SDK**: full RPC protocol, worker isolation, UI extensions, job scheduling

### What Paperclip Does NOT Have

- **No server-side memory system.** No memory tables, no embeddings, no retrieval scoring. Memory is file-based, per-agent, on the agent's local disk (PARA method: projects/areas/resources/archives + daily notes + MEMORY.md). "Memory does not survive session restarts. Files do."
- **No context assembly intelligence.** Agents get environment variables and a heartbeat-context endpoint. No token budgets, no attention optimization, no four-tier memory retrieval.
- **No tool-level permissions.** One boolean permission: `canCreateAgents`. Safety is financial (budgets) and organizational (hierarchy), not cognitive.
- **No proactive system.** No briefings, no dropped-ball detection, no meeting prep, no stale work scanning.
- **No unified item model.** Basic issue tracker (title, description, status, assignee). No records, no custom fields, no views, no item linking.

### Key Takeaway

Paperclip is a dispatcher and record-keeper. OpenLoop is a cognitive architecture and personal productivity system. They overlap on "agents doing work on tasks" but diverge on everything else. Paperclip's operational patterns (heartbeat, checkout, cost tracking, adapter interface) are transferable. Its organizational patterns (org chart, governance, budgets) are not relevant.

---

## Implementation Priority

These capabilities are ordered by when they'd realistically be needed:

| Capability | When | Depends On |
|---|---|---|
| Token tracking (2b) | P2 — when automations run regularly | conversation_messages table exists |
| Heartbeat protocol (2a) | P2 — when automations are built | automation infrastructure |
| External task sources (1) | P3 — after core is stable and in daily use | data source infrastructure, adapter interface |
| Atomic task checkout (2c) | P3 — when concurrent agents are real | multiple automations running simultaneously |
| Model adapter interface (2d) | P3 — when non-Claude models are wanted | clear use case for a non-Claude agent |
| Multi-agent orchestration (3) | P3+ — when delegation chains are needed | sub-agent delegation (P1), task checkout |

None of these block the current implementation plan. The current architecture (CAPABILITIES.md P0-P2) is the right thing to build now. These are extensions that build on top of it.

---

## Open Questions

1. **Which external task tool first?** Asana has the most mature API and an existing MCP server, but requires a paid plan for useful features. Trello's free tier is more capable. Linear is modern but niche. The choice depends on what you're actually using when this becomes relevant.

2. **Bidirectional sync vs. read/write through?** Bidirectional sync (webhook-driven, OpenLoop caches external state) is more complex but enables offline access and faster UI rendering. Read/write through (always hit the external API) is simpler but slower and requires connectivity. For a personal tool, read/write through is probably fine initially.

3. **How does external task state feed into context assembly?** When a space is bound to Asana, the context assembler needs to include Asana task state in the working memory tier. This could be a periodic snapshot (cached on sync) or a live fetch (slower but always current). The adapter interface should support both patterns.

4. **Token tracking granularity?** Per-message is the most granular and useful. Per-conversation is cheaper to compute. Per-agent-per-month is the minimum useful aggregation. Start with per-message logging (it's just two columns) and aggregate as needed.
