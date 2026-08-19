from __future__ import annotations

import ipaddress
import json
import threading

from sqlalchemy.orm import Session, sessionmaker
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from autosurf.infrastructure.database import SystemSettingRecord


_LAN_NETWORKS = tuple(ipaddress.ip_network(value) for value in (
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "198.18.0.0/15",
    "127.0.0.0/8",
    "169.254.0.0/16",
    "::1/128",
    "fc00::/7",
    "fe80::/10",
))
_LAN_ONLY_SETTING_KEY = "access.lan_only"


def is_lan_address(host: str | None) -> bool:
    if not host:
        return False
    try:
        address = ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        return False
    return any(address in network for network in _LAN_NETWORKS if address.version == network.version)


class LanAccessMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, policy: "LanAccessPolicy") -> None:
        super().__init__(app)
        self._policy = policy

    async def dispatch(self, request: Request, call_next):
        client_host = request.client.host if request.client else None
        if self._policy.lan_only and not is_lan_address(client_host):
            return JSONResponse({"detail": "当前站点仅允许局域网访问"}, status_code=403)
        return await call_next(request)


class LanAccessPolicy:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions
        self._lock = threading.Lock()
        self._lan_only = self._load()

    @property
    def lan_only(self) -> bool:
        with self._lock:
            return self._lan_only

    def set_lan_only(self, enabled: bool) -> bool:
        value = bool(enabled)
        with self._lock:
            with self._sessions.begin() as session:
                record = session.get(SystemSettingRecord, _LAN_ONLY_SETTING_KEY)
                if record is None:
                    session.add(SystemSettingRecord(
                        key=_LAN_ONLY_SETTING_KEY,
                        value_json=json.dumps(value),
                    ))
                else:
                    record.value_json = json.dumps(value)
            self._lan_only = value
            return value

    def _load(self) -> bool:
        with self._sessions() as session:
            record = session.get(SystemSettingRecord, _LAN_ONLY_SETTING_KEY)
        if record is None:
            return True
        try:
            value = json.loads(record.value_json)
        except (TypeError, ValueError):
            return True
        return value if isinstance(value, bool) else True
