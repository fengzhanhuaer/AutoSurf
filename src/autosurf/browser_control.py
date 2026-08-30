from __future__ import annotations

import asyncio
import json
import os
import shutil
import threading
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any, Callable

from playwright.async_api import async_playwright
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from autosurf.automations.browser_session import (
    PersistentBrowserRuntime,
    PersistentBrowserSession,
    STANDALONE_CDP_ENDPOINT,
    browser_profile_path,
    close_persistent_browser,
    connect_standalone_browser,
    launch_standalone_browser,
    new_offscreen_browser_page,
    prepare_browser_for_run,
    register_shared_browser_provider,
    save_browser_after_run,
    standalone_browser_pages,
    validated_http_url,
)
from autosurf.domain.models import ExecutionStatus, RunContext
from autosurf.infrastructure.database import ExecutionRecord, SystemSettingRecord


REMOTE_DESKTOP_PREFIX = "/browser-control/remote"
DEFAULT_SOCKET_PATH = Path("/tmp/autosurf-novnc.sock")
VNC_LOOPBACK_PORT = 5900
AUDIO_SAMPLE_RATE = 48_000
AUDIO_CHANNELS = 2
AUDIO_CHUNK_BYTES = AUDIO_SAMPLE_RATE * AUDIO_CHANNELS * 2 // 10
RESTART_DELAY_SECONDS = 3
STARTUP_TIMEOUT_SECONDS = 30
BROWSER_RESOLUTION_SETTING_KEY = "browser.display_resolution"
DEFAULT_BROWSER_RESOLUTION = (1365, 768)
SUPPORTED_BROWSER_RESOLUTIONS = (
    (1280, 720),
    DEFAULT_BROWSER_RESOLUTION,
    (1600, 900),
    (1920, 1080),
)


class BrowserControlError(RuntimeError):
    pass


class BrowserControlInactive(BrowserControlError):
    pass


class CdpAutomationProvider:
    """Attach a worker process to the always-on Chrome without using its visible window."""

    def __init__(self, endpoint: str = STANDALONE_CDP_ENDPOINT) -> None:
        self._endpoint = endpoint

    async def _connect(self, playwright: Any, runtime: PersistentBrowserRuntime) -> Any:
        last_error: Exception | None = None
        for _ in range(120):
            try:
                return await connect_standalone_browser(playwright, runtime)
            except Exception as exc:
                last_error = exc
                await asyncio.sleep(0.5)
        assert last_error is not None
        raise last_error

    @asynccontextmanager
    async def automation_session(
        self,
        run_context: RunContext,
        url: str,
        *,
        playwright: Any | None = None,
    ):
        validated_http_url(url)
        manager = None
        current_playwright = playwright
        if current_playwright is None:
            manager = async_playwright()
            current_playwright = await manager.start()
        runtime = PersistentBrowserRuntime(
            context=None,
            profile_path=browser_profile_path(),
            mode="persistent_headful",
            display=None,
            cdp_endpoint=self._endpoint,
        )
        connected = None
        owned_pages: set[Any] = set()
        try:
            connected = await self._connect(current_playwright, runtime)
            assert connected.context is not None
            await prepare_browser_for_run(connected, run_context, url)

            async def create_page() -> Any:
                page = await new_offscreen_browser_page(connected.context)
                owned_pages.add(page)
                return page

            yield PersistentBrowserSession(
                connected.context,
                "shared",
                connected.mode,
                page_factory=create_page,
            )
        finally:
            if connected is not None and connected.context is not None:
                with suppress(Exception):
                    await save_browser_after_run(connected, url)
                for page in owned_pages:
                    with suppress(Exception):
                        await page.close()
            if manager is not None:
                with suppress(Exception):
                    await current_playwright.stop()


class BrowserControlBusy(BrowserControlError):
    pass


def validate_browser_resolution(width: int, height: int) -> tuple[int, int]:
    value = (int(width), int(height))
    if value not in SUPPORTED_BROWSER_RESOLUTIONS:
        supported = "、".join(f"{item[0]}x{item[1]}" for item in SUPPORTED_BROWSER_RESOLUTIONS)
        raise ValueError(f"不支持该分辨率，可选：{supported}")
    return value


