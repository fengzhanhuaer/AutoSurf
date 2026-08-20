from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, sessionmaker

from autosurf.application.registry import HandlerRegistry
from autosurf.domain.models import ExecutionStatus, RunContext, RunOutcome, utc_now
from autosurf.domain.scheduling import (
    SIGNIN_INTERVAL_SECONDS,
    SIGNIN_START_TIME,
    next_signin_run_at,
)
from autosurf.infrastructure.crypto import SecretBox
from autosurf.infrastructure.database import AutomationRecord, CredentialRecord, ExecutionRecord
from autosurf.pt_discovery import (
    PT_COOKIE_MARKERS,
    canonical_pt_site_domain,
    discover_pt_site,
    is_ignored_pt_domain,
    pt_site_domain_aliases,
)
from autosurf.periodic_templates import apply_periodic_template


class CredentialService:
    def __init__(self, sessions: sessionmaker[Session], secrets: SecretBox) -> None:
        self.sessions = sessions
        self.secrets = secrets

    def upsert(self, name: str, domain: str, cookies: dict[str, str], provider: str = "manual") -> CredentialRecord:
        if not all(isinstance(key, str) and isinstance(value, str) for key, value in cookies.items()):
            raise ValueError("cookies must be a string mapping")
        return self._upsert_payload(name, domain, cookies, provider)

    def upsert_cookie_records(self, name: str, domain: str, cookies: list[dict[str, Any]],
                              provider: str = "cookiecloud",
                              user_agent: str | None = None) -> CredentialRecord:
        if not cookies:
            raise ValueError("cookie records cannot be empty")
        payload = {"format": "cookie_records_v1", "cookies": cookies}
        if user_agent:
            payload["user_agent"] = str(user_agent)[:1024]
        return self._upsert_payload(name, domain, payload, provider)

    def upsert_web_storage(self, name: str, domain: str, payload: dict[str, Any]) -> CredentialRecord:
        if payload.get("format") != "web_storage_v1" or not isinstance(payload.get("values"), dict):
            raise ValueError("web storage credential payload is invalid")
        return self._upsert_payload(name, domain, payload, "web_storage")

    def _upsert_payload(self, name: str, domain: str, payload: Any, provider: str) -> CredentialRecord:
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
            record.encrypted_payload = self.secrets.encrypt_json(payload)
            record.updated_at = now
            session.flush()
            return record

    def cookies_for(self, record: CredentialRecord | None) -> dict[str, str]:
        if record is None:
            return {}
        return self.cookies_from_payload(record.encrypted_payload)

    def cookies_from_payload(self, payload: str | None) -> dict[str, str]:
        cookies, _ = self.credential_values_from_payload(payload)
        return cookies

    def browser_cookies_from_payload(self, payload: str | None) -> list[dict[str, Any]] | None:
        _, cookies = self.credential_values_from_payload(payload)
        return cookies

    def browser_user_agent_from_payload(self, payload: str | None) -> str | None:
        if payload is None:
            return None
        value = self.secrets.decrypt_json(payload)
        if not isinstance(value, dict) or value.get("format") != "cookie_records_v1":
            return None
        user_agent = value.get("user_agent")
        return str(user_agent)[:1024] if isinstance(user_agent, str) and user_agent.strip() else None

    def credential_values_from_payload(self, payload: str | None) -> tuple[dict[str, str], list[dict[str, Any]] | None]:
        if payload is None:
            return {}, None
        value = self.secrets.decrypt_json(payload)
        if isinstance(value, dict) and value.get("format") == "cookie_records_v1":
            records = value.get("cookies")
            if not isinstance(records, list):
                raise ValueError("credential cookie records are invalid")
            browser_cookies = [dict(item) for item in records if isinstance(item, dict)]
            cookies = {
                str(item["name"]): str(item["value"])
                for item in browser_cookies
                if item.get("name") is not None and item.get("value") is not None
            }
            if not cookies:
                raise ValueError("credential cookie records are empty")
            return cookies, browser_cookies
        if isinstance(value, dict) and value.get("format") == "web_storage_v1":
            values = value.get("values")
            if not isinstance(values, dict) or not all(
                isinstance(key, str) and isinstance(item, str)
                for key, item in values.items()
            ):
                raise ValueError("web storage credential values are invalid")
            return dict(values), []
        if not isinstance(value, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
            raise ValueError("credential payload is not a cookie mapping")
        return value, None

    def merged_cookiecloud_snapshot(self, records: list[CredentialRecord]) -> tuple[int | None, str | None]:
        if not records:
            return None, None
        merged: dict[tuple[str, str, str], dict[str, Any]] = {}
        user_agent = None
        for record in sorted(records, key=lambda item: (item.updated_at, item.domain, item.name)):
            current_user_agent = self.browser_user_agent_from_payload(record.encrypted_payload)
            if current_user_agent:
                user_agent = current_user_agent
            _, browser_cookies = self.credential_values_from_payload(record.encrypted_payload)
            if browser_cookies is None:
                continue
            for cookie in browser_cookies:
                if cookie.get("name") is None or cookie.get("value") is None:
                    continue
                key = (
                    str(cookie["name"]),
                    str(cookie.get("domain") or record.domain).lower().lstrip("."),
                    str(cookie.get("path") or "/"),
                )
                merged[key] = dict(cookie)
        if not merged:
            primary = records[-1]
            return primary.version, primary.encrypted_payload
        payload = {
            "format": "cookie_records_v1",
            "cookies": list(merged.values()),
        }
        if user_agent:
            payload["user_agent"] = user_agent
        return max(record.version for record in records), self.secrets.encrypt_json(payload)


class AutomationService:
    def __init__(self, sessions: sessionmaker[Session], registry: HandlerRegistry) -> None:
        self.sessions = sessions
        self.registry = registry

    def create(self, name: str, handler_type: str, interval_seconds: int, config: dict,
               credential_id: str | None = None,
               next_run_at: datetime | None = None) -> AutomationRecord:
        self.registry.get(handler_type)
        now = utc_now()
        record = AutomationRecord(id=str(uuid4()), name=name, handler_type=handler_type, enabled=True,
                                  interval_seconds=interval_seconds, next_run_at=next_run_at or now,
                                  config_json=json.dumps(config), credential_id=credential_id)
        with self.sessions.begin() as session:
            if credential_id is not None and session.get(CredentialRecord, credential_id) is None:
                raise ValueError("credential does not exist")
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


def align_all_signin_schedules(sessions: sessionmaker[Session]) -> tuple[int, datetime]:
    return _align_signin_schedules(sessions, only_missing=False)


class QueueService:
    def __init__(self, sessions: sessionmaker[Session], lease_seconds: int,
                 credentials: CredentialService | None = None) -> None:
        self.sessions = sessions
        self.lease_seconds = lease_seconds
        self.credentials = credentials

    def _credential_snapshot(self, session: Session,
                             automation: AutomationRecord) -> tuple[int | None, str | None]:
        credential = automation.credential
        if credential is None:
            return None, None
        if (
            credential.provider != "cookiecloud"
            or self.credentials is None
        ):
            return credential.version, credential.encrypted_payload
        aliases = pt_site_domain_aliases(credential.domain)
        related = session.scalars(select(CredentialRecord).where(
            CredentialRecord.provider == "cookiecloud",
            CredentialRecord.domain.in_(aliases),
        )).all()
        return self.credentials.merged_cookiecloud_snapshot(related)

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
                    credential_version, credential_payload = self._credential_snapshot(session, automation)
                    session.add(ExecutionRecord(id=str(uuid4()), automation_id=automation.id,
                                                scheduled_at=scheduled_at, status=ExecutionStatus.PENDING,
                                                available_at=now + timedelta(seconds=random_delay_seconds), attempts=0,
                                                credential_version=credential_version,
                                                credential_payload=credential_payload))
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
            existing = session.scalar(select(ExecutionRecord).where(
                ExecutionRecord.automation_id == automation.id,
                ExecutionRecord.status.in_([
                    ExecutionStatus.PENDING, ExecutionStatus.RUNNING, ExecutionStatus.RETRY_WAIT,
                ]),
            ).order_by(ExecutionRecord.scheduled_at.desc()).limit(1))
            if existing is not None:
                if existing.status in {ExecutionStatus.PENDING, ExecutionStatus.RETRY_WAIT}:
                    credential_version, credential_payload = self._credential_snapshot(
                        session, automation
                    )
                    existing.credential_version = credential_version
                    existing.credential_payload = credential_payload
                    existing.available_at = now
                session.flush()
                return existing
            credential_version, credential_payload = self._credential_snapshot(session, automation)
            execution = ExecutionRecord(id=str(uuid4()), automation_id=automation.id, scheduled_at=now,
                                        status=ExecutionStatus.PENDING, available_at=now, attempts=0,
                                        credential_version=credential_version,
                                        credential_payload=credential_payload)
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
        max_attempts = 3
        retry_interval_seconds = None
        try:
            with self.sessions() as session:
                execution = session.get(ExecutionRecord, claimed.id)
                if execution is None:
                    raise RuntimeError("claimed execution disappeared")
                automation = execution.automation
                automation_config = json.loads(automation.config_json)
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
                cookies, browser_cookies = self.credentials.credential_values_from_payload(
                    execution.credential_payload
                )
                browser_user_agent = self.credentials.browser_user_agent_from_payload(
                    execution.credential_payload
                )
                context = RunContext(execution_id=execution.id, config=automation_config,
                                     cookies=cookies, browser_cookies=browser_cookies,
                                     user_agent=browser_user_agent)
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


def reconcile_pt_site_aliases(sessions: sessionmaker[Session],
                              credentials: CredentialService) -> int:
    merged_count = 0
    now = utc_now()
    with sessions.begin() as session:
        automations = session.scalars(select(AutomationRecord).where(
            AutomationRecord.handler_type == "pt_signin"
        ).order_by(AutomationRecord.name, AutomationRecord.id)).all()
        groups: dict[str, list[AutomationRecord]] = {}
        for automation in automations:
            credential = automation.credential
            if credential is None or credential.provider != "cookiecloud":
                continue
            groups.setdefault(canonical_pt_site_domain(credential.domain), []).append(automation)

        for records in groups.values():
            if len(records) < 2:
                continue

            def score(automation: AutomationRecord) -> tuple[int, int, bool, Any, str]:
                credential = automation.credential
                try:
                    cookie_names = set(credentials.cookies_for(credential))
                except ValueError:
                    cookie_names = set()
                return (
                    len({name.lower() for name in cookie_names}.intersection(PT_COOKIE_MARKERS)),
                    len(cookie_names),
                    credential.domain.startswith("www."),
                    credential.updated_at,
                    automation.id,
                )

            primary = max(records, key=score)
            primary.enabled = any(record.enabled for record in records)
            primary.next_run_at = min(record.next_run_at for record in records)
            configs = []
            for record in records:
                try:
                    configs.append(json.loads(record.config_json))
                except (TypeError, ValueError):
                    configs.append({})
            primary_config = configs[records.index(primary)]
            primary_config["sign_in_enabled"] = any(
                config.get("sign_in_enabled", True) for config in configs
            )
            primary_config["profile_refresh_enabled"] = any(
                config.get("profile_refresh_enabled", False) for config in configs
            )
            primary.config_json = json.dumps(primary_config, ensure_ascii=False)
            try:
                primary_cookie_names = set(credentials.cookies_for(primary.credential))
            except ValueError:
                primary_cookie_names = set()
            primary_discovery = discover_pt_site(
                primary.credential.domain,
                primary_cookie_names,
            )
            if primary_discovery:
                primary.name = primary_discovery.name
            duplicate_ids = {record.id for record in records if record.id != primary.id}
            executions = session.scalars(select(ExecutionRecord).where(
                ExecutionRecord.automation_id.in_(duplicate_ids)
            )).all()
            for execution in executions:
                execution.automation_id = primary.id
            for record in records:
                if record.id != primary.id:
                    session.delete(record)
                    merged_count += 1
            session.flush()

            active = session.scalars(select(ExecutionRecord).where(
                ExecutionRecord.automation_id == primary.id,
                ExecutionRecord.status.in_([
                    ExecutionStatus.PENDING, ExecutionStatus.RUNNING, ExecutionStatus.RETRY_WAIT,
                ]),
            ).order_by(ExecutionRecord.available_at, ExecutionRecord.scheduled_at)).all()
            for execution in active[1:]:
                execution.status = ExecutionStatus.CANCELLED
                execution.lease_until = None
                execution.finished_at = now
                execution.error = "同一 PT 站点的重复任务已合并"

        session.flush()
        remaining = session.scalars(select(AutomationRecord).where(
            AutomationRecord.handler_type == "pt_signin"
        )).all()
        for automation in remaining:
            credential = automation.credential
            if credential is None or credential.provider not in {"cookiecloud", "web_storage"}:
                continue
            try:
                config = json.loads(automation.config_json)
            except (TypeError, ValueError):
                config = {}
            if is_ignored_pt_domain(credential.domain):
                automation.enabled = False
                config.update({
                    "sign_in_enabled": False,
                    "profile_refresh_enabled": False,
                    "sign_in_supported": False,
                    "profile_refresh_supported": False,
                })
                automation.config_json = json.dumps(config, ensure_ascii=False)
                active = session.scalars(select(ExecutionRecord).where(
                    ExecutionRecord.automation_id == automation.id,
                    ExecutionRecord.status.in_([
                        ExecutionStatus.PENDING,
                        ExecutionStatus.RUNNING,
                        ExecutionStatus.RETRY_WAIT,
                    ]),
                )).all()
                for execution in active:
                    execution.status = ExecutionStatus.CANCELLED
                    execution.lease_until = None
                    execution.finished_at = now
                    execution.error = "站点已停用"
                continue
            try:
                credential_markers = set(credentials.cookies_for(credential))
            except ValueError:
                credential_markers = set()
            discovery = discover_pt_site(credential.domain, credential_markers)
            if discovery and config.get("discovered"):
                changed = False
                newly_cataloged = (
                    config.get("discovery_reason") == "cookie_signature"
                    and discovery.reason == "site_catalog"
                )
                if credential.provider == "cookiecloud":
                    aliases = pt_site_domain_aliases(credential.domain)
                    related = session.scalars(select(CredentialRecord).where(
                        CredentialRecord.provider == "cookiecloud",
                        CredentialRecord.domain.in_(aliases),
                    )).all()
                    current_credentials = [
                        item for item in related
                        if item.domain.removeprefix("www.") == discovery.site_key
                    ]
                    if current_credentials:
                        def current_score(item: CredentialRecord) -> tuple[int, int, bool, Any, str]:
                            try:
                                cookie_names = set(credentials.cookies_for(item))
                            except ValueError:
                                cookie_names = set()
                            return (
                                len({name.lower() for name in cookie_names}.intersection(PT_COOKIE_MARKERS)),
                                len(cookie_names),
                                item.domain.startswith("www."),
                                item.updated_at,
                                item.id,
                            )

                        preferred = max(current_credentials, key=current_score)
                        if automation.credential_id != preferred.id:
                            automation.credential = preferred
                            credential = preferred
                            changed = True
                if config.get("url") != discovery.url:
                    config["url"] = discovery.url
                    changed = True
                if config.get("credential_domain") != discovery.site_key:
                    config["credential_domain"] = discovery.site_key
                    changed = True
                if config.get("discovery_strategy") != discovery.strategy:
                    config["discovery_strategy"] = discovery.strategy
                    changed = True
                if config.get("discovery_reason") != discovery.reason:
                    config["discovery_reason"] = discovery.reason
                    changed = True
                if config.get("profile_url") != discovery.profile_url:
                    config["profile_url"] = discovery.profile_url
                    changed = True
                if automation.name != discovery.name:
                    automation.name = discovery.name
                    changed = True
                previous_sign_in_supported = bool(config.get("sign_in_supported", True))
                previous_profile_refresh_supported = bool(
                    config.get("profile_refresh_supported", True)
                )
                if config.get("sign_in_supported") != discovery.sign_in_supported:
                    config["sign_in_supported"] = discovery.sign_in_supported
                    changed = True
                if config.get("profile_refresh_supported") != discovery.profile_refresh_supported:
                    config["profile_refresh_supported"] = discovery.profile_refresh_supported
                    changed = True
                if discovery.sign_in_supported and not previous_sign_in_supported:
                    config["sign_in_enabled"] = True
                    changed = True
                if not discovery.sign_in_supported and config.get("sign_in_enabled", True):
                    config["sign_in_enabled"] = False
                    changed = True
                    if discovery.profile_refresh_supported and previous_sign_in_supported:
                        config["profile_refresh_enabled"] = True
                if (
                    discovery.default_profile_refresh_enabled
                    and discovery.profile_refresh_supported
                    and (newly_cataloged or not previous_profile_refresh_supported)
                    and not config.get("profile_refresh_enabled", False)
                ):
                    config["profile_refresh_enabled"] = True
                    changed = True
                if not discovery.supported and automation.enabled:
                    automation.enabled = False
                    changed = True
                if changed:
                    automation.config_json = json.dumps(config, ensure_ascii=False)
                if not discovery.supported:
                    active = session.scalars(select(ExecutionRecord).where(
                        ExecutionRecord.automation_id == automation.id,
                        ExecutionRecord.status.in_([
                            ExecutionStatus.PENDING,
                            ExecutionStatus.RUNNING,
                            ExecutionStatus.RETRY_WAIT,
                        ]),
                    )).all()
                    for execution in active:
                        execution.status = ExecutionStatus.CANCELLED
                        execution.lease_until = None
                        execution.finished_at = now
                        execution.error = "站点当前没有可自动执行的操作"
            if config.get("credential_aliases_merged"):
                continue
            aliases = pt_site_domain_aliases(credential.domain)
            related = session.scalars(select(CredentialRecord).where(
                CredentialRecord.provider == "cookiecloud",
                CredentialRecord.domain.in_(aliases),
            )).all()
            if len(related) < 2:
                continue
            version, payload = credentials.merged_cookiecloud_snapshot(related)
            active = session.scalar(select(ExecutionRecord).where(
                ExecutionRecord.automation_id == automation.id,
                ExecutionRecord.status.in_([
                    ExecutionStatus.PENDING, ExecutionStatus.RUNNING, ExecutionStatus.RETRY_WAIT,
                ]),
            ).order_by(ExecutionRecord.available_at, ExecutionRecord.scheduled_at).limit(1))
            if active is not None:
                active.credential_version = version
                active.credential_payload = payload
            config["credential_aliases_merged"] = True
            automation.config_json = json.dumps(config, ensure_ascii=False)
    return merged_count


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
