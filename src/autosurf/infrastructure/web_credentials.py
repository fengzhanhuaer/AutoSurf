from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from autosurf.application.services import CredentialService
from autosurf.domain.models import utc_now
from autosurf.infrastructure.crypto import SecretBox
from autosurf.infrastructure.database import AutomationRecord, CredentialRecord
from autosurf.pt_discovery import discover_pt_site
from autosurf.userscripts import WEB_CREDENTIAL_SCRIPT_SOURCES, web_credential_script_source


class WebCredentialStore:
    def __init__(self, sessions: sessionmaker[Session], secrets: SecretBox,
                 credentials: CredentialService) -> None:
        self.sessions = sessions
        self.secrets = secrets
        self.credentials = credentials

    def statuses(self) -> dict[str, Any]:
        return {"items": [self.status(source_key) for source_key in WEB_CREDENTIAL_SCRIPT_SOURCES]}

    def status(self, source_key: str = "rousi") -> dict[str, Any]:
        source = web_credential_script_source(source_key)
        with self.sessions() as session:
            record = self._record(session, source_key)
            payload = self._payload(record)
            configured_keys = sorted(
                key for key, value in payload.get("values", {}).items()
                if isinstance(value, str) and value
            )
            configured = all(key in configured_keys for key in source.required_storage_keys)
            return {
                "source_key": source.key,
                "site": source.name,
                "domain": source.domain,
                "script_configured": bool(payload.get("upload_key_hash")),
                "credential_configured": configured,
                "token_configured": configured,
                "configured_keys": configured_keys,
                "last_sync_at": payload.get("last_sync_at"),
                "credential_id": record.id if record else None,
                "credential_version": record.version if record else None,
            }

    def rotate_upload_key(self, source_key: str, upload_key: str | None = None) -> CredentialRecord:
        if upload_key is None:
            upload_key = source_key
            source_key = "rousi"
        payload = self._current_payload(source_key)
        payload["upload_key_hash"] = _secret_hash(upload_key)
        return self._save(source_key, payload)

    def update_values(self, source_key: str, upload_key: str,
                      supplied_values: dict[str, str]) -> tuple[CredentialRecord, bool]:
        source = web_credential_script_source(source_key)
        unknown_keys = set(supplied_values) - set(source.storage_keys)
        if unknown_keys:
            raise ValueError(f"unsupported storage key: {sorted(unknown_keys)[0]}")
        values = {
            key: value.strip()
            for key, value in supplied_values.items()
            if isinstance(value, str) and value.strip()
        }
        missing = set(source.required_storage_keys) - set(values)
        if missing:
            raise ValueError(f"missing storage key: {sorted(missing)[0]}")
        if any(len(value) > 8192 for value in values.values()):
            raise ValueError("web credential value is too long")

        payload = self._current_payload(source_key)
        expected = str(payload.get("upload_key_hash") or "")
        if not expected or not hmac.compare_digest(expected, _secret_hash(upload_key)):
            raise PermissionError("invalid upload key")
        changed = payload.get("values", {}) != values
        payload["values"] = values
        payload["last_sync_at"] = utc_now().isoformat(timespec="seconds") + "Z"
        record = self._save(source_key, payload)
        self._bind_existing_tasks(source_key, record, set(values))
        return record, changed

    def update_token(self, upload_key: str, token: str) -> tuple[CredentialRecord, bool]:
        return self.update_values("rousi", upload_key, {"token": token})

    def clear_values(self, source_key: str) -> None:
        payload = self._current_payload(source_key)
        payload["values"] = {}
        payload["last_sync_at"] = None
        if payload.get("upload_key_hash"):
            self._save(source_key, payload)

    def clear_token(self) -> None:
        self.clear_values("rousi")

    def _current_payload(self, source_key: str) -> dict[str, Any]:
        with self.sessions() as session:
            return self._payload(self._record(session, source_key))

    def _save(self, source_key: str, payload: dict[str, Any]) -> CredentialRecord:
        source = web_credential_script_source(source_key)
        return self.credentials.upsert_web_storage(
            self._credential_name(source_key), source.domain, payload,
        )

    def _record(self, session: Session, source_key: str) -> CredentialRecord | None:
        return session.scalar(select(CredentialRecord).where(
            CredentialRecord.name == self._credential_name(source_key),
        ))

    @staticmethod
    def _credential_name(source_key: str) -> str:
        return f"web-storage:{web_credential_script_source(source_key).domain}"

    def _payload(self, record: CredentialRecord | None) -> dict[str, Any]:
        if record is None:
            return {"format": "web_storage_v1", "values": {}}
        value = self.secrets.decrypt_json(record.encrypted_payload)
        if not isinstance(value, dict) or value.get("format") != "web_storage_v1":
            raise ValueError("web credential payload is invalid")
        values = value.get("values")
        if not isinstance(values, dict):
            raise ValueError("web credential values are invalid")
        return dict(value)

    def _bind_existing_tasks(self, source_key: str, credential: CredentialRecord,
                             storage_keys: set[str]) -> None:
        source = web_credential_script_source(source_key)
        discovery = discover_pt_site(source.domain, storage_keys)
        if discovery is None or not discovery.supported:
            return
        with self.sessions.begin() as session:
            records = session.scalars(select(AutomationRecord).where(
                AutomationRecord.handler_type == "pt_signin",
            )).all()
            for record in records:
                current = record.credential
                if current is None:
                    continue
                current_discovery = discover_pt_site(current.domain, set())
                if current_discovery is None or current_discovery.site_key != discovery.site_key:
                    continue
                config = _json_object(record.config_json)
                was_unsupported = not bool(config.get("sign_in_supported", False))
                record.credential_id = credential.id
                record.name = discovery.name
                if was_unsupported:
                    record.enabled = True
                    record.next_run_at = utc_now()
                config.update({
                    "url": discovery.url,
                    "credential_domain": discovery.site_key,
                    "discovery_strategy": discovery.strategy,
                    "profile_url": discovery.profile_url,
                    "sign_in_supported": discovery.sign_in_supported,
                    "profile_refresh_supported": discovery.profile_refresh_supported,
                    "sign_in_enabled": discovery.sign_in_supported,
                })
                record.config_json = _json_dump(config)


def _secret_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _json_object(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _json_dump(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False)
