from pathlib import Path

import pytest

from autosurf.config import Settings
from autosurf.upgrade import _backup_database, upgrade


def settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path / "data", secret_key="s" * 32,
                    username="admin", password="password123")


def test_database_backup_is_created(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    database = data_dir / "autosurf.db"
    database.write_bytes(b"database-content")

    backup = _backup_database(data_dir)

    assert backup is not None
    assert backup.parent == data_dir / "backups"
    assert backup.read_bytes() == b"database-content"


def test_upgrade_rejects_non_git_directory(tmp_path):
    with pytest.raises(RuntimeError, match="not a Git checkout"):
        upgrade(settings(tmp_path), tmp_path)


def test_upgrade_rejects_dirty_worktree_before_backup(tmp_path, monkeypatch):
    calls = []

    def fake_git(_repository, *args):
        calls.append(args)
        if args == ("rev-parse", "--is-inside-work-tree"):
            return "true\n"
        if args == ("status", "--porcelain"):
            return " M src/file.py\n"
        raise AssertionError(args)

    monkeypatch.setattr("autosurf.upgrade._git", fake_git)
    with pytest.raises(RuntimeError, match="uncommitted changes"):
        upgrade(settings(tmp_path), tmp_path)
    assert not (tmp_path / "data" / "backups").exists()
