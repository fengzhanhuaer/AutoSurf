import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
import hashlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import inspect
import json
from pathlib import Path
import re
import subprocess
import threading
from types import SimpleNamespace
import zipfile

import httpx
import pytest

from autosurf.automations.browser_session import (
    PersistentBrowserRuntime,
    PersistentBrowserSession,
    foreground_browser_page,
    new_browser_task_page,
    prepare_detached_browser_challenge,
    prepared_browser_task_page,
    persistent_browser_task_page,
    persistent_chromium_session,
    register_shared_browser_provider,
    with_browser_details,
)
from autosurf.browser_control import (
    BrowserControlBusy,
    BrowserControlService,
    BrowserDisplaySettings,
    CdpAutomationProvider,
    detached_safeline_warmup,
)
from autosurf.config import Settings
from autosurf.domain.models import RunContext, RunOutcome, RunResult
from autosurf.main import create_app
from autosurf.main import run_worker


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
        self.window_name = ""
        self.foreground_calls = 0

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

    async def evaluate(self, script, value=None):
        if "window.name = name" in script:
            self.window_name = value
            return None
        if "window.name" in script:
            return self.window_name
        return None

    async def bring_to_front(self):
        self.foreground_calls += 1


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
async def test_task_page_uses_a_separate_visible_chrome_window():
    page = FakePage()
    commands = []

    class Cdp:
        async def send(self, method, params=None):
            commands.append((method, params))
            if method == "Target.createTarget":
                return {"targetId": "target-1"}
            if method == "Browser.getWindowForTarget":
                return {"windowId": 42}
            return {}

        async def detach(self):
            commands.append(("detach", None))

    class ExpectedPage:
        async def __aenter__(self):
            future = asyncio.get_running_loop().create_future()
            future.set_result(page)
            return SimpleNamespace(value=future)

        async def __aexit__(self, *_args):
            return None

    class Browser:
        async def new_browser_cdp_session(self):
            return Cdp()

    context = SimpleNamespace(
        browser=Browser(),
        expect_page=lambda **_kwargs: ExpectedPage(),
    )

    created = await new_browser_task_page(context)

    assert created is page
    create = next(params for method, params in commands if method == "Target.createTarget")
    assert create == {"url": "about:blank", "newWindow": True, "background": False}
    bounds = next(params for method, params in commands if method == "Browser.setWindowBounds")
    assert bounds["windowId"] == 42
    assert bounds["bounds"]["left"] == 0
    assert commands[-1] == ("detach", None)


@pytest.mark.asyncio
async def test_persistent_task_page_reuses_its_marked_window(monkeypatch):
    context = FakeContext()
    created = []

    async def create_page(value):
        page = await value.new_page()
        created.append(page)
        return page

    monkeypatch.setattr(
        "autosurf.automations.browser_session.new_browser_task_page", create_page,
    )

    first = await persistent_browser_task_page(context)
    second = await persistent_browser_task_page(context)

    assert first is second
    assert created == [first]
    assert first.window_name == "__autosurf_automation_window__"
    assert first.foreground_calls == 1


@pytest.mark.asyncio
async def test_prepared_task_page_adopts_warmup_tab_and_closes_previous_task_page():
    previous = FakePage("https://previous.example/")
    previous.window_name = "__autosurf_automation_window__"
    manual = FakePage("https://manual.example/")
    warmup = FakePage("https://www.hdkyl.in/")
    context = FakeContext()
    context.pages = [manual, previous, warmup]

    selected = await prepared_browser_task_page(
        context, "https://www.hdkyl.in/attendance.php",
    )

    assert selected is warmup
    assert warmup.window_name == "__autosurf_automation_window__"
    assert warmup.foreground_calls == 1
    assert previous.closed is True
    assert manual.closed is False


@pytest.mark.asyncio
async def test_detached_safeline_warmup_skips_non_468(monkeypatch, tmp_path):
    opened = []

    monkeypatch.setattr("autosurf.browser_control._probe_http_status", lambda _url: 200)

    async def open_url(*_args):
        opened.append(True)
        return True

    monkeypatch.setattr("autosurf.browser_control._open_url_without_cdp", open_url)
    runtime = PersistentBrowserRuntime(
        context=None,
        profile_path=tmp_path,
        mode="persistent_headful",
        display=None,
        cdp_endpoint="http://127.0.0.1:9222",
    )

    assert await detached_safeline_warmup(runtime, "https://example.com/") is False
    assert opened == []


