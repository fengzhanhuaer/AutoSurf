import pytest

from autosurf.automations.browser_signin import BrowserSignInHandler
from autosurf.automations.browser_session import playwright_cookies
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
