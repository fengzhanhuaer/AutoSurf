from __future__ import annotations

import ipaddress
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


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


def is_lan_address(host: str | None) -> bool:
    if not host:
        return False
    try:
        address = ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        return False
    return any(address in network for network in _LAN_NETWORKS if address.version == network.version)


class LanAccessMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        client_host = request.client.host if request.client else None
        if not is_lan_address(client_host):
            return JSONResponse({"detail": "当前站点仅允许局域网访问"}, status_code=403)
        return await call_next(request)
