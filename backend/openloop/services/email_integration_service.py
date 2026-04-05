"""Email integration service — sync, triage labels, and email operations."""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

from fastapi import HTTPException
from google.auth.exceptions import RefreshError
from googleapiclient.errors import HttpError
from sqlalchemy import String, type_coerce
from sqlalchemy.orm import Session

from backend.openloop.db.models import DataSource, EmailCache
from backend.openloop.services import data_source_service, gmail_client, notification_service
from contract.enums import SOURCE_TYPE_GMAIL, NotificationType

logger = logging.getLogger(__name__)

# Default triage labels (OL/ prefix avoids conflicts with user labels)
TRIAGE_LABELS = [
    "OL/Needs Response",
    "OL/FYI",
    "OL/Follow Up",
    "OL/Waiting",
    "OL/Agent Processed",
]


def _parse_iso(s: str) -> datetime:
    """Parse an ISO 8601 string, handling Google's 'Z' suffix."""
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _escape_like(term: str) -> str:
    """Escape SQL LIKE wildcards."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _parse_from_header(from_header: str | None) -> tuple[str | None, str | None]:
    """Parse a From header like 'Name <email@example.com>' into (name, address).

    Returns (from_name, from_address).
    """
    if not from_header:
        return None, None

    # Match "Name <email>" pattern
    match = re.match(r'^"?([^"<]*)"?\s*<([^>]+)>', from_header)
    if match:
        name = match.group(1).strip().strip('"') or None
        address = match.group(2).strip()
        return name, address

    # Bare email address
    if "@" in from_header:
        return None, from_header.strip()

    return from_header.strip(), None


def _parse_email_date(date_str: str | None) -> datetime:
    """Parse an RFC 2822 email date string into a naive UTC datetime.

    Falls back to now() if parsing fails.
    """
    if not date_str:
        return datetime.now(UTC).replace(tzinfo=None)
    try:
        dt = parsedate_to_datetime(date_str)
        # Convert to UTC and strip timezone
        return dt.astimezone(UTC).replace(tzinfo=None)
    except Exception:
        return datetime.now(UTC).replace(tzinfo=None)


def _parse_address_list(header_value: str | None) -> list[str]:
    """Split a comma-separated address header into a list."""
    if not header_value:
        return []
    return [addr.strip() for addr in header_value.split(",") if addr.strip()]


# Track consecutive sync failures per data source
_sync_failure_counts: dict[str, int] = {}
_FAILURE_THRESHOLD = 3


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------


def setup_email(
    db: Session,
    triage_labels: list[str] | None = None,
) -> DataSource:
    """Create a system DataSource for Gmail (idempotent) and run initial sync."""
    # Check if a system-level Gmail DataSource already exists
    existing = (
        db.query(DataSource)
        .filter(
            DataSource.source_type == SOURCE_TYPE_GMAIL,
            DataSource.space_id.is_(None),
        )
        .first()
    )
    if existing:
        return existing

    ds = data_source_service.create_data_source(
        db,
        space_id=None,
        name="Gmail",
        source_type=SOURCE_TYPE_GMAIL,
        config={
            "triage_labels": triage_labels or TRIAGE_LABELS,
            "sync_max_results": 50,
            "exclude_labels": ["SPAM", "TRASH"],
        },
    )

    # Create triage labels in Gmail
    ensure_triage_labels(db)

    # Run initial sync
    sync_inbox(db, ds.id)
    return ds


# ---------------------------------------------------------------------------
# Triage Labels
# ---------------------------------------------------------------------------


def ensure_triage_labels(db: Session) -> list[str]:
    """Create OL/ triage labels in Gmail if they don't already exist.

    Returns list of label names that were created (empty if all existed).
    """
    existing_labels = gmail_client.get_labels()
    existing_names = {label.get("name", "") for label in existing_labels}

    # Get configured labels from DataSource, fall back to defaults
    email_ds = (
        db.query(DataSource)
        .filter(
            DataSource.source_type == SOURCE_TYPE_GMAIL,
            DataSource.space_id.is_(None),
        )
        .first()
    )
    config = (email_ds.config or {}) if email_ds else {}
    labels_to_ensure = config.get("triage_labels", TRIAGE_LABELS)

    created: list[str] = []
    for label_name in labels_to_ensure:
        if label_name not in existing_names:
            try:
                gmail_client.create_label(label_name)
                created.append(label_name)
                logger.info("Created Gmail label: %s", label_name)
            except HttpError as exc:
                logger.error("Failed to create Gmail label '%s': %s", label_name, exc)

    return created


# ---------------------------------------------------------------------------
# Sync
# ---------------------------------------------------------------------------


def sync_inbox(db: Session, data_source_id: str, max_results: int = 50) -> dict:
    """Sync recent inbox messages from Gmail into the local EmailCache.

    Returns counts: ``{"added": N, "updated": N}``.
    """
    ds = data_source_service.get_data_source(db, data_source_id)
    config = ds.config or {}
    sync_max = config.get("sync_max_results", max_results)
    exclude_labels = config.get("exclude_labels", ["SPAM", "TRASH"])

    try:
        message_stubs = gmail_client.list_messages(
            label_ids=["INBOX"],
            max_results=sync_max,
        )
    except RefreshError:
        logger.error("Gmail token expired for data_source %s", data_source_id)
        notification_service.create_notification(
            db,
            type=NotificationType.SYSTEM,
            title="Gmail disconnected",
            body="Gmail authentication has expired — re-authentication needed.",
        )
        return {"added": 0, "updated": 0}
    except HttpError as exc:
        if exc.resp.status == 401:
            logger.error("Gmail 401 for data_source %s", data_source_id)
            notification_service.create_notification(
                db,
                type=NotificationType.SYSTEM,
                title="Gmail disconnected",
                body="Gmail authentication has expired — re-authentication needed.",
            )
            return {"added": 0, "updated": 0}

        # Other API error — increment failure counter
        _sync_failure_counts[data_source_id] = (
            _sync_failure_counts.get(data_source_id, 0) + 1
        )
        if _sync_failure_counts[data_source_id] >= _FAILURE_THRESHOLD:
            notification_service.create_notification(
                db,
                type=NotificationType.SYSTEM,
                title="Email sync failed",
                body="Email sync has failed 3 consecutive times — check Google auth.",
            )
        logger.error("Gmail API error for data_source %s: %s", data_source_id, exc)
        return {"added": 0, "updated": 0}

    added = 0
    updated = 0

    for stub in message_stubs:
        msg_id = stub.get("id")
        if not msg_id:
            continue

        try:
            msg_data = gmail_client.get_message_headers(msg_id)
        except HttpError as exc:
            logger.warning("Failed to fetch message %s: %s", msg_id, exc)
            continue

        # Skip messages with excluded labels
        msg_labels = msg_data.get("labelIds", [])
        if any(lbl in exclude_labels for lbl in msg_labels):
            continue

        headers = msg_data.get("headers", {})
        from_name, from_address = _parse_from_header(headers.get("from"))
        received_at = _parse_email_date(headers.get("date"))
        to_addresses = _parse_address_list(headers.get("to"))
        cc_addresses = _parse_address_list(headers.get("cc"))
        is_unread = "UNREAD" in msg_labels
        gmail_link = f"https://mail.google.com/mail/u/0/#inbox/{msg_id}"
        now = datetime.now(UTC).replace(tzinfo=None)

        # Upsert by gmail_message_id
        existing = (
            db.query(EmailCache)
            .filter(EmailCache.gmail_message_id == msg_id)
            .first()
        )

        if existing:
            # Update mutable fields
            existing.labels = msg_labels
            existing.is_unread = is_unread
            existing.snippet = msg_data.get("snippet", "")
            existing.synced_at = now
            updated += 1
        else:
            # Insert new record
            email_record = EmailCache(
                data_source_id=data_source_id,
                gmail_message_id=msg_id,
                gmail_thread_id=msg_data.get("threadId"),
                subject=headers.get("subject"),
                from_address=from_address,
                from_name=from_name,
                to_addresses=to_addresses,
                cc_addresses=cc_addresses,
                snippet=msg_data.get("snippet", ""),
                labels=msg_labels,
                is_unread=is_unread,
                received_at=received_at,
                gmail_link=gmail_link,
                synced_at=now,
            )
            db.add(email_record)
            added += 1

    # Reconcile stale cache: messages no longer in inbox (archived/deleted in Gmail)
    synced_ids = {stub.get("id") for stub in message_stubs if stub.get("id")}
    if synced_ids:
        stale_inbox = (
            db.query(EmailCache)
            .filter(
                EmailCache.data_source_id == data_source_id,
                EmailCache.gmail_message_id.notin_(synced_ids),
            )
            .all()
        )
        for stale in stale_inbox:
            current = list(stale.labels or [])
            if "INBOX" in current:
                current.remove("INBOX")
                stale.labels = current

    db.commit()

    # Success — reset failure count
    _sync_failure_counts[data_source_id] = 0

    return {"added": added, "updated": updated}


# ---------------------------------------------------------------------------
# Cache queries
# ---------------------------------------------------------------------------


def get_cached_messages(
    db: Session,
    label: str | None = None,
    query: str | None = None,
    unread_only: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> list[EmailCache]:
    """Query the local email cache with optional filters.

    Args:
        label: Filter by label name (checks JSON labels array).
        query: Search term to match against subject, from_name, or snippet.
        unread_only: If True, return only unread messages.
        limit: Maximum results to return.
        offset: Pagination offset.
    """
    q = db.query(EmailCache)

    if label:
        # SQLite stores JSON arrays as text; match the label within the serialized string
        escaped = _escape_like(label)
        q = q.filter(
            type_coerce(EmailCache.labels, String).like(f'%"{escaped}"%', escape="\\")
        )

    if query:
        escaped = _escape_like(query)
        pattern = f"%{escaped}%"
        q = q.filter(
            EmailCache.subject.ilike(pattern, escape="\\")
            | EmailCache.from_name.ilike(pattern, escape="\\")
            | EmailCache.snippet.ilike(pattern, escape="\\")
        )

    if unread_only:
        q = q.filter(EmailCache.is_unread == True)  # noqa: E712

    return (
        q.order_by(EmailCache.received_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


def get_inbox_stats(db: Session) -> dict:
    """Return inbox statistics from the local cache.

    Returns: ``{"unread_count": N, "by_label": {"OL/...": N, ...}, "oldest_unread": datetime|None}``
    """
    unread_count = (
        db.query(EmailCache)
        .filter(EmailCache.is_unread == True)  # noqa: E712
        .count()
    )

    # Count messages per triage label
    by_label: dict[str, int] = {}
    for label_name in TRIAGE_LABELS:
        escaped = _escape_like(label_name)
        count = (
            db.query(EmailCache)
            .filter(type_coerce(EmailCache.labels, String).like(f'%"{escaped}"%', escape="\\"))
            .count()
        )
        by_label[label_name] = count

    # Oldest unread message
    oldest_unread_msg = (
        db.query(EmailCache)
        .filter(EmailCache.is_unread == True)  # noqa: E712
        .order_by(EmailCache.received_at.asc())
        .first()
    )
    oldest_unread = oldest_unread_msg.received_at if oldest_unread_msg else None

    return {
        "unread_count": unread_count,
        "by_label": by_label,
        "oldest_unread": oldest_unread,
    }


# ---------------------------------------------------------------------------
# Email operations (API + cache sync)
# ---------------------------------------------------------------------------


def label_message(
    db: Session,
    message_id: str,
    add_labels: list[str] | None = None,
    remove_labels: list[str] | None = None,
) -> EmailCache:
    """Add/remove labels on a message via Gmail API and update the local cache."""
    cached = (
        db.query(EmailCache)
        .filter(EmailCache.gmail_message_id == message_id)
        .first()
    )
    if not cached:
        raise HTTPException(status_code=404, detail="Email not found in cache")

    gmail_client.modify_labels(message_id, add_labels=add_labels, remove_labels=remove_labels)

    # Update local cache labels
    current_labels = list(cached.labels or [])
    if remove_labels:
        current_labels = [lbl for lbl in current_labels if lbl not in remove_labels]
    if add_labels:
        for lbl in add_labels:
            if lbl not in current_labels:
                current_labels.append(lbl)

    cached.labels = current_labels
    cached.is_unread = "UNREAD" in current_labels
    cached.synced_at = datetime.now(UTC).replace(tzinfo=None)

    db.commit()
    db.refresh(cached)
    return cached


def archive_message(db: Session, message_id: str) -> EmailCache:
    """Archive a message via Gmail API and update the local cache."""
    cached = (
        db.query(EmailCache)
        .filter(EmailCache.gmail_message_id == message_id)
        .first()
    )
    if not cached:
        raise HTTPException(status_code=404, detail="Email not found in cache")

    gmail_client.archive_message(message_id)

    # Update local cache — remove INBOX from labels
    current_labels = list(cached.labels or [])
    current_labels = [lbl for lbl in current_labels if lbl != "INBOX"]
    cached.labels = current_labels
    cached.synced_at = datetime.now(UTC).replace(tzinfo=None)

    db.commit()
    db.refresh(cached)
    return cached


def mark_read(db: Session, message_id: str) -> EmailCache:
    """Mark a message as read via Gmail API and update the local cache."""
    cached = (
        db.query(EmailCache)
        .filter(EmailCache.gmail_message_id == message_id)
        .first()
    )
    if not cached:
        raise HTTPException(status_code=404, detail="Email not found in cache")

    gmail_client.mark_as_read(message_id)

    # Update local cache
    current_labels = list(cached.labels or [])
    current_labels = [lbl for lbl in current_labels if lbl != "UNREAD"]
    cached.labels = current_labels
    cached.is_unread = False
    cached.synced_at = datetime.now(UTC).replace(tzinfo=None)

    db.commit()
    db.refresh(cached)
    return cached


# ---------------------------------------------------------------------------
# Draft/Send operations (API only, no cache)
# ---------------------------------------------------------------------------


def create_draft(db: Session, to: str, subject: str, body: str, **kwargs) -> dict:
    """Create a draft message in Gmail."""
    return gmail_client.create_draft(
        to=to,
        subject=subject,
        body=body,
        cc=kwargs.get("cc"),
        bcc=kwargs.get("bcc"),
        reply_to=kwargs.get("reply_to"),
    )


def send_draft(db: Session, draft_id: str) -> dict:
    """Send an existing draft."""
    return gmail_client.send_draft(draft_id)


def send_reply(db: Session, message_id: str, body: str) -> dict:
    """Reply to a message within the same thread."""
    return gmail_client.send_reply(message_id, body)
