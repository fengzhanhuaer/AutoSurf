import subprocess
import sys
from pathlib import Path

import pytest

from autosurf.config import Settings
from autosurf.upgrade import _backup_database, _git, _run, upgrade


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


def test_upgrade_forces_worktree_to_remote_and_preserves_ignored_runtime(tmp_path, monkeypatch):
    remote = tmp_path / "remote.git"
    source = tmp_path / "source"
    repository = tmp_path / "program"
    subprocess.run(["git", "init", "--bare", "--initial-branch=main", remote], check=True)
    subprocess.run(["git", "init", "--initial-branch=main", source], check=True)
    subprocess.run(["git", "-C", source, "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", source, "config", "user.name", "AutoSurf Test"], check=True)
    source.joinpath(".gitignore").write_text(".venv/\n", encoding="utf-8")
    source.joinpath("tracked.txt").write_text("initial\n", encoding="utf-8")
    subprocess.run(["git", "-C", source, "add", "."], check=True)
    subprocess.run(["git", "-C", source, "commit", "-m", "initial"], check=True)
    subprocess.run(["git", "-C", source, "remote", "add", "origin", str(remote)], check=True)
    subprocess.run(["git", "-C", source, "push", "-u", "origin", "main"], check=True)
    subprocess.run(["git", "clone", "--branch", "main", str(remote), str(repository)], check=True)

    previous = subprocess.run(
        ["git", "-C", repository, "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    source.joinpath("tracked.txt").write_text("remote\n", encoding="utf-8")
    subprocess.run(["git", "-C", source, "commit", "-am", "remote update"], check=True)
    subprocess.run(["git", "-C", source, "push"], check=True)
    remote_revision = subprocess.run(
        ["git", "-C", source, "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()

    repository.joinpath("tracked.txt").write_text("local change\n", encoding="utf-8")
    repository.joinpath("untracked.txt").write_text("remove me\n", encoding="utf-8")
    repository.joinpath(".venv").mkdir()
    repository.joinpath(".venv", "runtime.txt").write_text("preserve me\n", encoding="utf-8")
    configured = settings(tmp_path)
    configured.data_dir.mkdir()
    configured.data_dir.joinpath("autosurf.db").write_bytes(b"database-content")

    def skip_package_install(repo, *args):
        if args[:3] == (sys.executable, "-m", "pip"):
            return subprocess.CompletedProcess(args, 0, "", "")
        return _run(repo, *args)

    monkeypatch.setenv("AUTOSURF_BRANCH", "main")
    monkeypatch.setattr("autosurf.upgrade._run", skip_package_install)
    monkeypatch.setattr("autosurf.upgrade.upgrade_database", lambda _url: None)

    result = upgrade(configured, repository)

    assert result.previous_revision == previous
    assert result.current_revision == remote_revision
    assert result.backup_path is not None
    assert result.backup_path.read_bytes() == b"database-content"
    assert repository.joinpath("tracked.txt").read_text(encoding="utf-8") == "remote\n"
    assert not repository.joinpath("untracked.txt").exists()
    assert repository.joinpath(".venv", "runtime.txt").read_text(encoding="utf-8") == "preserve me\n"


def test_git_allows_the_selected_repository_as_a_safe_directory(tmp_path, monkeypatch):
    captured = {}

    def fake_run(repository, *args):
        captured["repository"] = repository
        captured["args"] = args
        return type("Result", (), {"stdout": "true\n"})()

    monkeypatch.setattr("autosurf.upgrade._run", fake_run)

    assert _git(tmp_path, "status", "--porcelain") == "true\n"
    assert captured == {
        "repository": tmp_path,
        "args": ("git", "-c", f"safe.directory={tmp_path}", "status", "--porcelain"),
    }
