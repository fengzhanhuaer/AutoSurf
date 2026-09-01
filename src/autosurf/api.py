from __future__ import annotations

import json
import base64
from contextlib import suppress
from datetime import datetime, timedelta
import hashlib
import hmac
import io
from importlib.metadata import PackageNotFoundError, version
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import time
from typing import Any, Literal
from urllib.parse import urlparse
import zipfile

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import FileResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from autosurf.domain.models import ExecutionStatus, RunOutcome, utc_now
from autosurf.domain.scheduling import SIGNIN_START_TIME, next_signin_run_at
from autosurf.application.services import (
    PT_PROFILE_REFRESH_DEFAULT_VERSION,
    align_all_signin_schedules,
)
from autosurf.automations.pt_signin import sanitize_pt_profile_stats
from autosurf.automations.browser_session import (
    _standalone_chrome_executable,
    persistent_browser_mode,
)
from autosurf.browser_control import BrowserControlBusy
from autosurf.infrastructure.database import (
    AutomationRecord,
    ExecutionRecord,
)
from autosurf.pt_discovery import PT_SITE_CATALOG, discover_pt_site, is_ignored_pt_domain
from autosurf.periodic_templates import (
    PERIODIC_SITE_TEMPLATES,
    apply_periodic_template,
)


class AutomationInput(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    handler_type: str
    interval_seconds: int = Field(ge=60, le=31_536_000)
    config: dict[str, Any]


class PtSignInInput(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    url: str = Field(min_length=8, max_length=2048)
    interval_hours: int = Field(default=24, ge=1, le=720)
    timeout_seconds: int = Field(default=60, ge=5, le=180)
    random_delay_minutes: int = Field(default=30, ge=0, le=1440)
    retry_interval_hours: int = Field(default=2, ge=1, le=168)
    max_retries: int = Field(default=5, ge=0, le=20)
    click_selector: str | None = Field(default=None, max_length=1024)
    success_patterns: list[str] = Field(default_factory=list, max_length=20)
    already_patterns: list[str] = Field(default_factory=list, max_length=20)
    sign_in_enabled: bool = True
    profile_refresh_enabled: bool = True


class PtSignInEnabledInput(BaseModel):
    enabled: bool


class PtSiteActionsInput(BaseModel):
    sign_in_enabled: bool
    profile_refresh_enabled: bool


class PtSignInCollectInput(BaseModel):
    site_keys: list[str] = Field(min_length=1, max_length=200)
    interval_hours: int = Field(default=24, ge=1, le=720)
    timeout_seconds: int = Field(default=60, ge=5, le=180)
    random_delay_minutes: int = Field(default=30, ge=0, le=1440)
    retry_interval_hours: int = Field(default=2, ge=1, le=168)
    max_retries: int = Field(default=5, ge=0, le=20)
    sign_in_enabled: bool = True
    profile_refresh_enabled: bool = True


class PtBatchRunInput(BaseModel):
    action: Literal["sign_in", "profile_refresh"]


class PtSignInScheduleInput(BaseModel):
    interval_hours: int = Field(default=24, ge=1, le=720)
    timeout_seconds: int = Field(default=60, ge=5, le=180)
    random_delay_minutes: int = Field(default=30, ge=0, le=1440)
    retry_interval_hours: int = Field(default=2, ge=1, le=168)
    max_retries: int = Field(default=5, ge=0, le=20)


class PeriodicSignInInput(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    handler_type: str = "browser_signin"
    template_key: str | None = Field(default=None, max_length=64)
    url: str = Field(min_length=8, max_length=2048)
    interval_hours: int = Field(default=24, ge=1, le=720)
    timeout_seconds: int = Field(default=60, ge=1, le=180)
    random_delay_minutes: int = Field(default=30, ge=0, le=1440)
    retry_interval_hours: int = Field(default=2, ge=1, le=168)
    max_retries: int = Field(default=5, ge=0, le=20)
    method: str = "GET"
    wait_for_selector: str | None = Field(default=None, max_length=1024)
    click_selector: str | None = Field(default=None, max_length=1024)
    click_role: str | None = Field(default=None, max_length=64)
    click_name: str | None = Field(default=None, max_length=256)
    click_exact: bool = False
    wait_after_click_ms: int = Field(default=1500, ge=0, le=30_000)
    success_patterns: list[str] = Field(default_factory=list, max_length=20)
    already_patterns: list[str] = Field(default_factory=list, max_length=20)
    auth_expired_patterns: list[str] = Field(default_factory=list, max_length=20)


class PeriodicSignInScheduleInput(BaseModel):
    interval_hours: int = Field(default=24, ge=1, le=720)
    timeout_seconds: int = Field(default=60, ge=1, le=180)
    random_delay_minutes: int = Field(default=30, ge=0, le=1440)
    retry_interval_hours: int = Field(default=2, ge=1, le=168)
    max_retries: int = Field(default=5, ge=0, le=20)


class PeriodicSignInCollectInput(PeriodicSignInScheduleInput):
    site_keys: list[str] = Field(min_length=1, max_length=200)


class LoginInput(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=1024)


class SystemAccessSettingsInput(BaseModel):
    lan_only: bool = True


class BrowserResolutionInput(BaseModel):
    width: int
    height: int


SESSION_COOKIE = "autosurf_session"
SESSION_MAX_AGE_SECONDS = 7 * 24 * 60 * 60
basic_auth = HTTPBasic(auto_error=False)


def _valid_credentials(settings: Any, username: str, password: str) -> bool:
    username_ok = secrets.compare_digest(username.encode(), settings.username.encode())
    password_ok = secrets.compare_digest(password.encode(), settings.password.encode())
    return username_ok and password_ok


def _session_token(settings: Any, username: str, expires_at: int) -> str:
    payload = f"{username}\n{expires_at}".encode()
    encoded = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    signature = hmac.new(settings.secret_key.encode(), encoded.encode(), hashlib.sha256).digest()
    return f"{encoded}.{base64.urlsafe_b64encode(signature).decode().rstrip('=')}"


def _session_username(settings: Any, token: str | None) -> str | None:
    if not token:
        return None
    try:
        encoded, supplied_signature = token.split(".", 1)
        expected_signature = hmac.new(settings.secret_key.encode(), encoded.encode(), hashlib.sha256).digest()
        supplied = base64.urlsafe_b64decode(supplied_signature + "=" * (-len(supplied_signature) % 4))
        if not hmac.compare_digest(supplied, expected_signature):
            return None
        payload = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)).decode()
        username, expires_at = payload.rsplit("\n", 1)
        if int(expires_at) < int(time.time()) or username != settings.username:
            return None
        return username
    except (ValueError, UnicodeDecodeError):
        return None


def authenticated_session_username(settings: Any, token: str | None) -> str | None:
    return _session_username(settings, token)


def require_login(request: Request, credentials: HTTPBasicCredentials | None = Depends(basic_auth)) -> str:
    settings = request.app.state.settings
    if credentials:
        if _valid_credentials(settings, credentials.username, credentials.password):
            return credentials.username
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid username or password")
    username = _session_username(settings, request.cookies.get(SESSION_COOKIE))
    if username:
        return username
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="login required")


auth_router = APIRouter(prefix="/api/auth")


@auth_router.post("/login")
def login(data: LoginInput, request: Request, response: Response) -> dict[str, str]:
    settings = request.app.state.settings
    if not _valid_credentials(settings, data.username, data.password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    expires_at = int(time.time()) + SESSION_MAX_AGE_SECONDS
    response.set_cookie(
        SESSION_COOKIE,
        _session_token(settings, data.username, expires_at),
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="strict",
        path="/",
    )
    return {"username": data.username}


@auth_router.get("/session")
def current_session(request: Request) -> dict[str, str]:
    username = _session_username(request.app.state.settings, request.cookies.get(SESSION_COOKIE))
    if not username:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="login required")
    return {"username": username}


@auth_router.post("/logout", status_code=204)
def logout(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="strict")


router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_login)])


@router.get("/browser-control")
async def browser_control_status(request: Request) -> dict[str, Any]:
    return await request.app.state.browser_control.status()


@router.post("/browser-control/open")
async def open_browser_control_window(request: Request) -> dict[str, Any]:
    return await request.app.state.browser_control.open_window()


@router.patch("/browser-control/resolution")
async def set_browser_control_resolution(
    data: BrowserResolutionInput,
    request: Request,
) -> dict[str, Any]:
    try:
        return await request.app.state.browser_control.set_resolution(data.width, data.height)
    except BrowserControlBusy as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _program_repository() -> Path:
    configured = os.environ.get("AUTOSURF_PROGRAM_DIR")
    return Path(configured).resolve() if configured else Path(__file__).resolve().parents[2]


