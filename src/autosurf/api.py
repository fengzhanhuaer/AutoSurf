from __future__ import annotations

import json
import base64
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

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from autosurf.domain.models import utc_now
from autosurf.infrastructure.database import (
    AutomationRecord,
    CookieCloudBlob,
    CookieCloudSource,
    CredentialRecord,
    ExecutionRecord,
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
    click_selector: str | None = Field(default=None, max_length=1024)
    success_patterns: list[str] = Field(default_factory=list, max_length=20)
    already_patterns: list[str] = Field(default_factory=list, max_length=20)


class PtSignInEnabledInput(BaseModel):
    enabled: bool


class LoginInput(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=1024)


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
        "last_upgrade": _last_upgrade(request),
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
        if credential is None or credential.provider != "cookiecloud":
            raise HTTPException(status_code=422, detail="请选择 CookieCloud 导入的凭据")
        _validate_pt_url(data.url, credential.domain)
        credential_domain = credential.domain
    config = {
        "url": data.url,
        "credential_domain": credential_domain,
        "timeout_seconds": data.timeout_seconds,
        "click_selector": data.click_selector or None,
        "success_patterns": data.success_patterns,
        "already_patterns": data.already_patterns,
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


def _validate_pt_url(url: str, credential_domain: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise HTTPException(status_code=422, detail="签到地址必须是有效的 HTTP(S) URL")
    hostname = parsed.hostname.lower().rstrip(".")
    domain = credential_domain.lower().lstrip(".").rstrip(".")
    if hostname != domain and not hostname.endswith(f".{domain}"):
        raise HTTPException(status_code=422, detail="签到地址必须属于所选 CookieCloud 凭据域名")


def _require_pt_automation(record: AutomationRecord | None) -> AutomationRecord:
    if record is None or record.handler_type != "pt_signin":
        raise HTTPException(status_code=404, detail="PT 签到任务不存在")
    return record


def _pt_signin_site_view(record: AutomationRecord | None,
                         latest: ExecutionRecord | None) -> dict[str, Any]:
    record = _require_pt_automation(record)
    config = json.loads(record.config_json)
    credential = record.credential
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
            "click_selector": config.get("click_selector"),
            "success_patterns": config.get("success_patterns", []),
            "already_patterns": config.get("already_patterns", []),
        },
        "last_execution": execution_view(latest) if latest else None,
    }


def _pt_execution_view(record: ExecutionRecord) -> dict[str, Any]:
    result = execution_view(record)
    result.update({
        "automation_name": record.automation.name,
        "domain": record.automation.credential.domain if record.automation.credential else None,
    })
    return result


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
