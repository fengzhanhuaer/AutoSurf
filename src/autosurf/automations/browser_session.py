from __future__ import annotations

import asyncio
import json
import os
import signal
import shutil
import subprocess
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Protocol
from urllib.parse import ParseResult, urlparse
from urllib.request import urlopen

from autosurf.domain.models import RunContext, RunResult


WAF_COOKIE_NAMES = frozenset({
    "cf_clearance",
    "sl-challenge-server",
    "sl-session",
})
SHARED_PROFILE_KEY = "shared"
STANDALONE_CDP_ENDPOINT = "http://127.0.0.1:9222"
CHROME_SINGLETON_FILES = (
    "SingletonCookie",
    "SingletonLock",
    "SingletonSocket",
)
VULKAN_ICD_DIRECTORIES = (
    Path("/usr/share/vulkan/icd.d"),
    Path("/etc/vulkan/icd.d"),
)
_PROFILE_LOCKS: dict[str, asyncio.Lock] = {}
_SHARED_BROWSER_PROVIDER: "SharedBrowserProvider | None" = None


@dataclass(frozen=True)
class PersistentBrowserSession:
    context: Any
    profile_key: str
    mode: str
    display_name: str | None = None
    page_factory: Callable[[], Any] | None = None

    async def new_page(self) -> Any:
        if self.page_factory is not None:
            return await self.page_factory()
        return await self.context.new_page()


async def new_browser_session_page(session: Any) -> Any:
    factory = getattr(session, "new_page", None)
    if callable(factory):
        return await factory()
    return await session.context.new_page()


@dataclass
class VirtualDisplay:
    name: str
    process: subprocess.Popen[bytes]


@dataclass
class PersistentBrowserRuntime:
    context: Any | None
    profile_path: Path
    mode: str
    display: VirtualDisplay | None
    browser_process: Any | None = None
    cdp_endpoint: str | None = None
    browser_connection: Any | None = None


class SharedBrowserProvider(Protocol):
    def automation_session(
        self,
        run_context: RunContext,
        url: str,
        *,
        playwright: Any | None = None,
    ) -> Any: ...


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
    native_headful = os.name == "nt"
    return "persistent_headless" if force_headless or not (native_headful or shutil.which("Xvfb")) else "persistent_headful"


@asynccontextmanager
async def persistent_chromium_session(
    playwright: Any,
    run_context: RunContext,
    url: str,
):
    validated_http_url(url)
    provider = _SHARED_BROWSER_PROVIDER
    if provider is not None:
        async with provider.automation_session(
            run_context,
            url,
            playwright=playwright,
        ) as browser_session:
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
    display_size: tuple[int, int] = (1365, 768),
) -> PersistentBrowserRuntime:
    if url is not None:
        validated_http_url(url)
    profile_path = browser_profile_path()
    await _prepare_shared_profile(profile_path)
    await _remove_stale_chrome_singletons(profile_path)
    mode = persistent_browser_mode()
    display = None
    browser_context = None
    try:
        launch_env = dict(os.environ)
        if mode == "persistent_headful" and os.name != "nt":
            display = await _start_virtual_display(*display_size)
            launch_env["DISPLAY"] = display.name
        args = ["--disable-dev-shm-usage", *_chrome_graphics_args()]
        kwargs: dict[str, Any] = {
            "headless": mode == "persistent_headless",
            "locale": str(run_context.config.get("locale", "zh-CN")),
            "env": launch_env,
            "args": args,
        }
        browser_channel = os.environ.get("AUTOSURF_BROWSER_CHANNEL", "").strip()
        if browser_channel:
            kwargs["channel"] = browser_channel
        else:
            kwargs["executable_path"] = playwright.chromium.executable_path
        if remote_desktop and mode == "persistent_headful":
            args.extend([
                "--window-position=0,0",
                f"--window-size={display_size[0]},{display_size[1]}",
                "--no-first-run",
                "--no-default-browser-check",
            ])
            kwargs["no_viewport"] = True
        else:
            kwargs["viewport"] = {
                "width": display_size[0],
                "height": display_size[1],
            }
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


