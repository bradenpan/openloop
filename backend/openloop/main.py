import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.openloop.database import SessionLocal
from backend.openloop.logging_config import setup_logging

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Startup logic
    setup_logging()

    # Crash recovery — mark any previously-active conversations as interrupted
    from backend.openloop.agents.session_manager import recover_from_crash

    db = SessionLocal()
    try:
        count = recover_from_crash(db)
        if count > 0:
            logger.info("Crash recovery: marked %d conversations as interrupted", count)
    finally:
        db.close()

    # FTS index check — rebuild if source tables have data but FTS tables are empty
    from backend.openloop.services import search_service

    db = SessionLocal()
    try:
        rebuilt = search_service.check_and_rebuild_if_needed(db)
        if rebuilt:
            logger.info("FTS indexes rebuilt on startup")
    except Exception:
        logger.warning("FTS startup check failed — search may be unavailable", exc_info=True)
    finally:
        db.close()

    yield
    # Shutdown logic


app = FastAPI(
    title="OpenLoop",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Routers ---
from backend.openloop.api.routes.agents import router as agents_router  # noqa: E402
from backend.openloop.api.routes.conversations import router as conversations_router  # noqa: E402
from backend.openloop.api.routes.data_sources import router as data_sources_router  # noqa: E402
from backend.openloop.api.routes.documents import router as documents_router  # noqa: E402
from backend.openloop.api.routes.drive import router as drive_router  # noqa: E402
from backend.openloop.api.routes.events import router as events_router  # noqa: E402
from backend.openloop.api.routes.home import router as home_router  # noqa: E402
from backend.openloop.api.routes.items import router as items_router  # noqa: E402
from backend.openloop.api.routes.memory import router as memory_router  # noqa: E402
from backend.openloop.api.routes.notifications import router as notifications_router  # noqa: E402
from backend.openloop.api.routes.odin import router as odin_router  # noqa: E402
from backend.openloop.api.routes.running import router as running_router  # noqa: E402
from backend.openloop.api.routes.spaces import router as spaces_router  # noqa: E402
from backend.openloop.api.routes.search import router as search_router  # noqa: E402
from backend.openloop.api.routes.todos import router as todos_router  # noqa: E402

# NOTE: running_router must be included BEFORE agents_router because both use
# prefix /api/v1/agents and agents_router has a /{agent_id} catch-all that would
# capture the literal path "running" if it were registered first.
app.include_router(running_router)
app.include_router(agents_router)
app.include_router(conversations_router)
app.include_router(data_sources_router)
app.include_router(events_router)
app.include_router(documents_router)
app.include_router(drive_router)
app.include_router(home_router)
app.include_router(items_router)
app.include_router(memory_router)
app.include_router(notifications_router)
app.include_router(odin_router)
app.include_router(search_router)
app.include_router(spaces_router)
app.include_router(todos_router)


@app.get("/api/v1/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
