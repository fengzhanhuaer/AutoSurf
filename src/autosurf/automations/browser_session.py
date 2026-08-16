from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import ParseResult, urlparse

from autosurf.domain.models import RunContext, RunResult


WAF_COOKIE_NAMES = frozenset({
    "cf_clearance",
    "sl-challenge-server",
    "sl-session",
})
SHARED_PROFILE_KEY = "shared"
_PROFILE_LOCKS: dict[str, asyncio.Lock] = {}


@dataclass(frozen=True)
class PersistentBrowserSession:
    context: Any
    profile_key: str
    mode: str


@dataclass
class VirtualDisplay:
    name: str
    process: subprocess.Popen[bytes]


def validated_http_url(value: str) -> ParseResult:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("url must be an absolute HTTP(S) URL")
    return parsed


def playwright_cookies(context: RunContext, url: str) -> list[dict[str, Any]]:
    parsed = validated_http_url(url)
    hostname = parsed.hostname or ""
    if context.browser_cookies is None:
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


def browser_profile_path() -> Path:
    configured = os.environ.get("AUTOSURF_BROWSER_PROFILE_DIR", "").strip()
    if configured:
        root = Path(configured)
    elif os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "").strip():
        root = Path(os.environ["PLAYWRIGHT_BROWSERS_PATH"]) / "profiles"
    else:
        root = Path(os.environ.get("AUTOSURF_DATA_DIR", "data")) / "browser-profiles"
    return root / SHARED_PROFILE_KEY


def persistent_browser_mode() -> str:
    configured = os.environ.get("AUTOSURF_BROWSER_HEADLESS", "").strip().casefold()
    force_headless = configured in {"1", "true", "yes", "on"}
    return "persistent_headless" if force_headless or not shutil.which("Xvfb") else "persistent_headful"


@asynccontextmanager
async def persistent_chromium_session(
    playwright: Any,
    run_context: RunContext,
    url: str,
):
    validated_http_url(url)
    profile_path = browser_profile_path()
    lock = _PROFILE_LOCKS.setdefault(str(profile_path), asyncio.Lock())

    async with lock:
        await _prepare_shared_profile(profile_path)
        mode = persistent_browser_mode()
        display = None
        browser_context = None
        try:
            launch_env = dict(os.environ)
            if mode == "persistent_headful":
                display = await _start_virtual_display()
                launch_env["DISPLAY"] = display.name
            kwargs: dict[str, Any] = {
                "headless": mode == "persistent_headless",
                "executable_path": playwright.chromium.executable_path,
                "locale": str(run_context.config.get("locale", "zh-CN")),
                "viewport": {"width": 1365, "height": 768},
                "env": launch_env,
                "args": ["--disable-dev-shm-usage"],
            }
            user_agent = run_context.config.get("user_agent")
            if user_agent:
                kwargs["user_agent"] = str(user_agent)
            browser_context = await playwright.chromium.launch_persistent_context(
                str(profile_path), **kwargs,
            )
            await _restore_waf_cookie_state(browser_context, profile_path, url)
            await supplement_playwright_cookies(browser_context, run_context, url)
            yield PersistentBrowserSession(browser_context, SHARED_PROFILE_KEY, mode)
        finally:
            if browser_context is not None:
                with suppress(Exception):
                    await _save_waf_cookie_state(browser_context, profile_path, url)
                with suppress(Exception):
                    await browser_context.close()
            if display is not None:
                await _stop_virtual_display(display)


async def supplement_playwright_cookies(browser_context: Any, context: RunContext, url: str) -> None:
    incoming = playwright_cookies(context, url)
    if not incoming:
        return
    parsed = validated_http_url(url)
    origin = f"{parsed.scheme}://{parsed.netloc}/"
    existing = await browser_context.cookies([origin])
    existing_keys = {_cookie_key(item) for item in existing}
    updates = [
        item for item in incoming
        if item["name"].casefold() not in WAF_COOKIE_NAMES or _cookie_key(item) not in existing_keys
    ]
    if updates:
        await browser_context.add_cookies(updates)


def with_browser_details(result: RunResult, browser_session: PersistentBrowserSession) -> RunResult:
    details = dict(result.details or {})
    details["browser"] = {
        "persistent": True,
        "mode": browser_session.mode,
        "profile_key": browser_session.profile_key,
    }
    return RunResult(result.outcome, result.message, details)


