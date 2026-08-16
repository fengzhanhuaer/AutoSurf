import os

import pytest

from autosurf.automations.browser_signin import BrowserSignInHandler
from autosurf.automations.browser_session import (
    _restore_waf_cookie_state,
    _save_waf_cookie_state,
    _prepare_shared_profile,
    browser_profile_path,
    persistent_browser_mode,
    playwright_cookies,
    supplement_playwright_cookies,
)
from autosurf.domain.models import RunContext


@pytest.mark.asyncio
async def test_browser_signin_rejects_non_http_url_before_launch():
    handler = BrowserSignInHandler()
    with pytest.raises(ValueError, match="absolute HTTP"):
        await handler.run(RunContext(execution_id="test", config={"url": "file:///etc/passwd"}, cookies={}))


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
async def test_cookiecloud_updates_login_cookies_but_preserves_profile_waf_cookies():
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

    assert {item["name"] for item in browser_context.updates} == {"c_secure_uid", "c_secure_pass"}
    assert next(item for item in browser_context.updates if item["name"] == "c_secure_uid")["value"] == "new"


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
