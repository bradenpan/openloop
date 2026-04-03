from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.openloop.agents.agent_runner import list_running
from backend.openloop.api.schemas import RunningSessionResponse
from backend.openloop.database import get_db

router = APIRouter(prefix="/api/v1/agents", tags=["agents"])


@router.get("/running", response_model=list[RunningSessionResponse])
def get_running_sessions(db: Session = Depends(get_db)) -> list[dict]:
    """Return all running sessions from DB queries."""
    return list_running(db)
