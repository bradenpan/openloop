"""Google Drive API client for OpenLoop.

Handles OAuth2 authentication and file operations against the Google Drive API.
Credentials are stored in the project root (credentials.json / token.json).
"""

from __future__ import annotations

import io
import logging

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

from backend.openloop.services import google_auth

logger = logging.getLogger(__name__)

# Scopes:
#   drive — full read/write access to files. OpenLoop enforces folder-level
#   restrictions at the application layer (agents can only access files in
#   Drive folders linked to their spaces via DataSources).
# Changing scopes requires re-authentication: delete token.json and re-authorize.
SCOPES = [
    "https://www.googleapis.com/auth/drive",
]

# Register Drive scopes with the shared OAuth infrastructure
google_auth.register_scopes("drive", SCOPES)

# Re-export paths so existing test patches on this module still work.
# Tests patch e.g. "backend.openloop.services.gdrive_client._TOKEN_PATH".
_CREDENTIALS_PATH = google_auth._CREDENTIALS_PATH
_TOKEN_PATH = google_auth._TOKEN_PATH

# Google Docs MIME types that require export rather than direct download
_GOOGLE_EXPORT_MAP = {
    "application/vnd.google-apps.document": ("text/plain", ".txt"),
    "application/vnd.google-apps.spreadsheet": ("text/csv", ".csv"),
    "application/vnd.google-apps.presentation": ("text/plain", ".txt"),
}


def is_authenticated() -> bool:
    """Check if token.json exists and contains valid (or refreshable) credentials."""
    if not _TOKEN_PATH.exists():
        return False
    try:
        creds = Credentials.from_authorized_user_file(str(_TOKEN_PATH), SCOPES)
        if creds.valid:
            return True
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            _TOKEN_PATH.write_text(creds.to_json())
            return True
    except Exception:
        logger.warning("Token validation failed", exc_info=True)
    return False


def get_drive_service():
    """Authenticate with Google Drive and return a service resource.

    First tries shared OAuth credentials; falls back to interactive flow.
    """
    creds = google_auth.get_credentials()

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not _CREDENTIALS_PATH.exists():
                raise FileNotFoundError(
                    f"Google OAuth credentials not found at {_CREDENTIALS_PATH}. "
                    "Download credentials.json from Google Cloud Console."
                )
            # Interactive fallback — launches browser for consent
            flow = InstalledAppFlow.from_client_secrets_file(
                str(_CREDENTIALS_PATH), SCOPES
            )
            creds = flow.run_local_server(port=0)

        google_auth._TOKEN_PATH.write_text(creds.to_json())

    return build("drive", "v3", credentials=creds)


def list_files(folder_id: str, page_size: int = 100) -> list[dict]:
    """List files in a Drive folder.

    Returns list of dicts with keys: id, name, mimeType, size, modifiedTime.
    """
    service = get_drive_service()
    results = (
        service.files()
        .list(
            q=f"'{folder_id}' in parents and trashed = false",
            pageSize=page_size,
            fields="files(id, name, mimeType, size, modifiedTime)",
        )
        .execute()
    )
    return results.get("files", [])


def read_file(file_id: str) -> tuple[bytes, str]:
    """Download file content from Drive.

    For Google Docs/Sheets/Slides, exports as text/csv.
    Returns (content_bytes, mime_type).
    """
    service = get_drive_service()

    # Get file metadata to determine type
    meta = service.files().get(fileId=file_id, fields="mimeType, name").execute()
    mime_type = meta.get("mimeType", "")

    if mime_type in _GOOGLE_EXPORT_MAP:
        export_mime, _ = _GOOGLE_EXPORT_MAP[mime_type]
        content = service.files().export(fileId=file_id, mimeType=export_mime).execute()
        if isinstance(content, str):
            content = content.encode("utf-8")
        return content, export_mime

    # Regular file — download directly
    content = service.files().get_media(fileId=file_id).execute()
    if isinstance(content, str):
        content = content.encode("utf-8")
    return content, mime_type


def read_file_text(file_id: str) -> str | None:
    """Read file content as text string. Returns None for binary files."""
    content_bytes, mime_type = read_file(file_id)

    # Text-like MIME types
    if mime_type.startswith("text/") or mime_type in (
        "application/json",
        "application/xml",
        "application/javascript",
    ):
        return content_bytes.decode("utf-8", errors="replace")

    # Google exports are always text
    if mime_type in ("text/plain", "text/csv"):
        return content_bytes.decode("utf-8", errors="replace")

    return None


def create_file(
    folder_id: str,
    name: str,
    content: str,
    mime_type: str = "text/plain",
) -> dict:
    """Create a new file in a Drive folder.

    Returns file metadata dict with id, name, mimeType.
    """
    service = get_drive_service()

    file_metadata = {
        "name": name,
        "parents": [folder_id],
    }

    media = MediaIoBaseUpload(
        io.BytesIO(content.encode("utf-8")),
        mimetype=mime_type,
        resumable=False,
    )

    file = (
        service.files()
        .create(body=file_metadata, media_body=media, fields="id, name, mimeType")
        .execute()
    )
    return file


def update_file(
    file_id: str,
    content: str,
    mime_type: str = "text/plain",
) -> dict:
    """Update the content of an existing Drive file.

    Cannot update native Google Docs/Sheets/Slides — the API rejects
    media uploads on native formats. Use the Google Docs editor instead.

    Returns file metadata dict with id, name, mimeType.
    """
    service = get_drive_service()

    # Check if file is a native Google format (cannot accept media upload)
    file_meta = service.files().get(fileId=file_id, fields="mimeType").execute()
    if file_meta.get("mimeType") in _GOOGLE_EXPORT_MAP:
        raise ValueError(
            f"Cannot update native Google format ({file_meta['mimeType']}). "
            "Use the Google Docs/Sheets/Slides editor instead."
        )

    media = MediaIoBaseUpload(
        io.BytesIO(content.encode("utf-8")),
        mimetype=mime_type,
        resumable=False,
    )

    file = (
        service.files()
        .update(fileId=file_id, media_body=media, fields="id, name, mimeType")
        .execute()
    )
    return file


def rename_file(file_id: str, new_name: str) -> dict:
    """Rename a Drive file.

    Returns file metadata dict with id, name, mimeType.
    """
    service = get_drive_service()

    file = (
        service.files()
        .update(fileId=file_id, body={"name": new_name}, fields="id, name, mimeType")
        .execute()
    )
    return file


def move_file(file_id: str, new_folder_id: str) -> dict:
    """Move a Drive file to a different folder.

    Returns file metadata dict with id, name, mimeType, parents.
    """
    service = get_drive_service()

    # Get current parents to remove
    current = service.files().get(fileId=file_id, fields="parents").execute()
    previous_parents = ",".join(current.get("parents", []))

    update_kwargs: dict = {
        "fileId": file_id,
        "addParents": new_folder_id,
        "fields": "id, name, mimeType, parents",
    }
    if previous_parents:
        update_kwargs["removeParents"] = previous_parents

    file = service.files().update(**update_kwargs).execute()
    return file
