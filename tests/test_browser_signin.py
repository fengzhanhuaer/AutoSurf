import os
from types import SimpleNamespace

import pytest

from autosurf.automations.browser_signin import BrowserSignInHandler, _classify_body
from autosurf.automations.browser_session import (
    _restore_waf_cookie_state,
    _save_waf_cookie_state,
    _prepare_shared_profile,
    _remove_stale_chrome_singletons,
    PersistentBrowserRuntime,
    browser_environment_run_context,
    browser_profile_path,
    connect_standalone_browser,
    launch_persistent_browser,
    launch_standalone_browser,
    persistent_browser_mode,
    playwright_cookies,
)
from autosurf.domain.models import RunContext
from autosurf.domain.models import RunOutcome


@pytest.mark.asyncio
async def test_browser_signin_rejects_non_http_url_before_launch():
    handler = BrowserSignInHandler()
    with pytest.raises(ValueError, match="absolute HTTP"):
        await handler.run(RunContext(execution_id="test", config={"url": "file:///etc/passwd"}, cookies={}))


def test_browser_signin_classifies_nodeseek_before_and_after_click():
    config = {
        "success_patterns": [r"今日签到获得鸡腿\d+个"],
        "already_patterns": [r"今日签到获得鸡腿\d+个"],
        "auth_expired_patterns": ["登录后签到"],
    }
    already = _classify_body(config, "今日签到获得鸡腿5个", 200, before_click=True)
    success = _classify_body(config, "今日签到获得鸡腿5个", 200, before_click=False)
    expired = _classify_body(config, "登录后签到", 200, before_click=True)

    assert already.outcome == RunOutcome.ALREADY_DONE
    assert success.outcome == RunOutcome.SUCCESS
    assert expired.outcome == RunOutcome.AUTH_EXPIRED


def test_browser_handler_is_registered(tmp_path):
    from autosurf.config import Settings
    from autosurf.main import create_app

    app = create_app(Settings(data_dir=tmp_path, secret_key="s" * 32,
                              username="admin", password="password123"))
    assert "browser_signin" in app.state.registry.types()


def test_browser_cookie_records_keep_scope_and_filter_other_domains():
    context = RunContext(
        execution_id="test",
        config={},
        cookies={"sid": "fallback"},
        browser_cookies=[
            {"name": "sid", "value": "scoped", "domain": ".example.com", "path": "/tracker",
             "secure": True, "httpOnly": True, "sameSite": "Lax", "expires": 2_000_000_000},
            {"name": "other", "value": "secret", "domain": ".other.test", "path": "/"},
        ],
    )

    assert playwright_cookies(context, "https://pt.example.com/attendance.php") == [{
        "name": "sid",
        "value": "scoped",
        "domain": ".example.com",
        "path": "/tracker",
        "secure": True,
        "httpOnly": True,
        "sameSite": "Lax",
        "expires": 2_000_000_000.0,
    }]


def test_browser_cookie_records_require_haidan_www_target_for_www_scope():
    context = RunContext(
        execution_id="test",
        config={},
        cookies={"c_secure_uid": "7"},
        browser_cookies=[{
            "name": "c_secure_uid",
            "value": "7",
            "domain": ".www.haidan.cc",
            "path": "/",
        }],
    )

    assert playwright_cookies(context, "https://haidan.cc/") == []
    assert playwright_cookies(context, "https://www.haidan.cc/") == [{
        "name": "c_secure_uid",
        "value": "7",
        "domain": ".www.haidan.cc",
        "path": "/",
        "secure": True,
        "httpOnly": False,
    }]


def test_browser_profile_path_is_shared_and_kept_below_browser_mount(tmp_path, monkeypatch):
    monkeypatch.delenv("AUTOSURF_BROWSER_PROFILE_DIR", raising=False)
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))

    assert browser_profile_path() == tmp_path / "profiles" / "shared"


@pytest.mark.asyncio
async def test_shared_browser_profile_seeds_from_latest_legacy_profile(tmp_path):
    older = tmp_path / "old-site"
    latest = tmp_path / "latest-site"
    older.mkdir()
    latest.mkdir()
    older.joinpath("marker").write_text("old", encoding="utf-8")
    latest.joinpath("marker").write_text("latest", encoding="utf-8")
    older.touch()
    latest.touch()
    older_mtime = older.stat().st_mtime - 60
    os.utime(older, (older_mtime, older_mtime))

    shared = tmp_path / "shared"
    await _prepare_shared_profile(shared)

    assert shared.joinpath("marker").read_text(encoding="utf-8") == "latest"