@pytest.mark.asyncio
async def test_detached_safeline_warmup_opens_before_polling_normal_page(
    monkeypatch, tmp_path,
):
    events = []

    def probe(_url):
        events.append("probe")
        return 468

    async def pages(_runtime):
        events.append("pages")
        return [{
            "type": "page",
            "url": "https://www.hdkyl.in/",
            "title": "HDKylin - Powered by NexusPHP",
        }]

    async def open_url(_runtime, _url):
        events.append("open")
        return True

    async def sleep(_delay):
        events.append("sleep")

    monkeypatch.setattr("autosurf.browser_control._probe_http_status", probe)
    monkeypatch.setattr("autosurf.browser_control.standalone_browser_pages", pages)
    monkeypatch.setattr("autosurf.browser_control._open_url_without_cdp", open_url)
    monkeypatch.setattr("autosurf.browser_control.asyncio.sleep", sleep)
    runtime = PersistentBrowserRuntime(
        context=None,
        profile_path=tmp_path,
        mode="persistent_headful",
        display=None,
        cdp_endpoint="http://127.0.0.1:9222",
    )

    assert await detached_safeline_warmup(
        runtime,
        "https://www.hdkyl.in/attendance.php",
        minimum_seconds=0,
        timeout_seconds=1,
    ) is True
    assert events[:3] == ["probe", "pages", "open"]
    assert events[3:] == ["sleep", "pages"]


@pytest.mark.asyncio
async def test_detached_safeline_warmup_times_out_without_marking_prepared(
    monkeypatch, tmp_path,
):
    opened = []

    monkeypatch.setattr("autosurf.browser_control._probe_http_status", lambda _url: 468)

    async def pages(_runtime):
        return [{
            "type": "page",
            "url": "https://www.hdkyl.in/",
            "title": "www.hdkyl.in",
        }]

    async def open_url(_runtime, url):
        opened.append(url)
        return True

    monkeypatch.setattr("autosurf.browser_control.standalone_browser_pages", pages)
    monkeypatch.setattr("autosurf.browser_control._open_url_without_cdp", open_url)
    runtime = PersistentBrowserRuntime(
        context=None,
        profile_path=tmp_path,
        mode="persistent_headful",
        display=None,
        cdp_endpoint="http://127.0.0.1:9222",
    )

    assert await detached_safeline_warmup(
        runtime,
        "https://www.hdkyl.in/attendance.php",
        minimum_seconds=0,
        timeout_seconds=0,
    ) is False
    assert opened == ["https://www.hdkyl.in/attendance.php"]


@pytest.mark.asyncio
async def test_detached_challenge_provider_failure_falls_back():
    class Provider:
        async def prepare_detached_challenge(self, _context, _url):
            raise RuntimeError("warmup unavailable")

    register_shared_browser_provider(Provider())
    try:
        prepared = await prepare_detached_browser_challenge(
            RunContext("execution-fallback", {}, {}),
            "https://example.com/",
        )
    finally:
        register_shared_browser_provider(None)

    assert prepared is False


def test_browser_details_record_detached_waf_warmup():
    session = PersistentBrowserSession(
        context=object(),
        profile_key="shared",
        mode="persistent_headful",
        detached_waf_warmup=True,
    )

    result = with_browser_details(
        RunResult(RunOutcome.ALREADY_DONE, "today"), session,
    )

    assert result.details["browser"]["detached_waf_warmup"] is True


@pytest.mark.asyncio
async def test_foreground_browser_page_only_activates_visible_window():
    class Page:
        foreground_calls = 0

        async def bring_to_front(self):
            self.foreground_calls += 1

    page_instance = Page()

    async with foreground_browser_page(page_instance):
        assert page_instance.foreground_calls == 1

    assert page_instance.foreground_calls == 1


@pytest.mark.asyncio
async def test_worker_cdp_provider_keeps_and_reuses_automation_window(tmp_path, monkeypatch):
    control_page = FakePage("https://manual.example/")
    task_page = FakePage()
    context = FakeContext()
    context.pages = [control_page]
    playwright = FakePlaywright()

    async def connect(_playwright, runtime):
        assert _playwright is playwright
        return replace(runtime, context=context, browser_connection=object())

    async def create_page(value):
        assert value is context
        context.pages.append(task_page)
        return task_page

    monkeypatch.setattr("autosurf.browser_control.connect_standalone_browser", connect)
    monkeypatch.setattr(
        "autosurf.automations.browser_session.new_browser_task_page", create_page,
    )
    provider = CdpAutomationProvider()

    async with provider.automation_session(
        RunContext("worker-execution", {}, {}),
        "https://example.com/",
        playwright=playwright,
    ) as session:
        assert await session.new_page() is task_page

    async with provider.automation_session(
        RunContext("worker-execution-2", {}, {}),
        "https://example.com/",
        playwright=playwright,
    ) as session:
        assert await session.new_page() is task_page

    assert task_page.closed is False
    assert control_page.closed is False
    assert context.pages.count(task_page) == 1
    assert playwright.stopped is False