async def launch_standalone_browser(
    _playwright: Any,
    run_context: RunContext,
    *,
    url: str | None = None,
    remote_desktop: bool = False,
    display_size: tuple[int, int] = (1365, 768),
    process_factory: Callable[..., Any] = asyncio.create_subprocess_exec,
) -> PersistentBrowserRuntime:
    """Start ordinary Chrome; Playwright connects separately only when needed."""
    if url is not None:
        validated_http_url(url)
    profile_path = browser_profile_path()
    await _prepare_shared_profile(profile_path)
    await _remove_stale_chrome_singletons(profile_path)
    mode = persistent_browser_mode()
    if remote_desktop and mode != "persistent_headful":
        raise RuntimeError("独立浏览器窗口需要有头模式")

    display = None
    browser_process = None
    try:
        launch_env = dict(os.environ)
        if mode == "persistent_headful" and os.name != "nt":
            display = await _start_virtual_display(*display_size)
            launch_env["DISPLAY"] = display.name
        executable = _standalone_chrome_executable()
        platform_args = [] if os.name == "nt" else [
            "--disable-dev-shm-usage",
            "--password-store=basic",
            "--disable-setuid-sandbox",
        ]
        args = [
            executable,
            f"--user-data-dir={profile_path}",
            "--remote-debugging-address=127.0.0.1",
            f"--remote-debugging-port={urlparse(STANDALONE_CDP_ENDPOINT).port}",
            "--no-first-run",
            "--no-default-browser-check",
            *platform_args,
            f"--lang={str(run_context.config.get('locale', 'zh-CN'))}",
            *_chrome_graphics_args(),
        ]
        if mode == "persistent_headless":
            args.append("--headless=new")
        if remote_desktop and mode == "persistent_headful":
            args.extend([
                "--window-position=0,0",
                f"--window-size={display_size[0]},{display_size[1]}",
            ])
        args.append(url or "about:blank")
        browser_process = await process_factory(
            *args,
            env=launch_env,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        await _wait_for_standalone_cdp(browser_process, STANDALONE_CDP_ENDPOINT)
        return PersistentBrowserRuntime(
            context=None,
            profile_path=profile_path,
            mode=mode,
            display=display,
            browser_process=browser_process,
            cdp_endpoint=STANDALONE_CDP_ENDPOINT,
        )
    except Exception:
        if browser_process is not None:
            await _terminate_async_process(browser_process)
        if display is not None:
            await _stop_virtual_display(display)
        raise


async def connect_standalone_browser(
    playwright: Any,
    runtime: PersistentBrowserRuntime,
) -> PersistentBrowserRuntime:
    if not runtime.cdp_endpoint:
        raise RuntimeError("Chrome DevTools endpoint is unavailable")
    browser = await playwright.chromium.connect_over_cdp(
        runtime.cdp_endpoint,
        is_local=True,
        no_defaults=True,
    )
    if not browser.contexts:
        raise RuntimeError("Chrome DevTools did not expose a browser context")
    return replace(
        runtime,
        context=browser.contexts[0],
        browser_connection=browser,
    )


async def standalone_browser_pages(
    runtime: PersistentBrowserRuntime,
) -> list[dict[str, Any]]:
    if not runtime.cdp_endpoint:
        return []

    def read() -> list[dict[str, Any]]:
        with urlopen(f"{runtime.cdp_endpoint}/json/list", timeout=2) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, list):
            return []
        return [
            item
            for item in payload
            if isinstance(item, dict) and item.get("type") == "page"
        ]

    return await asyncio.to_thread(read)


async def new_browser_task_page(browser_context: Any) -> Any:
    """Create a separate, visible Chrome window for one automation task."""
    browser = browser_context.browser
    if browser is None:
        raise RuntimeError("Chrome CDP browser connection is unavailable")
    cdp = await browser.new_browser_cdp_session()
    page = None
    try:
        async with browser_context.expect_page(timeout=10_000) as page_info:
            target = await cdp.send("Target.createTarget", {
                "url": "about:blank",
                "newWindow": True,
                "background": False,
            })
        page = await page_info.value
        target_id = str(target["targetId"])
        window = await cdp.send("Browser.getWindowForTarget", {"targetId": target_id})
        window_id = int(window["windowId"])
        await cdp.send("Browser.setWindowBounds", {
            "windowId": window_id,
            "bounds": {
                "left": 0,
                "top": 0,
                "width": 1365,
                "height": 768,
                "windowState": "normal",
            },
        })
        return page
    except Exception:
        if page is not None:
            with suppress(Exception):
                await page.close()
        raise
    finally:
        with suppress(Exception):
            await cdp.detach()


@asynccontextmanager
async def foreground_browser_page(page: Any):
    """Bring a visible Chrome task window forward for interactive checks."""
    with suppress(Exception):
        await page.bring_to_front()
    yield


async def prepare_browser_for_run(
    runtime: PersistentBrowserRuntime,
    run_context: RunContext,
    url: str,
) -> None:
    # The shared Chromium profile is the sole runtime source of session state.
    del runtime, run_context
    validated_http_url(url)


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
                """() => {
                  const readStorage = (source) => Object.fromEntries(
                    Array.from({length: source.length}, (_, index) => {
                      const key = source.key(index);
                      return [key, source.getItem(key)];
                    }).filter(([key, value]) => key !== null && value !== null)
                  );
                  return {
                    autosurfBrowserEnvironment: true,
                    values: {...readStorage(localStorage), ...readStorage(sessionStorage)},
                  };
                }"""
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
    if runtime.browser_process is not None:
        await _terminate_async_process(runtime.browser_process)
    elif runtime.context is not None:
        with suppress(Exception):
            await runtime.context.close()
    if runtime.display is not None:
        await _stop_virtual_display(runtime.display)


def with_browser_details(result: RunResult, browser_session: PersistentBrowserSession) -> RunResult:
    details = dict(result.details or {})
    details["browser"] = {
        "persistent": True,
        "mode": browser_session.mode,
        "profile_key": browser_session.profile_key,
    }
    return RunResult(result.outcome, result.message, details)


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


