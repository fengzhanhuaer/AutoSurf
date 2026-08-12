from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from autosurf.infrastructure.database import AutomationRecord, CredentialRecord, ExecutionRecord


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


def require_token(request: Request, authorization: Annotated[str | None, Header()] = None) -> None:
    expected = request.app.state.settings.api_token
    if authorization != f"Bearer {expected}":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid API token")


router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_token)])


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
    return {"action": "done", "uuid": uuid}


@cookiecloud_router.get("/get/{uuid}")
@cookiecloud_router.post("/get/{uuid}")
def cookiecloud_get(uuid: str, request: Request) -> dict[str, Any]:
    payload = request.app.state.cookiecloud.get(uuid)
    if payload is None:
        raise HTTPException(status_code=404, detail="CookieCloud key not found")
    return payload