def _cookie_key(item: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(item.get("name") or "").casefold(),
        str(item.get("domain") or "").casefold().lstrip("."),
        str(item.get("path") or "/"),
    )


async def _restore_waf_cookie_state(browser_context: Any, profile_path: Path, url: str) -> None:
    state_path = profile_path / ".autosurf-waf-cookies.json"
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return
    records = None
    if isinstance(payload, dict):
        domains = payload.get("domains")
        if isinstance(domains, dict):
            hostname = _state_domain(url)
            state_key = next(
                (key for key in sorted(domains, key=len, reverse=True)
                 if hostname == key or hostname.endswith(f".{key}")),
                None,
            )
            domain_state = domains.get(state_key) if state_key else None
            if isinstance(domain_state, dict):
                records = domain_state.get("cookies")
        elif isinstance(payload.get("cookies"), list):
            # Read the previous per-profile format and migrate it on the next save.
            records = payload["cookies"]
    if not isinstance(records, list):
        return
    cookies = playwright_cookies(
        RunContext("browser-profile", {}, {}, [
            item for item in records
            if isinstance(item, dict) and str(item.get("name") or "").casefold() in WAF_COOKIE_NAMES
        ]),
        url,
    )
    if cookies:
        await browser_context.add_cookies(cookies)


async def _save_waf_cookie_state(browser_context: Any, profile_path: Path, url: str) -> None:
    parsed = validated_http_url(url)
    origin = f"{parsed.scheme}://{parsed.netloc}/"
    records = [
        _stored_cookie(item) for item in await browser_context.cookies([origin])
        if str(item.get("name") or "").casefold() in WAF_COOKIE_NAMES
    ]
    state_path = profile_path / ".autosurf-waf-cookies.json"
    domains: dict[str, Any] = {}
    try:
        existing = json.loads(state_path.read_text(encoding="utf-8"))
        if isinstance(existing, dict) and isinstance(existing.get("domains"), dict):
            domains = existing["domains"]
        elif isinstance(existing, dict) and isinstance(existing.get("cookies"), list):
            for item in existing["cookies"]:
                if not isinstance(item, dict):
                    continue
                domain = str(item.get("domain") or "").lower().lstrip(".").rstrip(".")
                if domain:
                    domains.setdefault(domain, {"cookies": []})["cookies"].append(item)
    except (OSError, ValueError, TypeError):
        pass
    domains[_state_domain(url)] = {"cookies": records}
    temporary = state_path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"domains": domains}, ensure_ascii=False), encoding="utf-8")
    temporary.replace(state_path)


def _state_domain(url: str) -> str:
    return (validated_http_url(url).hostname or "").lower().rstrip(".")


async def _prepare_shared_profile(profile_path: Path) -> None:
    if profile_path.exists():
        return
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_profiles = [
        item for item in profile_path.parent.iterdir()
        if item.is_dir() and item.name != profile_path.name
    ]
    if not legacy_profiles:
        profile_path.mkdir(parents=True, exist_ok=True)
        return
    latest = max(legacy_profiles, key=lambda item: item.stat().st_mtime)
    try:
        await asyncio.to_thread(shutil.copytree, latest, profile_path)
    except FileExistsError:
        pass


def _stored_cookie(item: dict[str, Any]) -> dict[str, Any]:
    allowed = {"name", "value", "domain", "path", "expires", "httpOnly", "secure", "sameSite"}
    return {key: item[key] for key in allowed if key in item}


async def _start_virtual_display() -> VirtualDisplay:
    socket_dir = Path("/tmp/.X11-unix")
    socket_dir.mkdir(parents=True, exist_ok=True)
    for number in range(90, 190):
        socket = socket_dir / f"X{number}"
        lock = Path(f"/tmp/.X{number}-lock")
        if socket.exists() or lock.exists():
            continue
        process = subprocess.Popen(
            ["Xvfb", f":{number}", "-screen", "0", "1365x768x24", "-nolisten", "tcp"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for _ in range(50):
            if socket.exists():
                return VirtualDisplay(f":{number}", process)
            if process.poll() is not None:
                break
            await asyncio.sleep(0.05)
        await _terminate_process(process)
    raise RuntimeError("cannot start a virtual display for Chromium")


async def _stop_virtual_display(display: VirtualDisplay) -> None:
    await _terminate_process(display.process)


async def _terminate_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        await asyncio.wait_for(asyncio.to_thread(process.wait), timeout=3)
    except TimeoutError:
        process.kill()
        await asyncio.to_thread(process.wait)
