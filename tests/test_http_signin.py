import httpx
import pytest

from autosurf.automations.http_signin import HttpSignInHandler
from autosurf.domain.models import RunContext, RunOutcome


@pytest.mark.asyncio
async def test_http_signin_uses_cookiecloud_browser_user_agent(monkeypatch):
    captured = {}

    class FakeClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def request(self, method, url, **kwargs):
            captured.update({"method": method, "url": url, **kwargs})
            return httpx.Response(
                200,
                text='{"success":true,"message":"签到成功"}',
                request=httpx.Request(method, url),
            )

    monkeypatch.setattr("autosurf.automations.http_signin.httpx.AsyncClient", FakeClient)
    result = await HttpSignInHandler().run(RunContext(
        execution_id="test",
        config={
            "url": "https://www.nodeseek.com/api/attendance?random=false",
            "method": "POST",
            "origin": "https://www.nodeseek.com",
            "referer": "https://www.nodeseek.com/board",
            "json": {"random": False},
            "success_patterns": [r'"success"\s*:\s*true'],
        },
        cookies={"session": "secret"},
        user_agent="Chrome-from-cookiecloud/151",
    ))

    assert captured["headers"]["User-Agent"] == "Chrome-from-cookiecloud/151"
    assert captured["headers"]["Origin"] == "https://www.nodeseek.com"
    assert captured["headers"]["Referer"] == "https://www.nodeseek.com/board"
    assert captured["method"] == "POST"
    assert captured["json"] == {"random": False}
    assert result.outcome == RunOutcome.SUCCESS
    assert result.details["status_code"] == 200
