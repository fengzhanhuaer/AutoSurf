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


ROUSI_CREDENTIAL_NAME = "web-storage:rousi.pro"
ROUSI_DOMAIN = "rousi.pro"


class WebCredentialStore:
    def __init__(self, sessions: sessionmaker[Session], secrets: SecretBox,
                 credentials: CredentialService) -> None:
        self.sessions = sessions
        self.secrets = secrets
        self.credentials = credentials

    def status(self) -> dict[str, Any]:
        with self.sessions() as session:
            record = self._record(session)
            payload = self._payload(record)
            return {
                "site": "Rousi",
                "domain": ROUSI_DOMAIN,
                "script_configured": bool(payload.get("upload_key_hash")),
                "token_configured": bool(payload.get("values", {}).get("token")),
                "last_sync_at": payload.get("last_sync_at"),
                "credential_id": record.id if record else None,
                "credential_version": record.version if record else None,
            }

    def rotate_upload_key(self, upload_key: str) -> CredentialRecord:
        payload = self._current_payload()
        payload["upload_key_hash"] = _secret_hash(upload_key)
        return self._save(payload)

    def update_token(self, upload_key: str, token: str) -> tuple[CredentialRecord, bool]:
        token = token.strip()
        if not token:
            raise ValueError("token cannot be empty")
        payload = self._current_payload()
        expected = str(payload.get("upload_key_hash") or "")
        if not expected or not hmac.compare_digest(expected, _secret_hash(upload_key)):
            raise PermissionError("invalid upload key")
        values = payload.setdefault("values", {})
        changed = values.get("token") != token
        values["token"] = token
        payload["last_sync_at"] = utc_now().isoformat(timespec="seconds") + "Z"
        record = self._save(payload)
        self._bind_existing_rousi_tasks(record)
        return record, changed

    def clear_token(self) -> None:
        payload = self._current_payload()
        payload["values"] = {}
        payload["last_sync_at"] = None
        if payload.get("upload_key_hash"):
            self._save(payload)

    def _current_payload(self) -> dict[str, Any]:
        with self.sessions() as session:
            return self._payload(self._record(session))

    def _save(self, payload: dict[str, Any]) -> CredentialRecord:
        return self.credentials.upsert_web_storage(
            ROUSI_CREDENTIAL_NAME, ROUSI_DOMAIN, payload,
        )

    def _record(self, session: Session) -> CredentialRecord | None:
        return session.scalar(select(CredentialRecord).where(
            CredentialRecord.name == ROUSI_CREDENTIAL_NAME,
        ))

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

    def _bind_existing_rousi_tasks(self, credential: CredentialRecord) -> None:
        discovery = discover_pt_site(ROUSI_DOMAIN, {"token"})
        if discovery is None:
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
                if current_discovery is None or current_discovery.site_key != ROUSI_DOMAIN:
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
                    "sign_in_supported": True,
                    "profile_refresh_supported": False,
                    "sign_in_enabled": True,
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
