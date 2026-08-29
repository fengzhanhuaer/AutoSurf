from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any, Callable

from playwright.async_api import async_playwright

from autosurf.automations.browser_session import (
    PersistentBrowserRuntime,
    PersistentBrowserSession,
    close_persistent_browser,
    launch_persistent_browser,
    prepare_browser_for_run,
    register_shared_browser_provider,
    save_browser_after_run,
    validated_http_url,
)
from autosurf.domain.models import RunContext


REMOTE_DESKTOP_PREFIX = "/browser-control/remote"
DEFAULT_SOCKET_PATH = Path("/tmp/autosurf-novnc.sock")
VNC_LOOPBACK_PORT = 5900
RESTART_DELAY_SECONDS = 3
STARTUP_TIMEOUT_SECONDS = 30


class BrowserControlError(RuntimeError):
    pass


class BrowserControlInactive(BrowserControlError):
    pass


class BrowserControlService:
    def __init__(
        self,
        *,
        playwright_factory: Callable[[], Any] = async_playwright,
        browser_launcher: Callable[..., Any] = launch_persistent_browser,
        browser_closer: Callable[..., Any] = close_persistent_browser,
        process_factory: Callable[..., Any] = asyncio.create_subprocess_exec,
        socket_path: Path = DEFAULT_SOCKET_PATH,
    ) -> None:
        self._playwright_factory = playwright_factory
        self._browser_launcher = browser_launcher
        self._browser_closer = browser_closer
        self._process_factory = process_factory
        self._socket_path = socket_path
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
            page = await self._control_page()
            with suppress(Exception):
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

    async def status(self, *, touch: bool = False) -> dict[str, Any]:
        del touch
        runtime = self._runtime
        active = (
            runtime is not None
            and self._vnc_process is not None
            and self._remote_process is not None
            and self._socket_path.exists()
        )
        url = ""
        title = ""
        if runtime is not None:
            pages = [page for page in runtime.context.pages if not page.is_closed()]
            if pages:
                page = pages[-1]
                url = str(page.url or "")
                with suppress(Exception):
                    title = str(await page.title())[:300]
        task = self._task
        return {
            "active": active,
            "starting": self._starting,
            "url": url,
            "title": title,
            "mode": runtime.mode if runtime is not None else None,
            "viewport": {"width": 1365, "height": 768},
            "error": self._error,
            "task_running": bool(task is not None and not task.done()),
            "always_on": True,
            "busy": self._operation_lock.locked(),
            "automation_owner": self._automation_owner,
            "remote_url": (
                f"{REMOTE_DESKTOP_PREFIX}/vnc.html"
                f"?autoconnect=1&resize=scale&reconnect=1&reconnect_delay=2000"
                f"&path=websockify"
            ),
            "restart_count": self._restart_count,
            "stream_log": self._stream_log,
        }

    @asynccontextmanager
    async def automation_session(self, run_context: RunContext, url: str):
        validated_http_url(url)
        runtime = await self._wait_for_runtime()
        async with self._operation_lock:
            if runtime is not self._runtime:
                runtime = await self._wait_for_runtime()
            self._automation_owner = run_context.execution_id
            pages_before = set(runtime.context.pages)
            try:
                await prepare_browser_for_run(runtime, run_context, url)
                yield PersistentBrowserSession(
                    runtime.context,
                    "shared",
                    runtime.mode,
                    runtime.display.name if runtime.display else None,
                )
            finally:
                with suppress(Exception):
                    await save_browser_after_run(runtime, url)
                for page in list(runtime.context.pages):
                    if page not in pages_before:
                        with suppress(Exception):
                            await page.close()
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
        manager = self._playwright_factory()
        playwright = None
        runtime = None
        vnc = None
        remote = None
        log_tasks: list[asyncio.Task[None]] = []
        closed = asyncio.Event()
        try:
            playwright = await manager.start()
            context = RunContext(
                execution_id="browser-control",
                config={"locale": "zh-CN"},
                cookies={},
            )
            runtime = await self._browser_launcher(
                playwright,
                context,
                remote_desktop=True,
            )
            if runtime.display is None:
                raise BrowserControlError("完整浏览器控制需要 Docker 中的 Xvfb")
            runtime.context.on("close", lambda _context: closed.set())
            page = await self._control_page(runtime)
            page.set_default_timeout(15_000)
            self._runtime = runtime
            vnc, remote = await self._start_remote_desktop(runtime.display.name)
            self._vnc_process = vnc
            self._remote_process = remote
            for process in (vnc, remote):
                if process.stdout is not None:
                    log_tasks.append(asyncio.create_task(self._drain_stream(process.stdout)))
                if process.stderr is not None:
                    log_tasks.append(asyncio.create_task(self._drain_stream(process.stderr)))
            await self._wait_for_socket(remote)
            self._error = None
            self._starting = False
            self._initial_ready.set()

            stop_wait = asyncio.create_task(stop_event.wait())
            close_wait = asyncio.create_task(closed.wait())
            vnc_wait = asyncio.create_task(vnc.wait())
            remote_wait = asyncio.create_task(remote.wait())
            done, pending = await asyncio.wait(
                {stop_wait, close_wait, vnc_wait, remote_wait},
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
            if close_wait in done and not stop_event.is_set():
                raise BrowserControlError("Chromium 意外退出")
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
            if playwright is not None:
                with suppress(Exception):
                    await playwright.stop()
            self._socket_path.unlink(missing_ok=True)

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
        if current is None:
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