def _upgrade_command() -> list[str] | None:
    configured = os.environ.get("AUTOSURF_UPGRADE_SCRIPT")
    if configured and Path(configured).is_file():
        if os.name == "nt" and configured.lower().endswith(".ps1"):
            return [
                "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                "-File", configured,
            ]
        return ["/bin/sh", configured]
    executable = shutil.which("autosurf-upgrade")
    return [executable] if executable else None


def _upgrade_request_file() -> Path | None:
    configured = os.environ.get("AUTOSURF_UPGRADE_REQUEST_FILE", "").strip()
    return Path(configured) if configured else None


def _upgrade_lock_file() -> Path:
    configured = os.environ.get("AUTOSURF_UPGRADE_LOCK_FILE", "").strip()
    return Path(configured) if configured else Path("/tmp/autosurf-upgrade-in-progress")


def _program_revision(repository: Path) -> str | None:
    result = subprocess.run(
        ["git", "-c", f"safe.directory={repository}", "rev-parse", "HEAD"],
        cwd=repository,
        text=True,
        capture_output=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _remote_revision(repository: Path, branch: str) -> tuple[str | None, str | None]:
    try:
        result = subprocess.run(
            ["git", "-c", f"safe.directory={repository}", "ls-remote", "--exit-code",
             "origin", f"refs/heads/{branch}"],
            cwd=repository,
            text=True,
            capture_output=True,
            check=False,
            timeout=15,
        )
    except subprocess.TimeoutExpired:
        return None, "远端版本检查超时"
    if result.returncode != 0 or not result.stdout.strip():
        return None, "无法读取远端版本"
    revision = result.stdout.split()[0]
    if len(revision) != 40:
        return None, "远端返回了无效版本"
    return revision, None


def _upgrade_running(request: Request) -> bool:
    process = getattr(request.app.state, "upgrade_process", None)
    process_running = process is not None and process.poll() is None
    request_file = _upgrade_request_file()
    return (
        process_running
        or _upgrade_lock_file().exists()
        or bool(request_file is not None and request_file.exists())
    )


def _last_upgrade(request: Request) -> dict[str, str] | None:
    status_file = request.app.state.settings.data_dir / "upgrade-status.json"
    try:
        result = json.loads(status_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(result, dict) or result.get("state") not in {"running", "complete", "failed"}:
        return None
    return {key: str(result[key]) for key in ("state", "updated_at") if key in result}


def _settle_stale_upgrade(request: Request, last: dict[str, str] | None, *, running: bool,
                          local_revision: str | None, remote_revision: str | None,
                          check_error: str | None, browser: dict[str, Any],
                          dependencies: dict[str, Any]) -> dict[str, str] | None:
    if not last or last.get("state") != "running" or running:
        return last
    complete = bool(
        check_error is None
        and local_revision
        and local_revision == remote_revision
        and browser.get("installed")
        and dependencies.get("checked")
        and dependencies.get("satisfied")
    )
    settled = {
        "state": "complete" if complete else "failed",
        "updated_at": utc_now().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    status_file = request.app.state.settings.data_dir / "upgrade-status.json"
    with suppress(OSError):
        status_file.write_text(json.dumps(settled, ensure_ascii=True) + "\n", encoding="utf-8")
    return settled


def _browser_runtime() -> dict[str, Any]:
    browser_root = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", ""))
    configured_executable = os.environ.get("AUTOSURF_BROWSER_EXECUTABLE_PATH", "").strip()
    if not configured_executable and (
        os.name == "nt" or os.environ.get("AUTOSURF_BROWSER_CHANNEL", "").strip() == "chrome"
    ):
        with suppress(RuntimeError):
            configured_executable = _standalone_chrome_executable()
    try:
        playwright_version = version("playwright")
    except PackageNotFoundError:
        playwright_version = None
    chromium_revision = None
    chromium_version = None
    try:
        from importlib.resources import files

        manifest = json.loads(files("playwright").joinpath("driver/package/browsers.json").read_text(encoding="utf-8"))
        chromium = next(item for item in manifest["browsers"] if item["name"] == "chromium")
        chromium_revision = str(chromium["revision"])
        chromium_version = str(chromium.get("browserVersion") or "") or None
    except (ImportError, KeyError, OSError, StopIteration, TypeError, ValueError):
        pass
    browser_name = "Chromium"
    browser_version = chromium_version
    if configured_executable:
        executable = Path(configured_executable)
        installed = executable.is_file()
        browser_name = (
            "Chrome for Testing"
            if "runtime" in {part.casefold() for part in executable.parts}
            else "Google Chrome"
        )
        browser_version = _windows_file_version(executable) if os.name == "nt" else None
        if installed and not browser_version:
            with suppress(OSError, subprocess.SubprocessError):
                output = subprocess.run(
                    [str(executable), "--version"],
                    capture_output=True,
                    check=True,
                    text=True,
                    timeout=5,
                ).stdout.strip()
                browser_version = re.sub(r"^Google Chrome\s+", "", output) or None
    else:
        installed = bool(
            browser_root.name and chromium_revision
            and browser_root.joinpath(
                f"chromium-{chromium_revision}", "chrome-linux64", "chrome"
            ).is_file()
        )
    return {
        "installed": installed,
        "browser_name": browser_name,
        "browser_version": browser_version,
        "playwright_version": playwright_version,
        "persistent": bool(
            os.environ.get("AUTOSURF_BROWSER_PROFILE_DIR")
            or os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
        ),
        "session_mode": persistent_browser_mode(),
        "chromium_revision": chromium_revision,
        "chromium_version": chromium_version,
    }


def _windows_file_version(path: Path) -> str | None:
    if os.name != "nt" or not path.is_file():
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class FixedFileInfo(ctypes.Structure):
            _fields_ = [
                ("signature", wintypes.DWORD),
                ("struct_version", wintypes.DWORD),
                ("file_version_ms", wintypes.DWORD),
                ("file_version_ls", wintypes.DWORD),
                ("product_version_ms", wintypes.DWORD),
                ("product_version_ls", wintypes.DWORD),
                ("file_flags_mask", wintypes.DWORD),
                ("file_flags", wintypes.DWORD),
                ("file_os", wintypes.DWORD),
                ("file_type", wintypes.DWORD),
                ("file_subtype", wintypes.DWORD),
                ("file_date_ms", wintypes.DWORD),
                ("file_date_ls", wintypes.DWORD),
            ]

        version_api = ctypes.windll.version
        size = version_api.GetFileVersionInfoSizeW(str(path), None)
        if not size:
            return None
        buffer = ctypes.create_string_buffer(size)
        if not version_api.GetFileVersionInfoW(str(path), 0, size, buffer):
            return None
        pointer = ctypes.c_void_p()
        length = wintypes.UINT()
        if not version_api.VerQueryValueW(buffer, "\\", ctypes.byref(pointer), ctypes.byref(length)):
            return None
        info = ctypes.cast(pointer, ctypes.POINTER(FixedFileInfo)).contents
        values = (
            info.file_version_ms >> 16,
            info.file_version_ms & 0xFFFF,
            info.file_version_ls >> 16,
            info.file_version_ls & 0xFFFF,
        )
        return ".".join(str(value) for value in values)
    except (AttributeError, OSError, ValueError):
        return None


def _python_dependencies(repository: Path) -> dict[str, Any]:
    try:
        import tomllib

        try:
            from packaging.requirements import Requirement
        except ImportError:
            # pip vendors packaging, which keeps the checker usable while an old
            # installation is repairing a missing direct packaging dependency.
            from pip._vendor.packaging.requirements import Requirement

        project = tomllib.loads(repository.joinpath("pyproject.toml").read_text(encoding="utf-8"))
        declared = project.get("project", {}).get("dependencies", [])
        if not isinstance(declared, list):
            raise ValueError("project.dependencies must be a list")

        issues: list[dict[str, str | None]] = []
        checked = 0
        for value in declared:
            requirement = Requirement(str(value))
            if requirement.marker and not requirement.marker.evaluate():
                continue
            checked += 1
            required = str(requirement.specifier) or "任意版本"
            try:
                installed = version(requirement.name)
            except PackageNotFoundError:
                issues.append({
                    "name": requirement.name,
                    "required": required,
                    "installed": None,
                    "status": "missing",
                })
                continue
            if requirement.specifier and not requirement.specifier.contains(installed, prereleases=True):
                issues.append({
                    "name": requirement.name,
                    "required": required,
                    "installed": installed,
                    "status": "incompatible",
                })
        return {
            "checked": True,
            "satisfied": not issues,
            "total": checked,
            "issue_count": len(issues),
            "issues": issues,
            "error": None,
        }
    except (ImportError, OSError, TypeError, ValueError) as exc:
        return {
            "checked": False,
            "satisfied": False,
            "total": 0,
            "issue_count": 0,
            "issues": [],
            "error": f"依赖版本检查失败: {exc}",
        }


def _upgrade_status(request: Request) -> dict[str, Any]:
    repository = _program_repository()
    command = _upgrade_command()
    branch = os.environ.get("AUTOSURF_BRANCH", "main")
    local_revision = _program_revision(repository)
    running = _upgrade_running(request)
    remote_revision, check_error = (None, None) if running else _remote_revision(repository, branch)
    browser = _browser_runtime()
    python_dependencies = _python_dependencies(repository)
    environment_available = (
        command is not None or _upgrade_request_file() is not None
    ) and repository.joinpath(".git").is_dir()
    update_available = bool(local_revision and remote_revision and local_revision != remote_revision)
    dependency_repair_needed = python_dependencies["checked"] and not python_dependencies["satisfied"]
    last_upgrade = _settle_stale_upgrade(
        request, _last_upgrade(request), running=running,
        local_revision=local_revision, remote_revision=remote_revision,
        check_error=check_error, browser=browser, dependencies=python_dependencies,
    )
    return {
        "available": environment_available,
        "can_upgrade": environment_available and check_error is None and (
            update_available or dependency_repair_needed
        ),
        "running": running,
        "revision": local_revision,
        "local_revision": local_revision,
        "remote_revision": remote_revision,
        "update_available": update_available,
        "version_check_error": check_error,
        "branch": branch,
        "browser": browser,
        "python_dependencies": python_dependencies,
        "last_upgrade": last_upgrade,
    }


@router.get("/system/upgrade")
def upgrade_status(request: Request) -> dict[str, Any]:
    return _upgrade_status(request)




@router.get("/system/access")
def system_access_settings(request: Request) -> dict[str, bool]:
    return {"lan_only": request.app.state.lan_access.lan_only}


@router.patch("/system/access")
def update_system_access_settings(
    data: SystemAccessSettingsInput, request: Request,
) -> dict[str, bool]:
    return {"lan_only": request.app.state.lan_access.set_lan_only(data.lan_only)}


@router.post("/system/upgrade", status_code=202)
def start_upgrade(request: Request) -> dict[str, Any]:
    repository = _program_repository()
    command = _upgrade_command()
    request_file = _upgrade_request_file()
    with request.app.state.upgrade_guard:
        if (command is None and request_file is None) or not repository.joinpath(".git").is_dir():
            raise HTTPException(status_code=409, detail="当前运行环境不支持网页升级")
        if _upgrade_running(request):
            raise HTTPException(status_code=409, detail="升级正在进行")
        current = _upgrade_status(request)
        if current["version_check_error"]:
            raise HTTPException(status_code=503, detail=current["version_check_error"])
        if not current["can_upgrade"]:
            raise HTTPException(status_code=409, detail="当前已是最新版本")

        if request_file is not None:
            request_file.parent.mkdir(parents=True, exist_ok=True)
            request_file.write_text(
                json.dumps({"requested_at": utc_now().strftime("%Y-%m-%dT%H:%M:%SZ")}) + "\n",
                encoding="utf-8",
            )
            return {**current, "running": True, "accepted": True}

        if os.name != "nt":
            command = ["/bin/sh", "-c", 'sleep 1; exec "$@"', "autosurf-upgrade", *command]
        request.app.state.upgrade_process = subprocess.Popen(
            command,
            cwd=repository,
            stdin=subprocess.DEVNULL,
            close_fds=True,
            start_new_session=os.name != "nt",
        )
    return {**current, "running": True, "accepted": True}




@router.get("/site-settings/backup")
def backup_site_settings(request: Request) -> Response:
    with request.app.state.sessions() as session:
        automations = session.scalars(
            select(AutomationRecord).order_by(AutomationRecord.name, AutomationRecord.id)
        ).all()
        payload = {
            "schema_version": 2,
            "exported_at": utc_now().isoformat(),
            "automations": [{
                "id": item.id,
                "name": item.name,
                "handler_type": item.handler_type,
                "enabled": item.enabled,
                "interval_seconds": item.interval_seconds,
                "next_run_at": item.next_run_at.isoformat(),
                "config": json.loads(item.config_json),
            } for item in automations],
        }

    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "site-settings.json",
            json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
        )
        archive.writestr(
            "README.txt",
            "AutoSurf site settings backup\n"
            "Contains automation definitions but no browser profile or login data.\n"
            "Restore this ZIP only through AutoSurf's Site Settings page.\n",
        )
    filename = f"autosurf-site-settings-{utc_now():%Y%m%d-%H%M%S}.zip"
    return Response(
        archive_buffer.getvalue(),
        media_type="application/zip",
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.post("/site-settings/restore")
async def restore_site_settings(request: Request) -> dict[str, Any]:
    raw = await request.body()
    if not raw or len(raw) > 10 * 1024 * 1024:
        raise HTTPException(status_code=422, detail="请选择不超过 10 MB 的 AutoSurf 站点设置 ZIP")
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            if "site-settings.json" not in archive.namelist():
                raise ValueError("ZIP 中缺少 site-settings.json")
            if archive.getinfo("site-settings.json").file_size > 20 * 1024 * 1024:
                raise ValueError("站点设置文件过大")
            payload = json.loads(archive.read("site-settings.json"))
        automations = _validated_site_settings_backup(payload, request.app.state.registry)
    except (ValueError, KeyError, TypeError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
        raise HTTPException(status_code=422, detail=f"无法恢复站点设置：{exc}") from exc

    with request.app.state.sessions.begin() as session:
        session.execute(delete(ExecutionRecord))
        session.execute(delete(AutomationRecord))
        for item in automations:
            session.add(AutomationRecord(
                id=item["id"],
                name=item["name"],
                handler_type=item["handler_type"],
                enabled=item["enabled"],
                interval_seconds=item["interval_seconds"],
                next_run_at=item["next_run_at"],
                config_json=json.dumps(item["config"], ensure_ascii=False),
            ))

    return {
        "restored": True,
        "automation_count": len(automations),
    }


def _validated_site_settings_backup(
    payload: Any, registry: Any,
) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or payload.get("schema_version") != 2:
        raise ValueError("不支持的备份版本")
    automations = payload.get("automations")
    if not isinstance(automations, list):
        raise ValueError("备份数据结构不完整")

    automation_ids: set[str] = set()
    checked_automations = []
    for raw_item in automations:
        if not isinstance(raw_item, dict):
            raise ValueError("周期任务数据无效")
        handler_type = str(raw_item.get("handler_type") or "")
        registry.get(handler_type)
        interval_seconds = int(raw_item.get("interval_seconds") or 0)
        config = raw_item.get("config")
        item = {
            "id": str(raw_item.get("id") or ""),
            "name": str(raw_item.get("name") or ""),
            "handler_type": handler_type,
            "enabled": bool(raw_item.get("enabled", True)),
            "interval_seconds": interval_seconds,
            "next_run_at": _backup_datetime(raw_item.get("next_run_at")),
            "config": config,
        }
        if not item["id"] or len(item["id"]) > 36 or item["id"] in automation_ids:
            raise ValueError("周期任务标识无效或重复")
        if not item["name"] or len(item["name"]) > 128:
            raise ValueError("周期任务名称无效")
        if interval_seconds < 60 or interval_seconds > 31_536_000 or not isinstance(config, dict):
            raise ValueError("周期任务配置无效")
        automation_ids.add(item["id"])
        checked_automations.append(item)
    return checked_automations


def _backup_datetime(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("备份时间无效")
    try:
        return datetime.fromisoformat(value.removesuffix("Z"))
    except ValueError as exc:
        raise ValueError("备份时间无效") from exc


@router.get("/handlers")
def handlers(request: Request) -> dict[str, list[str]]:
    return {"items": request.app.state.registry.types()}


@router.post("/automations", status_code=201)
def create_automation(data: AutomationInput, request: Request) -> dict[str, Any]:
    try:
        record = request.app.state.automations.create(data.name, data.handler_type, data.interval_seconds,
                                                      data.config)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return automation_view(record)


@router.get("/automations")
def list_automations(request: Request) -> dict[str, Any]:
    with request.app.state.sessions() as session:
        records = session.scalars(select(AutomationRecord).order_by(AutomationRecord.name)).all()
        return {"items": [automation_view(item) for item in records]}


@router.post("/automations/{automation_id}/run", status_code=202)
def run_automation(automation_id: str, request: Request) -> dict[str, str]:
    try:
        execution = request.app.state.queue.enqueue_now(automation_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"execution_id": execution.id, "status": execution.status}


@router.get("/executions")
def list_executions(request: Request, limit: int = 50) -> dict[str, Any]:
    limit = min(max(limit, 1), 200)
    with request.app.state.sessions() as session:
        records = session.scalars(select(ExecutionRecord).order_by(ExecutionRecord.scheduled_at.desc()).limit(limit)).all()
        return {"items": [execution_view(item) for item in records]}


@router.get("/debug/executions")
def list_debug_executions(
    request: Request,
    limit: int = Query(default=100, ge=1, le=200),
    automation_id: str | None = Query(default=None, max_length=36),
    execution_status: str | None = Query(default=None, alias="status", max_length=24),
    outcome: str | None = Query(default=None, max_length=24),
) -> dict[str, Any]:
    valid_statuses = {item.value for item in ExecutionStatus}
    valid_outcomes = {item.value for item in RunOutcome}
    if execution_status and execution_status not in valid_statuses:
        raise HTTPException(status_code=422, detail="执行状态筛选值无效")
    if outcome and outcome not in valid_outcomes:
        raise HTTPException(status_code=422, detail="执行结果筛选值无效")

    with request.app.state.sessions() as session:
        query = select(ExecutionRecord).join(AutomationRecord)
        if automation_id:
            query = query.where(ExecutionRecord.automation_id == automation_id)
        if execution_status:
            query = query.where(ExecutionRecord.status == execution_status)
        records = session.scalars(query.order_by(
            ExecutionRecord.scheduled_at.desc(), ExecutionRecord.id.desc(),
        ).limit(1000 if outcome else limit)).all()
        views = [
            _debug_execution_view(record, request.app.state.settings.data_dir)
            for record in records
        ]
        if outcome:
            views = [item for item in views if item["outcome"] == outcome]
        views = views[:limit]

        automations = session.scalars(select(AutomationRecord).order_by(
            AutomationRecord.name, AutomationRecord.id,
        )).all()
        return {
            "items": views,
            "automations": [{
                "id": item.id,
                "name": item.name,
                "handler_type": item.handler_type,
            } for item in automations],
        }


@router.get("/debug/executions/{execution_id}/artifact")
def debug_execution_artifact(execution_id: str, request: Request) -> Response:
    with request.app.state.sessions() as session:
        if session.get(ExecutionRecord, execution_id) is None:
            raise HTTPException(status_code=404, detail="执行记录不存在")
    artifact_dir = request.app.state.settings.data_dir.joinpath("browser-artifacts").resolve()
    artifact = artifact_dir.joinpath(f"{execution_id}.png").resolve()
    if artifact.parent != artifact_dir or not artifact.is_file():
        raise HTTPException(status_code=404, detail="执行截图不存在")
    return FileResponse(
        artifact,
        media_type="image/png",
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
    )


@router.patch("/signin/schedule")
def align_signin_schedule(request: Request) -> dict[str, Any]:
    updated, next_run_at = align_all_signin_schedules(request.app.state.sessions)
    return {
        "updated": updated,
        "interval_hours": 24,
        "daily_start_time": SIGNIN_START_TIME,
        "next_run_at": next_run_at,
    }


@router.post("/periodic-signin/sites", status_code=201)
def create_periodic_signin_site(data: PeriodicSignInInput, request: Request) -> dict[str, Any]:
    handler_type = data.handler_type.strip().lower()
    if handler_type not in {"browser_signin", "http_signin"}:
        raise HTTPException(status_code=422, detail="普通周期任务仅支持浏览器或 HTTP 执行")
    method = data.method.strip().upper()
    if method not in {"GET", "POST"}:
        raise HTTPException(status_code=422, detail="HTTP 方法仅支持 GET 或 POST")
    _validate_site_url(data.url)
    template = next(
        (item for item in PERIODIC_SITE_TEMPLATES if item.key == data.template_key), None,
    )
    if template is not None and (
        (urlparse(data.url).hostname or "").lower() not in template.domains
    ):
        raise HTTPException(
            status_code=422, detail=f"{template.name} 模板必须使用对应站点地址",
        )
    if bool(data.click_role) != bool(data.click_name):
        raise HTTPException(status_code=422, detail="按按钮文字点击时必须同时填写角色和名称")

    config = {
        "handler_type": handler_type,
        "template_key": data.template_key or None,
        "url": data.url,
        "timeout_seconds": data.timeout_seconds,
        "random_delay_minutes": data.random_delay_minutes,
        "retry_interval_minutes": data.retry_interval_hours * 60,
        "max_retries": data.max_retries,
        "method": method,
        "wait_for_selector": data.wait_for_selector or None,
        "click_selector": data.click_selector or None,
        "click_role": data.click_role or None,
        "click_name": data.click_name or None,
        "click_exact": data.click_exact,
        "wait_after_click_ms": data.wait_after_click_ms,
        "success_patterns": data.success_patterns,
        "already_patterns": data.already_patterns,
        "auth_expired_patterns": data.auth_expired_patterns,
        "daily_start_time": SIGNIN_START_TIME,
    }
    handler_type, config = apply_periodic_template(config, handler_type)
    try:
        record = request.app.state.automations.create(
            data.name, handler_type, data.interval_hours * 3600, config,
            next_run_at=next_signin_run_at(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    with request.app.state.sessions() as session:
        return _periodic_signin_site_view(session.get(AutomationRecord, record.id), None)


@router.get("/periodic-signin/sites")
def list_periodic_signin_sites(request: Request) -> dict[str, Any]:
    with request.app.state.sessions() as session:
        records = session.scalars(select(AutomationRecord).where(
            AutomationRecord.handler_type.in_(["browser_signin", "http_signin"])
        ).order_by(AutomationRecord.name)).all()
        ids = [record.id for record in records]
        latest: dict[str, ExecutionRecord] = {}
        if ids:
            executions = session.scalars(select(ExecutionRecord).where(
                ExecutionRecord.automation_id.in_(ids)
            ).order_by(ExecutionRecord.scheduled_at.desc(), ExecutionRecord.id.desc())).all()
            for execution in executions:
                latest.setdefault(execution.automation_id, execution)
        return {
            "items": [
                _periodic_signin_site_view(record, latest.get(record.id)) for record in records
            ]
        }


@router.get("/periodic-signin/candidates")
def list_periodic_signin_candidates(request: Request) -> dict[str, Any]:
    return {"items": _periodic_signin_candidates(request)}


@router.post("/periodic-signin/sites/collect", status_code=201)
def collect_periodic_signin_sites(
    data: PeriodicSignInCollectInput, request: Request,
) -> dict[str, Any]:
    site_keys = list(dict.fromkeys(data.site_keys))
    candidate_items = _periodic_signin_candidates(request)
    candidates = {item["site_key"]: item for item in candidate_items}
    selected = [candidates.get(site_key) for site_key in site_keys]
    if any(item is None for item in selected):
        raise HTTPException(status_code=422, detail="所选项目中包含未知周期站点")

    requested: list[dict[str, Any]] = []
    selected_keys: set[str] = set()
    for item in selected:
        assert item is not None
        if item["template_key"] in selected_keys:
            continue
        selected_keys.add(item["template_key"])
        requested.append(item)

    created_ids: list[str] = []
    skipped: list[dict[str, Any]] = []
    for candidate in requested:
        if candidate["configured"]:
            skipped.append(candidate)
            continue
        config = {
            "handler_type": candidate["handler_type"],
            "template_key": candidate["template_key"],
            "url": candidate["url"],
            "timeout_seconds": data.timeout_seconds,
            "random_delay_minutes": data.random_delay_minutes,
            "retry_interval_minutes": data.retry_interval_hours * 60,
            "max_retries": data.max_retries,
            "daily_start_time": SIGNIN_START_TIME,
        }
        handler_type, config = apply_periodic_template(config, candidate["handler_type"])
        try:
            record = request.app.state.automations.create(
                candidate["name"], handler_type, data.interval_hours * 3600, config,
                next_run_at=next_signin_run_at(),
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        created_ids.append(record.id)

    with request.app.state.sessions() as session:
        records = session.scalars(select(AutomationRecord).where(
            AutomationRecord.id.in_(created_ids)
        ).order_by(AutomationRecord.name)).all() if created_ids else []
        return {
            "created": [_periodic_signin_site_view(record, None) for record in records],
            "skipped": [{
                "site_key": item["site_key"],
                "automation_id": item["automation_id"],
                "reason": "already_configured",
            } for item in skipped],
        }


@router.patch("/periodic-signin/sites/{automation_id}/schedule")
def set_periodic_signin_schedule(
    automation_id: str, data: PeriodicSignInScheduleInput, request: Request,
) -> dict[str, Any]:
    with request.app.state.sessions.begin() as session:
        record = _require_periodic_automation(session.get(AutomationRecord, automation_id))
        config = json.loads(record.config_json)
        config.update({
            "timeout_seconds": data.timeout_seconds,
            "random_delay_minutes": data.random_delay_minutes,
            "retry_interval_minutes": data.retry_interval_hours * 60,
            "max_retries": data.max_retries,
            "daily_start_time": SIGNIN_START_TIME,
        })
        record.interval_seconds = data.interval_hours * 3600
        record.next_run_at = next_signin_run_at()
        record.config_json = json.dumps(config, ensure_ascii=False)
        session.flush()
        return _periodic_signin_site_view(record, None)


@router.patch("/periodic-signin/sites/{automation_id}/enabled")
def set_periodic_signin_site_enabled(
    automation_id: str, data: PtSignInEnabledInput, request: Request,
) -> dict[str, Any]:
    with request.app.state.sessions.begin() as session:
        record = _require_periodic_automation(session.get(AutomationRecord, automation_id))
        record.enabled = data.enabled
        if data.enabled:
            record.next_run_at = next_signin_run_at()
        session.flush()
        return _periodic_signin_site_view(record, None)


@router.delete("/periodic-signin/sites/{automation_id}", status_code=204)
def delete_periodic_signin_site(automation_id: str, request: Request) -> None:
    with request.app.state.sessions.begin() as session:
        record = _require_periodic_automation(session.get(AutomationRecord, automation_id))
        session.execute(delete(ExecutionRecord).where(ExecutionRecord.automation_id == automation_id))
        session.delete(record)


@router.post("/periodic-signin/sites/{automation_id}/run", status_code=202)
def run_periodic_signin_site(automation_id: str, request: Request) -> dict[str, str]:
    with request.app.state.sessions() as session:
        _require_periodic_automation(session.get(AutomationRecord, automation_id))
    execution = request.app.state.queue.enqueue_now(automation_id)
    return {"execution_id": execution.id, "status": execution.status}


@router.post("/periodic-signin/run-all", status_code=202)
def run_all_periodic_tasks(request: Request) -> dict[str, Any]:
    with request.app.state.sessions() as session:
        records = session.scalars(select(AutomationRecord).where(
            AutomationRecord.handler_type.in_(["browser_signin", "http_signin"])
        ).order_by(AutomationRecord.name)).all()
        eligible = [(record.id, record.name) for record in records if record.enabled]
        skipped = [
            {"automation_id": record.id, "name": record.name, "reason": "disabled"}
            for record in records if not record.enabled
        ]
    return _enqueue_automation_batch(request, eligible, skipped=skipped)


@router.get("/periodic-signin/executions")
def list_periodic_signin_executions(request: Request, limit: int = 50) -> dict[str, Any]:
    limit = min(max(limit, 1), 200)
    with request.app.state.sessions() as session:
        records = session.scalars(select(ExecutionRecord).join(AutomationRecord).where(
            AutomationRecord.handler_type.in_(["browser_signin", "http_signin"])
        ).order_by(ExecutionRecord.scheduled_at.desc()).limit(limit)).all()
        return {"items": [_periodic_execution_view(item) for item in records]}


@router.post("/pt-signin/sites", status_code=201)
def create_pt_signin_site(data: PtSignInInput, request: Request) -> dict[str, Any]:
    _validate_pt_url(data.url)
    hostname = (urlparse(data.url).hostname or "").lower()
    discovery = discover_pt_site(hostname, set())
    sign_in_supported = discovery.sign_in_supported if discovery else True
    profile_refresh_supported = discovery.profile_refresh_supported if discovery else True
    config = {
        "url": data.url,
        "site_domain": discovery.site_key if discovery else hostname,
        "timeout_seconds": data.timeout_seconds,
        "random_delay_minutes": data.random_delay_minutes,
        "retry_interval_minutes": data.retry_interval_hours * 60,
        "max_retries": data.max_retries,
        "click_selector": data.click_selector or None,
        "success_patterns": data.success_patterns,
        "already_patterns": data.already_patterns,
        "sign_in_enabled": data.sign_in_enabled and sign_in_supported,
        "profile_refresh_enabled": (
            data.profile_refresh_enabled
            or bool(discovery and discovery.default_profile_refresh_enabled)
        ) and profile_refresh_supported,
        "sign_in_supported": sign_in_supported,
        "profile_refresh_supported": profile_refresh_supported,
        "profile_refresh_default_version": PT_PROFILE_REFRESH_DEFAULT_VERSION,
        "discovery_strategy": discovery.strategy if discovery else None,
        "profile_url": discovery.profile_url if discovery else None,
        "daily_start_time": SIGNIN_START_TIME,
    }
    try:
        record = request.app.state.automations.create(
            data.name, "pt_signin", data.interval_hours * 3600, config,
            next_run_at=next_signin_run_at(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    with request.app.state.sessions() as session:
        return _pt_signin_site_view(session.get(AutomationRecord, record.id), None)


@router.get("/pt-signin/sites")
def list_pt_signin_sites(request: Request) -> dict[str, Any]:
    with request.app.state.sessions() as session:
        records = session.scalars(select(AutomationRecord).where(
            AutomationRecord.handler_type == "pt_signin"
        ).order_by(AutomationRecord.name)).all()
        ids = [record.id for record in records]
        latest: dict[str, ExecutionRecord] = {}
        if ids:
            executions = session.scalars(select(ExecutionRecord).where(
                ExecutionRecord.automation_id.in_(ids)
            ).order_by(ExecutionRecord.scheduled_at.desc())).all()
            for execution in executions:
                latest.setdefault(execution.automation_id, execution)
        return {"items": [_pt_signin_site_view(record, latest.get(record.id)) for record in records]}


@router.get("/pt-signin/candidates")
def list_pt_signin_candidates(request: Request, include_unknown: bool = True) -> dict[str, Any]:
    return {"items": _pt_signin_candidates(request, include_unknown)}


@router.post("/pt-signin/sites/collect", status_code=201)
def collect_pt_signin_sites(data: PtSignInCollectInput, request: Request) -> dict[str, Any]:
    site_keys = list(dict.fromkeys(data.site_keys))
    candidate_items = _pt_signin_candidates(request, True)
    candidates = {item["site_key"]: item for item in candidate_items}
    selected = [candidates.get(site_key) for site_key in site_keys]
    if any(item is None or not item["recognized"] for item in selected):
        raise HTTPException(status_code=422, detail="所选项目中包含未识别的 PT 站点")
    requested = []
    selected_site_keys: set[str] = set()
    for item in selected:
        if item["site_key"] in selected_site_keys:
            continue
        selected_site_keys.add(item["site_key"])
        requested.append(item)
    unsupported = [item["name"] for item in requested if not item["supported"]]
    if unsupported:
        raise HTTPException(status_code=422, detail=f"以下站点尚需专用适配：{'、'.join(unsupported)}")

    created_ids: list[str] = []
    skipped: list[dict[str, Any]] = []
    for candidate in requested:
        if candidate["configured"]:
            skipped.append(candidate)
            continue
        config = {
            "url": candidate["url"],
            "site_domain": candidate["site_key"],
            "timeout_seconds": data.timeout_seconds,
            "random_delay_minutes": data.random_delay_minutes,
            "retry_interval_minutes": data.retry_interval_hours * 60,
            "max_retries": data.max_retries,
            "click_selector": None,
            "success_patterns": [],
            "already_patterns": [],
            "sign_in_enabled": data.sign_in_enabled and candidate["sign_in_supported"],
            "profile_refresh_enabled": (
                data.profile_refresh_enabled or candidate["default_profile_refresh_enabled"]
            ) and candidate["profile_refresh_supported"],
            "sign_in_supported": candidate["sign_in_supported"],
            "profile_refresh_supported": candidate["profile_refresh_supported"],
            "profile_refresh_default_version": PT_PROFILE_REFRESH_DEFAULT_VERSION,
            "discovery_strategy": candidate["strategy"],
            "profile_url": candidate["profile_url"],
            "discovered": True,
            "discovery_reason": candidate["reason"],
            "daily_start_time": SIGNIN_START_TIME,
        }
        try:
            record = request.app.state.automations.create(
                candidate["name"], "pt_signin", data.interval_hours * 3600, config,
                next_run_at=next_signin_run_at(),
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        created_ids.append(record.id)

    with request.app.state.sessions() as session:
        records = session.scalars(select(AutomationRecord).where(
            AutomationRecord.id.in_(created_ids)
        ).order_by(AutomationRecord.name)).all() if created_ids else []
        return {
            "created": [_pt_signin_site_view(record, None) for record in records],
            "skipped": [{
                "site_key": item["site_key"],
                "automation_id": item["automation_id"],
                "reason": "already_configured",
            } for item in skipped],
        }


@router.patch("/pt-signin/sites/{automation_id}/schedule")
def set_pt_signin_schedule(automation_id: str, data: PtSignInScheduleInput,
                           request: Request) -> dict[str, Any]:
    with request.app.state.sessions.begin() as session:
        record = _require_pt_automation(session.get(AutomationRecord, automation_id))
        config = json.loads(record.config_json)
        config.update({
            "timeout_seconds": data.timeout_seconds,
            "random_delay_minutes": data.random_delay_minutes,
            "retry_interval_minutes": data.retry_interval_hours * 60,
            "max_retries": data.max_retries,
            "daily_start_time": SIGNIN_START_TIME,
        })
        record.interval_seconds = data.interval_hours * 3600
        record.next_run_at = next_signin_run_at()
        record.config_json = json.dumps(config, ensure_ascii=False)
        session.flush()
        return _pt_signin_site_view(record, None)


@router.patch("/pt-signin/sites/{automation_id}/enabled")
def set_pt_signin_site_enabled(automation_id: str, data: PtSignInEnabledInput,
                               request: Request) -> dict[str, Any]:
    with request.app.state.sessions.begin() as session:
        record = session.get(AutomationRecord, automation_id)
        _require_pt_automation(record)
        record.enabled = data.enabled
        if data.enabled:
            record.next_run_at = next_signin_run_at()
        session.flush()
        return _pt_signin_site_view(record, None)


@router.patch("/pt-signin/sites/{automation_id}/actions")
def set_pt_site_actions(automation_id: str, data: PtSiteActionsInput,
                        request: Request) -> dict[str, Any]:
    with request.app.state.sessions.begin() as session:
        record = _require_pt_automation(session.get(AutomationRecord, automation_id))
        config = json.loads(record.config_json)
        sign_in_supported, profile_refresh_supported = _pt_site_capabilities(record, config)
        if data.sign_in_enabled and not sign_in_supported:
            raise HTTPException(status_code=422, detail="该站点没有签到功能，仅支持刷新个人信息")
        if data.profile_refresh_enabled and not profile_refresh_supported:
            raise HTTPException(status_code=422, detail="该站点不支持刷新个人信息")
        was_enabled = record.enabled
        config.update({
            "sign_in_enabled": data.sign_in_enabled,
            "profile_refresh_enabled": data.profile_refresh_enabled,
            "sign_in_supported": sign_in_supported,
            "profile_refresh_supported": profile_refresh_supported,
        })
        record.config_json = json.dumps(config, ensure_ascii=False)
        record.enabled = data.sign_in_enabled or data.profile_refresh_enabled
        if record.enabled and not was_enabled:
            record.next_run_at = next_signin_run_at()
        session.flush()
        return _pt_signin_site_view(record, None)


@router.delete("/pt-signin/sites/{automation_id}", status_code=204)
def delete_pt_signin_site(automation_id: str, request: Request) -> None:
    with request.app.state.sessions.begin() as session:
        record = session.get(AutomationRecord, automation_id)
        _require_pt_automation(record)
        session.execute(delete(ExecutionRecord).where(ExecutionRecord.automation_id == automation_id))
        session.delete(record)


@router.post("/pt-signin/sites/{automation_id}/run", status_code=202)
def run_pt_signin_site(automation_id: str, request: Request) -> dict[str, str]:
    with request.app.state.sessions() as session:
        _require_pt_automation(session.get(AutomationRecord, automation_id))
    execution = request.app.state.queue.enqueue_now(automation_id)
    return {"execution_id": execution.id, "status": execution.status}


@router.post("/pt-signin/run-all", status_code=202)
def run_all_pt_actions(data: PtBatchRunInput, request: Request) -> dict[str, Any]:
    eligible: list[tuple[str, str]] = []
    skipped: list[dict[str, str]] = []
    with request.app.state.sessions() as session:
        records = session.scalars(select(AutomationRecord).where(
            AutomationRecord.handler_type == "pt_signin"
        ).order_by(AutomationRecord.name)).all()
        for record in records:
            try:
                config = json.loads(record.config_json)
            except (TypeError, ValueError):
                skipped.append({
                    "automation_id": record.id, "name": record.name, "reason": "invalid_config",
                })
                continue
            sign_in_supported, profile_refresh_supported = _pt_site_capabilities(record, config)
            if data.action == "sign_in":
                action_enabled = bool(config.get("sign_in_enabled", True)) and sign_in_supported
            else:
                action_enabled = (
                    bool(config.get("profile_refresh_enabled", False))
                    and profile_refresh_supported
                )
            if record.enabled and action_enabled:
                eligible.append((record.id, record.name))
            else:
                skipped.append({
                    "automation_id": record.id,
                    "name": record.name,
                    "reason": "disabled" if not record.enabled else "action_disabled",
                })

    config_override = {
        "sign_in_enabled": data.action == "sign_in",
        "profile_refresh_enabled": data.action == "profile_refresh",
    }
    return _enqueue_automation_batch(
        request, eligible, config_override=config_override, skipped=skipped,
        action=data.action,
    )


@router.get("/pt-signin/executions")
def list_pt_signin_executions(request: Request, limit: int = 50) -> dict[str, Any]:
    limit = min(max(limit, 1), 200)
    with request.app.state.sessions() as session:
        records = session.scalars(select(ExecutionRecord).join(AutomationRecord).where(
            AutomationRecord.handler_type == "pt_signin"
        ).order_by(ExecutionRecord.scheduled_at.desc()).limit(limit)).all()
        return {"items": [_pt_execution_view(item) for item in records]}


@router.get("/pt-signin/stats")
def list_pt_site_stats(request: Request) -> dict[str, Any]:
    with request.app.state.sessions() as session:
        sites = session.scalars(select(AutomationRecord).where(
            AutomationRecord.handler_type == "pt_signin"
        ).order_by(AutomationRecord.name)).all()
        site_ids = [site.id for site in sites]
        executions = session.scalars(select(ExecutionRecord).where(
            ExecutionRecord.automation_id.in_(site_ids),
            ExecutionRecord.result_json.is_not(None),
        ).order_by(ExecutionRecord.finished_at.desc(), ExecutionRecord.scheduled_at.desc())).all() \
            if site_ids else []
        latest: dict[str, tuple[dict[str, str], datetime]] = {}
        latest_refresh: dict[str, tuple[str | None, str | None, datetime]] = {}
        for execution in executions:
            timestamp = execution.finished_at or execution.scheduled_at
            if execution.automation_id not in latest_refresh:
                refresh = _profile_refresh_status_from_result(execution.result_json)
                if refresh is not None:
                    latest_refresh[execution.automation_id] = (*refresh, timestamp)
            if execution.automation_id not in latest:
                stats = _profile_stats_from_result(execution.result_json)
                if stats:
                    latest[execution.automation_id] = (stats, timestamp)

        items = []
        for site in sites:
            config = json.loads(site.config_json)
            snapshot = latest.get(site.id)
            if not config.get("profile_refresh_enabled", False) and snapshot is None:
                continue
            stats, updated_at = snapshot if snapshot else ({}, None)
            refresh_outcome, refresh_message, refresh_updated_at = latest_refresh.get(
                site.id, (None, None, None),
            )
            items.append({
                "automation_id": site.id,
                "name": site.name,
                "domain": str(config.get("site_domain") or "") or None,
                "profile_refresh_enabled": bool(config.get("profile_refresh_enabled", False)),
                "updated_at": updated_at,
                "stats": stats,
                "refresh_outcome": refresh_outcome,
                "refresh_message": refresh_message,
                "refresh_updated_at": refresh_updated_at,
            })
        return {"items": items}


@router.get("/pt-signin/history")
def pt_signin_history(
    request: Request,
    days: int = Query(default=7, ge=1, le=31),
    timezone_offset: int = Query(default=0, ge=-840, le=840),
) -> dict[str, Any]:
    offset = timedelta(minutes=timezone_offset)
    local_today = (utc_now() + offset).date()
    date_values = [local_today - timedelta(days=index) for index in range(days)]
    window_start = datetime.combine(date_values[-1], datetime.min.time()) - offset

    with request.app.state.sessions() as session:
        sites = session.scalars(select(AutomationRecord).where(
            AutomationRecord.handler_type == "pt_signin"
        ).order_by(AutomationRecord.name)).all()
        site_ids = [site.id for site in sites]
        executions = session.scalars(select(ExecutionRecord).where(
            ExecutionRecord.automation_id.in_(site_ids),
            ExecutionRecord.scheduled_at >= window_start,
        ).order_by(ExecutionRecord.scheduled_at.desc(), ExecutionRecord.id.desc())).all() if site_ids else []
        date_keys = {value.isoformat() for value in date_values}
        history_actions: dict[str, str | None] = {}
        for site in sites:
            config = json.loads(site.config_json)
            sign_in_supported, profile_refresh_supported = _pt_site_capabilities(site, config)
            sign_in_enabled = sign_in_supported and bool(config.get("sign_in_enabled", True))
            profile_refresh_enabled = profile_refresh_supported and bool(
                config.get("profile_refresh_enabled", False)
            )
            history_actions[site.id] = (
                "sign_in" if sign_in_enabled
                else "profile_refresh" if profile_refresh_enabled
                else None
            )
        enabled_site_ids = [site_id for site_id, action in history_actions.items() if action]
        latest = session.scalar(select(ExecutionRecord).where(
            ExecutionRecord.automation_id.in_(enabled_site_ids)
        ).order_by(
            ExecutionRecord.scheduled_at.desc(), ExecutionRecord.id.desc()
        ).limit(1)) if enabled_site_ids else None
        daily: dict[str, dict[str, dict[str, Any]]] = {site.id: {} for site in sites}
        site_history: dict[str, dict[str, dict[str, str]]] = {site.id: {} for site in sites}
        record_counts = {site.id: 0 for site in sites}
        for execution in executions:
            action = history_actions.get(execution.automation_id)
            if action is None:
                continue
            day = (execution.scheduled_at + offset).date().isoformat()
            if day not in date_keys:
                continue
            view = _pt_history_execution_view(execution, action)
            if view is None:
                continue
            record_counts[execution.automation_id] += 1
            daily[execution.automation_id].setdefault(day, view)
            if action != "sign_in" or not execution.result_json:
                continue
            with suppress(ValueError, TypeError):
                result = json.loads(execution.result_json)
                if not isinstance(result, dict):
                    continue
                details = result.get("details")
                if not isinstance(details, dict):
                    continue
                reported = details.get("site_history")
                if not isinstance(reported, list):
                    continue
                for item in reported:
                    if not isinstance(item, dict):
                        continue
                    reported_day = str(item.get("date") or "")
                    if reported_day not in date_keys:
                        continue
                    site_history[execution.automation_id].setdefault(reported_day, {
                        "date": reported_day,
                        "reward": str(item.get("reward") or "")[:100],
                    })

        return {
            "today": local_today.isoformat(),
            "days": [{
                "date": value.isoformat(),
                "label": f"{value.month}/{value.day}",
                "is_today": value == local_today,
            } for value in date_values],
            "items": [{
                "automation_id": site.id,
                "name": site.name,
                "domain": str(json.loads(site.config_json).get("site_domain") or "") or None,
                "url": json.loads(site.config_json).get("url"),
                "enabled": site.enabled,
                "history_action": history_actions[site.id],
                "record_count": record_counts[site.id],
                "executions": daily[site.id],
                "site_history": site_history[site.id],
            } for site in sites],
            "latest_execution": _pt_execution_view(latest) if latest else None,
        }


def _validate_site_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise HTTPException(status_code=422, detail="签到地址必须是有效的 HTTP(S) URL")


def _validate_pt_url(url: str) -> None:
    _validate_site_url(url)


def _periodic_signin_candidates(request: Request) -> list[dict[str, Any]]:
    with request.app.state.sessions() as session:
        automations = session.scalars(select(AutomationRecord).where(
            AutomationRecord.handler_type.in_(["browser_signin", "http_signin"])
        )).all()
        configured: dict[str, str] = {}
        for automation in automations:
            with suppress(TypeError, ValueError):
                template_key = str(json.loads(automation.config_json).get("template_key") or "")
                if template_key:
                    configured.setdefault(template_key, automation.id)

        items: list[dict[str, Any]] = []
        for template in PERIODIC_SITE_TEMPLATES:
            handler_type, config = apply_periodic_template({"template_key": template.key})
            items.append({
                "template_key": template.key,
                "site_key": template.key,
                "name": template.name,
                "url": config["url"],
                "site_url": config["url"],
                "handler_type": handler_type,
                "reason": "site_template",
                "supported": True,
                "configured": template.key in configured,
                "automation_id": configured.get(template.key),
            })
    return sorted(items, key=lambda item: item["name"].casefold())


def _pt_signin_candidates(request: Request, include_unknown: bool) -> list[dict[str, Any]]:
    del include_unknown
    with request.app.state.sessions() as session:
        automations = session.scalars(select(AutomationRecord).where(
            AutomationRecord.handler_type == "pt_signin"
        ).order_by(AutomationRecord.name)).all()
        configured: dict[str, str] = {}
        for record in automations:
            with suppress(TypeError, ValueError):
                config = json.loads(record.config_json)
                site_key = str(config.get("site_domain") or "").lower()
                if not site_key:
                    site_key = (urlparse(str(config.get("url") or "")).hostname or "").lower()
                if site_key:
                    configured.setdefault(site_key, record.id)

        items: list[dict[str, Any]] = []
        for definition in PT_SITE_CATALOG:
            if is_ignored_pt_domain(definition.domain):
                continue
            discovery = discover_pt_site(definition.domain, set())
            if discovery is None:
                continue
            automation_id = configured.get(discovery.site_key)
            items.append({
                "site_key": discovery.site_key,
                "domain": discovery.site_key,
                "name": discovery.name,
                "url": discovery.url,
                "recognized": True,
                "reason": discovery.reason,
                "strategy": discovery.strategy,
                "profile_url": discovery.profile_url,
                "supported": discovery.supported,
                "sign_in_supported": discovery.sign_in_supported,
                "profile_refresh_supported": discovery.profile_refresh_supported,
                "default_sign_in_enabled": discovery.default_sign_in_enabled,
                "default_profile_refresh_enabled": discovery.default_profile_refresh_enabled,
                "configured": automation_id is not None,
                "automation_id": automation_id,
            })
    return sorted(items, key=lambda item: (
        not item["supported"], item["name"].casefold(), item["domain"],
    ))


def _enqueue_automation_batch(
    request: Request,
    automations: list[tuple[str, str]],
    *,
    config_override: dict[str, Any] | None = None,
    skipped: list[dict[str, str]] | None = None,
    action: str | None = None,
) -> dict[str, Any]:
    queued: list[dict[str, str]] = []
    skipped_active: list[dict[str, str]] = []
    for automation_id, name in automations:
        execution, created = request.app.state.queue.enqueue_now_with_status(
            automation_id, config_override, activate_existing=False,
        )
        item = {
            "automation_id": automation_id,
            "name": name,
            "execution_id": execution.id,
            "status": execution.status,
        }
        (queued if created else skipped_active).append(item)
    return {
        "action": action,
        "queued": queued,
        "skipped_active": skipped_active,
        "skipped": skipped or [],
    }


def _require_pt_automation(record: AutomationRecord | None) -> AutomationRecord:
    if record is None or record.handler_type != "pt_signin":
        raise HTTPException(status_code=404, detail="PT 签到任务不存在")
    return record


def _require_periodic_automation(record: AutomationRecord | None) -> AutomationRecord:
    if record is None or record.handler_type not in {"browser_signin", "http_signin"}:
        raise HTTPException(status_code=404, detail="普通周期任务不存在")
    return record


def _periodic_signin_site_view(
    record: AutomationRecord | None, latest: ExecutionRecord | None,
) -> dict[str, Any]:
    record = _require_periodic_automation(record)
    config = json.loads(record.config_json)
    return {
        "id": record.id,
        "name": record.name,
        "handler_type": record.handler_type,
        "enabled": record.enabled,
        "interval_hours": record.interval_seconds // 3600,
        "next_run_at": record.next_run_at,
        "url": config.get("url"),
        "site_url": config.get("site_url") or config.get("url"),
        "template_key": config.get("template_key"),
        "domain": (urlparse(str(config.get("url") or "")).hostname or "").lower() or None,
        "config": {
            "timeout_seconds": config.get("timeout_seconds", 60),
            "random_delay_minutes": config.get("random_delay_minutes", 30),
            "retry_interval_hours": max(int(config.get("retry_interval_minutes", 120)) // 60, 1),
            "max_retries": config.get("max_retries", 5),
            "method": (config.get("browser_request") or {}).get("method") or config.get("method", "GET"),
            "browser_request": config.get("browser_request"),
            "wait_for_selector": config.get("wait_for_selector"),
            "click_selector": config.get("click_selector"),
            "click_role": config.get("click_role"),
            "click_name": config.get("click_name"),
            "click_exact": bool(config.get("click_exact", False)),
            "already_selector": config.get("already_selector"),
            "success_selector": config.get("success_selector"),
            "wait_after_click_ms": config.get("wait_after_click_ms", 1500),
            "success_patterns": config.get("success_patterns", []),
            "already_patterns": config.get("already_patterns", []),
            "auth_expired_patterns": config.get("auth_expired_patterns", []),
            "daily_start_time": config.get("daily_start_time", SIGNIN_START_TIME),
        },
        "last_execution": execution_view(latest) if latest else None,
    }


def _pt_signin_site_view(record: AutomationRecord | None,
                         latest: ExecutionRecord | None) -> dict[str, Any]:
    record = _require_pt_automation(record)
    config = json.loads(record.config_json)
    sign_in_supported, profile_refresh_supported = _pt_site_capabilities(record, config)
    discovery = _pt_discovery_for_config(config)
    legacy_profile_refresh_default = bool(
        discovery
        and discovery.default_profile_refresh_enabled
        and "profile_refresh_supported" not in config
    )
    return {
        "id": record.id,
        "name": record.name,
        "enabled": record.enabled,
        "interval_hours": record.interval_seconds // 3600,
        "next_run_at": record.next_run_at,
        "url": config.get("url"),
        "domain": str(config.get("site_domain") or "") or None,
        "config": {
            "timeout_seconds": config.get("timeout_seconds", 60),
            "random_delay_minutes": config.get("random_delay_minutes", 30),
            "retry_interval_hours": max(int(config.get("retry_interval_minutes", 120)) // 60, 1),
            "max_retries": config.get("max_retries", 5),
            "click_selector": config.get("click_selector"),
            "success_patterns": config.get("success_patterns", []),
            "already_patterns": config.get("already_patterns", []),
            "sign_in_enabled": bool(config.get("sign_in_enabled", True)) and sign_in_supported,
            "profile_refresh_enabled": (
                (
                    bool(config.get("profile_refresh_enabled", False))
                    or legacy_profile_refresh_default
                )
                and profile_refresh_supported
            ),
            "sign_in_supported": sign_in_supported,
            "profile_refresh_supported": profile_refresh_supported,
            "daily_start_time": config.get("daily_start_time", SIGNIN_START_TIME),
        },
        "last_execution": execution_view(latest) if latest else None,
    }


def _pt_site_capabilities(record: AutomationRecord, config: dict[str, Any]) -> tuple[bool, bool]:
    del record
    discovery = _pt_discovery_for_config(config)
    catalog_sign_in_supported = discovery.sign_in_supported if discovery else True
    catalog_profile_refresh_supported = discovery.profile_refresh_supported if discovery else True
    return (
        bool(config.get(
            "sign_in_supported", catalog_sign_in_supported,
        )) and catalog_sign_in_supported,
        bool(config.get(
            "profile_refresh_supported", catalog_profile_refresh_supported,
        )) and catalog_profile_refresh_supported,
    )


def _pt_discovery_for_config(config: dict[str, Any]):
    domain = str(config.get("site_domain") or "").lower()
    if not domain:
        domain = (urlparse(str(config.get("url") or "")).hostname or "").lower()
    return discover_pt_site(domain, set()) if domain else None


def _pt_execution_view(record: ExecutionRecord) -> dict[str, Any]:
    result = execution_view(record)
    result.update({
        "automation_name": record.automation.name,
        "domain": str(json.loads(record.automation.config_json).get("site_domain") or "") or None,
    })
    return result


def _periodic_execution_view(record: ExecutionRecord) -> dict[str, Any]:
    result = execution_view(record)
    config = json.loads(record.automation.config_json)
    result.update({
        "automation_name": record.automation.name,
        "url": config.get("site_url") or config.get("url"),
        "domain": (urlparse(str(config.get("url") or "")).hostname or "").lower() or None,
    })
    return result


def _pt_history_execution_view(record: ExecutionRecord, action: str) -> dict[str, Any] | None:
    view = execution_view(record)
    view["action_type"] = action
    result = view.get("result")
    if not isinstance(result, dict):
        return view
    actions = (result.get("details") or {}).get("actions")
    if not isinstance(actions, dict):
        return view
    action_result = actions.get(action)
    if not isinstance(action_result, dict) or not action_result.get("enabled"):
        return None
    if action_result.get("outcome"):
        view["result"] = {
            "outcome": action_result.get("outcome"),
            "message": action_result.get("message"),
            "details": action_result.get("details"),
        }
    return view


def _profile_stats_from_result(result_json: str | None) -> dict[str, str]:
    if not result_json:
        return {}
    with suppress(ValueError, TypeError):
        result = json.loads(result_json)
        details = result.get("details") or {}
        stats = details.get("profile_stats")
        if not isinstance(stats, dict):
            actions = details.get("actions")
            refresh = actions.get("profile_refresh") if isinstance(actions, dict) else None
            refresh_details = refresh.get("details") if isinstance(refresh, dict) else None
            stats = refresh_details.get("profile_stats") if isinstance(refresh_details, dict) else None
        if isinstance(stats, dict):
            return sanitize_pt_profile_stats({
                str(key): str(value)[:160]
                for key, value in stats.items()
                if value is not None and str(value).strip()
            })
    return {}


def _profile_refresh_status_from_result(
    result_json: str | None,
) -> tuple[str | None, str | None] | None:
    if not result_json:
        return None
    with suppress(ValueError, TypeError):
        result = json.loads(result_json)
        actions = (result.get("details") or {}).get("actions")
        if not isinstance(actions, dict):
            return None
        refresh = actions.get("profile_refresh")
        if not isinstance(refresh, dict) or not refresh.get("enabled"):
            return None
        outcome = str(refresh.get("outcome") or "").strip() or None
        message = str(refresh.get("message") or "").strip()[:300] or None
        return outcome, message
    return None


def automation_view(record: AutomationRecord) -> dict[str, Any]:
    return {"id": record.id, "name": record.name, "handler_type": record.handler_type,
            "enabled": record.enabled, "interval_seconds": record.interval_seconds,
            "next_run_at": record.next_run_at,
            "config": json.loads(record.config_json)}


def execution_view(record: ExecutionRecord) -> dict[str, Any]:
    return {"id": record.id, "automation_id": record.automation_id, "scheduled_at": record.scheduled_at,
            "status": record.status, "attempts": record.attempts, "result": json.loads(record.result_json) if record.result_json else None,
            "error": record.error, "started_at": record.started_at, "finished_at": record.finished_at}


_DEBUG_SENSITIVE_KEYS = (
    "access_key", "api_key", "authorization", "cookie", "credential", "password",
    "private_key", "secret", "token", "upload_key",
)
_DEBUG_INLINE_SECRET = re.compile(
    r"(?i)\b(access[_ -]?key|api[_ -]?key|authorization|cookie|password|private[_ -]?key|"
    r"secret|token|upload[_ -]?key)(\s*[:=]\s*)([^\r\n]+)"
)


def _debug_execution_view(record: ExecutionRecord, data_dir: Path) -> dict[str, Any]:
    raw_result: Any = None
    if record.result_json:
        with suppress(ValueError, TypeError):
            raw_result = json.loads(record.result_json)
    result = _sanitize_debug_value(raw_result)
    artifact = data_dir.joinpath("browser-artifacts", f"{record.id}.png")
    artifact_url = (
        f"/api/v1/debug/executions/{record.id}/artifact" if artifact.is_file() else None
    )
    if isinstance(result, dict):
        details = result.get("details")
        if isinstance(details, dict) and "screenshot" in details:
            details["screenshot"] = artifact_url or "截图文件不存在"
    outcome = result.get("outcome") if isinstance(result, dict) else None
    message = result.get("message") if isinstance(result, dict) else None
    duration_ms = None
    if record.started_at and record.finished_at:
        duration_ms = max(int((record.finished_at - record.started_at).total_seconds() * 1000), 0)
    return {
        "id": record.id,
        "automation_id": record.automation_id,
        "automation_name": record.automation.name,
        "handler_type": record.automation.handler_type,
        "scheduled_at": record.scheduled_at,
        "started_at": record.started_at,
        "finished_at": record.finished_at,
        "duration_ms": duration_ms,
        "status": record.status,
        "attempts": record.attempts,
        "outcome": outcome,
        "message": _sanitize_debug_text(message) if message is not None else None,
        "error": _sanitize_debug_text(record.error) if record.error else None,
        "result": result,
        "artifact_url": artifact_url,
    }


def _sanitize_debug_value(value: Any, key: str = "", depth: int = 0) -> Any:
    if any(part in key.casefold() for part in _DEBUG_SENSITIVE_KEYS):
        return "[已脱敏]"
    if depth >= 8:
        return "[内容层级过深]"
    if isinstance(value, dict):
        return {
            str(item_key)[:160]: _sanitize_debug_value(item_value, str(item_key), depth + 1)
            for item_key, item_value in list(value.items())[:100]
        }
    if isinstance(value, list):
        return [_sanitize_debug_value(item, key, depth + 1) for item in value[:100]]
    if isinstance(value, str):
        return _sanitize_debug_text(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _sanitize_debug_text(str(value))


def _sanitize_debug_text(value: Any, limit: int = 8000) -> str:
    text = _DEBUG_INLINE_SECRET.sub(
        lambda match: f"{match.group(1)}{match.group(2)}[已脱敏]", str(value),
    )
    return text if len(text) <= limit else f"{text[:limit]}\n...[内容已截断]"