@pytest.mark.asyncio
async def test_worker_cdp_provider_prepares_before_connect_and_adopts_warmup_page(
    tmp_path, monkeypatch,
):
    events = []
    warmup_page = FakePage("https://www.hdkyl.in/")
    context = FakeContext()
    context.pages = [warmup_page]
    playwright = FakePlaywright()

    async def warmup(runtime, url):
        events.append(("warmup", url, runtime.cdp_endpoint))
        return True

    async def connect(_playwright, runtime):
        events.append(("connect", runtime.cdp_endpoint))
        return replace(runtime, context=context, browser_connection=object())

    monkeypatch.setattr("autosurf.browser_control.detached_safeline_warmup", warmup)
    monkeypatch.setattr("autosurf.browser_control.connect_standalone_browser", connect)
    monkeypatch.setattr(
        "autosurf.browser_control.browser_profile_path", lambda: tmp_path,
    )
    provider = CdpAutomationProvider()
    run_context = RunContext("execution-waf", {}, {})

    assert await provider.prepare_detached_challenge(
        run_context, "https://www.hdkyl.in/attendance.php",
    ) is True
    async with provider.automation_session(
        run_context,
        "https://www.hdkyl.in/attendance.php",
        playwright=playwright,
    ) as session:
        assert session.detached_waf_warmup is True
        assert await session.new_page() is warmup_page

    assert events[0][0] == "warmup"
    assert events[1][0] == "connect"


@pytest.mark.asyncio
async def test_worker_cdp_provider_waits_for_chrome_startup(tmp_path, monkeypatch):
    context = FakeContext()
    attempts = 0
    sleeps = []

    async def connect(_playwright, runtime):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise ConnectionError("Chrome is starting")
        return replace(runtime, context=context, browser_connection=object())

    async def sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr("autosurf.browser_control.connect_standalone_browser", connect)
    monkeypatch.setattr("autosurf.browser_control.asyncio.sleep", sleep)
    provider = CdpAutomationProvider()
    runtime = PersistentBrowserRuntime(
        context=None,
        profile_path=tmp_path,
        mode="persistent_headful",
        display=None,
        cdp_endpoint="http://127.0.0.1:9222",
    )

    connected = await provider._connect(FakePlaywright(), runtime)

    assert connected.context is context
    assert attempts == 3
    assert sleeps == [0.5, 0.5]


def test_web_app_and_worker_have_separate_process_responsibilities():
    web_source = inspect.getsource(create_app)
    worker_source = inspect.getsource(run_worker)
    main_source = Path("src/autosurf/main.py").read_text(encoding="utf-8")

    assert "scheduler_loop" not in web_source
    assert "worker_loop" not in web_source
    assert "scheduler_loop" in worker_source
    assert "worker_loop" in worker_source
    assert 'subcommands.add_parser("worker"' in main_source
    assert '"autosurf.main", "worker"' in main_source


