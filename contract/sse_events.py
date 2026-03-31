"""SSE event Pydantic models — one model per event type.

All SSE events share a `type` field (SSEEventType enum) plus event-specific fields.
These models define the contract between backend SSE streaming and frontend consumers.
"""

from pydantic import BaseModel

from contract.enums import (
    BackgroundTaskStatus,
    NotificationType,
    SSEEventType,
    ToolCallStatus,
)


class SSETokenEvent(BaseModel):
    """Streaming conversation token."""

    type: SSEEventType = SSEEventType.TOKEN
    conversation_id: str
    content: str


class SSEToolCallEvent(BaseModel):
    """Agent calling a tool."""

    type: SSEEventType = SSEEventType.TOOL_CALL
    conversation_id: str
    tool_name: str
    status: ToolCallStatus


class SSEToolResultEvent(BaseModel):
    """Tool call completed."""

    type: SSEEventType = SSEEventType.TOOL_RESULT
    conversation_id: str
    tool_name: str
    result_summary: str


class SSEApprovalRequestEvent(BaseModel):
    """Permission needed from user."""

    type: SSEEventType = SSEEventType.APPROVAL_REQUEST
    conversation_id: str
    request_id: str
    tool_name: str
    resource: str
    operation: str


class SSENotificationEvent(BaseModel):
    """System notification."""

    type: SSEEventType = SSEEventType.NOTIFICATION
    notification_id: str
    notification_type: NotificationType
    title: str
    body: str | None = None


class SSERouteEvent(BaseModel):
    """Odin routing action — tells frontend to navigate."""

    type: SSEEventType = SSEEventType.ROUTE
    space_id: str | None = None
    conversation_id: str | None = None


class SSEBackgroundUpdateEvent(BaseModel):
    """Background task status update."""

    type: SSEEventType = SSEEventType.BACKGROUND_UPDATE
    task_id: str
    status: BackgroundTaskStatus
    progress: float | None = None


class SSEErrorEvent(BaseModel):
    """Error event."""

    type: SSEEventType = SSEEventType.ERROR
    conversation_id: str | None = None
    message: str


# Union type for all SSE events — useful for type narrowing on the frontend side
SSEEvent = (
    SSETokenEvent
    | SSEToolCallEvent
    | SSEToolResultEvent
    | SSEApprovalRequestEvent
    | SSENotificationEvent
    | SSERouteEvent
    | SSEBackgroundUpdateEvent
    | SSEErrorEvent
)
