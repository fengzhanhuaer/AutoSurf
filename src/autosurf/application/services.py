from __future__ import annotations

import json
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, sessionmaker

from autosurf.application.registry import HandlerRegistry
from autosurf.domain.models import ExecutionStatus, RunContext, utc_now
from autosurf.infrastructure.crypto import SecretBox
from autosurf.infrastructure.database import AutomationRecord, CredentialRecord, ExecutionRecord


class CredentialService:
    def __init__(self, sessions: sessionmaker[Session], secrets: SecretBox) -> None:
        self.sessions = sessions
        self.secrets = secrets

    def upsert(self, name: str, domain: str, cookies: dict[str, str], provider: str = "manual") -> CredentialRecord:
        now = utc_now()
        with self.sessions.begin() as session:
            record = session.scalar(select(CredentialRecord).where(CredentialRecord.name == name))
            if record is None:
                record = CredentialRecord(id=str(uuid4()), name=name, provider=provider, domain=domain,
                                          encrypted_payload="", version=0, updated_at=now)
                session.add(record)
            record.domain = domain.lower().lstrip(".")
            record.provider = provider
            record.version += 1
            record.encrypted_payload = self.secrets.encrypt_json(cookies)
            record.updated_at = now
            session.flush()
            return record

    def cookies_for(self, record: CredentialRecord | None) -> dict[str, str]:
        if record is None:
            return {}
        return self.cookies_from_payload(record.encrypted_payload)

    def cookies_from_payload(self, payload: str | None) -> dict[str, str]:
        if payload is None:
            return {}
        value = self.secrets.decrypt_json(payload)
        if not isinstance(value, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
            raise ValueError("credential payload is not a cookie mapping")
        return value


class AutomationService:
    def __init__(self, sessions: sessionmaker[Session], registry: HandlerRegistry) -> None:
        self.sessions = sessions
        self.registry = registry

    def create(self, name: str, handler_type: str, interval_seconds: int, config: dict,
               credential_id: str | None = None) -> AutomationRecord:
        self.registry.get(handler_type)
        now = utc_now()
        record = AutomationRecord(id=str(uuid4()), name=name, handler_type=handler_type, enabled=True,
                                  interval_seconds=interval_seconds, next_run_at=now,
                                  config_json=json.dumps(config), credential_id=credential_id)
        with self.sessions.begin() as session:
            if credential_id is not None and session.get(CredentialRecord, credential_id) is None:
                raise ValueError("credential does not exist")
            session.add(record)
        return record


class QueueService:
    def __init__(self, sessions: sessionmaker[Session], lease_seconds: int) -> None:
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
                exists = session.scalar(select(ExecutionRecord.id).where(
                    ExecutionRecord.automation_id == automation.id,
                    ExecutionRecord.scheduled_at == scheduled_at,
                ))
                if exists is None:
                    session.add(ExecutionRecord(id=str(uuid4()), automation_id=automation.id,
                                                scheduled_at=scheduled_at, status=ExecutionStatus.PENDING,
                                                available_at=now, attempts=0,
                                                credential_version=automation.credential.version if automation.credential else None,
                                                credential_payload=automation.credential.encrypted_payload if automation.credential else None))
                    count += 1
                while automation.next_run_at <= now:
                    automation.next_run_at += timedelta(seconds=automation.interval_seconds)
        return count

    def enqueue_now(self, automation_id: str) -> ExecutionRecord:
        now = utc_now()
        with self.sessions.begin() as session:
            automation = session.get(AutomationRecord, automation_id)
            if automation is None:
                raise ValueError("automation does not exist")
            execution = ExecutionRecord(id=str(uuid4()), automation_id=automation.id, scheduled_at=now,
                                        status=ExecutionStatus.PENDING, available_at=now, attempts=0,
                                        credential_version=automation.credential.version if automation.credential else None,
                                        credential_payload=automation.credential.encrypted_payload if automation.credential else None)
            session.add(execution)
        return execution

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
                record.finished_at = utc_now()
                record.lease_until = None

    def fail(self, execution_id: str, error: str, max_attempts: int = 3) -> None:
        now = utc_now()
        with self.sessions.begin() as session:
            record = session.get(ExecutionRecord, execution_id)
            if record is None:
                return
            record.error = error[:4000]
            record.lease_until = None
            if record.attempts < max_attempts:
                record.status = ExecutionStatus.RETRY_WAIT
                record.available_at = now + timedelta(seconds=30 * (2 ** (record.attempts - 1)))
            else:
                record.status = ExecutionStatus.FAILED
                record.finished_at = now


class ExecutionService:
    def __init__(self, sessions: sessionmaker[Session], queue: QueueService,
                 credentials: CredentialService, registry: HandlerRegistry) -> None:
        self.sessions = sessions
        self.queue = queue
        self.credentials = credentials
        self.registry = registry

    async def run_one(self) -> bool:
        claimed = self.queue.claim()
        if claimed is None:
            return False
        try:
            with self.sessions() as session:
                execution = session.get(ExecutionRecord, claimed.id)
                if execution is None:
                    raise RuntimeError("claimed execution disappeared")
                automation = execution.automation
                cookies = self.credentials.cookies_from_payload(execution.credential_payload)
                context = RunContext(execution_id=execution.id, config=json.loads(automation.config_json), cookies=cookies)
                handler = self.registry.get(automation.handler_type)
            result = await handler.run(context)
            self.queue.succeed(claimed.id, {"outcome": result.outcome, "message": result.message,
                                            "details": result.details})
        except Exception as exc:
            self.queue.fail(claimed.id, f"{type(exc).__name__}: {exc}")
        return True
