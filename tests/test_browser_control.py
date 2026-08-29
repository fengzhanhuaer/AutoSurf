import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from autosurf.automations.browser_session import (
    PersistentBrowserRuntime,
    persistent_chromium_session,
    register_shared_browser_provider,
)
from autosurf.browser_control import BrowserControlService
from autosurf.config import Settings
from autosurf.domain.models import RunContext
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


class FakePage:
    def __init__(self, url="about:blank"):
        self.url = url
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

    async def close(self):
        self.closed = True


class FakeContext:
    def __init__(self):
        self.pages = [FakePage()]
        self.listeners = {}

    def on(self, event, callback):
        self.listeners[event] = callback

    async def new_page(self):
        page = FakePage()
        self.pages.append(page)
        return page


class FakePlaywright:
    def __init__(self):
        self.stopped = False

    async def stop(self):
        self.stopped = True


class FakePlaywrightManager:
    def __init__(self, playwright):
        self.playwright = playwright

    async def start(self):
        return self.playwright


class FakeProcess:
    def __init__(self):
        self.returncode = None
        self.stdout = None
        self.stderr = None
        self._stopped = asyncio.Event()

    async def wait(self):
        await self._stopped.wait()
        return self.returncode

    def terminate(self):
        self.returncode = 0
        self._stopped.set()

    def kill(self):
        self.terminate()


@pytest.mark.asyncio
async def test_browser_control_stays_running_and_leases_task_pages(tmp_path, monkeypatch):
    socket_path = tmp_path / "selkies.sock"
    context = FakeContext()
    runtime = PersistentBrowserRuntime(
        context=context,
        profile_path=tmp_path / "profile",
        mode="persistent_headful",
        display=SimpleNamespace(name=":90"),
    )
    playwright = FakePlaywright()
    launched = []
    closed = []

    async def browser_launcher(_playwright, run_context, *, remote_desktop):
        launched.append((run_context.execution_id, remote_desktop))
        return runtime

    async def browser_closer(value):
        closed.append(value)

    async def process_factory(*args, **kwargs):
        assert "--unix-socket=" + str(socket_path) in args
        assert "--subfolder=/browser-control/remote" in args
        assert kwargs["env"]["DISPLAY"] == ":90"
        socket_path.touch()
        return FakeProcess()

    prepared = []
    saved = []

    async def prepare(value, run_context, url):
        prepared.append((value, run_context.execution_id, url))

    async def save(value, url):
        saved.append((value, url))

    monkeypatch.setattr("autosurf.browser_control.prepare_browser_for_run", prepare)
    monkeypatch.setattr("autosurf.browser_control.save_browser_after_run", save)

    service = BrowserControlService(
        playwright_factory=lambda: FakePlaywrightManager(playwright),
        browser_launcher=browser_launcher,
        browser_closer=browser_closer,
        process_factory=process_factory,
        socket_path=socket_path,
    )
    started = await service.start()
    assert started["active"] is True
    assert started["always_on"] is True
    assert started["remote_url"] == "/browser-control/remote/"
    assert launched == [("browser-control", True)]

    run_context = RunContext("execution-1", {"url": "https://example.com/"}, {})
    async with service.automation_session(run_context, "https://example.com/") as session:
        assert session.context is context
        task_page = await context.new_page()
        status = await service.status()
        assert status["busy"] is True
        assert status["automation_owner"] == "execution-1"

    assert task_page.closed is True
    assert context.pages[0].closed is False
    assert prepared == [(runtime, "execution-1", "https://example.com/")]
    assert saved == [(runtime, "https://example.com/")]
    assert (await service.status())["active"] is True

    await service.shutdown()
    assert closed == [runtime]
    assert playwright.stopped is True
    assert (await service.status())["active"] is False


@pytest.mark.asyncio
async def test_persistent_session_delegates_to_registered_host():
    calls = []

    class Provider:
        @asynccontextmanager
        async def automation_session(self, run_context, url):
            calls.append((run_context.execution_id, url))
            yield SimpleNamespace(context="shared", mode="persistent_headful")

    register_shared_browser_provider(Provider())
    try:
        context = RunContext("execution-2", {"url": "https://example.com/"}, {})
        async with persistent_chromium_session(None, context, "https://example.com/") as session:
            assert session.context == "shared"
    finally:
        register_shared_browser_provider(None)
    assert calls == [("execution-2", "https://example.com/")]


class FakeBrowserControlApi:
    async def status(self):
        return {
            "active": True,
            "starting": False,
            "url": "about:blank",
            "title": "Chromium",
            "mode": "persistent_headful",
            "viewport": {"width": 1365, "height": 768},
            "error": None,
            "task_running": True,
            "always_on": True,
            "busy": False,
            "automation_owner": None,
            "remote_url": "/browser-control/remote/",
        }


@pytest.mark.asyncio
async def test_browser_control_status_and_remote_proxy_require_login(settings):
    app = create_app(settings)
    app.state.browser_control = FakeBrowserControlApi()
    transport = httpx.ASGITransport(app=app)
    auth = (settings.username, settings.password)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/api/v1/browser-control")).status_code == 401
        status = await client.get("/api/v1/browser-control", auth=auth)
        assert status.status_code == 200
        assert status.json()["always_on"] is True

        assert (await client.get("/browser-control/remote/")).status_code == 401
        unavailable = await client.get("/browser-control/remote/", auth=auth)
        assert unavailable.status_code == 503


def test_browser_control_uses_unix_socket_and_existing_port_only():
    compose = Path("compose.yaml").read_text(encoding="utf-8")
    source = Path("src/autosurf/browser_control.py").read_text(encoding="utf-8")
    assert '"0.0.0.0:18980:8080"' in compose
    assert "18981" not in compose
    assert "6080" not in compose
    assert "5900" not in compose
    assert "--unix-socket=" in source
    assert "--subfolder=/browser-control/remote" not in compose


def test_browser_control_management_ui_embeds_full_remote_desktop():
    html = Path("src/autosurf/web/admin.html").read_text(encoding="utf-8")
    javascript = Path("src/autosurf/web/admin.js").read_text(encoding="utf-8")
    css = Path("src/autosurf/web/admin.css").read_text(encoding="utf-8")

    assert 'data-view="browser-control"' in html
    assert 'id="browser-control-panel"' in html
    assert 'id="browser-remote-frame"' in html
    assert 'title="Chromium 远程桌面"' in html
    assert 'id="browser-remote-cover"' in html
    assert 'id="browser-address-form"' not in html
    assert 'id="browser-start"' not in html
    assert 'id="browser-frame"' not in html
    assert 'api("/api/v1/browser-control"' in javascript
    assert '"/browser-control/remote/"' in javascript
    assert "/api/v1/browser-control/frame" not in javascript
    assert "aspect-ratio: 1365 / 768" in css
