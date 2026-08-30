from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.orm import sessionmaker

from autosurf.application.registry import HandlerRegistry
from autosurf.domain.models import ExecutionStatus, RunContext, RunOutcome, utc_now
from autosurf.domain.scheduling import (
    SIGNIN_INTERVAL_SECONDS,
    SIGNIN_START_TIME,
    next_signin_run_at,
)
from autosurf.infrastructure.database import AutomationRecord, ExecutionRecord
from autosurf.periodic_templates import apply_periodic_template


PT_PROFILE_REFRESH_DEFAULT_VERSION = 1


class AutomationService:
    def __init__(self, sessions: sessionmaker[Session], registry: HandlerRegistry) -> None:
        self.sessions = sessions
        self.registry = registry

    def create(self, name: str, handler_type: str, interval_seconds: int, config: dict,
               next_run_at: datetime | None = None) -> AutomationRecord:
        self.registry.get(handler_type)
        now = utc_now()
        record = AutomationRecord(id=str(uuid4()), name=name, handler_type=handler_type, enabled=True,
                                  interval_seconds=interval_seconds, next_run_at=next_run_at or now,
                                  config_json=json.dumps(config))
        with self.sessions.begin() as session:
            session.add(record)
        return record


def _align_signin_schedules(
    sessions: sessionmaker[Session], *, only_missing: bool,
) -> tuple[int, datetime]:
    updated = 0
    next_run_at = next_signin_run_at()
    with sessions.begin() as session:
        records = session.scalars(select(AutomationRecord).where(
            AutomationRecord.handler_type.in_(["pt_signin", "browser_signin", "http_signin"]),
        )).all()
        for record in records:
            try:
                config = json.loads(record.config_json)
            except (TypeError, ValueError):
                config = {}
            if only_missing and config.get("daily_start_time") == SIGNIN_START_TIME:
                continue
            config["daily_start_time"] = SIGNIN_START_TIME
            record.config_json = json.dumps(config, ensure_ascii=False)
            record.interval_seconds = SIGNIN_INTERVAL_SECONDS
            record.next_run_at = next_run_at
            updated += 1
    return updated, next_run_at


def reconcile_signin_schedules(sessions: sessionmaker[Session]) -> int:
    return _align_signin_schedules(sessions, only_missing=True)[0]


def reconcile_pt_profile_refresh_defaults(sessions: sessionmaker[Session]) -> int:
    """Apply the refresh-by-default policy once without overriding later user choices."""
    changed = 0
    with sessions.begin() as session:
        automations = session.scalars(select(AutomationRecord).where(
            AutomationRecord.handler_type == "pt_signin"
        )).all()
        for automation in automations:
            try:
                config = json.loads(automation.config_json)
            except (TypeError, ValueError):
                continue
            if config.get("profile_refresh_default_version") == PT_PROFILE_REFRESH_DEFAULT_VERSION:
                continue
            config.update({
                "profile_refresh_enabled": True,
                "profile_refresh_supported": True,
                "profile_refresh_default_version": PT_PROFILE_REFRESH_DEFAULT_VERSION,
            })
            automation.config_json = json.dumps(config, ensure_ascii=False)
            changed += 1
    return changed


def align_all_signin_schedules(sessions: sessionmaker[Session]) -> tuple[int, datetime]:
    return _align_signin_schedules(sessions, only_missing=False)


