"""Tests for scripts/backup_local.py."""

from datetime import datetime
from pathlib import Path

import pytest


@pytest.fixture()
def tmp_data_dir(tmp_path: Path):
    """Create a temporary data directory with a dummy database."""
    db_path = tmp_path / "openloop.db"
    db_path.write_text("fake-sqlite-data")

    backup_dir = tmp_path / "backups"
    last_backup_path = tmp_path / ".last_backup"

    return {
        "db_path": db_path,
        "backup_dir": backup_dir,
        "last_backup_path": last_backup_path,
    }


def test_backup_creates_file(tmp_data_dir):
    """create_backup should produce a timestamped .db file."""
    from scripts.backup_local import create_backup

    backup_path = create_backup(
        db_path=tmp_data_dir["db_path"],
        backup_dir=tmp_data_dir["backup_dir"],
    )

    assert backup_path.exists()
    assert backup_path.suffix == ".db"
    assert backup_path.name.startswith("openloop-")
    assert backup_path.parent == tmp_data_dir["backup_dir"]


def test_retention_deletes_old_backups(tmp_data_dir):
    """enforce_retention should keep only max_backups files."""
    from scripts.backup_local import enforce_retention

    backup_dir = tmp_data_dir["backup_dir"]
    backup_dir.mkdir(parents=True, exist_ok=True)

    # Create 15 fake backup files with distinct timestamps
    for i in range(15):
        name = f"openloop-2026-01-{i + 1:02d}-120000.db"
        (backup_dir / name).write_text(f"data-{i}")

    deleted = enforce_retention(backup_dir=backup_dir, max_backups=10)

    remaining = list(backup_dir.glob("openloop-*.db"))
    assert deleted == 5
    assert len(remaining) == 10


def test_last_backup_written(tmp_data_dir):
    """write_last_backup_timestamp should write an ISO timestamp."""
    from scripts.backup_local import write_last_backup_timestamp

    last_backup_path = tmp_data_dir["last_backup_path"]
    ts = write_last_backup_timestamp(last_backup_path=last_backup_path)

    assert last_backup_path.exists()
    content = last_backup_path.read_text().strip()
    assert content == ts
    # Should be parseable as ISO datetime
    parsed = datetime.fromisoformat(content)
    assert parsed.tzinfo is not None
