"""SQLAlchemy ORM models — all models in this single file.

Uses SQLAlchemy 2.0 declarative style with Mapped/mapped_column.
UUIDs stored as String(36). Every table has created_at (and updated_at where applicable).
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON as SA_JSON
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.openloop.database import Base

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# Join tables (no ORM class needed)
# ---------------------------------------------------------------------------

agent_spaces = Table(
    "agent_spaces",
    Base.metadata,
    Column("agent_id", String(36), ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True),
    Column("space_id", String(36), ForeignKey("spaces.id", ondelete="CASCADE"), primary_key=True),
)

document_items = Table(
    "document_items",
    Base.metadata,
    Column("document_id", String(36), ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True),
    Column("item_id", String(36), ForeignKey("items.id", ondelete="CASCADE"), primary_key=True),
)


# ---------------------------------------------------------------------------
# 1. spaces
# ---------------------------------------------------------------------------


class Space(Base):
    __tablename__ = "spaces"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    parent_space_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("spaces.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    template: Mapped[str] = mapped_column(String, nullable=False)
    board_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    default_view: Mapped[str | None] = mapped_column(String, nullable=True)
    board_columns: Mapped[list | None] = mapped_column(
        SA_JSON, default=lambda: ["idea", "scoping", "todo", "in_progress", "done"]
    )
    custom_field_schema: Mapped[list | None] = mapped_column(SA_JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    # Relationships
    parent: Mapped["Space | None"] = relationship("Space", remote_side="Space.id", lazy="select")
    items: Mapped[list["Item"]] = relationship(
        "Item",
        back_populates="space",
        lazy="select",
        cascade="all, delete-orphan",
    )
    conversations: Mapped[list["Conversation"]] = relationship(
        "Conversation",
        back_populates="space",
        lazy="select",
        cascade="all, delete-orphan",
    )
    documents: Mapped[list["Document"]] = relationship(
        "Document",
        back_populates="space",
        lazy="select",
        cascade="all, delete-orphan",
    )
    data_sources: Mapped[list["DataSource"]] = relationship(
        "DataSource",
        back_populates="space",
        lazy="select",
        cascade="all, delete-orphan",
    )
    conversation_summaries: Mapped[list["ConversationSummary"]] = relationship(
        "ConversationSummary",
        back_populates="space",
        lazy="select",
        cascade="all, delete-orphan",
    )
    agents: Mapped[list["Agent"]] = relationship(
        "Agent", secondary=agent_spaces, back_populates="spaces", lazy="select"
    )
    widgets: Mapped[list["SpaceWidget"]] = relationship(
        "SpaceWidget", back_populates="space", cascade="all, delete-orphan", lazy="select"
    )


# ---------------------------------------------------------------------------
# 1b. space_widgets
# ---------------------------------------------------------------------------


class SpaceWidget(Base):
    __tablename__ = "space_widgets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    widget_type: Mapped[str] = mapped_column(String, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    size: Mapped[str] = mapped_column(String, default="medium")
    config: Mapped[dict | None] = mapped_column(SA_JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    # Relationships
    space: Mapped["Space"] = relationship("Space", back_populates="widgets")


# ---------------------------------------------------------------------------
# 2. items (unified — tasks and records)
# ---------------------------------------------------------------------------


class Item(Base):
    __tablename__ = "items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    item_type: Mapped[str] = mapped_column(String, nullable=False)
    is_agent_task: Mapped[bool] = mapped_column(Boolean, default=False)
    is_done: Mapped[bool] = mapped_column(Boolean, default=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    stage: Mapped[str | None] = mapped_column(String, nullable=True)
    priority: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sort_position: Mapped[float] = mapped_column(Float, default=0.0)
    custom_fields: Mapped[dict | None] = mapped_column(SA_JSON, nullable=True)
    parent_item_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("items.id", ondelete="SET NULL"), nullable=True
    )
    assigned_agent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True
    )
    due_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_by: Mapped[str] = mapped_column(String, default="user")
    source_conversation_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True
    )
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    # Relationships
    space: Mapped["Space"] = relationship("Space", back_populates="items")
    parent_item: Mapped["Item | None"] = relationship(
        "Item", remote_side="Item.id", foreign_keys=[parent_item_id], lazy="select"
    )
    assigned_agent: Mapped["Agent | None"] = relationship(
        "Agent", foreign_keys=[assigned_agent_id], lazy="select"
    )
    source_conversation: Mapped["Conversation | None"] = relationship(
        "Conversation", foreign_keys=[source_conversation_id], lazy="select"
    )
    children: Mapped[list["Item"]] = relationship(
        "Item", foreign_keys="Item.parent_item_id", lazy="select",
        overlaps="parent_item",
    )
    events: Mapped[list["ItemEvent"]] = relationship(
        "ItemEvent",
        back_populates="item",
        lazy="select",
        cascade="all, delete-orphan",
    )
    documents: Mapped[list["Document"]] = relationship(
        "Document", secondary=document_items, back_populates="items", lazy="select"
    )


# ---------------------------------------------------------------------------
# 2b. item_links
# ---------------------------------------------------------------------------


class ItemLink(Base):
    __tablename__ = "item_links"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    source_item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    target_item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    link_type: Mapped[str] = mapped_column(String, default="related_to")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    # Relationships
    source_item: Mapped["Item"] = relationship("Item", foreign_keys=[source_item_id], lazy="select")
    target_item: Mapped["Item"] = relationship("Item", foreign_keys=[target_item_id], lazy="select")


# ---------------------------------------------------------------------------
# 3. item_events
# ---------------------------------------------------------------------------


class ItemEvent(Base):
    __tablename__ = "item_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    old_value: Mapped[str | None] = mapped_column(String, nullable=True)
    new_value: Mapped[str | None] = mapped_column(String, nullable=True)
    triggered_by: Mapped[str] = mapped_column(String, default="user")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    # Relationships
    item: Mapped["Item"] = relationship("Item", back_populates="events")


# ---------------------------------------------------------------------------
# 4. agents
# ---------------------------------------------------------------------------


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    default_model: Mapped[str] = mapped_column(String, default="sonnet")
    skill_path: Mapped[str | None] = mapped_column(String, nullable=True)
    tools: Mapped[list | None] = mapped_column(SA_JSON, nullable=True)
    mcp_tools: Mapped[list | None] = mapped_column(SA_JSON, nullable=True)
    status: Mapped[str] = mapped_column(String, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    # Relationships
    spaces: Mapped[list["Space"]] = relationship(
        "Space", secondary=agent_spaces, back_populates="agents", lazy="select"
    )
    permissions: Mapped[list["AgentPermission"]] = relationship(
        "AgentPermission",
        back_populates="agent",
        lazy="select",
        cascade="all, delete-orphan",
    )
    conversations: Mapped[list["Conversation"]] = relationship(
        "Conversation",
        back_populates="agent",
        lazy="select",
        cascade="all, delete-orphan",
    )
    background_tasks: Mapped[list["BackgroundTask"]] = relationship(
        "BackgroundTask", back_populates="agent", lazy="select"
    )


# ---------------------------------------------------------------------------
# 5. agent_permissions
# ---------------------------------------------------------------------------


class AgentPermission(Base):
    __tablename__ = "agent_permissions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    agent_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    resource_pattern: Mapped[str] = mapped_column(String, nullable=False)
    operation: Mapped[str] = mapped_column(String, nullable=False)
    grant_level: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    # Relationships
    agent: Mapped["Agent"] = relationship("Agent", back_populates="permissions")


# ---------------------------------------------------------------------------
# 6. data_sources
# ---------------------------------------------------------------------------


class DataSource(Base):
    __tablename__ = "data_sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_type: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    config: Mapped[dict | None] = mapped_column(SA_JSON, nullable=True)
    refresh_schedule: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    # Relationships
    space: Mapped["Space"] = relationship("Space", back_populates="data_sources")


# ---------------------------------------------------------------------------
# 7. conversations
# ---------------------------------------------------------------------------


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    space_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("spaces.id", ondelete="CASCADE"), nullable=True, index=True
    )
    agent_id: Mapped[str] = mapped_column(String(36), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, default="active")
    model_override: Mapped[str | None] = mapped_column(String, nullable=True)
    sdk_session_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Relationships
    space: Mapped["Space | None"] = relationship("Space", back_populates="conversations")
    agent: Mapped["Agent"] = relationship("Agent", back_populates="conversations")
    messages: Mapped[list["ConversationMessage"]] = relationship(
        "ConversationMessage",
        back_populates="conversation",
        lazy="select",
        cascade="all, delete-orphan",
    )
    summaries: Mapped[list["ConversationSummary"]] = relationship(
        "ConversationSummary",
        back_populates="conversation",
        lazy="select",
        cascade="all, delete-orphan",
    )
    permission_requests: Mapped[list["PermissionRequest"]] = relationship(
        "PermissionRequest",
        back_populates="conversation",
        lazy="select",
        cascade="all, delete-orphan",
    )


# ---------------------------------------------------------------------------
# 8. conversation_messages
# ---------------------------------------------------------------------------


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    conversation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tool_calls: Mapped[dict | None] = mapped_column(SA_JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    # Relationships
    conversation: Mapped["Conversation"] = relationship("Conversation", back_populates="messages")


# ---------------------------------------------------------------------------
# 9. conversation_summaries
# ---------------------------------------------------------------------------


class ConversationSummary(Base):
    __tablename__ = "conversation_summaries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    conversation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    space_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("spaces.id", ondelete="CASCADE"), nullable=True, index=True
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    decisions: Mapped[list | None] = mapped_column(SA_JSON, nullable=True)
    open_questions: Mapped[list | None] = mapped_column(SA_JSON, nullable=True)
    is_checkpoint: Mapped[bool] = mapped_column(Boolean, default=False)
    # Phase 3b: summary consolidation
    is_meta_summary: Mapped[bool] = mapped_column(Boolean, default=False)
    consolidated_into: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("conversation_summaries.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    # Relationships
    conversation: Mapped["Conversation"] = relationship("Conversation", back_populates="summaries")
    space: Mapped["Space | None"] = relationship("Space", back_populates="conversation_summaries")
    consolidated_into_summary: Mapped["ConversationSummary | None"] = relationship(
        "ConversationSummary", remote_side="ConversationSummary.id", lazy="select"
    )


# ---------------------------------------------------------------------------
# 10. memory_entries
# ---------------------------------------------------------------------------


class MemoryEntry(Base):
    __tablename__ = "memory_entries"
    __table_args__ = (UniqueConstraint("namespace", "key", name="uq_memory_namespace_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    namespace: Mapped[str] = mapped_column(String, nullable=False)
    key: Mapped[str] = mapped_column(String, nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[list | None] = mapped_column(SA_JSON, nullable=True)
    source: Mapped[str] = mapped_column(String, default="user")
    # Phase 3b: scored retrieval fields
    importance: Mapped[float] = mapped_column(Float, default=0.5)
    access_count: Mapped[int] = mapped_column(Integer, default=0)
    last_accessed: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Phase 3b: temporal fact management
    valid_from: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Phase 3b: lifecycle management
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    category: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


# ---------------------------------------------------------------------------
# 10b. behavioral_rules (procedural memory)
# ---------------------------------------------------------------------------


class BehavioralRule(Base):
    __tablename__ = "behavioral_rules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    agent_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rule: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(String, nullable=False)
    source_conversation_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True
    )
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    apply_count: Mapped[int] = mapped_column(Integer, default=0)
    last_applied: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    # Relationships
    agent: Mapped["Agent"] = relationship("Agent", lazy="select")
    source_conversation: Mapped["Conversation | None"] = relationship(
        "Conversation", foreign_keys=[source_conversation_id], lazy="select"
    )


# ---------------------------------------------------------------------------
# 11. documents
# ---------------------------------------------------------------------------


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)
    local_path: Mapped[str | None] = mapped_column(String, nullable=True)
    drive_file_id: Mapped[str | None] = mapped_column(String, nullable=True)
    drive_folder_id: Mapped[str | None] = mapped_column(String, nullable=True)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String, nullable=True)
    content_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list | None] = mapped_column(SA_JSON, nullable=True)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    # Relationships
    space: Mapped["Space"] = relationship("Space", back_populates="documents")
    items: Mapped[list["Item"]] = relationship(
        "Item", secondary=document_items, back_populates="documents", lazy="select"
    )


# ---------------------------------------------------------------------------
# 12. permission_requests
# ---------------------------------------------------------------------------


class PermissionRequest(Base):
    __tablename__ = "permission_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    agent_id: Mapped[str] = mapped_column(String(36), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    conversation_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=True
    )
    tool_name: Mapped[str] = mapped_column(String, nullable=False)
    resource: Mapped[str] = mapped_column(String, nullable=False)
    operation: Mapped[str] = mapped_column(String, nullable=False)
    tool_input: Mapped[dict | None] = mapped_column(SA_JSON, nullable=True)
    status: Mapped[str] = mapped_column(String, default="pending")
    resolved_by: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Relationships
    agent: Mapped["Agent"] = relationship("Agent", lazy="select")
    conversation: Mapped["Conversation | None"] = relationship(
        "Conversation", back_populates="permission_requests"
    )


# ---------------------------------------------------------------------------
# 13. notifications
# ---------------------------------------------------------------------------


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    type: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    space_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("spaces.id", ondelete="CASCADE"), nullable=True)
    conversation_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=True
    )
    automation_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("automations.id", ondelete="SET NULL"), nullable=True
    )
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


# ---------------------------------------------------------------------------
# 14. automations
# ---------------------------------------------------------------------------


class Automation(Base):
    __tablename__ = "automations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    space_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("spaces.id", ondelete="SET NULL"), nullable=True)
    agent_id: Mapped[str] = mapped_column(String(36), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    instruction: Mapped[str] = mapped_column(Text, nullable=False)
    trigger_type: Mapped[str] = mapped_column(String, nullable=False)
    cron_expression: Mapped[str | None] = mapped_column(String, nullable=True)
    event_source: Mapped[str | None] = mapped_column(String, nullable=True)
    event_filter: Mapped[dict | None] = mapped_column(SA_JSON, nullable=True)
    model_override: Mapped[str | None] = mapped_column(String, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_run_status: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    # Relationships
    agent: Mapped["Agent"] = relationship("Agent", lazy="select")
    runs: Mapped[list["AutomationRun"]] = relationship(
        "AutomationRun",
        back_populates="automation",
        lazy="select",
        cascade="all, delete-orphan",
    )


# ---------------------------------------------------------------------------
# 15. automation_runs
# ---------------------------------------------------------------------------


class AutomationRun(Base):
    __tablename__ = "automation_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    automation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("automations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    background_task_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("background_tasks.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String, nullable=False)
    result_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Relationships
    automation: Mapped["Automation"] = relationship("Automation", back_populates="runs")
    background_task: Mapped["BackgroundTask | None"] = relationship("BackgroundTask", lazy="select")


# ---------------------------------------------------------------------------
# 16. background_tasks
# ---------------------------------------------------------------------------


class BackgroundTask(Base):
    __tablename__ = "background_tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    conversation_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True
    )
    automation_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("automations.id", ondelete="SET NULL"), nullable=True
    )
    agent_id: Mapped[str] = mapped_column(String(36), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    space_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("spaces.id", ondelete="SET NULL"), nullable=True)
    item_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("items.id", ondelete="SET NULL"), nullable=True)
    instruction: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String, default="queued")
    result_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Phase 3b: workflow tracking
    current_step: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_steps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    step_results: Mapped[list | None] = mapped_column(SA_JSON, nullable=True)
    parent_task_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("background_tasks.id", ondelete="SET NULL"), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    # Relationships
    agent: Mapped["Agent"] = relationship("Agent", back_populates="background_tasks")
    conversation: Mapped["Conversation | None"] = relationship("Conversation", lazy="select")
    space: Mapped["Space | None"] = relationship("Space", lazy="select")
    item: Mapped["Item | None"] = relationship("Item", lazy="select")
    parent_task: Mapped["BackgroundTask | None"] = relationship(
        "BackgroundTask", remote_side="BackgroundTask.id", lazy="select"
    )