@pytest.mark.asyncio
async def test_shared_browser_profile_removes_only_stale_chrome_singletons(tmp_path):
    profile = tmp_path / "shared"
    profile.mkdir()
    profile.joinpath("SingletonCookie").write_text("stale", encoding="utf-8")
    profile.joinpath("SingletonLock").symlink_to("old-container-123")
    profile.joinpath("SingletonSocket").symlink_to("/tmp/old-container/socket")
    profile.joinpath("Local State").write_text("login-data", encoding="utf-8")
    profile.joinpath("Default").mkdir()
    profile.joinpath("Profile 1").mkdir()
    profile.joinpath("Profile 1", "Sync Data").write_text("kept", encoding="utf-8")

    await _remove_stale_chrome_singletons(profile)

    assert not profile.joinpath("SingletonCookie").exists()
    assert not profile.joinpath("SingletonLock").is_symlink()
    assert not profile.joinpath("SingletonSocket").is_symlink()
    assert profile.joinpath("Local State").read_text(encoding="utf-8") == "login-data"
    assert profile.joinpath("Default").is_dir()
    assert profile.joinpath("Profile 1", "Sync Data").read_text(encoding="utf-8") == "kept"


def test_browser_mode_falls_back_to_persistent_headless_without_xvfb(monkeypatch):
    monkeypatch.delenv("AUTOSURF_BROWSER_HEADLESS", raising=False)
    monkeypatch.setattr("autosurf.automations.browser_session.shutil.which", lambda _name: None)
    assert persistent_browser_mode() == "persistent_headless"

    monkeypatch.setenv("AUTOSURF_BROWSER_HEADLESS", "true")
    monkeypatch.setattr("autosurf.automations.browser_session.shutil.which", lambda _name: "Xvfb")
    assert persistent_browser_mode() == "persistent_headless"

    monkeypatch.setenv("AUTOSURF_BROWSER_HEADLESS", "false")
    assert persistent_browser_mode() == "persistent_headful"


@pytest.mark.asyncio
async def test_docker_browser_uses_the_google_chrome_channel(tmp_path, monkeypatch):
    class Chromium:
        executable_path = "/playwright/chromium"

        def __init__(self):
            self.kwargs = None

        async def launch_persistent_context(self, _profile_path, **kwargs):
            self.kwargs = kwargs
            return object()

    chromium = Chromium()
    playwright = type("Playwright", (), {"chromium": chromium})()
    monkeypatch.setenv("AUTOSURF_BROWSER_CHANNEL", "chrome")
    monkeypatch.setenv("AUTOSURF_BROWSER_HEADLESS", "true")
    monkeypatch.setenv("AUTOSURF_BROWSER_PROFILE_DIR", str(tmp_path))

    runtime = await launch_persistent_browser(
        playwright,
        RunContext("start", {}, {}),
        display_size=(1920, 1080),
    )

    assert runtime.context is not None
    assert chromium.kwargs["channel"] == "chrome"
    assert "executable_path" not in chromium.kwargs
    assert chromium.kwargs["viewport"] == {"width": 1920, "height": 1080}


@pytest.mark.asyncio
async def test_standalone_chrome_is_not_launched_with_playwright_automation_flags(
    tmp_path, monkeypatch
):
    commands = []

    class Process:
        returncode = None
        stdout = None
        stderr = None

    async def process_factory(*args, **kwargs):
        commands.append((args, kwargs))
        return Process()

    async def start_display(width, height):
        assert (width, height) == (1920, 1080)
        return SimpleNamespace(name=":99", process=object())

    async def ready(_process, endpoint):
        assert endpoint == "http://127.0.0.1:9222"

    monkeypatch.setenv("AUTOSURF_BROWSER_PROFILE_DIR", str(tmp_path))
    monkeypatch.setenv("AUTOSURF_BROWSER_HEADLESS", "false")
    monkeypatch.setattr(
        "autosurf.automations.browser_session.shutil.which", lambda name: name,
    )
    monkeypatch.setattr(
        "autosurf.automations.browser_session._standalone_chrome_executable",
        lambda: "/usr/bin/google-chrome-stable",
    )
    monkeypatch.setattr(
        "autosurf.automations.browser_session._start_virtual_display", start_display,
    )
    monkeypatch.setattr(
        "autosurf.automations.browser_session._wait_for_standalone_cdp", ready,
    )

    runtime = await launch_standalone_browser(
        None,
        RunContext("start", {"locale": "zh-CN"}, {}),
        remote_desktop=True,
        display_size=(1920, 1080),
        process_factory=process_factory,
    )

    args, kwargs = commands[0]
    assert args[0] == "/usr/bin/google-chrome-stable"
    assert f"--user-data-dir={tmp_path / 'shared'}" in args
    assert "--remote-debugging-address=127.0.0.1" in args
    assert "--remote-debugging-port=9222" in args
    assert "--window-size=1920,1080" in args
    assert not any(value.startswith("--profile-directory") for value in args)
    assert "--no-sandbox" not in args
    assert "--enable-automation" not in args
    assert "--remote-debugging-pipe" not in args
    assert kwargs["env"]["DISPLAY"] == ":99"
    assert kwargs["start_new_session"] is True
    assert runtime.context is None
    assert runtime.cdp_endpoint == "http://127.0.0.1:9222"


