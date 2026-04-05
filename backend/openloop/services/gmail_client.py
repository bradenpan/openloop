"""Gmail API client for OpenLoop.

Handles message listing, reading, labeling, drafts, and sending via the Gmail
API.  Uses the shared google_auth module for OAuth credentials.
"""

from __future__ import annotations

import base64
import logging
import re
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from backend.openloop.services import google_auth

logger = logging.getLogger(__name__)

# Register gmail scopes on import
SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
google_auth.register_scopes("gmail", SCOPES)


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------


def is_authenticated() -> bool:
    """Check if Gmail scopes are granted."""
    return google_auth.is_authenticated(SCOPES)


def get_gmail_service():
    """Build and return a Gmail API v1 service resource."""
    creds = google_auth.get_credentials()
    if creds is None:
        raise RuntimeError(
            "Gmail not authenticated. Complete OAuth flow first."
        )
    # Check that gmail scopes are granted
    granted = set(creds.scopes or [])
    if not all(s in granted for s in SCOPES):
        raise RuntimeError(
            "Gmail scopes not granted. Re-authenticate with gmail scopes."
        )
    return build("gmail", "v1", credentials=creds)


# ---------------------------------------------------------------------------
# Retry wrapper
# ---------------------------------------------------------------------------


def _retry_api_call(func, max_retries: int = 3):
    """Wrap Google API calls with exponential backoff for 429 and 5xx errors."""
    for attempt in range(max_retries):
        try:
            return func()
        except HttpError as e:
            if e.resp.status in (429, 500, 502, 503) and attempt < max_retries - 1:
                wait = (2 ** attempt) + (time.time() % 1)  # jittered backoff
                logger.warning(
                    "Google API error %s, retrying in %.1fs", e.resp.status, wait
                )
                time.sleep(wait)
            else:
                raise


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_header(headers: list[dict], name: str) -> str | None:
    """Get a header value by name (case-insensitive)."""
    name_lower = name.lower()
    for h in headers:
        if h.get("name", "").lower() == name_lower:
            return h.get("value")
    return None


def _strip_html(html: str) -> str:
    """Basic HTML tag stripping for text fallback."""
    # Remove script and style blocks entirely
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
    # Replace <br> and <p> with newlines
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</p>", "\n", text, flags=re.IGNORECASE)
    # Strip remaining tags
    text = re.sub(r"<[^>]+>", "", text)
    # Collapse whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _parse_message_body(payload: dict) -> str:
    """Recursively walk MIME parts and extract the text body.

    Prefers text/plain; falls back to text/html with tag stripping.
    """
    mime_type = payload.get("mimeType", "")

    # Leaf node with body data
    body_data = payload.get("body", {}).get("data")
    if body_data and mime_type == "text/plain":
        return base64.urlsafe_b64decode(body_data + "==").decode("utf-8", errors="replace")

    # Recurse into parts
    parts = payload.get("parts", [])
    plain_text = ""
    html_text = ""

    for part in parts:
        part_mime = part.get("mimeType", "")
        part_body = part.get("body", {}).get("data")

        if part_mime == "text/plain" and part_body:
            plain_text = base64.urlsafe_b64decode(part_body + "==").decode("utf-8", errors="replace")
        elif part_mime == "text/html" and part_body:
            html_text = base64.urlsafe_b64decode(part_body + "==").decode("utf-8", errors="replace")
        elif part.get("parts"):
            # Nested multipart (e.g. multipart/alternative inside multipart/mixed)
            nested = _parse_message_body(part)
            if nested:
                if not plain_text:
                    plain_text = nested

    if plain_text:
        return plain_text
    if html_text:
        return _strip_html(html_text)

    # Single-part html message (no parts array)
    if body_data and mime_type == "text/html":
        raw_html = base64.urlsafe_b64decode(body_data + "==").decode("utf-8", errors="replace")
        return _strip_html(raw_html)

    return ""


def _build_mime_message(
    to: str,
    subject: str,
    body: str,
    cc: str | None = None,
    bcc: str | None = None,
    reply_to: str | None = None,
    thread_id: str | None = None,
    in_reply_to: str | None = None,
    references: str | None = None,
) -> dict:
    """Build a Gmail API-compatible message dict with base64url-encoded raw field."""
    message = MIMEText(body, "plain", "utf-8")
    message["To"] = to
    message["Subject"] = subject

    if cc:
        message["Cc"] = cc
    if bcc:
        message["Bcc"] = bcc
    if reply_to:
        message["Reply-To"] = reply_to
    if in_reply_to:
        message["In-Reply-To"] = in_reply_to
    if references:
        message["References"] = references

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    result: dict = {"raw": raw}
    if thread_id:
        result["threadId"] = thread_id
    return result