@pytest.mark.asyncio
async def test_browser_control_stays_running_and_leases_task_pages(tmp_path, monkeypatch):
    socket_path = tmp_path / "novnc.sock"
    context = FakeContext()
    playwright = FakePlaywright()
    launched = []
    runtimes = []
    closed = []
    processes = []

    async def browser_launcher(
        _playwright,
        run_context,
        *,
        remote_desktop,
        display_size,
        process_factory,
    ):
        assert _playwright is None
        assert process_factory is not None
        launched.append((run_context.execution_id, remote_desktop, display_size))
        runtime = PersistentBrowserRuntime(
            context=None,
            profile_path=tmp_path / "profile",
            mode="persistent_headful",
            display=SimpleNamespace(name=":90"),
            browser_process=FakeProcess(),
            cdp_endpoint="http://127.0.0.1:9222",
        )
        runtimes.append(runtime)
        return runtime

    connected = []

    async def browser_connector(value, current_runtime):
        connected.append((value, current_runtime))
        return replace(current_runtime, context=context, browser_connection=object())

    async def browser_closer(value):
        closed.append(value)
        value.browser_process.terminate()

    async def process_factory(*args, **kwargs):
        assert kwargs["env"]["DISPLAY"] == ":90"
        process = FakeProcess()
        processes.append((args, process))
        if args[0] == "x11vnc":
            assert "-localhost" in args
            assert "-rfbport" in args
        else:
            assert args[0] == "websockify"
            assert "--unix-listen=" + str(socket_path) in args
            assert "--web=/usr/share/novnc" in args
            socket_path.touch()
        return process

    prepared = []
    saved = []

    async def prepare(value, run_context, url):
        prepared.append((value, run_context.execution_id, url))

    async def save(value, url):
        saved.append((value, url))

    async def create_task_page(value):
        assert value is context
        return await value.new_page()

    monkeypatch.setattr("autosurf.browser_control.prepare_browser_for_run", prepare)
    monkeypatch.setattr("autosurf.browser_control.save_browser_after_run", save)
    monkeypatch.setattr(
        "autosurf.automations.browser_session.new_browser_task_page", create_task_page,
    )

    display_settings = SimpleNamespace(
        resolution=(1365, 768),
        changes=[],
    )

    def set_resolution(width, height):
        display_settings.resolution = (width, height)
        display_settings.changes.append((width, height))

    display_settings.set_resolution = set_resolution
    service = BrowserControlService(
        playwright_factory=lambda: FakePlaywrightManager(playwright),
        browser_launcher=browser_launcher,
        browser_connector=browser_connector,
        browser_closer=browser_closer,
        process_factory=process_factory,
        socket_path=socket_path,
        display_settings=display_settings,
    )
    started = await service.start()
    assert started["active"] is True, started["error"]
    assert started["starting"] is False
    assert started["always_on"] is True
    assert started["native_window"] is True
    assert started["remote_url"] is None
    assert launched == [("browser-control", True, (1365, 768))]

    resized = await service.set_resolution(1920, 1080)
    assert resized["active"] is True
    assert resized["viewport"] == {"width": 1920, "height": 1080}
    assert display_settings.changes == [(1920, 1080)]
    assert launched[-1] == ("browser-control", True, (1920, 1080))
    active_runtime = runtimes[-1]

    run_context = RunContext("execution-1", {"url": "https://example.com/"}, {})
    async with service.automation_session(run_context, "https://example.com/") as session:
        assert session.context is context
        task_page = await session.new_page()
        status = await service.status()
        assert status["busy"] is True
        assert status["automation_owner"] == "execution-1"
        with pytest.raises(BrowserControlBusy):
            await service.set_resolution(1600, 900)

    assert task_page.closed is False
    assert context.pages[0].closed is False
    assert prepared[0][0].context is context
    assert prepared[0][1:] == ("execution-1", "https://example.com/")
    assert saved[0][0].context is context
    assert saved[0][1] == "https://example.com/"
    assert connected == [(playwright, active_runtime)]

    task_playwright = FakePlaywright()
    async with service.automation_session(
        RunContext("execution-2", {}, {}),
        "https://example.com/",
        playwright=task_playwright,
    ) as session:
        assert await session.new_page() is task_page
    assert connected[-1] == (task_playwright, active_runtime)
    assert task_playwright.stopped is False
    assert (await service.status())["active"] is True

    await service.shutdown()
    assert all(process.returncode == 0 for _, process in processes)
    assert closed == runtimes
    assert playwright.stopped is True
    assert (await service.status())["active"] is False


@pytest.mark.asyncio
async def test_persistent_session_delegates_to_registered_host():
    calls = []

    class Provider:
        @asynccontextmanager
        async def automation_session(self, run_context, url, *, playwright=None):
            assert playwright == "task-playwright"
            calls.append((run_context.execution_id, url))
            yield SimpleNamespace(context="shared", mode="persistent_headful")

    register_shared_browser_provider(Provider())
    try:
        context = RunContext("execution-2", {"url": "https://example.com/"}, {})
        async with persistent_chromium_session(
            "task-playwright", context, "https://example.com/"
        ) as session:
            assert session.context == "shared"
    finally:
        register_shared_browser_provider(None)
    assert calls == [("execution-2", "https://example.com/")]


