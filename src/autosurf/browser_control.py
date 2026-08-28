from __future__ import annotations

import asyncio
import time
from contextlib import suppress
from typing import Any, Callable

from playwright.async_api import async_playwright

from autosurf.automations.browser_session import (
    persistent_chromium_session,
    validated_http_url,
)
from autosurf.domain.models import RunContext


VIEWPORT_WIDTH = 1365
VIEWPORT_HEIGHT = 768
DEFAULT_IDLE_TIMEOUT_SECONDS = 15 * 60


class BrowserControlError(RuntimeError):
    pass


class BrowserControlInactive(BrowserControlError):
    pass


class BrowserControlService:
    def __init__(
        self,
        *,
        session_factory: Callable[..., Any] = persistent_chromium_session,
        playwright_factory: Callable[[], Any] = async_playwright,
        idle_timeout_seconds: float = DEFAULT_IDLE_TIMEOUT_SECONDS,
    ) -> None:
        self._session_factory = session_factory
        self._playwright_factory = playwright_factory
        self._idle_timeout_seconds = max(float(idle_timeout_seconds), 10.0)
        self._lifecycle_lock = asyncio.Lock()
        self._operation_lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None
        self._ready: asyncio.Event | None = None
        self._stop_event: asyncio.Event | None = None
        self._page: Any | None = None
        self._starting = False
        self._mode: str | None = None
        self._error: str | None = None
        self._last_activity = 0.0

    async def start(self, url: str) -> dict[str, Any]:
        target = validated_http_url(url).geturl()
        async with self._lifecycle_lock:
            if self._task is not None and not self._task.done():
                raise BrowserControlError("浏览器维护会话已经启动")
            self._ready = asyncio.Event()
            self._stop_event = asyncio.Event()
            self._starting = True
            self._page = None
            self._mode = None
            self._error = None
            self._last_activity = time.monotonic()
            self._task = asyncio.create_task(self._run(target))
            ready = self._ready
        try:
            await asyncio.wait_for(ready.wait(), timeout=30)
        except TimeoutError as exc:
            await self.stop()
            raise BrowserControlError("启动 Chrome 超时") from exc
        if self._page is None:
            message = self._error or "Chrome 启动失败"
            await self.stop()
            raise BrowserControlError(message)
        return await self.status(touch=True)

    async def stop(self) -> dict[str, Any]:
        async with self._lifecycle_lock:
            task = self._task
            stop_event = self._stop_event
            if task is None:
                self._reset_runtime()
                return await self.status()
        async with self._operation_lock:
            self._page = None
            if stop_event is not None:
                stop_event.set()
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=10)
        except TimeoutError:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        async with self._lifecycle_lock:
            if self._task is task:
                self._reset_runtime()
        return await self.status()

    async def shutdown(self) -> None:
        await self.stop()

    async def status(self, *, touch: bool = False) -> dict[str, Any]:
        if touch and self._page is not None:
            self._touch()
        page = self._page
        active = page is not None and not await self._page_is_closed(page)
        url = ""
        title = ""
        if active:
            url = str(page.url or "")
            with suppress(Exception):
                title = str(await page.title())[:300]
        task = self._task
        return {
            "active": active,
            "starting": self._starting,
            "url": url,
            "title": title,
            "mode": self._mode,
            "viewport": {"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT},
            "error": self._error,
            "task_running": bool(task is not None and not task.done()),
        }

    async def frame(self) -> bytes:
        page = await self._active_page()
        async with self._operation_lock:
            self._touch()
            try:
                return await page.screenshot(type="png", animations="disabled")
            except Exception as exc:
                self._record_error(exc)
                raise BrowserControlError("读取 Chrome 画面失败") from exc

    async def navigate(self, action: str, url: str | None = None) -> dict[str, Any]:
        page = await self._active_page()
        async with self._operation_lock:
            self._touch()
            try:
                if action == "goto":
                    if url is None:
                        raise ValueError("缺少网址")
                    target = validated_http_url(url).geturl()
                    await page.goto(target, wait_until="domcontentloaded", timeout=60_000)
                elif action == "back":
                    await page.go_back(wait_until="domcontentloaded", timeout=30_000)
                elif action == "forward":
                    await page.go_forward(wait_until="domcontentloaded", timeout=30_000)
                elif action == "reload":
                    await page.reload(wait_until="domcontentloaded", timeout=60_000)
                else:
                    raise ValueError("不支持的导航动作")
                self._error = None
            except ValueError:
                raise
            except Exception as exc:
                self._record_error(exc)
                raise BrowserControlError("Chrome 导航失败") from exc
        return await self.status(touch=True)

    async def input(
        self,
        action: str,
        *,
        x: float | None = None,
        y: float | None = None,
        delta_x: float = 0,
        delta_y: float = 0,
        key: str | None = None,
        text: str | None = None,
    ) -> dict[str, Any]:
        page = await self._active_page()
        async with self._operation_lock:
            self._touch()
            try:
                if action in {"click", "double_click"}:
                    if x is None or y is None:
                        raise ValueError("点击缺少坐标")
                    if not 0 <= x <= VIEWPORT_WIDTH or not 0 <= y <= VIEWPORT_HEIGHT:
                        raise ValueError("点击坐标超出画面")
                    await page.mouse.click(x, y, click_count=2 if action == "double_click" else 1)
                elif action == "wheel":
                    await page.mouse.wheel(delta_x, delta_y)
                elif action == "key":
                    if not key:
                        raise ValueError("缺少按键")
                    await page.keyboard.press(key)
                elif action == "text":
                    if text is None:
                        raise ValueError("缺少输入文字")
                    await page.keyboard.insert_text(text)
                else:
                    raise ValueError("不支持的输入动作")
                self._error = None
            except ValueError:
                raise
            except Exception as exc:
                self._record_error(exc)
                raise BrowserControlError("Chrome 输入操作失败") from exc
        return await self.status(touch=True)

    async def _run(self, url: str) -> None:
        ready = self._ready
        stop_event = self._stop_event
        assert ready is not None and stop_event is not None
        try:
            async with self._playwright_factory() as playwright:
                context = RunContext(
                    execution_id="browser-control",
                    config={"url": url},
                    cookies={},
                )
                async with self._session_factory(playwright, context, url) as session:
                    browser_context = session.context
                    page = (
                        browser_context.pages[0]
                        if browser_context.pages
                        else await browser_context.new_page()
                    )
                    page.set_default_timeout(15_000)
                    self._page = page
                    self._mode = session.mode
                    self._starting = False
                    try:
                        await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                    except Exception as exc:
                        self._record_error(exc)
                    ready.set()
                    while not stop_event.is_set():
                        try:
                            await asyncio.wait_for(stop_event.wait(), timeout=5)
                        except TimeoutError:
                            if time.monotonic() - self._last_activity >= self._idle_timeout_seconds:
                                break
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._record_error(exc)
            self._starting = False
            ready.set()
        finally:
            self._page = None
            self._mode = None
            self._starting = False
            ready.set()

    async def _active_page(self) -> Any:
        page = self._page
        if page is None or await self._page_is_closed(page):
            raise BrowserControlInactive("浏览器维护会话未启动")
        return page

    async def _page_is_closed(self, page: Any) -> bool:
        try:
            value = page.is_closed()
            return bool(await value) if hasattr(value, "__await__") else bool(value)
        except Exception:
            return True

    def _record_error(self, error: Exception) -> None:
        value = str(error).strip().splitlines()[0] if str(error).strip() else type(error).__name__
        self._error = value[:500]

    def _touch(self) -> None:
        self._last_activity = time.monotonic()

    def _reset_runtime(self) -> None:
        self._task = None
        self._ready = None
        self._stop_event = None
        self._page = None
        self._starting = False
        self._mode = None
