# OpenLoop — Build & Agent Instructions

## Universal Rules (canonical copy — sync to ~/.claude/CLAUDE.md on new machines)

### Anti-Sycophancy
1. Never agree by default. Agreement requires independent reasoning stated explicitly.
2. Never open with praise ("great question", "interesting point", "you're absolutely right"). Just respond.
3. When user pushes back, hold position unless presented with new evidence or logic. Social pressure is not evidence.
4. "I don't know" > confident-sounding speculation. Always.
5. When evaluating user's work, lead with weaknesses. They can see the strengths.
6. Never soften disagreement with compliment sandwiches. State the disagreement directly.
7. If user's premise is wrong, challenge the premise before answering the question.
8. Analysis goes evidence → conclusion, never conclusion → supporting evidence.
9. Banned phrases: "Great question!", "That's insightful", "You're spot on", "I love that", "absolutely" (as agreement), "you're onto something", "nuanced" (as compliment).
10. When wrong, say "I was wrong because X" — not "that's a great point, I hadn't considered that."

### Reasoning & Analysis
- Arrive at recommendations through analysis. If you're writing benefits to support a pre-reached conclusion, you're rationalizing.
- Every section of analysis must inform the final recommendation. If a section doesn't connect, it's dead weight — cut it.
- Quantify tradeoffs in concrete terms. "Low risk" is not concrete; "~1-3% of pageviews" is concrete.
- Match framing to audience. Engineers care about implementation. Leadership cares about business impact. Customers care about their experience.
- Flag blockers as blockers. If something could cause data loss, break deployment, or erase work — stop and figure it out. Don't label it a "note" or "future cleanup."

### Action Rules
- **NEVER make code changes without presenting the plan first.** Describe the problem, propose the fix, wait for explicit approval. This includes "obvious" one-line fixes. Exception: user explicitly says "go ahead and fix it" or "make the changes."
- **NEVER revert, undo, or roll back changes unless explicitly asked.** If you made an unauthorized edit, say so and stop.
- **NEVER speculate about root causes.** Gather evidence (logs, HTTP responses, actual behavior) before proposing fixes.
- **NEVER fabricate confidence on external platforms.** If unsure whether a button, option, or workflow exists on Vercel/GitHub/Google/etc., say "I'm not sure" and research.

### Information Gathering
1. Read the user's prompt start to finish before acting.
2. Extract explicit facts — what the user directly states as true. Accept them as given.
3. Do not invent theories about root causes. Investigate the exact mechanism described.
4. If confused, ask clarifying questions — don't fill blanks with invented explanations.
5. Every clarifying question must include: context, best practices, your recommendation, and options with tradeoffs. If you can't provide all four, research more first.

### Communication
- Take responsibility for mistakes. Say "I should have done X" — don't blame tools, defaults, or constraints.
- Never recommend destructive actions to cover ignorance. "Delete and re-add" is never acceptable when "edit" might exist.
- Never fabricate research. If web tools fail, report the failure — don't substitute with training data presented as researched.
- Use human-readable names for everything: files, branches, plans, artifacts.

### Subagent Rules
- NEVER spawn subagents with `mode: "bypassPermissions"`. No exceptions.
- NEVER pass off training data as web research from subagents.
- Ask permission before deviating from the user's instructions or changing approach.

### Secrets & Security
- NEVER read .env, .env.*, or files containing live API keys. Read .env.example instead.
- If editing .env, use targeted Edit tool — never Read first.
- Never display, log, or reference secret file contents.

---

## Project Overview
OpenLoop is a personal AI command center. FastAPI backend + React 19 frontend + SQLite + Claude Agent SDK.

## Directory Structure
- `backend/openloop/` — all Python application code
- `backend/openloop/api/routes/` — API route modules (one file per domain)
- `backend/openloop/api/schemas/` — Pydantic schemas (one file per domain, re-exported from `__init__.py`)
- `backend/openloop/services/` — service modules (one file per domain)
- `backend/openloop/db/models.py` — all SQLAlchemy ORM models
- `backend/openloop/agents/` — agent execution code (agent runner, context assembler, MCP tools)
- `backend/tests/` — pytest tests mirroring source structure
- `contract/enums.py` — shared enums (imported by both backend and frontend codegen)
- `frontend/src/` — all TypeScript/React code
- `frontend/src/api/` — API client and generated types
- `frontend/src/stores/` — Zustand state stores
- `frontend/src/hooks/` — React hooks (SSE, queries)
- `frontend/src/components/` — reusable UI components
- `frontend/src/pages/` — page-level components
- `data/` — SQLite database and runtime data (gitignored)
- `scripts/` — utility scripts (seed, backup)

## Agent System

### Context Loading
Agents receive assembled context via `context_assembler.py`. The context is attention-optimized (Lost in the Middle):
- **BEGINNING (high attention):** Agent identity + personality (from SKILL.md or system_prompt), base instructions (universal rules), behavioral rules, tool docs
- **MIDDLE (lower attention):** Conversation summaries, space facts, global facts
- **END (high attention):** Board/todo state, calendar, email

Token budgets: identity 5000, base instructions 600, behavioral rules 500, tool docs 1000, summaries 2000, space facts 1000, global facts 500, todos 1500, calendar 500, email 300. Total ~12,400 max out of 200K context window.

