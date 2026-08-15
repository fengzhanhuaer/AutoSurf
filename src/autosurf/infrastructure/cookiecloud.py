from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from autosurf.domain.models import utc_now
from autosurf.application.services import CredentialService
from autosurf.infrastructure.cookiecloud_crypto import decrypt_cookiecloud
from autosurf.infrastructure.crypto import SecretBox
from autosurf.infrastructure.database import CookieCloudBlob, CookieCloudSource


class CookieCloudStore:
    def __init__(self, sessions: sessionmaker[Session], secrets: SecretBox,
                 credentials: CredentialService) -> None:
        self.sessions = sessions
        self.secrets = secrets
        self.credentials = credentials

    def put(self, payload: dict[str, Any]) -> str:
        uuid = str(payload.get("uuid") or payload.get("key") or "").strip()
        if not uuid or len(uuid) > 128:
            raise ValueError("CookieCloud payload requires a valid uuid")
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        with self.sessions.begin() as session:
            blob = session.get(CookieCloudBlob, uuid)
            if blob is None:
                blob = CookieCloudBlob(uuid=uuid, encrypted_data=raw, updated_at=utc_now())
                session.add(blob)
            else:
                blob.encrypted_data = raw
                blob.updated_at = utc_now()
        return uuid

    def configure(self, uuid: str, password: str | None, auto_import: bool = True) -> CookieCloudSource:
        if not uuid or len(uuid) > 128:
            raise ValueError("invalid CookieCloud UUID")
        with self.sessions.begin() as session:
            source = session.get(CookieCloudSource, uuid)
            if source is None:
                if password is None:
                    raise ValueError("CookieCloud password is required for a new source")
                source = CookieCloudSource(uuid=uuid, encrypted_password="", auto_import=auto_import)
                session.add(source)
            if password is not None:
                source.encrypted_password = self.secrets.encrypt_json(password)
            source.auto_import = auto_import
            source.last_error = None
            session.flush()
            return source

    def set_auto_import(self, uuid: str, auto_import: bool) -> CookieCloudSource:
        with self.sessions.begin() as session:
            source = session.get(CookieCloudSource, uuid)
            if source is None:
                raise ValueError("CookieCloud source has not been configured")
            source.auto_import = auto_import
            source.last_error = None
            session.flush()
            return source

    def password_for(self, uuid: str) -> str:
        with self.sessions() as session:
            source = session.get(CookieCloudSource, uuid)
            if source is None or not source.encrypted_password:
                raise ValueError("CookieCloud password has not been configured")
            password = self.secrets.decrypt_json(source.encrypted_password)
        if not isinstance(password, str) or not password:
            raise ValueError("CookieCloud password is invalid")
        return password

    def import_credentials(self, uuid: str, password: str | None = None) -> dict[str, Any]:
        with self.sessions() as session:
            blob = session.get(CookieCloudBlob, uuid)
            source = session.get(CookieCloudSource, uuid)
            if blob is None:
                raise ValueError("CookieCloud key not found")
            payload = json.loads(blob.encrypted_data)
            if password is None:
                if source is None:
                    raise ValueError("CookieCloud password has not been configured")
                password = self.secrets.decrypt_json(source.encrypted_password)

        decrypted = decrypt_cookiecloud(uuid, password, str(payload.get("encrypted", "")),
                                        str(payload.get("crypto_type", "legacy")))
        imported: list[dict[str, Any]] = []
        for bucket, entries in decrypted["cookie_data"].items():
            if not isinstance(entries, list):
                continue
            domain = _canonical_domain(str(bucket), entries)
            cookies = [
                normalized
                for cookie in entries
                if isinstance(cookie, dict)
                for normalized in [_cookie_record(cookie, domain)]
                if normalized is not None
            ]
            if not domain or not cookies:
                continue
            record = self.credentials.upsert_cookie_records(
                f"cookiecloud:{uuid}:{domain}", domain, cookies, "cookiecloud"
            )
            imported.append({"id": record.id, "domain": domain, "version": record.version,
                             "cookie_count": len(cookies)})

        now = utc_now()
        if source is not None:
            with self.sessions.begin() as session:
                current = session.get(CookieCloudSource, uuid)
                current.last_import_at = now
                current.last_error = None
        return {"uuid": uuid, "update_time": decrypted.get("update_time"), "credentials": imported}

    def auto_import_if_configured(self, uuid: str) -> dict[str, Any] | None:
        with self.sessions() as session:
            source = session.get(CookieCloudSource, uuid)
            enabled = bool(source and source.auto_import)
        if not enabled:
            return None
        try:
            return self.import_credentials(uuid)
        except ValueError as exc:
            with self.sessions.begin() as session:
                current = session.get(CookieCloudSource, uuid)
                if current:
                    current.last_error = str(exc)
            raise

    def get(self, uuid: str) -> dict[str, Any] | None:
        with self.sessions() as session:
            blob = session.get(CookieCloudBlob, uuid)
            return json.loads(blob.encrypted_data) if blob else None


def _canonical_domain(bucket: str, entries: list[Any]) -> str:
    domain = bucket
    for cookie in entries:
        if isinstance(cookie, dict) and cookie.get("domain"):
            domain = str(cookie["domain"])
            break
    return domain.lower().strip().lstrip(".")


def _cookie_record(cookie: dict[str, Any], fallback_domain: str) -> dict[str, Any] | None:
    if cookie.get("name") is None or cookie.get("value") is None:
        return None
    record: dict[str, Any] = {
        "name": str(cookie["name"]),
        "value": str(cookie["value"]),
        "domain": str(cookie.get("domain") or fallback_domain).lower().strip(),
        "path": str(cookie.get("path") or "/"),
        "secure": bool(cookie.get("secure", False)),
        "httpOnly": bool(cookie.get("httpOnly", False)),
    }
    same_site = str(cookie.get("sameSite") or "").lower()
    same_site_values = {"strict": "Strict", "lax": "Lax", "none": "None", "no_restriction": "None"}
    if same_site in same_site_values:
        record["sameSite"] = same_site_values[same_site]
    expires = cookie.get("expirationDate", cookie.get("expires"))
    if isinstance(expires, (int, float)) and not isinstance(expires, bool) and expires > 0:
        record["expires"] = float(expires)
    return record
