from __future__ import annotations

import json
import secrets
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, Field
from sqlalchemy import select

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


basic_auth = HTTPBasic()


def require_login(request: Request, credentials: HTTPBasicCredentials = Depends(basic_auth)) -> str:
    settings = request.app.state.settings
    username_ok = secrets.compare_digest(credentials.username.encode(), settings.username.encode())
    password_ok = secrets.compare_digest(credentials.password.encode(), settings.password.encode())
    if not username_ok or not password_ok:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid username or password",
                            headers={"WWW-Authenticate": "Basic"})
    return credentials.username


router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_login)])


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
