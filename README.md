# OpenLoop

Personal AI command center. Manage work across multiple spaces, interact with AI agents, delegate tasks, track progress, and automate workflows — all from one interface.

## Status

**Pre-implementation.** Design documents finalized. Build starting from scratch.

## Design Documents

- **[CAPABILITIES.md](CAPABILITIES.md)** — what the system does (v5)
- **[ARCHITECTURE-PROPOSAL.md](ARCHITECTURE-PROPOSAL.md)** — how it's built (v4)

## Key Concepts

- **Spaces** — containers for related work. Can be a project, knowledge base, CRM, or simple to-do list.
- **To-dos** — lightweight checklist items. Every space has them.
- **Board items** — heavier work items that move through stages (Kanban). Optional per space.
- **Odin** — always-visible AI front door (Haiku). Routes you to the right agent and handles simple actions.
- **Agent conversations** — persistent, named chat threads with AI agents scoped to spaces.
- **Automations** — scheduled agent runs (daily briefing, email check, etc.).

## Architecture

- **Backend:** Python (FastAPI) + SQLite
- **Frontend:** React 19 + Tailwind CSS v4 (Vite)
- **AI:** Claude Agent SDK → Claude Max subscription (Haiku/Sonnet/Opus)
- **Streaming:** Server-Sent Events (SSE)

## Prior Art

Built from lessons learned with the `dispatch` prototype (C:\dev\dispatch). That codebase serves as a reference for SDK patterns, hook behavior, and permission approaches. See `dispatch/memory-bank/DECISIONS.md` for design rationale that carries forward.
