from enum import StrEnum


class SpaceTemplate(StrEnum):
    PROJECT = "project"
    CRM = "crm"
    KNOWLEDGE_BASE = "knowledge_base"
    SIMPLE = "simple"


class ItemType(StrEnum):
    TASK = "task"
    RECORD = "record"


class ConversationStatus(StrEnum):
    ACTIVE = "active"
    CLOSED = "closed"
    INTERRUPTED = "interrupted"


class GrantLevel(StrEnum):
    ALWAYS = "always"
    APPROVAL = "approval"
    NEVER = "never"


class Operation(StrEnum):
    READ = "read"
    CREATE = "create"
    EDIT = "edit"
    DELETE = "delete"
    EXECUTE = "execute"


class AutomationTriggerType(StrEnum):
    CRON = "cron"
    EVENT = "event"


class AutomationStatus(StrEnum):
    ENABLED = "enabled"
    DISABLED = "disabled"


class BackgroundTaskStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class NotificationType(StrEnum):
    APPROVAL_REQUEST = "approval_request"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    AUTOMATION_FAILED = "automation_failed"
    CONTEXT_WARNING = "context_warning"
    SYSTEM = "system"


class SSEEventType(StrEnum):
    TOKEN = "token"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    APPROVAL_REQUEST = "approval_request"
    NOTIFICATION = "notification"
    ROUTE = "route"
    BACKGROUND_UPDATE = "background_update"
    ERROR = "error"


class DefaultView(StrEnum):
    BOARD = "board"
    TABLE = "table"


class PermissionRequestStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class ToolCallStatus(StrEnum):
    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"


class MemoryNamespace(StrEnum):
    GLOBAL = "global"
    ODIN = "odin"
    # Space-specific namespaces use the space_id directly
