from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from autosurf.domain.models import utc_now
from autosurf.infrastructure.database import CookieCloudBlob


class CookieCloudStore:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self.sessions = sessions

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

    def get(self, uuid: str) -> dict[str, Any] | None:
        with self.sessions() as session:
            blob = session.get(CookieCloudBlob, uuid)
            return json.loads(blob.encrypted_data) if blob else None
