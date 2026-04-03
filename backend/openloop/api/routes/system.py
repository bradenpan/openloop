from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.openloop.api.schemas.system import (
    BackupStatusResponse,
    EmergencyStopResponse,
    SystemResumeResponse,
    SystemStatusResponse,
)
from backend.openloop.database import get_db
from backend.openloop.services import system_service

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


# ---------------------------------------------------------------------------
# Kill switch endpoints (Phase 8.4)
# ---------------------------------------------------------------------------


@router.post("/emergency-stop", response_model=EmergencyStopResponse)
def emergency_stop(db: Session = Depends(get_db)) -> EmergencyStopResponse:
    """Activate the system-wide kill switch. Halts all background work."""
    result = system_service.emergency_stop(db)
    return EmergencyStopResponse(**result)


@router.post("/resume", response_model=SystemResumeResponse)
def resume_system(db: Session = Depends(get_db)) -> SystemResumeResponse:
    """Clear the kill switch and re-enable background work."""
    result = system_service.resume(db)
    return SystemResumeResponse(**result)


@router.get("/status", response_model=SystemStatusResponse)
def get_system_status(db: Session = Depends(get_db)) -> SystemStatusResponse:
    """Return current system state (paused/active, active session count)."""
    result = system_service.get_status(db)
    return SystemStatusResponse(**result)
