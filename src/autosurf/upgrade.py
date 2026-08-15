from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from autosurf.config import Settings
from autosurf.infrastructure.migrations import upgrade_database


@dataclass(frozen=True)
class UpgradeResult:
    previous_revision: str
    current_revision: str
    backup_path: Path | None


def upgrade(settings: Settings, repository: Path | None = None) -> UpgradeResult:
    repository = (repository or Path.cwd()).resolve()
    _ensure_git_repository(repository)
    previous = _git(repository, "rev-parse", "HEAD").strip()
    branch = os.environ.get("AUTOSURF_BRANCH", "main").strip()
    if not branch:
        raise RuntimeError("AUTOSURF_BRANCH cannot be empty")
    _git(repository, "check-ref-format", "--branch", branch)
    remote_ref = f"refs/remotes/origin/{branch}"
    _git(
        repository,
        "fetch",
        "--prune",
        "origin",
        f"+refs/heads/{branch}:{remote_ref}",
    )

    backup = _backup_database(settings.data_dir)
    _git(repository, "reset", "--hard", remote_ref)
    # Preserve ignored runtime state such as .venv while removing local source additions.
    _git(repository, "clean", "-fd")
    current = _git(repository, "rev-parse", "HEAD").strip()
    _run(repository, sys.executable, "-m", "pip", "install", "--upgrade", "-e", ".")
    upgrade_database(settings.database_url)
    return UpgradeResult(previous_revision=previous, current_revision=current, backup_path=backup)


def _ensure_git_repository(repository: Path) -> None:
    try:
        inside = _git(repository, "rev-parse", "--is-inside-work-tree").strip()
    except RuntimeError as exc:
        raise RuntimeError(f"{repository} is not a Git checkout") from exc
    if inside != "true":
        raise RuntimeError(f"{repository} is not a Git checkout")


def _backup_database(data_dir: Path) -> Path | None:
    database = data_dir / "autosurf.db"
    if not database.exists():
        return None
    backup_dir = data_dir / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = backup_dir / f"autosurf-{timestamp}.db"
    shutil.copy2(database, destination)
    return destination


def _git(repository: Path, *args: str) -> str:
    return _run(repository, "git", "-c", f"safe.directory={repository}", *args).stdout


def _run(repository: Path, *args: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, cwd=repository, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"command failed ({' '.join(args)}): {detail}")
    return result
