from fastapi import APIRouter

from backend.openloop.agents.session_manager import list_active

router = APIRouter(prefix="/api/v1/agents", tags=["agents"])


@router.get("/running")
def get_running_sessions() -> list[dict]:
    """Return all active/queued sessions from in-memory tracking."""
    sessions = list_active()
    return [
        {
            "conversation_id": s.conversation_id,
            "agent_id": s.agent_id,
            "space_id": s.space_id,
            "sdk_session_id": s.sdk_session_id,
            "status": s.status,
            "started_at": s.started_at.isoformat(),
            "last_activity": s.last_activity.isoformat(),
        }
        for s in sessions
    ]
