import pytest

from autosurf.automations.browser_signin import BrowserSignInHandler
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