@pytest.mark.asyncio
async def test_playwright_connects_to_standalone_chrome_without_owning_it(tmp_path):
    context = object()

    class Chromium:
        async def connect_over_cdp(self, endpoint, **kwargs):
            assert endpoint == "http://127.0.0.1:9222"
            assert kwargs == {"is_local": True, "no_defaults": True}
            return SimpleNamespace(contexts=[context])

    runtime = PersistentBrowserRuntime(
        context=None,
        profile_path=tmp_path,
        mode="persistent_headful",
        display=None,
        browser_process=object(),
        cdp_endpoint="http://127.0.0.1:9222",
    )
    connected = await connect_standalone_browser(
        SimpleNamespace(chromium=Chromium()), runtime
    )

    assert connected.context is context
    assert connected.browser_process is runtime.browser_process
    assert connected.browser_connection is not None


@pytest.mark.asyncio
async def test_run_context_uses_current_browser_cookie_and_web_storage_values():
    class BrowserContext:
        async def cookies(self, _urls):
            return [{
                "name": "session",
                "value": "browser-current",
                "domain": ".tracker.example",
                "path": "/",
            }]

    class Page:
        context = BrowserContext()
        url = "https://tracker.example/"

        async def evaluate(self, script):
            assert "autosurfBrowserEnvironment" in script
            assert "sessionStorage" in script
            return {
                "autosurfBrowserEnvironment": True,
                "values": {"token": "browser-token"},
            }

    original = RunContext(
        "run", {}, {"session": "imported-old", "token": "imported-old"}
    )
    current = await browser_environment_run_context(
        Page(), original, "https://tracker.example/attendance.php"
    )

    assert current.cookies == {
        "session": "browser-current",
        "token": "browser-token",
    }


@pytest.mark.asyncio
async def test_browser_profile_state_persists_only_browser_bound_waf_cookies(tmp_path):
    class BrowserContext:
        def __init__(self, cookies):
            self.cookie_values = cookies
            self.updates = []

        async def cookies(self, _urls):
            return self.cookie_values

        async def add_cookies(self, values):
            self.updates.extend(values)

    source = BrowserContext([
        {"name": "sl-session", "value": "waf-secret", "domain": ".hdkyl.in", "path": "/"},
        {"name": "c_secure_pass", "value": "login-secret", "domain": ".hdkyl.in", "path": "/"},
    ])
    await _save_waf_cookie_state(source, tmp_path, "https://www.hdkyl.in/attendance.php")

    serialized = tmp_path.joinpath(".autosurf-waf-cookies.json").read_text(encoding="utf-8")
    assert "waf-secret" in serialized
    assert "login-secret" not in serialized

    restored = BrowserContext([])
    await _restore_waf_cookie_state(restored, tmp_path, "https://www.hdkyl.in/attendance.php")
    assert len(restored.updates) == 1
    assert restored.updates[0]["name"] == "sl-session"
    assert restored.updates[0]["value"] == "waf-secret"


@pytest.mark.asyncio
async def test_shared_browser_profile_keeps_waf_state_for_each_domain(tmp_path):
    class BrowserContext:
        def __init__(self, cookies):
            self.cookie_values = cookies
            self.updates = []

        async def cookies(self, _urls):
            return self.cookie_values

        async def add_cookies(self, values):
            self.updates.extend(values)

    await _save_waf_cookie_state(
        BrowserContext([{"name": "sl-session", "value": "hdk", "domain": ".hdkyl.in", "path": "/"}]),
        tmp_path,
        "https://www.hdkyl.in/attendance.php",
    )
    await _save_waf_cookie_state(
        BrowserContext([{"name": "cf_clearance", "value": "pt", "domain": ".pttime.org", "path": "/"}]),
        tmp_path,
        "https://pttime.org/attendance.php",
    )

    hdk = BrowserContext([])
    pttime = BrowserContext([])
    await _restore_waf_cookie_state(hdk, tmp_path, "https://www.hdkyl.in/attendance.php")
    await _restore_waf_cookie_state(pttime, tmp_path, "https://pttime.org/attendance.php")

    assert [(item["name"], item["value"]) for item in hdk.updates] == [("sl-session", "hdk")]
    assert [(item["name"], item["value"]) for item in pttime.updates] == [("cf_clearance", "pt")]
