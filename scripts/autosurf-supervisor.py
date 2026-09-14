from __future__ import annotations

import argparse
import ctypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time


CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000
WAIT_OBJECT_0 = 0
WAIT_ABANDONED = 0x00000080


def load_env_file(path: Path) -> None:
    """Load the installation environment before starting any child process."""
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key:
            os.environ[key] = value.strip().strip('"').strip("'")


def acquire_supervisor_mutex(root: Path) -> int | None:
    """Acquire a process-lifetime Windows mutex for one installation."""
    if os.name != "nt":
        return 1
    identifier = hashlib.sha256(str(root).casefold().encode("utf-8")).hexdigest()[:24]
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    handle = kernel32.CreateMutexW(None, False, f"Local\\AutoSurfSupervisor-{identifier}")
    if not handle:
        raise OSError(ctypes.get_last_error(), "CreateMutexW failed")
    kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel32.WaitForSingleObject.restype = ctypes.c_uint32
    result = kernel32.WaitForSingleObject(ctypes.c_void_p(handle), 0)
    if result not in {WAIT_OBJECT_0, WAIT_ABANDONED}:
        kernel32.CloseHandle(ctypes.c_void_p(handle))
        return None
    return int(handle)


def release_supervisor_mutex(handle: int | None) -> None:
    if handle and os.name == "nt":
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.ReleaseMutex.argtypes = [ctypes.c_void_p]
        kernel32.ReleaseMutex(ctypes.c_void_p(handle))
        kernel32.CloseHandle(ctypes.c_void_p(handle))


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
    load_env_file(root / ".env")
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

    mutex = acquire_supervisor_mutex(root)
    if mutex is None:
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
                    creationflags=CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW,
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
        release_supervisor_mutex(mutex)


if __name__ == "__main__":
    raise SystemExit(main())
