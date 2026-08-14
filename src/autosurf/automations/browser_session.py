from __future__ import annotations

from typing import Any
from urllib.parse import ParseResult, urlparse

from autosurf.domain.models import RunContext


def validated_http_url(value: str) -> ParseResult:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("url must be an absolute HTTP(S) URL")
    return parsed


def playwright_cookies(context: RunContext, url: str) -> list[dict[str, Any]]:
    parsed = validated_http_url(url)
    hostname = parsed.hostname or ""
    if not context.browser_cookies:
        return [
            {
                "name": name,
                "value": value,
                "domain": hostname,
                "path": "/",
                "secure": parsed.scheme == "https",
            }
            for name, value in context.cookies.items()
        ]

    result: list[dict[str, Any]] = []
    for source in context.browser_cookies:
        if source.get("name") is None or source.get("value") is None:
            continue
        domain = str(source.get("domain") or hostname).lower().lstrip(".")
        if hostname != domain and not hostname.endswith(f".{domain}"):
            continue
        item: dict[str, Any] = {
            "name": str(source["name"]),
            "value": str(source["value"]),
            "domain": str(source.get("domain") or hostname),
            "path": str(source.get("path") or "/"),
            "secure": bool(source.get("secure", parsed.scheme == "https")),
            "httpOnly": bool(source.get("httpOnly", False)),
        }
        if source.get("sameSite") in {"Strict", "Lax", "None"}:
            item["sameSite"] = source["sameSite"]
        expires = source.get("expires")
        if isinstance(expires, (int, float)) and not isinstance(expires, bool) and expires > 0:
            item["expires"] = float(expires)
        result.append(item)
    return result
