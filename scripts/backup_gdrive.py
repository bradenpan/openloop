"""Google Drive backup script for OpenLoop.

Uploads a copy of the SQLite database and compressed artifacts to Google Drive.
First run triggers an interactive OAuth flow; subsequent runs reuse the saved token.

Usage:
    PYTHONPATH=backend:. python backend/scripts/backup_gdrive.py
"""

import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path

# Repo root: two levels up from this file (scripts/backup_gdrive.py)
REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
DB_PATH = DATA_DIR / "openloop.db"
ARTIFACTS_DIR = DATA_DIR / "artifacts"
CREDENTIALS_PATH = REPO_ROOT / "credentials.json"
TOKEN_PATH = DATA_DIR / ".gdrive-token.json"
CONFIG_PATH = DATA_DIR / ".gdrive-config.json"

# Drive API scopes — file-level access only (no broad Drive access)
SCOPES = ["https://www.googleapis.com/auth/drive.file"]

# Retention: max backups to keep in the Drive folder
MAX_BACKUPS = 30


def _print_setup_instructions():
    """Print step-by-step instructions for Google Cloud OAuth setup."""
    print(
        f"""
================================================================================
  Google Drive Backup — First-Time Setup
================================================================================

  credentials.json not found at:
    {CREDENTIALS_PATH}

  To set up Google Drive backup, follow these steps:

  1. Go to https://console.cloud.google.com/
  2. Create a new project (or select an existing one)
  3. Enable the Google Drive API:
     - Go to "APIs & Services" > "Library"
     - Search for "Google Drive API"
     - Click "Enable"
  4. Create OAuth 2.0 credentials:
     - Go to "APIs & Services" > "Credentials"
     - Click "Create Credentials" > "OAuth client ID"
     - If prompted, configure the consent screen:
       * User type: External (or Internal if using Workspace)
       * App name: "OpenLoop Backup" (or whatever you like)
       * Add your email as a test user
     - Application type: "Desktop app"
     - Name: "OpenLoop Backup"
     - Click "Create"
  5. Download the credentials:
     - Click the download icon next to the newly created credential
     - Save the file as "credentials.json" in the project root:
       {CREDENTIALS_PATH}
  6. Run this script again:
     make backup-gdrive

================================================================================
"""
    )


def _get_credentials():
    """Load or create Google OAuth credentials.

    Returns a valid Credentials object, running the interactive OAuth flow
    if no saved token exists.
    """
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = None

    # Try loading saved token
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    # Refresh or re-authenticate
    if creds and creds.expired and creds.refresh_token:
        print("Refreshing expired token...")
        try:
            creds.refresh(Request())
        except Exception as e:
            print(f"Token refresh failed: {e}")
            print("Re-authenticating...")
            creds = None

    if not creds or not creds.valid:
        if not CREDENTIALS_PATH.exists():
            _print_setup_instructions()
            sys.exit(1)

        print("Starting OAuth flow — a browser window will open...")
        print("Authorize the application to access Google Drive.\n")
        flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_PATH), SCOPES)
        creds = flow.run_local_server(port=0)

        # Save token for future runs
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        TOKEN_PATH.write_text(creds.to_json())
        print(f"Token saved to {TOKEN_PATH}")

    return creds


def _get_drive_service(creds):
    """Build the Google Drive API service client."""
    from googleapiclient.discovery import build

    return build("drive", "v3", credentials=creds)


def _get_or_create_folder(service):
    """Get the configured Drive folder ID, or prompt the user to provide/create one.

    Returns the folder ID string.
    """
    # Check for saved config
    if CONFIG_PATH.exists():
        config = json.loads(CONFIG_PATH.read_text())
        folder_id = config.get("folder_id")
        if folder_id:
            # Verify the folder still exists
            try:
                folder = service.files().get(fileId=folder_id, fields="id, name, trashed").execute()
                if not folder.get("trashed"):
                    return folder_id
                print(f"Configured folder '{folder.get('name')}' was trashed.")
            except Exception:
                print("Configured folder no longer accessible.")

    # Prompt user
    print("\nGoogle Drive folder for backups:")
    print("  Enter a folder ID, or press Enter to create 'OpenLoop Backups'.")
    print("  (To find a folder ID: open the folder in Drive, copy the ID from the URL)")
    print("  URL format: https://drive.google.com/drive/folders/<FOLDER_ID>\n")

    folder_id = input("Folder ID (or Enter to create): ").strip()

    if not folder_id:
        # Create a new folder
        file_metadata = {
            "name": "OpenLoop Backups",
            "mimeType": "application/vnd.google-apps.folder",
        }
        folder = service.files().create(body=file_metadata, fields="id").execute()
        folder_id = folder["id"]
        print(f"Created folder 'OpenLoop Backups' (ID: {folder_id})")
    else:
        # Verify the provided folder exists
        try:
            folder = service.files().get(fileId=folder_id, fields="id, name").execute()
            print(f"Using folder: {folder.get('name')} (ID: {folder_id})")
        except Exception as e:
            print(f"Error: Could not access folder {folder_id}: {e}")
            sys.exit(1)

    # Save config
    CONFIG_PATH.write_text(json.dumps({"folder_id": folder_id}, indent=2))
    print(f"Config saved to {CONFIG_PATH}")

    return folder_id


