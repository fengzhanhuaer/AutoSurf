from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import ParseResult, urlparse

from autosurf.domain.models import RunContext, RunResult


WAF_COOKIE_NAMES = frozenset({
    "cf_clearance",
    "sl-challenge-server",
    "sl-session",
})
SHARED_PROFILE_KEY = "shared"
_PROFILE_LOCKS: dict[str, asyncio.Lock] = {}
_SHARED_BROWSER_PROVIDER: "SharedBrowserProvider | None" = None


@dataclass(frozen=True)
class PersistentBrowserSession:
    context: Any
    profile_key: str
    mode: str
    display_name: str | None = None


@dataclass
class VirtualDisplay:
    name: str
    process: subprocess.Popen[bytes]


@dataclass
class PersistentBrowserRuntime:
    context: Any
    profile_path: Path
    mode: str
    display: VirtualDisplay | None


class SharedBrowserProvider(Protocol):
    def automation_session(self, run_context: RunContext, url: str) -> Any: ...


def register_shared_browser_provider(provider: SharedBrowserProvider | None) -> None:
    global _SHARED_BROWSER_PROVIDER
    _SHARED_BROWSER_PROVIDER = provider


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
    provider = _SHARED_BROWSER_PROVIDER
    if provider is not None:
        async with provider.automation_session(run_context, url) as browser_session:
            yield browser_session
        return

    profile_path = browser_profile_path()
    lock = _PROFILE_LOCKS.setdefault(str(profile_path), asyncio.Lock())

    async with lock:
        runtime = None
        try:
            runtime = await launch_persistent_browser(playwright, run_context, url=url)
            yield PersistentBrowserSession(
                runtime.context,
                SHARED_PROFILE_KEY,
                runtime.mode,
                runtime.display.name if runtime.display else None,
            )
        finally:
            if runtime is not None:
                await close_persistent_browser(runtime, url=url)


async def launch_persistent_browser(
    playwright: Any,
    run_context: RunContext,
    *,
    url: str | None = None,
    remote_desktop: bool = False,
) -> PersistentBrowserRuntime:
    if url is not None:
        validated_http_url(url)
    profile_path = browser_profile_path()
    await _prepare_shared_profile(profile_path)
    mode = persistent_browser_mode()
    display = None
    browser_context = None
    try:
        launch_env = dict(os.environ)
        if mode == "persistent_headful":
            display = await _start_virtual_display()
            launch_env["DISPLAY"] = display.name
        args = ["--disable-dev-shm-usage"]
        kwargs: dict[str, Any] = {
            "headless": mode == "persistent_headless",
            "executable_path": playwright.chromium.executable_path,
            "locale": str(run_context.config.get("locale", "zh-CN")),
            "env": launch_env,
            "args": args,
        }
        if remote_desktop and mode == "persistent_headful":
            args.extend([
                "--window-position=0,0",
                "--window-size=1365,768",
                "--no-first-run",
                "--no-default-browser-check",
            ])
            kwargs["no_viewport"] = True
        else:
            kwargs["viewport"] = {"width": 1365, "height": 768}
        user_agent = run_context.config.get("user_agent") or run_context.user_agent
        if user_agent:
            kwargs["user_agent"] = str(user_agent)
        browser_context = await playwright.chromium.launch_persistent_context(
            str(profile_path), **kwargs,
        )
        runtime = PersistentBrowserRuntime(browser_context, profile_path, mode, display)
        if url is not None:
            await prepare_browser_for_run(runtime, run_context, url)
        return runtime
    except Exception:
        if browser_context is not None:
            with suppress(Exception):
                await browser_context.close()
        if display is not None:
            await _stop_virtual_display(display)
        raise


async def prepare_browser_for_run(
    runtime: PersistentBrowserRuntime,
    run_context: RunContext,
    url: str,
) -> None:
    # The shared Chromium profile is the sole runtime source of session state.
    del runtime, run_context
    validated_http_url(url)


async def bootstrap_browser_environment(
    runtime: PersistentBrowserRuntime,
    sources: list[tuple[str, RunContext]],
) -> int:
    state_path = runtime.profile_path / ".autosurf-environment-bootstrap.json"
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        payload = None
    if isinstance(payload, dict) and payload.get("completed") is True:
        return 0
    if not sources:
        return 0

    initialized_domains: set[str] = set()
    for url, context in sources:
        initialized = False
        if context.browser_cookies == []:
            initialized = await _bootstrap_local_storage(runtime.context, context, url)
        else:
            initialized = await supplement_playwright_cookies(runtime.context, context, url)
        if initialized:
            hostname = (validated_http_url(url).hostname or "").casefold().rstrip(".")
            initialized_domains.add(hostname)

    state_path.parent.mkdir(parents=True, exist_ok=True)
    pending = state_path.with_suffix(".tmp")
    pending.write_text(
        json.dumps(
            {
                "version": 1,
                "completed": True,
                "domains": sorted(initialized_domains),
            },
            ensure_ascii=True,
        ),
        encoding="utf-8",
    )
    pending.replace(state_path)
    return len(initialized_domains)