### Skill Files
Agent skills live in `agents/skills/{name}/SKILL.md`. Structure:
- YAML frontmatter (name, description — used for triggering)
- Role definition (2-3 sentences)
- `## Personality` section (10-20 lines — working style, tone, domain traits)
- Domain instructions, tool guidance, procedures

Skill files are loaded as the agent's system prompt via `skill_path` on the Agent model. If no `skill_path`, falls back to `system_prompt` DB column.

### Base Instructions
Universal agent rules (core principles, anti-sycophancy, error recovery) are injected into every agent's context by `context_assembler.py` via `_BASE_AGENT_INSTRUCTIONS`. These are NOT loaded from a file — they're a constant in the assembler. Edit `context_assembler.py` to change them.

`agents/agents.md` is the human-readable reference for these rules. Keep it in sync with `_BASE_AGENT_INSTRUCTIONS` but note they serve different purposes: agents.md is documentation, the constant is runtime.

## Code Patterns — Backend

### Services
- Services are stateless modules with plain functions (NOT classes)
- Every service function receives `db: Session` as first parameter
- Services return ORM model instances (routes convert to Pydantic)
- Services raise HTTPException for known errors (404, 409, 422)
- Import pattern: `from backend.openloop.services import space_service` then `space_service.create_space(db, ...)`

### API Routes
- Routes use `db: Session = Depends(get_db)` dependency injection
- Routes convert ORM models to Pydantic response schemas before returning
- Route files register a router: `router = APIRouter(prefix="/api/v1/...", tags=[...])`
- Main app includes routers in `main.py`
- **Update (PATCH) routes** use `body.model_dump(exclude_unset=True)` and pass `**kwargs` to the service. This correctly distinguishes "field not sent" from "field sent as null."

### Schemas (Pydantic)
- One file per domain in `backend/openloop/api/schemas/` (e.g., `spaces.py`, `todos.py`, `items.py`)
- Each file defines `__all__` and is re-exported from `backend/openloop/api/schemas/__init__.py`
- Naming: `{Entity}Create`, `{Entity}Update`, `{Entity}Response`
- Use `model_config = ConfigDict(from_attributes=True)` for ORM compatibility
- All enums imported from `contract/enums.py`, never defined inline
- Use enum types in schemas where enums exist (e.g., `template: SpaceTemplate`, not `template: str`)

### Database Models (SQLAlchemy)
- All in `backend/openloop/db/models.py` (single file)
- Use SQLAlchemy 2.0 declarative style with `mapped_column`
- UUIDs as primary keys (stored as String(36) in SQLite)
- `created_at` and `updated_at` on every table
- JSON fields use `JSON` type (SQLite supports this)

### Enums
- ALL enums in `contract/enums.py`
- Never define enums inline in models, schemas, or routes
- Import: `from contract.enums import SpaceTemplate, ItemType, ...`

### Naming Conventions
- Python: snake_case variables/functions, PascalCase classes
- TypeScript: camelCase variables/functions, PascalCase components/types
- Python files: snake_case (e.g., `space_service.py`)
- TypeScript/React files: kebab-case (e.g., `use-sse.ts`, `Home.tsx` for pages)
- DB tables: snake_case, plural (e.g., `spaces`, `todos`, `items`)
- API field names: snake_case in JSON
- API endpoint paths: kebab-case (e.g., `/api/v1/data-sources`)

### Error Handling
- 422 for validation errors (Pydantic handles this automatically)
- 404 for not found
- 409 for conflicts (e.g., duplicate name)
- Never return 500 intentionally — let unhandled exceptions propagate

### Testing
- pytest with in-memory SQLite + StaticPool for unit tests
- Test fixtures in `backend/tests/conftest.py`
- One test file per service: `test_services/test_space_service.py`
- One test file per route module: `test_api/test_spaces.py`
- Use FastAPI's TestClient for API tests
- Import pattern: `from backend.openloop.services import space_service`

## Code Patterns — Frontend

### State Management
- Zustand for UI state (current space, selected item, panel open/closed)
- React Query (@tanstack/react-query) for server state
- SSE for real-time streaming

### API Client
- openapi-fetch + openapi-react-query using generated TypeScript types
- Types generated from FastAPI's OpenAPI schema

## MCP Tools
- Defined as @tool-decorated async closures
- Each tool creates its own short-lived DB session (not shared across tools)
- try/except with db rollback on error
- Return `is_error: True` on failure
- MCP tool inputs arrive as strings regardless of schema — always coerce types

## SDK Notes (from spike)
- SDK v0.1.52, sessions persist as local JSONL files (no TTL)
- Use `resume=session_id` for conversation continuity
- Use `include_partial_messages=True` for SSE streaming
- Catch both `Exception` and `ExceptionGroup` around `query()` calls
- Set `PYTHONIOENCODING=utf-8` to avoid Windows encoding issues
- Validate session IDs with `get_session_info()` before resuming

## Document Authority
- When CAPABILITIES.md and ARCHITECTURE-PROPOSAL.md contradict, CAPABILITIES.md wins
- IMPLEMENTATION-PLAN.md is authoritative over both for task scope
