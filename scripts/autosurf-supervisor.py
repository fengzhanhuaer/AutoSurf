from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time


CREATE_NEW_PROCESS_GROUP = 0x00000200


def write_status(path: Path, state: str) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({
        "state": state,
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def stop_process_tree(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    subprocess.run(
        ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def upgrade_program(
    python: Path,
    program: Path,
    data: Path,
    log: object,
) -> bool:
    database = data / "autosurf.db"
    if database.is_file():
        backups = data / "backups"
        backups.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        shutil.copy2(database, backups / f"autosurf-{timestamp}.db")
    branch = os.environ.get("AUTOSURF_BRANCH", "main")
    commands = (
        ["git.exe", "-c", f"safe.directory={program}", "-C", str(program),
         "check-ref-format", "--branch", branch],
        ["git.exe", "-c", f"safe.directory={program}", "-C", str(program),
         "fetch", "--prune", "origin",
         f"+refs/heads/{branch}:refs/remotes/origin/{branch}"],
        ["git.exe", "-c", f"safe.directory={program}", "-C", str(program),
         "reset", "--hard", f"refs/remotes/origin/{branch}"],
        ["git.exe", "-c", f"safe.directory={program}", "-C", str(program),
         "clean", "-fd"],
        [str(python), "-m", "pip", "install", "--disable-pip-version-check",
         "--upgrade", "-e", str(program)],
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
         str(program / "scripts" / "install-browser.ps1"), "-InstallDir", str(program.parent)],
    )
    for command in commands:
        result = subprocess.run(
            command,
            cwd=program,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            check=False,
        )
        if result.returncode != 0:
            return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Supervise the native AutoSurf service")
    parser.add_argument("--root", type=Path, default=Path(r"C:\Tools\AutoSurf"))
    args = parser.parse_args()
    root = args.root.resolve()
    program = root / "program"
    data = root / "data"
    python = program / ".venv" / "Scripts" / "python.exe"
    request_file = data / "upgrade-request.json"
    upgrade_lock = data / "upgrade-in-progress.lock"
    status_file = data / "upgrade-status.json"
    pid_file = data / "supervisor.pid"
    log_file = data / "autosurf.log"
    data.mkdir(parents=True, exist_ok=True)
    if not python.is_file():
        raise RuntimeError(f"AutoSurf Python environment is missing: {python}")

    if pid_file.is_file():
        try:
            existing_pid = int(pid_file.read_text(encoding="ascii").strip())
            os.kill(existing_pid, 0)
        except (OSError, ValueError):
            pid_file.unlink(missing_ok=True)
        else:
            return 0
    pid_file.write_text(f"{os.getpid()}\n", encoding="ascii")
    process: subprocess.Popen[bytes] | None = None
    try:
        while True:
            if process is None or process.poll() is not None:
                log = log_file.open("ab", buffering=0)
                process = subprocess.Popen(
                    [str(python), "-m", "autosurf.main", "serve"],
                    cwd=root,
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    creationflags=CREATE_NEW_PROCESS_GROUP,
                )
                log.close()

            if request_file.exists():
                stop_process_tree(process)
                process = None
                upgrade_lock.touch()
                write_status(status_file, "running")
                try:
                    with log_file.open("ab", buffering=0) as log:
                        upgraded = upgrade_program(python, program, data, log)
                except Exception as exc:
                    with log_file.open("ab", buffering=0) as log:
                        log.write(f"Windows upgrade failed: {exc}\n".encode(errors="replace"))
                    upgraded = False
                write_status(status_file, "complete" if upgraded else "failed")
                request_file.unlink(missing_ok=True)
                upgrade_lock.unlink(missing_ok=True)
                time.sleep(1)
                continue

            if process.poll() is not None:
                time.sleep(3)
                process = None
                continue
            time.sleep(1)
    except KeyboardInterrupt:
        return 0
    finally:
        if process is not None:
            stop_process_tree(process)
        pid_file.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
