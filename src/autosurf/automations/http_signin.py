from __future__ import annotations

import re
from urllib.parse import urlparse

import httpx

from autosurf.domain.models import RunContext, RunOutcome, RunResult


class HttpSignInHandler:
    type = "http_signin"

    async def run(self, context: RunContext) -> RunResult:
        config = context.config
        url = str(config["url"])
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("url must be an absolute HTTP(S) URL")

        method = str(config.get("method", "GET")).upper()
        if method not in {"GET", "POST"}:
            raise ValueError("only GET and POST are supported")

        timeout = min(max(float(config.get("timeout_seconds", 30)), 1), 120)
        headers = {
            "User-Agent": str(config.get("user_agent") or context.user_agent or "AutoSurf/0.1"),
            "Accept": "application/json, text/plain, */*",
        }
        async with httpx.AsyncClient(follow_redirects=True, timeout=timeout, cookies=context.cookies,
                                     headers=headers) as client:
            response = await client.request(method, url, data=config.get("form"))

        body = response.text[:1_000_000]
        details = {"url": str(response.url), "status_code": response.status_code}
        if response.status_code in {401, 403}:
            return RunResult(
                RunOutcome.AUTH_EXPIRED, f"site returned HTTP {response.status_code}", details,
            )
        for pattern in config.get("auth_expired_patterns", []):
            if re.search(str(pattern), body, re.IGNORECASE):
                return RunResult(
                    RunOutcome.AUTH_EXPIRED, "site reports that login has expired", details,
                )
        for pattern in config.get("already_patterns", []):
            if re.search(pattern, body, re.IGNORECASE):
                return RunResult(
                    RunOutcome.ALREADY_DONE, "site reports this task is already complete", details,
                )
        for pattern in config.get("success_patterns", []):
            if re.search(pattern, body, re.IGNORECASE):
                return RunResult(RunOutcome.SUCCESS, "success pattern matched", details)
        if response.is_success and not config.get("success_patterns"):
            return RunResult(
                RunOutcome.SUCCESS, f"request completed with HTTP {response.status_code}", details,
            )
        return RunResult(
            RunOutcome.FAILED, f"no success pattern matched (HTTP {response.status_code})", details,
        )
