import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import backend.openloop.database as database_module
import backend.openloop.db.models  # noqa: F401 — register models with Base.metadata
from backend.openloop.database import Base, get_db
from backend.openloop.main import app

# In-memory SQLite for tests — StaticPool ensures all connections share one DB
_test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

# Override SessionLocal everywhere so that app lifespan (recover_from_crash,
# FTS checks, etc.) uses the test database instead of the production one.
# We must patch both the database module AND main.py since main.py does
# `from backend.openloop.database import SessionLocal` (binds the name locally).
_TestSessionLocalFactory = sessionmaker(
    autocommit=False, autoflush=False, bind=_test_engine
)
database_module.SessionLocal = _TestSessionLocalFactory

import backend.openloop.main as main_module  # noqa: E402
main_module.SessionLocal = _TestSessionLocalFactory


@event.listens_for(_test_engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_test_engine)


@pytest.fixture(autouse=True)
def _setup_db():
    Base.metadata.create_all(bind=_test_engine)
    yield
    Base.metadata.drop_all(bind=_test_engine)


@pytest.fixture()
def db_session() -> Session:
    session = TestSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(db_session: Session) -> TestClient:
    def _override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
