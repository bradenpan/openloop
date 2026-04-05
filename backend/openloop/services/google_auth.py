"""Shared Google OAuth infrastructure for all Google integrations (Drive, Calendar, Gmail)."""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_CREDENTIALS_PATH = _PROJECT_ROOT / "credentials.json"
_TOKEN_PATH = _PROJECT_ROOT / "token.json"

# Scope registry -- each integration registers its scopes on import
_SCOPE_REGISTRY: dict[str, list[str]] = {}


def register_scopes(integration: str, scopes: list[str]) -> None:
    """Register required scopes for an integration."""
    _SCOPE_REGISTRY[integration] = scopes


def get_all_required_scopes() -> list[str]:
    """Get the union of all registered integration scopes."""
    all_scopes: set[str] = set()
    for scopes in _SCOPE_REGISTRY.values():
        all_scopes.update(scopes)
    return sorted(all_scopes)


def get_credentials() -> Credentials | None:
    """Load token.json and return Credentials if valid or refreshable."""
    if not _TOKEN_PATH.exists():
        return None
    try:
        creds = Credentials.from_authorized_user_file(str(_TOKEN_PATH))
        if creds.valid:
            return creds
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            _TOKEN_PATH.write_text(creds.to_json())
            return creds
    except Exception:
        logger.warning("Token validation failed", exc_info=True)
    return None


def get_granted_scopes() -> list[str]:
    """Return the scopes currently granted in token.json."""
    if not _TOKEN_PATH.exists():
        return []
    try:
        creds = Credentials.from_authorized_user_file(str(_TOKEN_PATH))
        return list(creds.scopes or [])
    except Exception:
        return []


def get_missing_scopes() -> list[str]:
    """Compare token's granted scopes against all required scopes."""
    granted = set(get_granted_scopes())
    required = set(get_all_required_scopes())
    return sorted(required - granted)


def is_authenticated(required_scopes: list[str] | None = None) -> bool:
    """Check if token exists and includes the specified scopes."""
    creds = get_credentials()
    if creds is None:
        return False
    if required_scopes:
        granted = set(creds.scopes or [])
        return all(s in granted for s in required_scopes)
    return True


def refresh_if_needed(credentials: Credentials) -> Credentials:
    """Refresh expired token. Does NOT add new scopes."""
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
        _TOKEN_PATH.write_text(credentials.to_json())
    return credentials


# Background auth server tracking
_auth_server_lock = threading.Lock()
_auth_server_flow: InstalledAppFlow | None = None
_auth_server_thread: threading.Thread | None = None


def get_auth_url(scopes: list[str] | None = None) -> str:
    """Generate OAuth consent URL and start background server to receive callback.

    Uses include_granted_scopes=True for incremental authorization.
    Starts InstalledAppFlow.run_local_server() in a background thread.
    Only one auth flow runs at a time — calling again cancels the previous.
    Returns the consent URL immediately.
    """
    global _auth_server_flow, _auth_server_thread

    if not _CREDENTIALS_PATH.exists():
        raise FileNotFoundError(
            f"Google OAuth credentials not found at {_CREDENTIALS_PATH}. "
            "Download credentials.json from Google Cloud Console."
        )

    # Cancel any existing auth flow before starting a new one
    with _auth_server_lock:
        if _auth_server_flow is not None:
            logger.info("Cancelling previous OAuth flow before starting new one")
            try:
                # Shut down the local server if it's running
                if hasattr(_auth_server_flow, "_server") and _auth_server_flow._server:
                    _auth_server_flow._server.shutdown()
            except Exception:
                logger.debug("Could not shut down previous auth server", exc_info=True)
            _auth_server_flow = None
            _auth_server_thread = None

    target_scopes = scopes or get_all_required_scopes()

    flow = InstalledAppFlow.from_client_secrets_file(
        str(_CREDENTIALS_PATH),
        scopes=target_scopes,
    )

    # Generate the auth URL with incremental auth
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )

    # Start the local server in a background thread to wait for the callback
    def _run_server() -> None:
        global _auth_server_flow, _auth_server_thread
        try:
            with _auth_server_lock:
                _auth_server_flow = flow
            creds = flow.run_local_server(port=0, open_browser=False)
            _TOKEN_PATH.write_text(creds.to_json())
            logger.info("OAuth token saved successfully")
        except Exception:
            logger.error("OAuth callback server failed", exc_info=True)
        finally:
            with _auth_server_lock:
                _auth_server_flow = None
                _auth_server_thread = None

    thread = threading.Thread(target=_run_server, daemon=True)
    with _auth_server_lock:
        _auth_server_thread = thread
    thread.start()

    return auth_url


def get_auth_status() -> dict:
    """Get comprehensive auth status."""
    granted = get_granted_scopes()
    missing = get_missing_scopes()
    return {
        "authenticated": len(granted) > 0 and is_authenticated(),
        "granted_scopes": granted,
        "missing_scopes": missing,
        "has_credentials_file": _CREDENTIALS_PATH.exists(),
    }
