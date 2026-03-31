"""Structured JSON logging for OpenLoop agent sessions."""

import json
import logging
import logging.handlers
from datetime import UTC, datetime
from pathlib import Path

# Default log file location (relative to project root)
LOG_DIR = Path("data/logs")
LOG_FILE = LOG_DIR / "openloop.log"

# Rotation settings
MAX_BYTES = 10 * 1024 * 1024  # 10 MB
BACKUP_COUNT = 5


class JSONFormatter(logging.Formatter):
    """Format log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Include conversation_id and agent_id when present
        for key in ("conversation_id", "agent_id"):
            value = getattr(record, key, None)
            if value is not None:
                entry[key] = value

        # Merge any extra fields passed via the `extra` dict.
        # logging adds a bunch of internal attributes; we only merge
        # keys that were explicitly added by callers.
        _builtin = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__)
        for key, value in record.__dict__.items():
            if key not in _builtin and key not in entry:
                entry[key] = value

        # Exception info
        if record.exc_info and record.exc_info[1] is not None:
            entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(entry, default=str)


def setup_logging() -> None:
    """Configure structured JSON logging. Call once at app startup."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    handler = logging.handlers.RotatingFileHandler(
        filename=str(LOG_FILE),
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setFormatter(JSONFormatter())

    # Also log to stderr for local development
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(JSONFormatter())

    root = logging.getLogger("openloop")
    root.setLevel(logging.INFO)

    # Avoid duplicate handlers on repeated calls
    if not root.handlers:
        root.addHandler(handler)
        root.addHandler(console_handler)


def get_logger(name: str) -> logging.Logger:
    """Return a pre-configured logger under the ``openloop`` namespace.

    Usage::

        logger = get_logger(__name__)
        logger.info("Session started", extra={"conversation_id": cid, "agent_id": aid})
    """
    return logging.getLogger(f"openloop.{name}")
