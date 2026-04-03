# OpenLoop — Build Agent Instructions

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