async def browser_environment_run_context(
    page: Any,
    context: RunContext,
    url: str,
) -> RunContext:
    parsed = validated_http_url(url)
    origin = f"{parsed.scheme}://{parsed.netloc}/"
    values: dict[str, str] = {}
    browser_cookies: list[dict[str, Any]] | None = None
    environment_read = False
    try:
        records = await page.context.cookies([origin])
        browser_cookies = [dict(item) for item in records if isinstance(item, dict)]
        values.update({
            str(item["name"]): str(item["value"])
            for item in browser_cookies
            if item.get("name") is not None and item.get("value") is not None
        })
        environment_read = True
    except Exception:
        pass
    page_hostname = (urlparse(str(getattr(page, "url", ""))).hostname or "").casefold()
    target_hostname = (parsed.hostname or "").casefold()
    related_origin = (
        page_hostname == target_hostname
        or page_hostname.endswith(f".{target_hostname}")
        or target_hostname.endswith(f".{page_hostname}")
    ) if page_hostname and target_hostname else False
    if related_origin:
        try:
            storage = await page.evaluate(
                """() => ({
                  autosurfBrowserEnvironment: true,
                  values: Object.fromEntries(
                    Array.from({length: localStorage.length}, (_, index) => {
                      const key = localStorage.key(index);
                      return [key, localStorage.getItem(key)];
                    }).filter(([key, value]) => key !== null && value !== null)
                  ),
                })"""
            )
            if isinstance(storage, dict) and storage.get("autosurfBrowserEnvironment") is True:
                stored_values = storage.get("values")
                if isinstance(stored_values, dict):
                    values.update({
                        str(key): str(value)
                        for key, value in stored_values.items()
                        if isinstance(key, str) and isinstance(value, str)
                    })
                    environment_read = True
        except Exception:
            pass
    if not environment_read:
        return context
    return replace(context, cookies=values, browser_cookies=browser_cookies)


async def save_browser_after_run(runtime: PersistentBrowserRuntime, url: str) -> None:
    # Chromium persists cookies and storage in its profile without task-level exports.
    del runtime
    validated_http_url(url)


async def close_persistent_browser(
    runtime: PersistentBrowserRuntime,
    *,
    url: str | None = None,
) -> None:
    if url is not None:
        with suppress(Exception):
            await save_browser_after_run(runtime, url)
    with suppress(Exception):
        await runtime.context.close()
    if runtime.display is not None:
        await _stop_virtual_display(runtime.display)


async def supplement_playwright_cookies(
    browser_context: Any,
    context: RunContext,
    url: str,
) -> bool:
    incoming = playwright_cookies(context, url)
    if not incoming:
        return False
    parsed = validated_http_url(url)
    origin = f"{parsed.scheme}://{parsed.netloc}/"
    existing = await browser_context.cookies([origin])
    existing_keys = {_cookie_key(item) for item in existing}
    updates = [item for item in incoming if _cookie_key(item) not in existing_keys]
    if updates:
        await browser_context.add_cookies(updates)
    return True


async def _bootstrap_local_storage(
    browser_context: Any,
    context: RunContext,
    url: str,
) -> bool:
    values = {
        str(key): str(value)
        for key, value in context.cookies.items()
        if isinstance(key, str) and isinstance(value, str) and value
    }
    if not values:
        return False
    parsed = validated_http_url(url)
    origin = f"{parsed.scheme}://{parsed.netloc}/"
    page = await browser_context.new_page()

    async def serve_origin(route: Any) -> None:
        if route.request.is_navigation_request():
            await route.fulfill(status=200, content_type="text/html", body="<!doctype html>")
        else:
            await route.abort()

    try:
        await page.route("**/*", serve_origin)
        await page.goto(origin, wait_until="domcontentloaded", timeout=10_000)
        await page.evaluate(
            "values => Object.entries(values).forEach(([key, value]) => "
            "localStorage.setItem(key, value))",
            values,
        )
    finally:
        with suppress(Exception):
            await page.close()
    return True


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
