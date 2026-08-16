from __future__ import annotations

import json
import base64
from contextlib import suppress
from datetime import datetime, timedelta
import hashlib
import hmac
from importlib.metadata import PackageNotFoundError, version
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import time
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from autosurf.domain.models import utc_now
from autosurf.automations.pt_signin import sanitize_pt_profile_stats
from autosurf.automations.browser_session import persistent_browser_mode
from autosurf.infrastructure.database import (
    AutomationRecord,
    CookieCloudBlob,
    CookieCloudSource,
    CredentialRecord,
    ExecutionRecord,
)
from autosurf.pt_discovery import PT_COOKIE_MARKERS, discover_pt_site, is_ignored_pt_domain
from autosurf.userscripts import (
    WEB_CREDENTIAL_SCRIPT_SOURCES,
    build_web_credential_userscript,
    build_web_credential_userscript_bundle,
)


class CredentialInput(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    domain: str = Field(min_length=1, max_length=255)
    cookies: dict[str, str]


class AutomationInput(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    handler_type: str
    interval_seconds: int = Field(ge=60, le=31_536_000)
    credential_id: str | None = None
    config: dict[str, Any]


class CookieCloudSourceInput(BaseModel):
    uuid: str = Field(min_length=1, max_length=128)
    password: str | None = Field(default=None, min_length=1, max_length=1024)
    auto_import: bool = True


class CookieCloudImportInput(BaseModel):
    password: str | None = Field(default=None, min_length=1, max_length=1024)


class CookieCloudSourceSettingsInput(BaseModel):
    auto_import: bool


class PtSignInInput(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    credential_id: str = Field(min_length=1, max_length=36)
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
    profile_refresh_enabled: bool = False


class PtSignInEnabledInput(BaseModel):
    enabled: bool


class PtSiteActionsInput(BaseModel):
    sign_in_enabled: bool
    profile_refresh_enabled: bool


class PtSignInCollectInput(BaseModel):
    credential_ids: list[str] = Field(min_length=1, max_length=200)
    interval_hours: int = Field(default=24, ge=1, le=720)
    timeout_seconds: int = Field(default=60, ge=5, le=180)
    random_delay_minutes: int = Field(default=30, ge=0, le=1440)
    retry_interval_hours: int = Field(default=2, ge=1, le=168)
    max_retries: int = Field(default=5, ge=0, le=20)
    sign_in_enabled: bool = True
    profile_refresh_enabled: bool = False


class PtSignInScheduleInput(BaseModel):
    interval_hours: int = Field(default=24, ge=1, le=720)
    timeout_seconds: int = Field(default=60, ge=5, le=180)
    random_delay_minutes: int = Field(default=30, ge=0, le=1440)
    retry_interval_hours: int = Field(default=2, ge=1, le=168)
    max_retries: int = Field(default=5, ge=0, le=20)


class LoginInput(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=1024)


class WebCredentialScriptInput(BaseModel):
    base_url: str = Field(min_length=8, max_length=2048)


class WebCredentialUploadInput(BaseModel):
    token: str | None = Field(default=None, min_length=1, max_length=8192)
    values: dict[str, str] = Field(default_factory=dict)


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
web_credential_router = APIRouter(prefix="/api/web-credentials")


def _program_repository() -> Path:
    configured = os.environ.get("AUTOSURF_PROGRAM_DIR")
    return Path(configured).resolve() if configured else Path(__file__).resolve().parents[2]


def _upgrade_command() -> list[str] | None:
    configured = os.environ.get("AUTOSURF_UPGRADE_SCRIPT")
    if configured and Path(configured).is_file():
        return ["/bin/sh", configured]
    executable = shutil.which("autosurf-upgrade")
    return [executable] if executable else None


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
    return process_running or Path("/tmp/autosurf-upgrade-in-progress").exists()


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
    installed = bool(
        browser_root.name and chromium_revision
        and browser_root.joinpath(f"chromium-{chromium_revision}", "chrome-linux64", "chrome").is_file()
    )
    return {
        "installed": installed,
        "playwright_version": playwright_version,
        "persistent": bool(os.environ.get("PLAYWRIGHT_BROWSERS_PATH")),
        "session_mode": persistent_browser_mode(),
        "chromium_revision": chromium_revision,
        "chromium_version": chromium_version,
    }


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
    environment_available = command is not None and repository.joinpath(".git").is_dir()
    update_available = bool(local_revision and remote_revision and local_revision != remote_revision)
    browser_missing = not browser["installed"]
    dependency_repair_needed = python_dependencies["checked"] and not python_dependencies["satisfied"]
    last_upgrade = _settle_stale_upgrade(
        request, _last_upgrade(request), running=running,
        local_revision=local_revision, remote_revision=remote_revision,
        check_error=check_error, browser=browser, dependencies=python_dependencies,
    )
    return {
        "available": environment_available,
        "can_upgrade": environment_available and check_error is None and (
            update_available or browser_missing or dependency_repair_needed
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


@router.post("/system/upgrade", status_code=202)
def start_upgrade(request: Request) -> dict[str, Any]:
    repository = _program_repository()
    command = _upgrade_command()
    with request.app.state.upgrade_guard:
        if command is None or not repository.joinpath(".git").is_dir():
            raise HTTPException(status_code=409, detail="当前运行环境不支持网页升级")
        if _upgrade_running(request):
            raise HTTPException(status_code=409, detail="升级正在进行")
        current = _upgrade_status(request)
        if current["version_check_error"]:
            raise HTTPException(status_code=503, detail=current["version_check_error"])
        if not current["can_upgrade"]:
            raise HTTPException(status_code=409, detail="当前已是最新版本")

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


@router.get("/handlers")
def handlers(request: Request) -> dict[str, list[str]]:
    return {"items": request.app.state.registry.types()}


@router.post("/credentials", status_code=201)
def upsert_credential(data: CredentialInput, request: Request) -> dict[str, Any]:
    record = request.app.state.credentials.upsert(data.name, data.domain, data.cookies)
    return credential_view(record)


@router.get("/credentials")
def list_credentials(request: Request) -> dict[str, Any]:
    with request.app.state.sessions() as session:
        records = session.scalars(select(CredentialRecord).order_by(CredentialRecord.name)).all()
        return {"items": [credential_view(item) for item in records]}


@router.post("/automations", status_code=201)
def create_automation(data: AutomationInput, request: Request) -> dict[str, Any]:
    try:
        record = request.app.state.automations.create(data.name, data.handler_type, data.interval_seconds,
                                                      data.config, data.credential_id)
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


@router.post("/pt-signin/sites", status_code=201)
def create_pt_signin_site(data: PtSignInInput, request: Request) -> dict[str, Any]:
    with request.app.state.sessions() as session:
        credential = session.get(CredentialRecord, data.credential_id)
        if credential is None or credential.provider not in {"cookiecloud", "web_storage"}:
            raise HTTPException(status_code=422, detail="请选择受支持的站点凭据")
        _validate_pt_url(data.url, credential.domain)
        credential_domain = credential.domain
        try:
            cookie_names = set(request.app.state.credentials.cookies_for(credential))
        except ValueError:
            cookie_names = set()
        discovery = discover_pt_site(credential.domain, cookie_names)
        sign_in_supported = discovery.sign_in_supported if discovery else True
        profile_refresh_supported = discovery.profile_refresh_supported if discovery else True
    config = {
        "url": data.url,
        "credential_domain": credential_domain,
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
        "discovery_strategy": discovery.strategy if discovery else None,
        "profile_url": discovery.profile_url if discovery else None,
    }
    try:
        record = request.app.state.automations.create(
            data.name, "pt_signin", data.interval_hours * 3600, config, data.credential_id
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
    credential_ids = list(dict.fromkeys(data.credential_ids))
    candidate_items = _pt_signin_candidates(request, True)
    candidates = {
        credential_id: item
        for item in candidate_items
        for credential_id in item.get("credential_ids", [item["credential"]["id"]])
    }
    selected = [candidates.get(credential_id) for credential_id in credential_ids]
    if any(item is None or not item["recognized"] for item in selected):
        raise HTTPException(status_code=422, detail="所选凭据中包含未识别的 PT 站点")
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
            "credential_domain": candidate["credential"]["domain"],
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
            "discovery_strategy": candidate["strategy"],
            "profile_url": candidate["profile_url"],
            "discovered": True,
            "discovery_reason": candidate["reason"],
        }
        try:
            record = request.app.state.automations.create(
                candidate["name"], "pt_signin", data.interval_hours * 3600, config,
                candidate["credential"]["id"],
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
                "credential_id": item["credential"]["id"],
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
        })
        record.interval_seconds = data.interval_hours * 3600
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
            record.next_run_at = utc_now()
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
            record.next_run_at = utc_now()
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
        for execution in executions:
            if execution.automation_id in latest:
                continue
            stats = _profile_stats_from_result(execution.result_json)
            if stats:
                latest[execution.automation_id] = (
                    stats, execution.finished_at or execution.scheduled_at,
                )

        items = []
        for site in sites:
            config = json.loads(site.config_json)
            snapshot = latest.get(site.id)
            if not config.get("profile_refresh_enabled", False) and snapshot is None:
                continue
            stats, updated_at = snapshot if snapshot else ({}, None)
            items.append({
                "automation_id": site.id,
                "name": site.name,
                "domain": site.credential.domain if site.credential else None,
                "profile_refresh_enabled": bool(config.get("profile_refresh_enabled", False)),
                "updated_at": updated_at,
                "stats": stats,
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
                "domain": site.credential.domain if site.credential else None,
                "url": json.loads(site.config_json).get("url"),
                "enabled": site.enabled,
                "history_action": history_actions[site.id],
                "record_count": record_counts[site.id],
                "executions": daily[site.id],
                "site_history": site_history[site.id],
            } for site in sites],
            "latest_execution": _pt_execution_view(latest) if latest else None,
        }


def _validate_pt_url(url: str, credential_domain: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise HTTPException(status_code=422, detail="签到地址必须是有效的 HTTP(S) URL")
    hostname = parsed.hostname.lower().rstrip(".")
    domain = credential_domain.lower().lstrip(".").rstrip(".")
    if hostname != domain and not hostname.endswith(f".{domain}"):
        raise HTTPException(status_code=422, detail="签到地址必须属于所选凭据域名")


def _pt_signin_candidates(request: Request, include_unknown: bool) -> list[dict[str, Any]]:
    with request.app.state.sessions() as session:
        credentials = session.scalars(select(CredentialRecord).where(
            CredentialRecord.provider.in_(["cookiecloud", "web_storage"])
        ).order_by(CredentialRecord.domain, CredentialRecord.name)).all()
        automations = session.scalars(select(AutomationRecord).where(
            AutomationRecord.handler_type == "pt_signin"
        ).order_by(AutomationRecord.name)).all()
        configured = {
            record.credential_id: record.id for record in automations if record.credential_id
        }
        grouped: dict[str, dict[str, Any]] = {}
        unknown_items: list[dict[str, Any]] = []
        for credential in credentials:
            if is_ignored_pt_domain(credential.domain):
                continue
            try:
                cookie_names = set(request.app.state.credentials.cookies_for(credential))
            except ValueError:
                cookie_names = set()
            discovery = discover_pt_site(credential.domain, cookie_names)
            if discovery is None and not include_unknown:
                continue
            automation_id = configured.get(credential.id)
            item = {
                "credential": {
                    "id": credential.id,
                    "name": credential.name,
                    "domain": credential.domain,
                    "provider": credential.provider,
                    "version": credential.version,
                    "updated_at": credential.updated_at,
                },
                "credential_ids": [credential.id],
                "site_key": discovery.site_key if discovery else credential.domain,
                "name": discovery.name if discovery else credential.domain,
                "url": discovery.url if discovery else f"https://{credential.domain}/attendance.php",
                "recognized": discovery is not None,
                "reason": discovery.reason if discovery else "unknown",
                "strategy": discovery.strategy if discovery else None,
                "profile_url": discovery.profile_url if discovery else None,
                "supported": discovery.supported if discovery else False,
                "sign_in_supported": discovery.sign_in_supported if discovery else False,
                "profile_refresh_supported": discovery.profile_refresh_supported if discovery else False,
                "default_sign_in_enabled": discovery.default_sign_in_enabled if discovery else False,
                "default_profile_refresh_enabled": (
                    discovery.default_profile_refresh_enabled if discovery else False
                ),
                "configured": automation_id is not None,
                "automation_id": automation_id,
                "_score": (
                    discovery is not None
                    and discovery.strategy == "web_storage_browser"
                    and credential.provider == "web_storage",
                    len({name.lower() for name in cookie_names}.intersection(PT_COOKIE_MARKERS)),
                    len(cookie_names),
                    credential.domain.startswith("www."),
                    credential.updated_at,
                ),
            }
            if discovery is None:
                unknown_items.append(item)
                continue

            existing = grouped.get(discovery.site_key)
            if existing is None:
                grouped[discovery.site_key] = item
                continue
            configured_id = existing["automation_id"] or automation_id
            if item["_score"] > existing["_score"]:
                item["credential_ids"] = list(dict.fromkeys(
                    [item["credential"]["id"], *existing["credential_ids"]]
                ))
                item["configured"] = configured_id is not None
                item["automation_id"] = configured_id
                grouped[discovery.site_key] = item
            else:
                existing["credential_ids"].append(credential.id)
                existing["configured"] = configured_id is not None
                existing["automation_id"] = configured_id

        items = [*grouped.values(), *unknown_items]
        for item in items:
            item.pop("_score", None)
    return sorted(items, key=lambda item: (
        not item["recognized"], not item["supported"], item["name"].casefold(),
        item["credential"]["domain"],
    ))


def _require_pt_automation(record: AutomationRecord | None) -> AutomationRecord:
    if record is None or record.handler_type != "pt_signin":
        raise HTTPException(status_code=404, detail="PT 签到任务不存在")
    return record


def _pt_signin_site_view(record: AutomationRecord | None,
                         latest: ExecutionRecord | None) -> dict[str, Any]:
    record = _require_pt_automation(record)
    config = json.loads(record.config_json)
    sign_in_supported, profile_refresh_supported = _pt_site_capabilities(record, config)
    credential = record.credential
    discovery = _pt_discovery_for_credential(credential)
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
        "credential": {
            "id": credential.id,
            "name": credential.name,
            "domain": credential.domain,
            "version": credential.version,
        } if credential else None,
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
        },
        "last_execution": execution_view(latest) if latest else None,
    }


def _pt_site_capabilities(record: AutomationRecord, config: dict[str, Any]) -> tuple[bool, bool]:
    credential = record.credential
    discovery = _pt_discovery_for_credential(credential)
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


def _pt_discovery_for_credential(credential: CredentialRecord | None):
    if credential is None:
        return None
    markers = {"token"} if credential.provider == "web_storage" else set()
    return discover_pt_site(credential.domain, markers)


def _pt_execution_view(record: ExecutionRecord) -> dict[str, Any]:
    result = execution_view(record)
    result.update({
        "automation_name": record.automation.name,
        "domain": record.automation.credential.domain if record.automation.credential else None,
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
            stats = (
                details.get("actions", {}).get("profile_refresh", {}).get("details", {})
                .get("profile_stats")
            )
        if isinstance(stats, dict):
            return sanitize_pt_profile_stats({
                str(key): str(value)[:160]
                for key, value in stats.items()
                if value is not None and str(value).strip()
            })
    return {}


@router.put("/cookiecloud/sources/{uuid}")
def configure_cookiecloud(uuid: str, data: CookieCloudSourceInput, request: Request) -> dict[str, Any]:
    if uuid != data.uuid:
        raise HTTPException(status_code=422, detail="path UUID and body UUID must match")
    try:
        source = request.app.state.cookiecloud.configure(uuid, data.password, data.auto_import)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _cookiecloud_source_view(request, source.uuid)


@router.get("/cookiecloud/sources")
def list_cookiecloud_sources(request: Request) -> dict[str, Any]:
    with request.app.state.sessions() as session:
        sources = {item.uuid: item for item in session.scalars(
            select(CookieCloudSource).order_by(CookieCloudSource.uuid)
        ).all()}
        blobs = {item.uuid: item for item in session.scalars(
            select(CookieCloudBlob).order_by(CookieCloudBlob.uuid)
        ).all()}
        credentials = session.scalars(
            select(CredentialRecord).where(CredentialRecord.provider == "cookiecloud")
        ).all()

        items = []
        for uuid in sorted(sources.keys() | blobs.keys()):
            source = sources.get(uuid)
            blob = blobs.get(uuid)
            prefix = f"cookiecloud:{uuid}:"
            items.append({
                "uuid": uuid,
                "configured": source is not None,
                "password_configured": bool(source and source.encrypted_password),
                "auto_import": bool(source and source.auto_import),
                "last_import_at": source.last_import_at if source else None,
                "last_error": source.last_error if source else None,
                "blob_updated_at": blob.updated_at if blob else None,
                "credential_count": sum(item.name.startswith(prefix) for item in credentials),
            })
        return {"items": items}


@router.patch("/cookiecloud/sources/{uuid}/settings")
def update_cookiecloud_source_settings(uuid: str, data: CookieCloudSourceSettingsInput,
                                       request: Request) -> dict[str, Any]:
    try:
        request.app.state.cookiecloud.set_auto_import(uuid, data.auto_import)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _cookiecloud_source_view(request, uuid)


@router.post("/cookiecloud/sources/{uuid}/password/reveal")
def reveal_cookiecloud_password(uuid: str, request: Request, response: Response) -> dict[str, str]:
    try:
        password = request.app.state.cookiecloud.password_for(uuid)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return {"password": password}


@router.post("/cookiecloud/sources/{uuid}/import")
def import_cookiecloud(uuid: str, data: CookieCloudImportInput, request: Request) -> dict[str, Any]:
    try:
        return request.app.state.cookiecloud.import_credentials(uuid, data.password)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _cookiecloud_source_view(request: Request, uuid: str) -> dict[str, Any]:
    items = list_cookiecloud_sources(request)["items"]
    return next(item for item in items if item["uuid"] == uuid)


def credential_view(record: CredentialRecord) -> dict[str, Any]:
    return {"id": record.id, "name": record.name, "domain": record.domain, "provider": record.provider,
            "version": record.version, "updated_at": record.updated_at}


def automation_view(record: AutomationRecord) -> dict[str, Any]:
    return {"id": record.id, "name": record.name, "handler_type": record.handler_type,
            "enabled": record.enabled, "interval_seconds": record.interval_seconds,
            "next_run_at": record.next_run_at, "credential_id": record.credential_id,
            "config": json.loads(record.config_json)}


def execution_view(record: ExecutionRecord) -> dict[str, Any]:
    return {"id": record.id, "automation_id": record.automation_id, "scheduled_at": record.scheduled_at,
            "status": record.status, "attempts": record.attempts, "result": json.loads(record.result_json) if record.result_json else None,
            "error": record.error, "started_at": record.started_at, "finished_at": record.finished_at}


@router.get("/web-credentials/rousi")
def rousi_web_credential_status(request: Request) -> dict[str, Any]:
    return request.app.state.web_credentials.status("rousi")


@router.get("/web-credentials")
def web_credential_statuses(request: Request) -> dict[str, Any]:
    return request.app.state.web_credentials.statuses()


@router.post("/web-credentials/rousi/userscript")
def create_rousi_userscript(data: WebCredentialScriptInput, request: Request) -> Response:
    base_url = _web_credential_base_url(data.base_url)
    upload_key = secrets.token_urlsafe(32)
    request.app.state.web_credentials.rotate_upload_key(upload_key)
    script = build_web_credential_userscript(
        "rousi", f"{base_url}/api/web-credentials/rousi/token", upload_key,
    )
    return Response(
        script,
        media_type="text/javascript; charset=utf-8",
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": 'attachment; filename="autosurf-web-credential-sync.user.js"',
        },
    )


@router.post("/web-credentials/userscript")
def create_web_credential_userscript(data: WebCredentialScriptInput, request: Request) -> Response:
    base_url = _web_credential_base_url(data.base_url)
    configurations: dict[str, tuple[str, str]] = {}
    for source_key in WEB_CREDENTIAL_SCRIPT_SOURCES:
        upload_key = secrets.token_urlsafe(32)
        request.app.state.web_credentials.rotate_upload_key(source_key, upload_key)
        configurations[source_key] = (
            f"{base_url}/api/web-credentials/{source_key}/values", upload_key,
        )
    script = build_web_credential_userscript_bundle(configurations)
    return Response(
        script,
        media_type="text/javascript; charset=utf-8",
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": 'attachment; filename="autosurf-web-credential-sync.user.js"',
        },
    )


@router.delete("/web-credentials/rousi/token", status_code=204)
def clear_rousi_web_credential(request: Request) -> None:
    request.app.state.web_credentials.clear_token()


@router.delete("/web-credentials/{source_key}/values", status_code=204)
def clear_web_credential(source_key: str, request: Request) -> None:
    try:
        request.app.state.web_credentials.clear_values(source_key)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="unknown web credential source") from exc


@web_credential_router.post("/rousi/token")
def upload_rousi_web_credential(
    data: WebCredentialUploadInput,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    if data.token is None:
        raise HTTPException(status_code=422, detail="token is required")
    prefix = "Bearer "
    if not authorization or not authorization.startswith(prefix):
        raise HTTPException(status_code=401, detail="invalid upload key")
    try:
        record, changed = request.app.state.web_credentials.update_token(
            authorization[len(prefix):], data.token,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail="invalid upload key") from exc
    return {"status": "ok", "changed": changed, "updated_at": record.updated_at}


@web_credential_router.post("/{source_key}/values")
def upload_web_credential(
    source_key: str,
    data: WebCredentialUploadInput,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    prefix = "Bearer "
    if not authorization or not authorization.startswith(prefix):
        raise HTTPException(status_code=401, detail="invalid upload key")
    try:
        record, changed = request.app.state.web_credentials.update_values(
            source_key, authorization[len(prefix):], data.values,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail="invalid upload key") from exc
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if detail == "unknown web credential source" else 422
        raise HTTPException(status_code=status_code, detail=detail) from exc
    return {"status": "ok", "changed": changed, "updated_at": record.updated_at}


def _web_credential_base_url(value: str) -> str:
    parsed = urlparse(value.strip())
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise HTTPException(status_code=422, detail="上送地址必须是 HTTP(S) 服务根地址")
    return f"{parsed.scheme}://{parsed.netloc}"


cookiecloud_router = APIRouter(prefix="/cookiecloud")


@cookiecloud_router.get("/")
def cookiecloud_root() -> dict[str, str]:
    return {"message": "CookieCloud endpoint is ready"}


@cookiecloud_router.post("/")
@cookiecloud_router.post("/update")
def cookiecloud_update(payload: dict[str, Any], request: Request) -> dict[str, Any]:
    try:
        uuid = request.app.state.cookiecloud.put(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    imported = None
    try:
        imported = request.app.state.cookiecloud.auto_import_if_configured(uuid)
    except ValueError:
        pass
    return {"action": "done", "uuid": uuid, "imported": len(imported["credentials"]) if imported else 0}


@cookiecloud_router.get("/get/{uuid}")
@cookiecloud_router.post("/get/{uuid}")
def cookiecloud_get(uuid: str, request: Request) -> dict[str, Any]:
    payload = request.app.state.cookiecloud.get(uuid)
    if payload is None:
        raise HTTPException(status_code=404, detail="CookieCloud key not found")
    return payload