def _copy_database(tmp_dir: Path) -> Path | None:
    """Create a safe copy of the SQLite database.

    Uses sqlite3 .backup command if available, falls back to file copy.
    Returns the path to the backup file, or None if the DB doesn't exist.
    """
    if not DB_PATH.exists():
        print("Warning: Database not found, skipping DB backup.")
        return None

    timestamp = datetime.now(UTC).strftime("%Y-%m-%d-%H%M%S")
    backup_name = f"openloop-{timestamp}.db"
    backup_path = tmp_dir / backup_name

    try:
        result = subprocess.run(
            ["sqlite3", str(DB_PATH), f".backup '{backup_path}'"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            raise subprocess.SubprocessError(result.stderr)
        print(f"Database backed up via sqlite3: {backup_name}")
    except (FileNotFoundError, subprocess.SubprocessError):
        shutil.copy2(str(DB_PATH), str(backup_path))
        print(f"Database backed up via file copy: {backup_name}")

    return backup_path


def _compress_artifacts(tmp_dir: Path) -> Path | None:
    """Compress the artifacts directory into a tar.gz archive.

    Returns the path to the archive, or None if no artifacts exist.
    """
    if not ARTIFACTS_DIR.exists() or not any(ARTIFACTS_DIR.iterdir()):
        print("No artifacts found, skipping artifacts backup.")
        return None

    timestamp = datetime.now(UTC).strftime("%Y-%m-%d-%H%M%S")
    archive_name = f"artifacts-{timestamp}.tar.gz"
    archive_path = tmp_dir / archive_name

    with tarfile.open(str(archive_path), "w:gz") as tar:
        tar.add(str(ARTIFACTS_DIR), arcname="artifacts")

    print(f"Artifacts compressed: {archive_name}")
    return archive_path


def _upload_file(service, folder_id: str, file_path: Path) -> dict:
    """Upload a file to the specified Google Drive folder.

    Returns the Drive file metadata dict.
    """
    from googleapiclient.http import MediaFileUpload

    file_metadata = {
        "name": file_path.name,
        "parents": [folder_id],
    }

    # Determine MIME type
    if file_path.suffix == ".db":
        mime_type = "application/x-sqlite3"
    elif file_path.suffix == ".gz":
        mime_type = "application/gzip"
    else:
        mime_type = "application/octet-stream"

    media = MediaFileUpload(str(file_path), mimetype=mime_type, resumable=True)

    file = (
        service.files()
        .create(body=file_metadata, media_body=media, fields="id, name, size")
        .execute()
    )

    return file


def _enforce_retention(service, folder_id: str):
    """Delete oldest backups if the folder exceeds MAX_BACKUPS files.

    Only considers files matching the backup naming patterns
    (openloop-*.db, artifacts-*.tar.gz).
    """
    # List all files in the folder
    results = (
        service.files()
        .list(
            q=f"'{folder_id}' in parents and trashed = false",
            fields="files(id, name, createdTime)",
            orderBy="createdTime desc",
            pageSize=200,
        )
        .execute()
    )

    files = results.get("files", [])

    # Filter to only backup files
    backup_files = [
        f for f in files if f["name"].startswith("openloop-") or f["name"].startswith("artifacts-")
    ]

    if len(backup_files) <= MAX_BACKUPS:
        print(f"Retention: {len(backup_files)}/{MAX_BACKUPS} backups — no cleanup needed.")
        return

    # Delete oldest files beyond the limit
    to_delete = backup_files[MAX_BACKUPS:]
    print(f"Retention: {len(backup_files)} backups found, deleting {len(to_delete)} oldest...")

    for f in to_delete:
        try:
            service.files().delete(fileId=f["id"]).execute()
            print(f"  Deleted: {f['name']}")
        except Exception as e:
            print(f"  Warning: Failed to delete {f['name']}: {e}")


def _format_size(size_bytes: int) -> str:
    """Format byte count as human-readable string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} MB"


def main():
    """Run the Google Drive backup."""
    print("=" * 60)
    print("  OpenLoop — Google Drive Backup")
    print("=" * 60)
    print()

    # Step 1: Authenticate
    creds = _get_credentials()
    service = _get_drive_service(creds)
    print("Authenticated with Google Drive.\n")

    # Step 2: Get/create backup folder
    folder_id = _get_or_create_folder(service)
    print()

    # Step 3: Create local backup files
    uploaded = []
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)

        db_backup = _copy_database(tmp_path)
        artifacts_backup = _compress_artifacts(tmp_path)

        if not db_backup and not artifacts_backup:
            print("Nothing to back up.")
            return

        print()

        # Step 4: Upload
        if db_backup:
            print(f"Uploading {db_backup.name}...")
            result = _upload_file(service, folder_id, db_backup)
            size = int(result.get("size", 0))
            uploaded.append((result["name"], size))
            print(f"  Uploaded: {result['name']} ({_format_size(size)})")

        if artifacts_backup:
            print(f"Uploading {artifacts_backup.name}...")
            result = _upload_file(service, folder_id, artifacts_backup)
            size = int(result.get("size", 0))
            uploaded.append((result["name"], size))
            print(f"  Uploaded: {result['name']} ({_format_size(size)})")

    print()

    # Step 5: Enforce retention
    _enforce_retention(service, folder_id)

    # Write last-backup timestamp
    last_backup_path = DATA_DIR / ".last_backup"
    now = datetime.now(tz=UTC)
    last_backup_path.write_text(now.isoformat())
    print(f"Last backup timestamp written: {now.isoformat()}")

    # Summary
    print()
    print("=" * 60)
    print("  Backup Summary")
    print("=" * 60)
    for name, size in uploaded:
        print(f"  {name:40s} {_format_size(size):>10s}")
    total_size = sum(s for _, s in uploaded)
    print(f"  {'Total':40s} {_format_size(total_size):>10s}")
    print(f"  Folder ID: {folder_id}")
    print(f"  Retention: max {MAX_BACKUPS} backups")
    print("=" * 60)


if __name__ == "__main__":
    main()