# ---------------------------------------------------------------------------
# Message operations
# ---------------------------------------------------------------------------


def list_messages(
    query: str | None = None,
    label_ids: list[str] | None = None,
    max_results: int = 100,
) -> list[dict]:
    """List messages with optional Gmail search query and label filters.

    Returns list of message stubs (id, threadId).  Use get_message() for full
    content.
    """
    service = get_gmail_service()

    kwargs: dict = {
        "userId": "me",
        "maxResults": min(max_results, 500),
    }
    if query:
        kwargs["q"] = query
    if label_ids:
        kwargs["labelIds"] = label_ids

    all_messages: list[dict] = []
    page_token = None

    while True:
        if page_token:
            kwargs["pageToken"] = page_token

        result = _retry_api_call(
            lambda: service.users().messages().list(**kwargs).execute()
        )
        all_messages.extend(result.get("messages", []))

        page_token = result.get("nextPageToken")
        if not page_token or len(all_messages) >= max_results:
            break

    return all_messages[:max_results]


def get_message(message_id: str) -> dict:
    """Get full message content including parsed body and attachment metadata.

    Returns a dict with: id, threadId, labelIds, snippet, headers (dict),
    body (parsed plain text), attachments (list of metadata dicts),
    internalDate, and gmail_link.
    """
    service = get_gmail_service()
    raw = _retry_api_call(
        lambda: service.users()
        .messages()
        .get(userId="me", id=message_id, format="full")
        .execute()
    )

    headers = raw.get("payload", {}).get("headers", [])
    parsed_body = _parse_message_body(raw.get("payload", {}))

    # Extract attachment metadata (no download)
    attachments = []
    for part in raw.get("payload", {}).get("parts", []):
        filename = part.get("filename")
        if filename:
            attachments.append({
                "filename": filename,
                "mimeType": part.get("mimeType", ""),
                "size": part.get("body", {}).get("size", 0),
                "attachmentId": part.get("body", {}).get("attachmentId"),
            })

    return {
        "id": raw["id"],
        "threadId": raw["threadId"],
        "labelIds": raw.get("labelIds", []),
        "snippet": raw.get("snippet", ""),
        "headers": {
            "from": _extract_header(headers, "From"),
            "to": _extract_header(headers, "To"),
            "subject": _extract_header(headers, "Subject"),
            "date": _extract_header(headers, "Date"),
            "cc": _extract_header(headers, "Cc"),
        },
        "body": parsed_body,
        "attachments": attachments,
        "internalDate": raw.get("internalDate"),
        "gmail_link": f"https://mail.google.com/mail/u/0/#inbox/{raw['id']}",
    }


def get_message_headers(message_id: str) -> dict:
    """Get message headers only (faster than full message, for triage).

    Returns: id, threadId, labelIds, snippet, and headers dict.
    """
    service = get_gmail_service()
    raw = _retry_api_call(
        lambda: service.users()
        .messages()
        .get(
            userId="me",
            id=message_id,
            format="metadata",
            metadataHeaders=["From", "To", "Subject", "Date", "Cc"],
        )
        .execute()
    )

    headers = raw.get("payload", {}).get("headers", [])
    return {
        "id": raw["id"],
        "threadId": raw["threadId"],
        "labelIds": raw.get("labelIds", []),
        "snippet": raw.get("snippet", ""),
        "headers": {
            "from": _extract_header(headers, "From"),
            "to": _extract_header(headers, "To"),
            "subject": _extract_header(headers, "Subject"),
            "date": _extract_header(headers, "Date"),
            "cc": _extract_header(headers, "Cc"),
        },
        "gmail_link": f"https://mail.google.com/mail/u/0/#inbox/{raw['id']}",
    }


# ---------------------------------------------------------------------------
# Label operations
# ---------------------------------------------------------------------------


