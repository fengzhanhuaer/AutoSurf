from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from autosurf.browser_control import (
    BrowserControlInactive,
    BrowserControlService,
)
from autosurf.config import Settings
from autosurf.main import create_app


@pytest.fixture
def settings(tmp_path):
    return Settings(
        data_dir=tmp_path,
        secret_key="s" * 32,
        username="admin",
        password="password123",
        worker_poll_seconds=0.01,
        scheduler_poll_seconds=0.01,
    )


class FakeMouse:
    def __init__(self):
        self.clicks = []
        self.wheels = []

    async def click(self, x, y, *, click_count):
        self.clicks.append((x, y, click_count))

    async def wheel(self, delta_x, delta_y):
        self.wheels.append((delta_x, delta_y))


class FakeKeyboard:
    def __init__(self):
        self.keys = []
        self.text = []

    async def press(self, key):
        self.keys.append(key)

    async def insert_text(self, text):
        self.text.append(text)


class FakePage:
    def __init__(self):
        self.url = "about:blank"
        self.mouse = FakeMouse()
        self.keyboard = FakeKeyboard()
        self.history = []
        self.timeout = None
        self.closed = False

    def set_default_timeout(self, timeout):
        self.timeout = timeout

    def is_closed(self):
        return self.closed

    async def title(self):
        return f"Title: {self.url}"

    async def goto(self, url, **_kwargs):
        self.url = url
        self.history.append(("goto", url))

    async def go_back(self, **_kwargs):
        self.history.append(("back", None))

    async def go_forward(self, **_kwargs):
        self.history.append(("forward", None))

    async def reload(self, **_kwargs):
        self.history.append(("reload", None))

    async def screenshot(self, **kwargs):
        assert kwargs == {"type": "png", "animations": "disabled"}
        return b"\x89PNG\r\n\x1a\nframe"


class FakePlaywrightContext:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, *_args):
        return None


@pytest.fixture
def controlled_browser():
    page = FakePage()
    exited = {"value": False}

    @asynccontextmanager
    async def session_factory(_playwright, context, url):
        assert context.execution_id == "browser-control"
        assert context.config["url"] == url
        yield SimpleNamespace(
            context=SimpleNamespace(pages=[page]),
            mode="persistent_headful",
        )
        exited["value"] = True

    service = BrowserControlService(
        session_factory=session_factory,
        playwright_factory=FakePlaywrightContext,
        idle_timeout_seconds=60,
    )
    return service, page, exited


@pytest.mark.asyncio
async def test_browser_control_session_frame_navigation_and_input(controlled_browser):
    service, page, exited = controlled_browser

    started = await service.start("https://example.com/")
    assert started["active"] is True
    assert started["starting"] is False
    assert started["mode"] == "persistent_headful"
    assert started["viewport"] == {"width": 1365, "height": 768}
    assert page.timeout == 15_000
    assert await service.frame() == b"\x89PNG\r\n\x1a\nframe"

    await service.navigate("goto", "https://example.org/path")
    await service.navigate("back")
    await service.navigate("forward")
    await service.navigate("reload")
    await service.input("click", x=100, y=200)
    await service.input("double_click", x=101, y=201)
    await service.input("wheel", delta_x=3, delta_y=240)
    await service.input("key", key="Control+A")
    await service.input("text", text="测试 text")

    assert page.history == [
        ("goto", "https://example.com/"),
        ("goto", "https://example.org/path"),
        ("back", None),
        ("forward", None),
        ("reload", None),
    ]
    assert page.mouse.clicks == [(100, 200, 1), (101, 201, 2)]
    assert page.mouse.wheels == [(3, 240)]
    assert page.keyboard.keys == ["Control+A"]
    assert page.keyboard.text == ["测试 text"]

    stopped = await service.stop()
    assert stopped["active"] is False
    assert stopped["task_running"] is False
    assert exited["value"] is True


@pytest.mark.asyncio
async def test_browser_control_rejects_invalid_and_inactive_operations(controlled_browser):
    service, _page, _exited = controlled_browser

    with pytest.raises(ValueError):
        await service.start("file:///etc/passwd")
    with pytest.raises(BrowserControlInactive):
        await service.frame()

    await service.start("https://example.com/")
    with pytest.raises(ValueError, match="坐标"):
        await service.input("click", x=1400, y=10)
    with pytest.raises(ValueError, match="导航动作"):
        await service.navigate("invalid")
    await service.shutdown()


