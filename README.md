# OpenLoop

Personal AI command center. Manage work across multiple spaces, interact with AI agents, delegate tasks, track progress, and automate workflows — all from one interface.

## Status

**Phases 0–11 complete.** Core backend, agent system, frontend, memory architecture, records/documents/search, space layouts, unified item model, agent builder, sub-agent delegation, steering, automations, autonomous agent operations (kill switch, compaction, approval queues, fan-out, crash recovery), polish, backup, and E2E tests all built and reviewed. **Phase 12–14 (Integrations: Google Calendar, Gmail, Integration Builder) next** — see [INTEGRATION-CAPABILITIES.md](INTEGRATION-CAPABILITIES.md) and [IMPLEMENTATION-PLAN-PHASE12.md](IMPLEMENTATION-PLAN-PHASE12.md).

See [PROGRESS.md](PROGRESS.md) for detailed build status. See [guide.md](guide.md) for usage documentation.

## Design Documents

- **[guide.md](guide.md)** — user guide (getting started + system deep-dive)
- **[CAPABILITIES.md](CAPABILITIES.md)** — what the system does (v5, updated with agent intelligence upgrade)
- **[ARCHITECTURE-PROPOSAL.md](ARCHITECTURE-PROPOSAL.md)** — how it's built (v4, updated with four-tier memory, context safety, and new flows)
- **[CAPABILITIES-ADDENDUM.md](CAPABILITIES-ADDENDUM.md)** — product-level research report on the agent intelligence capabilities (rationale, user experience descriptions, competitive context, sources)
- **[IMPLEMENTATION-PLAN.md](IMPLEMENTATION-PLAN.md)** — phase-by-phase build plan, Phases 0–7
- **[IMPLEMENTATION-PLAN-PHASE8.md](IMPLEMENTATION-PLAN-PHASE8.md)** — Phases 8–11 (autonomous agent operations)
- **[AUTONOMOUS-AGENTS.md](AUTONOMOUS-AGENTS.md)** — autonomous agent operations design
- **[INTEGRATION-CAPABILITIES.md](INTEGRATION-CAPABILITIES.md)** — Google Calendar, Gmail, and Integration Builder capability spec
- **[IMPLEMENTATION-PLAN-PHASE12.md](IMPLEMENTATION-PLAN-PHASE12.md)** — Phases 12–14 (integrations)
- **[FUTURE-CAPABILITIES.md](FUTURE-CAPABILITIES.md)** — long-term roadmap (external task sources, model adapters)

## Key Concepts

- **Spaces** — containers for related work. Can be a project, knowledge base, CRM, or simple task list.
- **Items** — all tracked work. Tasks (things to do, with done/not-done) and records (entities to track, like contacts or leads). Viewable as list, kanban, or table.
- **Odin** — always-visible AI front door (Haiku). Routes you to the right agent (selecting the appropriate model based on task complexity) and handles simple actions.
- **Agents** — configured AIs with specific roles, tools, and permissions scoped to spaces. Each agent is a domain specialist (Recruiting Agent, Code Agent, Research Agent, etc.). Created through the Agent Builder.
- **Conversations** — persistent chat threads with agents. Context survives across sessions via four-tier memory and conversation summaries.
- **Documents** — uploaded files, scanned directories, or synced Google Drive folders. Text extracted and indexed for search.
- **Automations** — scheduled or event-triggered agent runs (daily briefing, stale work check, follow-up reminders, etc.).
- **Autonomous Agents** — Agents can pursue goals independently over hours. Give an agent an objective, it builds a task list, works through items, adapts its plan, and reports back. Built on three autonomy tiers (interactive, supervised, autonomous) with permission inheritance (sub-agents inherit parent scope, never exceed it), compaction for indefinite sessions, and safety controls (kill switch, audit logging, approval queues).

## Memory Architecture

Agents use a four-tier memory system based on cognitive science research (CoALA framework):

1. **Semantic memory** (facts) — knowledge about the world, with temporal validity and write-time deduplication
2. **Episodic memory** (conversation summaries) — what happened in past conversations, with automatic consolidation
3. **Working memory** (board/to-do state) — what's happening right now
4. **Procedural memory** (behavioral rules) — how to behave, learned from user corrections

Context is assembled with token budgets, scored retrieval (importance + recency + access frequency), and attention-optimized ordering. Pre-compaction flush prevents information loss during summarization.

## Tech Stack

- **Backend:** Python (FastAPI) + SQLite
- **Frontend:** React 19 + Tailwind CSS v4 (Vite)
- **AI:** Claude Agent SDK → Claude Max subscription (Haiku/Sonnet/Opus)
- **Streaming:** Server-Sent Events (SSE)
- **Search:** SQLite FTS5 (full-text search on memory, messages, summaries)

## Quick Start

```bash
make migrate      # initialize the database
make dev          # start backend (port 8010) + frontend (port 5173)
```

Open `http://localhost:5173`. Optionally seed demo data with `python scripts/seed.py`.

See [guide.md](guide.md) for full setup instructions, usage walkthrough, and system deep-dive.

## Prior Art

Built from lessons learned with the `dispatch` prototype (C:\dev\dispatch). Memory architecture informed by analysis of OpenClaw, Letta/MemGPT, Mem0, Zep, CrewAI, and LangMem. See [CAPABILITIES-ADDENDUM.md](CAPABILITIES-ADDENDUM.md) for the full competitive research.
