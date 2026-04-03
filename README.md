# OpenLoop

Personal AI command center. Manage work across multiple spaces, interact with AI agents, delegate tasks, track progress, and automate workflows — all from one interface.

## Status

**Phases 0–7 complete.** Core backend, agent system, frontend, memory architecture, records/documents/search, space layouts, unified item model, agent builder, sub-agent delegation, steering, automations, polish, backup, and E2E tests all built and reviewed.

See [PROGRESS.md](PROGRESS.md) for detailed build status and [IMPLEMENTATION-PLAN.md](IMPLEMENTATION-PLAN.md) for the full task breakdown. See [guide.md](guide.md) for usage documentation.

## Design Documents

- **[guide.md](guide.md)** — user guide (getting started + system deep-dive)
- **[CAPABILITIES.md](CAPABILITIES.md)** — what the system does (v5, updated with agent intelligence upgrade)
- **[ARCHITECTURE-PROPOSAL.md](ARCHITECTURE-PROPOSAL.md)** — how it's built (v4, updated with four-tier memory, context safety, and new flows)
- **[CAPABILITIES-ADDENDUM.md](CAPABILITIES-ADDENDUM.md)** — product-level research report on the agent intelligence capabilities (rationale, user experience descriptions, competitive context, sources)
- **[IMPLEMENTATION-PLAN.md](IMPLEMENTATION-PLAN.md)** — phase-by-phase build plan (59 tasks across 9 phases)

## Key Concepts

- **Spaces** — containers for related work. Can be a project, knowledge base, CRM, or simple task list.
- **Items** — all tracked work. Tasks (things to do, with done/not-done) and records (entities to track, like contacts or leads). Viewable as list, kanban, or table.
- **Odin** — always-visible AI front door (Haiku). Routes you to the right agent and handles simple actions.
- **Agents** — configured AIs with specific roles, tools, and permissions scoped to spaces. Each agent is a domain specialist (Recruiting Agent, Code Agent, Research Agent, etc.). Created through the Agent Builder.
- **Conversations** — persistent chat threads with agents. Context survives across sessions via four-tier memory and conversation summaries.
- **Documents** — uploaded files, scanned directories, or synced Google Drive folders. Text extracted and indexed for search.
- **Automations** — scheduled or event-triggered agent runs (daily briefing, stale work check, follow-up reminders, etc.).

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
