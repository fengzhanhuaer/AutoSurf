import os

import pytest

from autosurf.automations.browser_signin import BrowserSignInHandler, _classify_body
from autosurf.automations.browser_session import (
    _restore_waf_cookie_state,
    _save_waf_cookie_state,
    _prepare_shared_profile,
    _remove_stale_chrome_singletons,
    PersistentBrowserRuntime,
    bootstrap_browser_environment,
    browser_environment_run_context,
    browser_profile_path,
    launch_persistent_browser,
    persistent_browser_mode,
    playwright_cookies,
    supplement_playwright_cookies,
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

    await _remove_stale_chrome_singletons(profile)

    assert not profile.joinpath("SingletonCookie").exists()
    assert not profile.joinpath("SingletonLock").is_symlink()
    assert not profile.joinpath("SingletonSocket").is_symlink()
    assert profile.joinpath("Local State").read_text(encoding="utf-8") == "login-data"


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

    runtime = await launch_persistent_browser(playwright, RunContext("start", {}, {}))

    assert runtime.context is not None
    assert chromium.kwargs["channel"] == "chrome"
    assert "executable_path" not in chromium.kwargs


@pytest.mark.asyncio
async def test_browser_profile_cookies_take_precedence_over_imported_credentials():
    class BrowserContext:
        def __init__(self):
            self.updates = []

        async def cookies(self, _urls):
            return [
                {"name": "sl-session", "value": "profile-value", "domain": ".hdkyl.in", "path": "/"},
                {"name": "c_secure_uid", "value": "old", "domain": ".hdkyl.in", "path": "/"},
            ]

        async def add_cookies(self, values):
            self.updates.extend(values)

    browser_context = BrowserContext()
    context = RunContext(
        execution_id="test",
        config={},
        cookies={},
        browser_cookies=[
            {"name": "sl-session", "value": "desktop-value", "domain": ".hdkyl.in", "path": "/"},
            {"name": "c_secure_uid", "value": "new", "domain": ".hdkyl.in", "path": "/"},
            {"name": "c_secure_pass", "value": "secret", "domain": ".hdkyl.in", "path": "/"},
        ],
    )

    await supplement_playwright_cookies(browser_context, context, "https://www.hdkyl.in/attendance.php")

    assert {item["name"] for item in browser_context.updates} == {"c_secure_pass"}


@pytest.mark.asyncio
async def test_browser_credentials_are_injected_only_on_first_container_start(tmp_path):
    class BrowserContext:
        def __init__(self):
            self.updates = []

        async def cookies(self, _urls):
            return []

        async def add_cookies(self, values):
            self.updates.extend(values)

    browser_context = BrowserContext()
    runtime = PersistentBrowserRuntime(
        context=browser_context,
        profile_path=tmp_path,
        mode="persistent_headful",
        display=None,
    )
    first = RunContext(
        execution_id="first",
        config={},
        cookies={"session": "initial"},
    )
    later = RunContext(
        execution_id="later",
        config={},
        cookies={"session": "stale"},
    )

    await bootstrap_browser_environment(
        runtime, [("https://tracker.example/attendance.php", first)]
    )
    await bootstrap_browser_environment(
        runtime, [("https://tracker.example/attendance.php", later)]
    )

    assert [item["value"] for item in browser_context.updates] == ["initial"]
    state = tmp_path.joinpath(".autosurf-environment-bootstrap.json").read_text(
        encoding="utf-8"
    )
    assert "tracker.example" in state
    assert "initial" not in state


@pytest.mark.asyncio
async def test_web_storage_is_initialized_once_on_first_container_start(tmp_path):
    class Request:
        @staticmethod
        def is_navigation_request():
            return True

    class Route:
        request = Request()

        async def fulfill(self, **_kwargs):
            return None

        async def abort(self):
            raise AssertionError("navigation request should be fulfilled")

    class Page:
        def __init__(self):
            self.values = {}
            self.closed = False

        async def route(self, pattern, handler):
            assert pattern == "**/*"
            await handler(Route())

        async def goto(self, url, **kwargs):
            assert url == "https://kp.m-team.cc/"
            assert kwargs == {"wait_until": "domcontentloaded", "timeout": 10_000}

        async def evaluate(self, script, values):
            assert "localStorage.setItem" in script
            self.values.update(values)

        async def close(self):
            self.closed = True

    class BrowserContext:
        def __init__(self):
            self.pages = []

        async def new_page(self):
            page = Page()
            self.pages.append(page)
            return page

    browser_context = BrowserContext()
    runtime = PersistentBrowserRuntime(
        context=browser_context,
        profile_path=tmp_path,
        mode="persistent_headful",
        display=None,
    )
    first = RunContext("first", {}, {"auth": "initial"}, [])
    later = RunContext("later", {}, {"auth": "stale"}, [])

    await bootstrap_browser_environment(runtime, [("https://kp.m-team.cc/", first)])
    await bootstrap_browser_environment(runtime, [("https://kp.m-team.cc/", later)])

    assert len(browser_context.pages) == 1
    assert browser_context.pages[0].values == {"auth": "initial"}
    assert browser_context.pages[0].closed is True


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