class FakeBrowserControlApi:
    def __init__(self):
        self.active = False
        self.calls = []

    async def status(self, *, touch=False):
        return {
            "active": self.active,
            "starting": False,
            "url": "https://example.com/" if self.active else "",
            "title": "Example" if self.active else "",
            "mode": "persistent_headful" if self.active else None,
            "viewport": {"width": 1365, "height": 768},
            "error": None,
            "task_running": self.active,
            "touched": touch,
        }

    async def start(self, url):
        self.calls.append(("start", url))
        self.active = True
        return await self.status()

    async def stop(self):
        self.calls.append(("stop",))
        self.active = False
        return await self.status()

    async def frame(self):
        self.calls.append(("frame",))
        return b"\x89PNG\r\n\x1a\nframe"

    async def navigate(self, action, url):
        self.calls.append(("navigate", action, url))
        return await self.status()

    async def input(self, action, **kwargs):
        self.calls.append(("input", action, kwargs))
        return await self.status()


@pytest.mark.asyncio
async def test_browser_control_api_uses_existing_authenticated_router(settings):
    app = create_app(settings)
    fake = FakeBrowserControlApi()
    app.state.browser_control = fake
    transport = httpx.ASGITransport(app=app)
    auth = (settings.username, settings.password)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/api/v1/browser-control")).status_code == 401
        status = await client.get("/api/v1/browser-control", auth=auth)
        assert status.status_code == 200
        assert status.json()["active"] is False

        started = await client.post(
            "/api/v1/browser-control/session",
            auth=auth,
            json={"url": "https://example.com/"},
        )
        assert started.status_code == 201
        assert started.json()["active"] is True

        frame = await client.get("/api/v1/browser-control/frame", auth=auth)
        assert frame.status_code == 200
        assert frame.headers["content-type"] == "image/png"
        assert frame.headers["cache-control"] == "no-store, max-age=0"

        navigated = await client.post(
            "/api/v1/browser-control/navigate",
            auth=auth,
            json={"action": "goto", "url": "https://example.org/"},
        )
        assert navigated.status_code == 200
        clicked = await client.post(
            "/api/v1/browser-control/input",
            auth=auth,
            json={"action": "click", "x": 123, "y": 456},
        )
        assert clicked.status_code == 200
        stopped = await client.delete("/api/v1/browser-control/session", auth=auth)
        assert stopped.status_code == 200
        assert stopped.json()["active"] is False

    assert fake.calls == [
        ("start", "https://example.com/"),
        ("frame",),
        ("navigate", "goto", "https://example.org/"),
        (
            "input",
            "click",
            {
                "x": 123.0,
                "y": 456.0,
                "delta_x": 0.0,
                "delta_y": 0.0,
                "key": None,
                "text": None,
            },
        ),
        ("stop",),
    ]


def test_compose_keeps_browser_control_on_existing_port_only():
    compose = Path("compose.yaml").read_text(encoding="utf-8")
    assert '"0.0.0.0:18980:8080"' in compose
    assert "18981" not in compose
    assert "6080" not in compose
    assert "5900" not in compose


def test_browser_control_management_ui_contract():
    html = Path("src/autosurf/web/admin.html").read_text(encoding="utf-8")
    javascript = Path("src/autosurf/web/admin.js").read_text(encoding="utf-8")
    css = Path("src/autosurf/web/admin.css").read_text(encoding="utf-8")

    assert 'data-view="browser-control"' in html
    assert 'id="browser-control-panel"' in html
    assert 'id="browser-frame-shell"' in html
    assert 'class="browser-frame" id="browser-frame"' in html
    assert 'id="browser-address-form"' in html
    assert 'id="browser-text-form"' in html
    assert 'api("/api/v1/browser-control"' in javascript
    assert 'fetch(`/api/v1/browser-control/frame?t=${Date.now()}`' in javascript
    assert 'method: "POST", body: JSON.stringify({ action: "goto", url })' in javascript
    assert 'aspect-ratio: 1365 / 768' in css