class BrowserDisplaySettings:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions
        self._lock = threading.Lock()
        self._resolution = self._load()

    @property
    def resolution(self) -> tuple[int, int]:
        with self._lock:
            return self._resolution

    def set_resolution(self, width: int, height: int) -> tuple[int, int]:
        value = validate_browser_resolution(width, height)
        payload = json.dumps({"width": value[0], "height": value[1]})
        with self._lock:
            with self._sessions.begin() as session:
                record = session.get(SystemSettingRecord, BROWSER_RESOLUTION_SETTING_KEY)
                if record is None:
                    session.add(SystemSettingRecord(
                        key=BROWSER_RESOLUTION_SETTING_KEY,
                        value_json=payload,
                    ))
                else:
                    record.value_json = payload
            self._resolution = value
        return value

    def active_execution_id(self) -> str | None:
        with self._sessions() as session:
            return session.scalar(
                select(ExecutionRecord.id)
                .where(ExecutionRecord.status == ExecutionStatus.RUNNING)
                .order_by(ExecutionRecord.started_at.desc())
                .limit(1)
            )

    def _load(self) -> tuple[int, int]:
        with self._sessions() as session:
            record = session.get(SystemSettingRecord, BROWSER_RESOLUTION_SETTING_KEY)
        if record is None:
            return DEFAULT_BROWSER_RESOLUTION
        try:
            value = json.loads(record.value_json)
            return validate_browser_resolution(value["width"], value["height"])
        except (KeyError, TypeError, ValueError):
            return DEFAULT_BROWSER_RESOLUTION