class QueueService:
    def __init__(self, sessions: sessionmaker, lease_seconds: int) -> None:
        self.sessions = sessions
        self.lease_seconds = lease_seconds

    def enqueue_due(self) -> int:
        now = utc_now()
        count = 0
        with self.sessions.begin() as session:
            due = session.scalars(select(AutomationRecord).where(
                AutomationRecord.enabled.is_(True), AutomationRecord.next_run_at <= now
            )).all()
            for automation in due:
                scheduled_at = automation.next_run_at
                random_delay_seconds = 0
                if automation.handler_type in {"pt_signin", "browser_signin", "http_signin"}:
                    try:
                        config = json.loads(automation.config_json)
                    except (TypeError, ValueError):
                        config = {}
                    if automation.handler_type == "pt_signin" or "random_delay_minutes" in config:
                        random_delay_minutes = _bounded_int(
                            config.get("random_delay_minutes"), 30, 0, 1440
                        )
                        if random_delay_minutes:
                            random_delay_seconds = secrets.randbelow(random_delay_minutes * 60 + 1)
                exists = session.scalar(select(ExecutionRecord.id).where(
                    ExecutionRecord.automation_id == automation.id,
                    ExecutionRecord.scheduled_at == scheduled_at,
                ))
                if exists is None:
                    session.add(ExecutionRecord(id=str(uuid4()), automation_id=automation.id,
                                                scheduled_at=scheduled_at, status=ExecutionStatus.PENDING,
                                                available_at=now + timedelta(seconds=random_delay_seconds),
                                                attempts=0))
                    count += 1
                while automation.next_run_at <= now:
                    automation.next_run_at += timedelta(seconds=automation.interval_seconds)
        return count

    def enqueue_now(
        self, automation_id: str, config_override: dict[str, Any] | None = None,
    ) -> ExecutionRecord:
        return self.enqueue_now_with_status(automation_id, config_override)[0]

    def enqueue_now_with_status(
        self, automation_id: str, config_override: dict[str, Any] | None = None,
        *, activate_existing: bool = True,
    ) -> tuple[ExecutionRecord, bool]:
        now = utc_now()
        with self.sessions.begin() as session:
            automation = session.get(AutomationRecord, automation_id)
            if automation is None:
                raise ValueError("automation does not exist")
            existing = session.scalar(select(ExecutionRecord).where(
                ExecutionRecord.automation_id == automation.id,
                ExecutionRecord.status.in_([
                    ExecutionStatus.PENDING, ExecutionStatus.RUNNING, ExecutionStatus.RETRY_WAIT,
                ]),
            ).order_by(ExecutionRecord.scheduled_at.desc()).limit(1))
            if existing is not None:
                if activate_existing and existing.status in {
                    ExecutionStatus.PENDING, ExecutionStatus.RETRY_WAIT,
                }:
                    existing.available_at = now
                session.flush()
                return existing, False
            execution = ExecutionRecord(id=str(uuid4()), automation_id=automation.id, scheduled_at=now,
                                        status=ExecutionStatus.PENDING, available_at=now, attempts=0,
                                        config_override_json=(
                                            json.dumps(config_override, ensure_ascii=False)
                                            if config_override else None
                                        ))
            session.add(execution)
        return execution, True

    def claim(self) -> ExecutionRecord | None:
        now = utc_now()
        with self.sessions.begin() as session:
            execution = session.scalar(select(ExecutionRecord).where(
                ExecutionRecord.available_at <= now,
                or_(ExecutionRecord.status.in_([ExecutionStatus.PENDING, ExecutionStatus.RETRY_WAIT]),
                    (ExecutionRecord.status == ExecutionStatus.RUNNING) & (ExecutionRecord.lease_until < now)),
            ).order_by(ExecutionRecord.available_at, ExecutionRecord.scheduled_at).limit(1))
            if execution is None:
                return None
            execution.status = ExecutionStatus.RUNNING
            execution.attempts += 1
            execution.started_at = execution.started_at or now
            execution.lease_until = now + timedelta(seconds=self.lease_seconds)
            session.flush()
            return execution

    def succeed(self, execution_id: str, result: dict) -> None:
        with self.sessions.begin() as session:
            record = session.get(ExecutionRecord, execution_id)
            if record is not None:
                record.status = ExecutionStatus.SUCCEEDED
                record.result_json = json.dumps(result, ensure_ascii=False)
                record.error = None
                record.finished_at = utc_now()
                record.lease_until = None

    def fail(self, execution_id: str, error: str, max_attempts: int = 3,
             result: dict[str, Any] | None = None,
             retry_interval_seconds: int | None = None) -> None:
        now = utc_now()
        with self.sessions.begin() as session:
            record = session.get(ExecutionRecord, execution_id)
            if record is None:
                return
            record.error = error[:4000]
            record.result_json = json.dumps(result, ensure_ascii=False) if result else None
            record.lease_until = None
            if record.attempts < max_attempts:
                record.status = ExecutionStatus.RETRY_WAIT
                delay = retry_interval_seconds
                if delay is None:
                    delay = 30 * (2 ** (record.attempts - 1))
                record.available_at = now + timedelta(seconds=max(delay, 1))
            else:
                record.status = ExecutionStatus.FAILED
                record.finished_at = now


class ExecutionService:
    def __init__(self, sessions: sessionmaker, queue: QueueService,
                 registry: HandlerRegistry) -> None:
        self.sessions = sessions
        self.queue = queue
        self.registry = registry

    async def run_one(self) -> bool:
        claimed = self.queue.claim()
        if claimed is None:
            return False
        max_attempts = 3
        retry_interval_seconds = None
        try:
            with self.sessions() as session:
                execution = session.get(ExecutionRecord, claimed.id)
                if execution is None:
                    raise RuntimeError("claimed execution disappeared")
                automation = execution.automation
                automation_config = json.loads(automation.config_json)
                if execution.config_override_json:
                    config_override = json.loads(execution.config_override_json)
                    if not isinstance(config_override, dict):
                        raise RuntimeError("execution configuration override must be an object")
                    automation_config.update(config_override)
                if (
                    automation.handler_type == "pt_signin"
                    or "max_retries" in automation_config
                    or "retry_interval_minutes" in automation_config
                ):
                    max_retries = _bounded_int(automation_config.get("max_retries"), 5, 0, 20)
                    retry_minutes = _bounded_int(
                        automation_config.get("retry_interval_minutes"), 120, 1, 10080
                    )
                    max_attempts = max_retries + 1
                    retry_interval_seconds = retry_minutes * 60
                context = RunContext(execution_id=execution.id, config=automation_config,
                                     cookies={}, browser_cookies=None, user_agent=None)
                handler = self.registry.get(automation.handler_type)
            result = await handler.run(context)
            result_payload = {"outcome": result.outcome, "message": result.message, "details": result.details}
            if result.outcome in {RunOutcome.SUCCESS, RunOutcome.ALREADY_DONE}:
                self.queue.succeed(claimed.id, result_payload)
            else:
                self.queue.fail(
                    claimed.id, result.message, max_attempts=max_attempts,
                    result=result_payload, retry_interval_seconds=retry_interval_seconds,
                )
        except Exception as exc:
            self.queue.fail(
                claimed.id, f"{type(exc).__name__}: {exc}", max_attempts=max_attempts,
                retry_interval_seconds=retry_interval_seconds,
            )
        return True


def reconcile_periodic_signin_templates(sessions: sessionmaker[Session]) -> int:
    changed = 0
    with sessions.begin() as session:
        automations = session.scalars(select(AutomationRecord).where(
            AutomationRecord.handler_type.in_(["browser_signin", "http_signin"])
        )).all()
        for automation in automations:
            try:
                config = json.loads(automation.config_json)
            except (TypeError, ValueError):
                continue
            handler_type, updated = apply_periodic_template(config, automation.handler_type)
            if handler_type == automation.handler_type and updated == config:
                continue
            automation.handler_type = handler_type
            automation.config_json = json.dumps(updated, ensure_ascii=False)
            changed += 1
    return changed


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return min(max(parsed, minimum), maximum)