class FakeBrowserControlApi:
    def __init__(self):
        self.viewport = {"width": 1365, "height": 768}

    async def status(self):
        return {
            "active": True,
            "starting": False,
            "url": "about:blank",
            "title": "Chromium",
            "mode": "persistent_headful",
            "viewport": self.viewport,
            "supported_resolutions": [
                {"width": 1365, "height": 768, "label": "1365 x 768"},
                {"width": 1920, "height": 1080, "label": "1920 x 1080"},
            ],
            "error": None,
            "task_running": True,
            "always_on": True,
            "busy": False,
            "automation_owner": None,
            "remote_url": "/browser-control/remote/vnc.html?autoconnect=1&path=websockify",
        }

    async def set_resolution(self, width, height):
        if (width, height) not in {(1365, 768), (1920, 1080)}:
            raise ValueError("unsupported")
        self.viewport = {"width": width, "height": height}
        return await self.status()

    async def open_window(self):
        return await self.status()


@pytest.mark.asyncio
async def test_browser_control_status_and_native_window_actions_require_login(settings):
    app = create_app(settings)
    app.state.browser_control = FakeBrowserControlApi()
    transport = httpx.ASGITransport(app=app)
    auth = (settings.username, settings.password)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/api/v1/browser-control")).status_code == 401
        status = await client.get("/api/v1/browser-control", auth=auth)
        assert status.status_code == 200
        assert status.json()["always_on"] is True

        opened = await client.post("/api/v1/browser-control/open", auth=auth)
        assert opened.status_code == 200

        denied_resize = await client.patch(
            "/api/v1/browser-control/resolution",
            json={"width": 1920, "height": 1080},
        )
        assert denied_resize.status_code == 401
        resized = await client.patch(
            "/api/v1/browser-control/resolution",
            auth=auth,
            json={"width": 1920, "height": 1080},
        )
        assert resized.status_code == 200
        assert resized.json()["viewport"] == {"width": 1920, "height": 1080}
        unsupported = await client.patch(
            "/api/v1/browser-control/resolution",
            auth=auth,
            json={"width": 3840, "height": 2160},
        )
        assert unsupported.status_code == 422

        assert (await client.get("/browser-control/remote/")).status_code == 404


def test_windows_installation_uses_localhost_without_docker_artifacts():
    install = Path("scripts/install.ps1").read_text(encoding="utf-8")
    browser_install = Path("scripts/install-browser.ps1").read_text(encoding="utf-8")
    browser_manifest = json.loads(Path("browser-runtime.json").read_text(encoding="utf-8"))
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert '"C:\\Tools\\AutoSurf"' in install
    assert '[string]$Username = "adminforautosurf"' in install
    assert "AUTOSURF_HOST=127.0.0.1" in install
    assert "AUTOSURF_PORT=18980" in install
    assert "AUTOSURF_BROWSER_PROFILE_DIR" in install
    assert "fetch --prune origin" in install
    assert 'reset --hard "refs/remotes/origin/$Branch"' in install
    assert "AUTOSURF_BROWSER_EXECUTABLE_PATH=$rootEnv/runtime/chrome/chrome.exe" in install
    assert "HttpWebRequest" in browser_install
    assert "AddRange" in browser_install
    assert "maximumAttempts = 8" in browser_install
    assert "System.Security.Cryptography.MD5" in browser_install
    assert 'Join-Path $data "install.log"' in install
    assert "if ($createdPassword)" in install
    assert browser_manifest == {
        "version": "152.0.7977.64",
        "platform": "win64",
        "archive_url": (
            "https://storage.googleapis.com/chrome-for-testing-public/"
            "152.0.7977.64/win64/chrome-win64.zip"
        ),
        "archive_size": 202713690,
        "archive_md5": "fb058f51b0b74259c94148f9ac569040",
        "archive_root": "chrome-win64",
        "executable": "chrome.exe",
    }
    assert not Path("Dockerfile").exists()
    assert not Path("compose.yaml").exists()
    assert "docker/build-push-action" not in workflow


