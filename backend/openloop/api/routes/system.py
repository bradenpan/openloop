from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter

from backend.openloop.api.schemas.system import BackupStatusResponse

router = APIRouter(prefix="/api/v1/system", tags=["system"])

# Resolve data directory relative to repo root
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
_LAST_BACKUP_PATH = _REPO_ROOT / "data" / ".last_backup"


@router.get("/backup-status", response_model=BackupStatusResponse)
def get_backup_status() -> BackupStatusResponse:
    """Return the last backup timestamp and whether a backup is needed."""
    if not _LAST_BACKUP_PATH.exists():
        return BackupStatusResponse(
            last_backup_at=None,
            hours_since_backup=None,
            needs_backup=True,
        )

    try:
        raw = _LAST_BACKUP_PATH.read_text().strip()
        last_backup = datetime.fromisoformat(raw)
        # Ensure timezone-aware
        if last_backup.tzinfo is None:
            last_backup = last_backup.replace(tzinfo=UTC)
        now = datetime.now(UTC)
        delta = now - last_backup
        hours = int(delta.total_seconds() // 3600)
        return BackupStatusResponse(
            last_backup_at=raw,
            hours_since_backup=hours,
            needs_backup=hours >= 24,
        )
    except (ValueError, OSError):
        return BackupStatusResponse(
            last_backup_at=None,
            hours_since_backup=None,
            needs_backup=True,
        )
