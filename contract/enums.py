from enum import StrEnum


class SpaceTemplate(StrEnum):
    PROJECT = "project"
    DATABASE = "crm"
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
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"
    PENDING_RESUME = "pending_resume"


class BackgroundTaskRunType(StrEnum):
    TASK = "task"
    AUTONOMOUS = "autonomous"
    HEARTBEAT = "heartbeat"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"


class NotificationType(StrEnum):
    APPROVAL_REQUEST = "approval_request"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    AUTOMATION_FAILED = "automation_failed"
    AUTOMATION_MISSED = "automation_missed"
    CONTEXT_WARNING = "context_warning"
    MEMORY_CONSOLIDATION = "memory_consolidation"
    SYSTEM = "system"
    EMERGENCY_STOP = "emergency_stop"
    HEARTBEAT_ACTION = "heartbeat_action"
    SUB_TASK_COMPLETED = "sub_task_completed"


class SSEEventType(StrEnum):
    TOKEN = "token"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    APPROVAL_REQUEST = "approval_request"
    NOTIFICATION = "notification"
    ROUTE = "route"
    BACKGROUND_UPDATE = "background_update"
    RATE_LIMITED = "rate_limited"
    ERROR = "error"
    AUTONOMOUS_PROGRESS = "autonomous_progress"
    APPROVAL_QUEUED = "approval_queued"
    GOAL_COMPLETE = "goal_complete"


class DefaultView(StrEnum):
    BOARD = "board"
    TABLE = "table"
    LIST = "list"


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


class RuleSourceType(StrEnum):
    CORRECTION = "correction"
    VALIDATION = "validation"


class RuleOrigin(StrEnum):
    AGENT_INFERRED = "agent_inferred"
    USER_CONFIRMED = "user_confirmed"
    SYSTEM = "system"


class DedupDecision(StrEnum):
    ADD = "add"
    UPDATE = "update"
    DELETE = "delete"
    NOOP = "noop"


class LinkType(StrEnum):
    RELATED_TO = "related_to"


class WidgetType(StrEnum):
    TODO_PANEL = "todo_panel"
    KANBAN_BOARD = "kanban_board"
    DATA_TABLE = "data_table"
    CONVERSATIONS = "conversations"
    CALENDAR_EVENTS = "calendar_events"
    EMAIL_FEED = "email_feed"
    CHART = "chart"
    STAT_CARD = "stat_card"
    MARKDOWN = "markdown"
    DATA_FEED = "data_feed"
    GOOGLE_SHEET = "google_sheet"


class WidgetSize(StrEnum):
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"
    FULL = "full"


# ---------------------------------------------------------------------------
# Source type constants (not an enum — source_type is a plain String column)
# ---------------------------------------------------------------------------

SOURCE_TYPE_GOOGLE_DRIVE = "google_drive"
SOURCE_TYPE_GOOGLE_CALENDAR = "google_calendar"
SOURCE_TYPE_GMAIL = "gmail"
SOURCE_TYPE_API = "api"