def modify_labels(
    message_id: str,
    add_labels: list[str] | None = None,
    remove_labels: list[str] | None = None,
) -> dict:
    """Add and/or remove labels from a message."""
    service = get_gmail_service()
    body: dict = {}
    if add_labels:
        body["addLabelIds"] = add_labels
    if remove_labels:
        body["removeLabelIds"] = remove_labels

    return _retry_api_call(
        lambda: service.users()
        .messages()
        .modify(userId="me", id=message_id, body=body)
        .execute()
    )


def archive_message(message_id: str) -> dict:
    """Archive a message by removing the INBOX label."""
    return modify_labels(message_id, remove_labels=["INBOX"])


def mark_as_read(message_id: str) -> dict:
    """Mark a message as read by removing the UNREAD label."""
    return modify_labels(message_id, remove_labels=["UNREAD"])


def get_labels() -> list[dict]:
    """List all labels for the authenticated user."""
    service = get_gmail_service()
    result = _retry_api_call(
        lambda: service.users().labels().list(userId="me").execute()
    )
    return result.get("labels", [])


def create_label(name: str) -> dict:
    """Create a new label (e.g. OL/Triaged, OL/ActionNeeded)."""
    service = get_gmail_service()
    label_body = {
        "name": name,
        "labelListVisibility": "labelShow",
        "messageListVisibility": "show",
    }
    return _retry_api_call(
        lambda: service.users()
        .labels()
        .create(userId="me", body=label_body)
        .execute()
    )


# ---------------------------------------------------------------------------
# Draft and send operations
# ---------------------------------------------------------------------------


def create_draft(
    to: str,
    subject: str,
    body: str,
    reply_to: str | None = None,
    cc: str | None = None,
    bcc: str | None = None,
) -> dict:
    """Create a draft message."""
    service = get_gmail_service()
    message = _build_mime_message(
        to=to,
        subject=subject,
        body=body,
        cc=cc,
        bcc=bcc,
        reply_to=reply_to,
    )
    return _retry_api_call(
        lambda: service.users()
        .drafts()
        .create(userId="me", body={"message": message})
        .execute()
    )


def send_draft(draft_id: str) -> dict:
    """Send an existing draft."""
    service = get_gmail_service()
    return _retry_api_call(
        lambda: service.users()
        .drafts()
        .send(userId="me", body={"id": draft_id})
        .execute()
    )


def send_reply(message_id: str, body: str) -> dict:
    """Reply to a message within the same thread.

    Fetches the original message to get threadId, Subject, and
    In-Reply-To / References headers for proper threading.
    """
    original = get_message(message_id)
    headers = original["headers"]

    # Build Re: subject if not already present
    subject = headers.get("subject") or ""
    if not subject.lower().startswith("re:"):
        subject = f"Re: {subject}"

    # Get the original Message-ID for threading headers
    service = get_gmail_service()
    raw_msg = _retry_api_call(
        lambda: service.users()
        .messages()
        .get(
            userId="me",
            id=message_id,
            format="metadata",
            metadataHeaders=["Message-ID", "References"],
        )
        .execute()
    )
    raw_headers = raw_msg.get("payload", {}).get("headers", [])
    original_message_id = _extract_header(raw_headers, "Message-ID")
    existing_references = _extract_header(raw_headers, "References") or ""

    # Build References header: existing references + original Message-ID
    references = existing_references
    if original_message_id:
        references = f"{existing_references} {original_message_id}".strip()

    # Reply to the sender
    reply_to_addr = headers.get("from") or ""

    message = _build_mime_message(
        to=reply_to_addr,
        subject=subject,
        body=body,
        thread_id=original["threadId"],
        in_reply_to=original_message_id,
        references=references,
    )

    return _retry_api_call(
        lambda: service.users()
        .messages()
        .send(userId="me", body=message)
        .execute()
    )


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


def get_inbox_stats() -> dict:
    """Get inbox statistics: unread count and per-label message counts.

    Only queries INBOX and UNREAD labels to avoid N+1 API calls. For per-label
    counts, use the local cache via email_integration_service.get_inbox_stats().
    """
    service = get_gmail_service()

    # Get INBOX label for total and unread counts (single API call)
    inbox_label = _retry_api_call(
        lambda: service.users()
        .labels()
        .get(userId="me", id="INBOX")
        .execute()
    )

    return {
        "inbox_total": inbox_label.get("messagesTotal", 0),
        "inbox_unread": inbox_label.get("messagesUnread", 0),
    }