class BrowserControlService:
    def __init__(
        self,
        *,
        playwright_factory: Callable[[], Any] = async_playwright,
        browser_launcher: Callable[..., Any] = launch_standalone_browser,
        browser_connector: Callable[..., Any] = connect_standalone_browser,
        browser_closer: Callable[..., Any] = close_persistent_browser,
        process_factory: Callable[..., Any] = asyncio.create_subprocess_exec,
        socket_path: Path = DEFAULT_SOCKET_PATH,
        display_settings: BrowserDisplaySettings | None = None,
    ) -> None:
        self._playwright_factory = playwright_factory
        self._browser_launcher = browser_launcher
        self._browser_connector = browser_connector
        self._browser_closer = browser_closer
        self._process_factory = process_factory
        self._socket_path = socket_path
        self._display_settings = display_settings
        self._resolution = (
            display_settings.resolution
            if display_settings is not None
            else DEFAULT_BROWSER_RESOLUTION
        )
        self._lifecycle_lock = asyncio.Lock()
        self._operation_lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None
        self._stop_event: asyncio.Event | None = None
        self._initial_ready: asyncio.Event | None = None
        self._runtime: PersistentBrowserRuntime | None = None
        self._vnc_process: Any | None = None
        self._remote_process: Any | None = None
        self._starting = False
        self._error: str | None = None
        self._automation_owner: str | None = None
        self._restart_count = 0
        self._stream_log: str | None = None

    @property
    def socket_path(self) -> Path:
        return self._socket_path

    async def start(self, url: str | None = None) -> dict[str, Any]:
        if url is not None:
            validated_http_url(url)
        async with self._lifecycle_lock:
            if self._task is None or self._task.done():
                self._stop_event = asyncio.Event()
                self._initial_ready = asyncio.Event()
                self._starting = True
                self._error = None
                self._task = asyncio.create_task(
                    self._supervise(), name="autosurf-browser-control",
                )
                register_shared_browser_provider(self)
            ready = self._initial_ready
        if ready is not None:
            with suppress(TimeoutError):
                await asyncio.wait_for(ready.wait(), timeout=STARTUP_TIMEOUT_SECONDS)
        if url is not None and self._runtime is not None:
            with suppress(Exception):
                async with self._connected_runtime(self._runtime) as connected:
                    page = await self._control_page(connected)
                    await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        return await self.status()

    async def stop(self) -> dict[str, Any]:
        async with self._lifecycle_lock:
            task = self._task
            stop_event = self._stop_event
            if stop_event is not None:
                stop_event.set()
        if task is not None:
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=15)
            except TimeoutError:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
        async with self._lifecycle_lock:
            if self._task is task:
                self._task = None
                self._stop_event = None
                self._initial_ready = None
                register_shared_browser_provider(None)
        return await self.status()

    async def shutdown(self) -> None:
        await self.stop()

    async def open_window(self) -> dict[str, Any]:
        status = await self.start()
        runtime = self._runtime
        if os.name == "nt" and runtime is not None and runtime.browser_process is not None:
            await asyncio.to_thread(_activate_windows_process, runtime.browser_process.pid)
        return status

    async def set_resolution(self, width: int, height: int) -> dict[str, Any]:
        resolution = validate_browser_resolution(width, height)
        if resolution == self._resolution:
            return await self.status()
        active_execution = self._database_active_execution_id()
        if self._operation_lock.locked() or active_execution is not None:
            raise BrowserControlBusy("自动任务正在操作浏览器，请稍后再切换分辨率")
        async with self._operation_lock:
            if self._display_settings is not None:
                self._display_settings.set_resolution(*resolution)
            self._resolution = resolution
            await self.stop()
            await self.start()
        return await self.status()

    async def status(self, *, touch: bool = False) -> dict[str, Any]:
        del touch
        runtime = self._runtime
        native_window = os.name == "nt"
        active = (
            runtime is not None
            and (
                runtime.browser_process is None
                or runtime.browser_process.returncode is None
            )
            and (
                native_window
                or (
                    self._vnc_process is not None
                    and self._remote_process is not None
                    and self._socket_path.exists()
                )
            )
        )
        url = ""
        title = ""
        if runtime is not None:
            if runtime.cdp_endpoint:
                with suppress(Exception):
                    pages = await standalone_browser_pages(runtime)
                    if pages:
                        page = pages[0]
                        url = str(page.get("url") or "")
                        title = str(page.get("title") or "")[:300]
            elif runtime.context is not None:
                pages = [page for page in runtime.context.pages if not page.is_closed()]
                if pages:
                    page = pages[-1]
                    url = str(page.url or "")
                    with suppress(Exception):
                        title = str(await page.title())[:300]
        task = self._task
        database_owner = self._database_active_execution_id()
        automation_owner = self._automation_owner or database_owner
        return {
            "active": active,
            "starting": self._starting,
            "url": url,
            "title": title,
            "mode": runtime.mode if runtime is not None else None,
            "viewport": {
                "width": self._resolution[0],
                "height": self._resolution[1],
            },
            "supported_resolutions": [
                {
                    "width": width,
                    "height": height,
                    "label": f"{width} x {height}",
                }
                for width, height in SUPPORTED_BROWSER_RESOLUTIONS
            ],
            "error": self._error,
            "task_running": bool(task is not None and not task.done()),
            "always_on": True,
            "busy": self._operation_lock.locked() or database_owner is not None,
            "automation_owner": automation_owner,
            "native_window": native_window,
            "remote_url": None if native_window else (
                f"{REMOTE_DESKTOP_PREFIX}/vnc.html"
                f"?autoconnect=1&resize=scale&reconnect=1&reconnect_delay=2000"
                f"&path=websockify"
            ),
            "restart_count": self._restart_count,
            "stream_log": self._stream_log,
            "audio_supported": not native_window and shutil.which("parec") is not None,
            "native_audio": native_window,
            "audio_format": {
                "sample_rate": AUDIO_SAMPLE_RATE,
                "channels": AUDIO_CHANNELS,
                "sample_format": "s16le",
            },
        }

    def _database_active_execution_id(self) -> str | None:
        lookup = getattr(self._display_settings, "active_execution_id", None)
        return lookup() if callable(lookup) else None

    @asynccontextmanager
    async def automation_session(
        self,
        run_context: RunContext,
        url: str,
        *,
        playwright: Any | None = None,
    ):
        validated_http_url(url)
        runtime = await self._wait_for_runtime()
        async with self._operation_lock:
            if runtime is not self._runtime:
                runtime = await self._wait_for_runtime()
            self._automation_owner = run_context.execution_id
            owned_pages: set[Any] = set()
            try:
                async with self._connected_runtime(runtime, playwright=playwright) as connected:
                    assert connected.context is not None

                    async def create_page() -> Any:
                        page = await new_offscreen_browser_page(connected.context)
                        owned_pages.add(page)
                        return page

                    try:
                        await prepare_browser_for_run(connected, run_context, url)
                        yield PersistentBrowserSession(
                            connected.context,
                            "shared",
                            connected.mode,
                            connected.display.name if connected.display else None,
                            page_factory=create_page,
                        )
                    finally:
                        with suppress(Exception):
                            await save_browser_after_run(connected, url)
                        for page in owned_pages:
                            with suppress(Exception):
                                await page.close()
            finally:
                self._automation_owner = None

    async def proxy_http(self, request: Any, path: str) -> Any:
        from starlette.responses import Response

        if not self._socket_path.exists():
            return Response("远程浏览器正在恢复", status_code=503)
        from aiohttp import ClientSession, UnixConnector
        target_path = f"/{path}" if path else "/vnc.html"
        target = f"http://localhost{target_path}"
        if request.url.query:
            target = f"{target}?{request.url.query}"
        headers = _proxy_headers(request.headers, include_cookie=False)
        body = await request.body()
        try:
            connector = UnixConnector(path=str(self._socket_path))
            async with ClientSession(connector=connector) as session:
                async with session.request(
                    request.method,
                    target,
                    headers=headers,
                    data=body or None,
                    allow_redirects=False,
                ) as upstream:
                    payload = await upstream.read()
                    return Response(
                        payload,
                        status_code=upstream.status,
                        headers=_response_headers(upstream.headers),
                    )
        except Exception as exc:
            self._record_error(exc)
            return Response("远程浏览器暂不可用", status_code=503)

    async def proxy_websocket(self, websocket: Any) -> None:
        if not self._socket_path.exists():
            await websocket.close(code=1013, reason="remote browser is starting")
            return
        from aiohttp import ClientSession, UnixConnector, WSMsgType
        target = "http://localhost/websockify"
        if websocket.url.query:
            target = f"{target}?{websocket.url.query}"
        headers = _proxy_headers(websocket.headers, include_cookie=False)
        await websocket.accept()
        try:
            connector = UnixConnector(path=str(self._socket_path))
            async with ClientSession(connector=connector) as session:
                async with session.ws_connect(
                    target,
                    headers=headers,
                    autoping=True,
                    compress=0,
                    max_msg_size=0,
                ) as upstream:
                    async def client_to_upstream() -> None:
                        while True:
                            message = await websocket.receive()
                            if message.get("type") == "websocket.disconnect":
                                await upstream.close()
                                return
                            if message.get("text") is not None:
                                await upstream.send_str(message["text"])
                            elif message.get("bytes") is not None:
                                await upstream.send_bytes(message["bytes"])

                    async def upstream_to_client() -> None:
                        async for message in upstream:
                            if message.type == WSMsgType.TEXT:
                                await websocket.send_text(message.data)
                            elif message.type == WSMsgType.BINARY:
                                await websocket.send_bytes(message.data)
                            elif message.type in {WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.ERROR}:
                                return

                    tasks = {
                        asyncio.create_task(client_to_upstream()),
                        asyncio.create_task(upstream_to_client()),
                    }
                    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                    for task in pending:
                        task.cancel()
                    await asyncio.gather(*done, *pending, return_exceptions=True)
        except Exception as exc:
            self._record_error(exc)
        finally:
            with suppress(Exception):
                await websocket.close()

    async def stream_audio(self, websocket: Any) -> None:
        parec = shutil.which("parec")
        if parec is None:
            await websocket.close(code=1013, reason="audio capture is unavailable")
            return
        source = os.environ.get("AUTOSURF_AUDIO_SOURCE", "autosurf.monitor")
        await websocket.accept()
        process = None
        try:
            process = await self._process_factory(
                parec,
                f"--device={source}",
                "--format=s16le",
                f"--rate={AUDIO_SAMPLE_RATE}",
                f"--channels={AUDIO_CHANNELS}",
                "--latency-msec=100",
                "--raw",
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            if process.stdout is None:
                raise BrowserControlError("音频采集进程没有输出流")
            while True:
                chunk = await process.stdout.read(AUDIO_CHUNK_BYTES)
                if not chunk:
                    code = await process.wait()
                    raise BrowserControlError(f"音频采集意外退出，状态码 {code}")
                await websocket.send_bytes(chunk)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._record_error(exc)
        finally:
            if process is not None:
                await _terminate_process(process)
            with suppress(Exception):
                await websocket.close()

    async def _supervise(self) -> None:
        initial_ready = self._initial_ready
        stop_event = self._stop_event
        assert initial_ready is not None and stop_event is not None
        first_attempt = True
        while not stop_event.is_set():
            self._starting = True
            try:
                await self._run_once(stop_event)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._record_error(exc)
            finally:
                self._starting = False
                initial_ready.set()
            if stop_event.is_set():
                break
            if not first_attempt:
                self._restart_count += 1
            first_attempt = False
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=RESTART_DELAY_SECONDS)
            except TimeoutError:
                pass

    async def _run_once(self, stop_event: asyncio.Event) -> None:
        if os.name == "nt":
            await self._run_native_once(stop_event)
            return
        runtime = None
        vnc = None
        remote = None
        log_tasks: list[asyncio.Task[None]] = []
        try:
            context = RunContext(
                execution_id="browser-control",
                config={"locale": "zh-CN"},
                cookies={},
            )
            runtime = await self._browser_launcher(
                None,
                context,
                remote_desktop=True,
                display_size=self._resolution,
                process_factory=self._process_factory,
            )
            if runtime.display is None:
                raise BrowserControlError("完整浏览器控制需要 Docker 中的 Xvfb")
            self._runtime = runtime
            vnc, remote = await self._start_remote_desktop(runtime.display.name)
            self._vnc_process = vnc
            self._remote_process = remote
            for process in (runtime.browser_process, vnc, remote):
                if process is None:
                    continue
                if process.stdout is not None:
                    log_tasks.append(asyncio.create_task(self._drain_stream(process.stdout)))
                if process.stderr is not None:
                    log_tasks.append(asyncio.create_task(self._drain_stream(process.stderr)))
            await self._wait_for_socket(remote)
            self._error = None
            self._starting = False
            self._initial_ready.set()

            stop_wait = asyncio.create_task(stop_event.wait())
            browser_wait = (
                asyncio.create_task(runtime.browser_process.wait())
                if runtime.browser_process is not None
                else None
            )
            vnc_wait = asyncio.create_task(vnc.wait())
            remote_wait = asyncio.create_task(remote.wait())
            waiters = {stop_wait, vnc_wait, remote_wait}
            if browser_wait is not None:
                waiters.add(browser_wait)
            done, pending = await asyncio.wait(
                waiters,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            if vnc_wait in done and not stop_event.is_set():
                raise BrowserControlError(
                    f"x11vnc 意外退出，状态码 {vnc_wait.result()}",
                )
            if remote_wait in done and not stop_event.is_set():
                raise BrowserControlError(
                    f"noVNC 意外退出，状态码 {remote_wait.result()}",
                )
            if (
                browser_wait is not None
                and browser_wait in done
                and not stop_event.is_set()
            ):
                raise BrowserControlError(
                    f"Google Chrome 意外退出，状态码 {browser_wait.result()}",
                )
        finally:
            self._runtime = None
            self._vnc_process = None
            self._remote_process = None
            for process in (remote, vnc):
                if process is not None:
                    await _terminate_process(process)
            for task in log_tasks:
                task.cancel()
            await asyncio.gather(*log_tasks, return_exceptions=True)
            if runtime is not None:
                await self._browser_closer(runtime)
            self._socket_path.unlink(missing_ok=True)

    async def _run_native_once(self, stop_event: asyncio.Event) -> None:
        runtime = None
        log_tasks: list[asyncio.Task[None]] = []
        try:
            context = RunContext(
                execution_id="browser-control",
                config={"locale": "zh-CN"},
                cookies={},
            )
            runtime = await self._browser_launcher(
                None,
                context,
                remote_desktop=True,
                display_size=self._resolution,
                process_factory=self._process_factory,
            )
            self._runtime = runtime
            process = runtime.browser_process
            if process is not None:
                if process.stdout is not None:
                    log_tasks.append(asyncio.create_task(self._drain_stream(process.stdout)))
                if process.stderr is not None:
                    log_tasks.append(asyncio.create_task(self._drain_stream(process.stderr)))
            self._error = None
            self._starting = False
            self._initial_ready.set()

            stop_wait = asyncio.create_task(stop_event.wait())
            if process is None:
                await stop_wait
                return
            browser_wait = asyncio.create_task(process.wait())
            done, pending = await asyncio.wait(
                {stop_wait, browser_wait},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            if browser_wait in done and not stop_event.is_set():
                raise BrowserControlError(
                    f"Google Chrome 意外退出，状态码 {browser_wait.result()}",
                )
        finally:
            self._runtime = None
            for task in log_tasks:
                task.cancel()
            await asyncio.gather(*log_tasks, return_exceptions=True)
            if runtime is not None:
                await self._browser_closer(runtime)

    @asynccontextmanager
    async def _connected_runtime(
        self,
        runtime: PersistentBrowserRuntime,
        *,
        playwright: Any | None = None,
    ):
        manager = None
        current_playwright = playwright
        if current_playwright is None:
            manager = self._playwright_factory()
            current_playwright = await manager.start()
        try:
            yield await self._browser_connector(current_playwright, runtime)
        finally:
            if manager is not None:
                with suppress(Exception):
                    await current_playwright.stop()

    async def _start_remote_desktop(self, display_name: str) -> tuple[Any, Any]:
        self._socket_path.parent.mkdir(parents=True, exist_ok=True)
        self._socket_path.unlink(missing_ok=True)
        vnc_command = [
            "x11vnc",
            "-display", display_name,
            "-forever",
            "-shared",
            "-localhost",
            "-rfbport", str(VNC_LOOPBACK_PORT),
            "-nopw",
            "-noxdamage",
        ]
        env = dict(os.environ)
        env["DISPLAY"] = display_name
        vnc = await self._process_factory(
            *vnc_command,
            env=env,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        remote_command = [
            "websockify",
            f"--unix-listen={self._socket_path}",
            "--unix-listen-mode=0600",
            "--web=/usr/share/novnc",
            "--heartbeat=30",
            f"127.0.0.1:{VNC_LOOPBACK_PORT}",
        ]
        try:
            remote = await self._process_factory(
                *remote_command,
                env=env,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except Exception:
            await _terminate_process(vnc)
            raise
        return vnc, remote

    async def _wait_for_socket(self, process: Any) -> None:
        for _ in range(300):
            if self._socket_path.exists():
                return
            if process.returncode is not None:
                raise BrowserControlError(
                    f"noVNC 启动失败，状态码 {process.returncode}",
                )
            await asyncio.sleep(0.05)
        raise BrowserControlError("noVNC Unix socket 启动超时")

    async def _wait_for_runtime(self) -> PersistentBrowserRuntime:
        for _ in range(300):
            runtime = self._runtime
            if runtime is not None:
                return runtime
            await asyncio.sleep(0.1)
        raise BrowserControlInactive("常驻 Chromium 尚未就绪")

    async def _control_page(self, runtime: PersistentBrowserRuntime | None = None) -> Any:
        current = runtime or self._runtime
        if current is None or current.context is None:
            raise BrowserControlInactive("常驻 Chromium 尚未就绪")
        pages = [page for page in current.context.pages if not page.is_closed()]
        return pages[0] if pages else await current.context.new_page()

    async def _drain_stream(self, stream: Any) -> None:
        while True:
            line = await stream.readline()
            if not line:
                return
            value = line.decode(errors="replace").strip()
            if value:
                self._stream_log = value[:500]

    def _record_error(self, error: Exception) -> None:
        value = str(error).strip().splitlines()[0] if str(error).strip() else type(error).__name__
        self._error = value[:500]


def _proxy_headers(headers: Any, *, include_cookie: bool = True) -> dict[str, str]:
    excluded = {
        "connection",
        "content-length",
        "transfer-encoding",
        "upgrade",
        "sec-websocket-key",
        "sec-websocket-version",
        "sec-websocket-extensions",
        "sec-websocket-protocol",
        "authorization",
    }
    if not include_cookie:
        excluded.add("cookie")
    return {
        str(key): str(value)
        for key, value in headers.items()
        if str(key).lower() not in excluded
    }


def _activate_windows_process(process_id: int) -> bool:
    if os.name != "nt":
        return False
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    found: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(window: int, _parameter: int) -> bool:
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(window, ctypes.byref(owner))
        if owner.value == process_id and user32.IsWindowVisible(window):
            found.append(window)
            return False
        return True

    user32.EnumWindows(visit, 0)
    if not found:
        return False
    window = found[0]
    user32.ShowWindow(window, 9)
    return bool(user32.SetForegroundWindow(window))


def _response_headers(headers: Any) -> dict[str, str]:
    excluded = {"connection", "content-length", "transfer-encoding", "content-encoding"}
    return {
        str(key): str(value)
        for key, value in headers.items()
        if str(key).lower() not in excluded
    }


async def _terminate_process(process: Any) -> None:
    if process.returncode is not None:
        return
    process.terminate()
    try:
        await asyncio.wait_for(process.wait(), timeout=5)
    except TimeoutError:
        process.kill()
        await process.wait()