def test_pinned_browser_installer_verifies_extracts_and_reuses_runtime(tmp_path):
    download_root = tmp_path / "downloads"
    download_root.mkdir()
    archive = download_root / "chrome.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("chrome-win64/chrome.exe", b"test-browser")

    handler = lambda *args, **kwargs: SimpleHTTPRequestHandler(  # noqa: E731
        *args, directory=str(download_root), **kwargs,
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    root = tmp_path / "AutoSurf"
    program = root / "program"
    program.mkdir(parents=True)
    manifest = {
        "version": "test-version",
        "platform": "win64",
        "archive_url": f"http://127.0.0.1:{server.server_port}/chrome.zip",
        "archive_size": archive.stat().st_size,
        "archive_md5": hashlib.md5(archive.read_bytes()).hexdigest(),  # noqa: S324
        "archive_root": "chrome-win64",
        "executable": "chrome.exe",
    }
    program.joinpath("browser-runtime.json").write_text(
        json.dumps(manifest), encoding="utf-8",
    )
    command = [
        "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
        str(Path("scripts/install-browser.ps1").resolve()), "-InstallDir", str(root),
    ]
    try:
        installed = subprocess.run(command, capture_output=True, text=True, check=False)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert installed.returncode == 0, installed.stderr
    executable = root / "runtime" / "chrome" / "chrome.exe"
    assert executable.read_bytes() == b"test-browser"
    assert root.joinpath("runtime/chrome/.autosurf-version").read_text().strip() == "test-version"

    reused = subprocess.run(command, capture_output=True, text=True, check=False)
    assert reused.returncode == 0, reused.stderr
    assert "already installed" in reused.stdout


def test_browser_control_management_ui_opens_a_native_window_without_embedding_video():
    html = Path("src/autosurf/web/admin.html").read_text(encoding="utf-8")
    javascript = Path("src/autosurf/web/admin.js").read_text(encoding="utf-8")
    assert 'data-view="browser-control"' in html
    assert 'id="browser-control-panel"' in html
    assert 'id="browser-control-surface"' in html
    assert 'id="browser-open-window"' in html
    assert 'id="browser-resolution"' in html
    assert 'value="1920x1080"' in html
    assert 'id="browser-remote-frame"' not in html
    assert 'id="browser-fullscreen"' not in html
    assert 'id="browser-audio"' not in html
    assert 'api("/api/v1/browser-control"' in javascript
    assert 'api("/api/v1/browser-control/open"' in javascript
    assert 'method: "PATCH"' in javascript


def test_management_javascript_only_references_registered_elements():
    javascript = Path("src/autosurf/web/admin.js").read_text(encoding="utf-8")
    element_block = javascript.split("const elements = {", 1)[1].split("\n};", 1)[0]
    registered = set(re.findall(r"^\s{2}([A-Za-z][A-Za-z0-9]*):", element_block, re.MULTILINE))
    referenced = set(re.findall(r"\belements\.([A-Za-z][A-Za-z0-9]*)", javascript))
    assert referenced <= registered, sorted(referenced - registered)
    assert "CredentialOptions" not in javascript


@pytest.mark.asyncio
async def test_browser_audio_streams_pcm_and_stops_capture(tmp_path, monkeypatch):
    commands = []

    class AudioStream:
        async def read(self, _size):
            return b"\x00\x00\x01\x00"

    class AudioProcess(FakeProcess):
        def __init__(self):
            super().__init__()
            self.stdout = AudioStream()

    async def process_factory(*args, **kwargs):
        commands.append((args, kwargs))
        return AudioProcess()

    class WebSocket:
        def __init__(self):
            self.accepted = False
            self.payloads = []
            self.closed = False

        async def accept(self):
            self.accepted = True

        async def send_bytes(self, payload):
            self.payloads.append(payload)
            raise RuntimeError("client disconnected")

        async def close(self, **_kwargs):
            self.closed = True

    monkeypatch.setattr("autosurf.browser_control.shutil.which", lambda value: "/usr/bin/parec" if value == "parec" else None)
    monkeypatch.setenv("AUTOSURF_AUDIO_SOURCE", "autosurf.monitor")
    service = BrowserControlService(process_factory=process_factory, socket_path=tmp_path / "novnc.sock")
    websocket = WebSocket()

    await service.stream_audio(websocket)

    assert websocket.accepted is True
    assert websocket.payloads == [b"\x00\x00\x01\x00"]
    assert websocket.closed is True
    args, kwargs = commands[0]
    assert args[:3] == ("/usr/bin/parec", "--device=autosurf.monitor", "--format=s16le")
    assert "--rate=48000" in args
    assert "--channels=2" in args
    assert kwargs["stdout"] == asyncio.subprocess.PIPE


def test_browser_display_resolution_persists_in_system_settings(settings):
    app = create_app(settings)
    display_settings = BrowserDisplaySettings(app.state.sessions)
    assert display_settings.resolution == (1365, 768)
    assert display_settings.set_resolution(1920, 1080) == (1920, 1080)
    assert BrowserDisplaySettings(app.state.sessions).resolution == (1920, 1080)
    with pytest.raises(ValueError):
        display_settings.set_resolution(3840, 2160)
