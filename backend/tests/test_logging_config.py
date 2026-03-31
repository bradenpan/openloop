"""Tests for structured JSON logging configuration."""

import json
import logging
import logging.handlers

import pytest

from backend.openloop.logging_config import (
    BACKUP_COUNT,
    MAX_BYTES,
    get_logger,
    setup_logging,
)


@pytest.fixture(autouse=True)
def _isolate_logging(tmp_path, monkeypatch):
    """Redirect log output to a temp directory and reset handlers between tests."""
    monkeypatch.setattr("backend.openloop.logging_config.LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(
        "backend.openloop.logging_config.LOG_FILE", tmp_path / "logs" / "openloop.log"
    )

    # Remove any handlers added by previous tests
    root = logging.getLogger("openloop")
    root.handlers.clear()

    yield

    root.handlers.clear()


def test_get_logger_returns_logger():
    logger = get_logger("test_module")
    assert isinstance(logger, logging.Logger)
    assert logger.name == "openloop.test_module"


def test_setup_logging_creates_log_directory(tmp_path, monkeypatch):
    log_dir = tmp_path / "logs"
    monkeypatch.setattr("backend.openloop.logging_config.LOG_DIR", log_dir)
    monkeypatch.setattr("backend.openloop.logging_config.LOG_FILE", log_dir / "openloop.log")

    assert not log_dir.exists()
    setup_logging()
    assert log_dir.exists()


def test_log_message_produces_valid_json(tmp_path, monkeypatch):
    log_dir = tmp_path / "logs"
    log_file = log_dir / "openloop.log"
    monkeypatch.setattr("backend.openloop.logging_config.LOG_DIR", log_dir)
    monkeypatch.setattr("backend.openloop.logging_config.LOG_FILE", log_file)

    setup_logging()
    logger = get_logger("session")
    logger.info(
        "Session started",
        extra={"conversation_id": "conv-123", "agent_id": "agent-456"},
    )

    # Flush handlers
    for handler in logging.getLogger("openloop").handlers:
        handler.flush()

    text = log_file.read_text(encoding="utf-8").strip()
    assert text, "Log file should not be empty"

    entry = json.loads(text)
    assert entry["level"] == "INFO"
    assert entry["message"] == "Session started"
    assert entry["logger"] == "openloop.session"
    assert entry["conversation_id"] == "conv-123"
    assert entry["agent_id"] == "agent-456"
    assert "timestamp" in entry


def test_rotation_config(tmp_path, monkeypatch):
    log_dir = tmp_path / "logs"
    log_file = log_dir / "openloop.log"
    monkeypatch.setattr("backend.openloop.logging_config.LOG_DIR", log_dir)
    monkeypatch.setattr("backend.openloop.logging_config.LOG_FILE", log_file)

    setup_logging()

    root = logging.getLogger("openloop")
    rotating_handlers = [
        h for h in root.handlers if isinstance(h, logging.handlers.RotatingFileHandler)
    ]
    assert len(rotating_handlers) == 1

    rh = rotating_handlers[0]
    assert rh.maxBytes == MAX_BYTES
    assert rh.backupCount == BACKUP_COUNT


def test_log_warning_and_error_levels(tmp_path, monkeypatch):
    log_dir = tmp_path / "logs"
    log_file = log_dir / "openloop.log"
    monkeypatch.setattr("backend.openloop.logging_config.LOG_DIR", log_dir)
    monkeypatch.setattr("backend.openloop.logging_config.LOG_FILE", log_file)

    setup_logging()
    logger = get_logger("permissions")
    logger.warning("Permission denied", extra={"agent_id": "a1"})
    logger.error("SDK failure", extra={"conversation_id": "c1"})

    for handler in logging.getLogger("openloop").handlers:
        handler.flush()

    lines = log_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2

    warn_entry = json.loads(lines[0])
    assert warn_entry["level"] == "WARNING"
    assert warn_entry["agent_id"] == "a1"

    err_entry = json.loads(lines[1])
    assert err_entry["level"] == "ERROR"
    assert err_entry["conversation_id"] == "c1"


def test_no_duplicate_handlers_on_repeated_setup(tmp_path, monkeypatch):
    log_dir = tmp_path / "logs"
    log_file = log_dir / "openloop.log"
    monkeypatch.setattr("backend.openloop.logging_config.LOG_DIR", log_dir)
    monkeypatch.setattr("backend.openloop.logging_config.LOG_FILE", log_file)

    setup_logging()
    handler_count = len(logging.getLogger("openloop").handlers)

    setup_logging()
    assert len(logging.getLogger("openloop").handlers) == handler_count