async def _remove_stale_chrome_singletons(profile_path: Path) -> None:
    """Drop process-scoped locks left behind when a container is replaced."""

    def remove() -> None:
        for name in CHROME_SINGLETON_FILES:
            path = profile_path / name
            if path.is_symlink() or path.is_file():
                path.unlink(missing_ok=True)

    await asyncio.to_thread(remove)


def _stored_cookie(item: dict[str, Any]) -> dict[str, Any]:
    allowed = {"name", "value", "domain", "path", "expires", "httpOnly", "secure", "sameSite"}
    return {key: item[key] for key in allowed if key in item}


async def _start_virtual_display(width: int = 1365, height: int = 768) -> VirtualDisplay:
    socket_dir = Path("/tmp/.X11-unix")
    socket_dir.mkdir(parents=True, exist_ok=True)
    for number in range(90, 190):
        socket = socket_dir / f"X{number}"
        lock = Path(f"/tmp/.X{number}-lock")
        if socket.exists() or lock.exists():
            continue
        process = subprocess.Popen(
            [
                "Xvfb", f":{number}", "-screen", "0",
                f"{width}x{height}x24", "-nolisten", "tcp",
            ],
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


def _standalone_chrome_executable() -> str:
    configured = os.environ.get("AUTOSURF_BROWSER_EXECUTABLE_PATH", "").strip()
    if configured:
        if Path(configured).is_file():
            return configured
        raise RuntimeError(f"AutoSurf browser runtime was not found: {configured}")
    if os.name == "nt":
        managed = Path(os.environ.get("AUTOSURF_INSTALL_DIR", r"C:\Tools\AutoSurf"))
        candidate = managed / "runtime" / "chrome" / "chrome.exe"
        if candidate.is_file():
            return str(candidate)
        raise RuntimeError(f"AutoSurf browser runtime was not found: {candidate}")
    executable = shutil.which("google-chrome-stable") or shutil.which("google-chrome")
    if executable:
        return executable
    raise RuntimeError("Google Chrome executable was not found")


def _chrome_graphics_args() -> list[str]:
    """Select hardware WebGL when DRM and a Vulkan driver are usable."""
    configured = os.environ.get("AUTOSURF_BROWSER_GRAPHICS", "auto").strip().casefold()
    if configured not in {"auto", "hardware", "software"}:
        configured = "auto"

    if os.name == "nt" and configured != "software":
        return [] if configured == "auto" else ["--enable-gpu", "--ignore-gpu-blocklist"]

    render_nodes = sorted(Path("/dev/dri").glob("renderD*"))
    has_render_node = any(os.access(node, os.R_OK | os.W_OK) for node in render_nodes)
    has_vulkan_icd = any(
        any(directory.glob("*.json"))
        for directory in VULKAN_ICD_DIRECTORIES
        if directory.is_dir()
    )
    use_hardware = configured == "hardware" or (
        configured == "auto" and has_render_node and has_vulkan_icd
    )
    if use_hardware:
        return [
            "--enable-gpu",
            "--use-gl=angle",
            "--use-angle=vulkan",
            "--enable-features=Vulkan,DefaultANGLEVulkan,VulkanFromANGLE",
            "--ignore-gpu-blocklist",
            "--disable-vulkan-surface",
            "--enable-unsafe-swiftshader",
        ]
    return [
        "--use-gl=angle",
        "--use-angle=swiftshader-webgl",
        "--enable-unsafe-swiftshader",
    ]


async def _wait_for_standalone_cdp(process: Any, endpoint: str) -> None:
    def read_version() -> bool:
        try:
            with urlopen(f"{endpoint}/json/version", timeout=1) as response:
                payload = json.loads(response.read().decode("utf-8"))
            return isinstance(payload, dict) and bool(payload.get("webSocketDebuggerUrl"))
        except Exception:
            return False

    for _ in range(300):
        if process.returncode is not None:
            raise RuntimeError(f"Google Chrome exited with status {process.returncode}")
        if await asyncio.to_thread(read_version):
            return
        await asyncio.sleep(0.05)
    raise RuntimeError("Google Chrome DevTools endpoint startup timed out")


async def _terminate_async_process(process: Any) -> None:
    if process.returncode is not None:
        return
    process_group = getattr(process, "pid", None) if os.name != "nt" else None
    try:
        if process_group is not None:
            os.killpg(process_group, signal.SIGTERM)
        else:
            process.terminate()
    except (LookupError, OSError):
        with suppress(Exception):
            process.terminate()
    try:
        await asyncio.wait_for(process.wait(), timeout=5)
    except TimeoutError:
        try:
            if process_group is not None:
                os.killpg(process_group, signal.SIGKILL)
            else:
                process.kill()
        except (LookupError, OSError):
            with suppress(Exception):
                process.kill()
        await process.wait()


async def _terminate_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        await asyncio.wait_for(asyncio.to_thread(process.wait), timeout=3)
    except TimeoutError:
        process.kill()
        await asyncio.to_thread(process.wait)
