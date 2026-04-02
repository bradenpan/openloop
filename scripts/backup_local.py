"""Local backup script for OpenLoop.

Copies the SQLite database to data/backups/ with a timestamped filename.
Uses sqlite3 .backup command for safety, falls back to shutil.copy2.
Retains the last 10 backups, deletes older ones.

Usage:
    python scripts/backup_local.py
"""

import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
DB_PATH = DATA_DIR / "openloop.db"
BACKUP_DIR = DATA_DIR / "backups"
LAST_BACKUP_PATH = DATA_DIR / ".last_backup"

MAX_BACKUPS = 10


def _format_size(size_bytes: int) -> str:
    """Format byte count as human-readable string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} MB"


def create_backup(
    db_path: Path = DB_PATH,
    backup_dir: Path = BACKUP_DIR,
) -> Path:
    """Create a timestamped backup of the SQLite database.

    Returns the path to the created backup file.
    """
    if not db_path.exists():
        print(f"Error: Database not found at {db_path}")
        sys.exit(1)

    backup_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(UTC).strftime("%Y-%m-%d-%H%M%S")
    backup_name = f"openloop-{timestamp}.db"
    backup_path = backup_dir / backup_name

    # Try sqlite3 .backup command first (safe for concurrent access)
    try:
        result = subprocess.run(
            ["sqlite3", str(db_path), f".backup '{backup_path}'"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            raise subprocess.SubprocessError(result.stderr)
        method = "sqlite3 .backup"
    except (FileNotFoundError, subprocess.SubprocessError):
        shutil.copy2(str(db_path), str(backup_path))
        method = "file copy"

    print(f"Backup created via {method}: {backup_name}")
    return backup_path


def enforce_retention(backup_dir: Path = BACKUP_DIR, max_backups: int = MAX_BACKUPS) -> int:
    """Delete oldest backups beyond the retention limit.

    Returns the number of backups deleted.
    """
    if not backup_dir.exists():
        return 0

    # Sort by name descending (names contain timestamps, so this is chronological)
    backups = sorted(backup_dir.glob("openloop-*.db"), reverse=True)

    if len(backups) <= max_backups:
        return 0

    to_delete = backups[max_backups:]
    for old_backup in to_delete:
        old_backup.unlink()
        print(f"  Deleted old backup: {old_backup.name}")

    return len(to_delete)


def write_last_backup_timestamp(last_backup_path: Path = LAST_BACKUP_PATH) -> str:
    """Write the current UTC timestamp to the .last_backup file.

    Returns the ISO timestamp string.
    """
    now = datetime.now(UTC)
    iso_str = now.isoformat()
    last_backup_path.write_text(iso_str)
    return iso_str


def main():
    """Run the local backup."""
    print("=" * 50)
    print("  OpenLoop — Local Backup")
    print("=" * 50)
    print()

    # Create backup
    backup_path = create_backup()
    size = backup_path.stat().st_size
    print(f"  Size: {_format_size(size)}")
    print()

    # Enforce retention
    deleted = enforce_retention()
    remaining = len(list(BACKUP_DIR.glob("openloop-*.db")))
    if deleted > 0:
        print(f"  Cleaned up {deleted} old backup(s)")
    print(f"  Backups on disk: {remaining}/{MAX_BACKUPS}")
    print()

    # Write timestamp
    ts = write_last_backup_timestamp()
    print(f"  Last backup timestamp: {ts}")

    print()
    print("=" * 50)
    print(f"  {backup_path.name}  ({_format_size(size)})")
    print("=" * 50)


if __name__ == "__main__":
    main()
