import httpx
import pytest

from autosurf.automations.pt_signin import PtSignInHandler, classify_pt_page
from autosurf.config import Settings
from autosurf.domain.models import RunContext, RunOutcome
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


def test_pt_page_classification_distinguishes_common_results():
    assert classify_pt_page(
        "https://tracker.test/attendance.php", 403, "Just a moment... cf-chl-token"
    ) == RunOutcome.BLOCKED
    assert classify_pt_page(
        "https://tracker.test/attendance.php", 200, "今日已签到"
    ) == RunOutcome.ALREADY_DONE
    assert classify_pt_page(
        "https://tracker.test/attendance.php", 200, "签到成功，本次签到获得 10 积分"
    ) == RunOutcome.SUCCESS
    assert classify_pt_page(
        "https://tracker.test/login.php", 200, "欢迎"
    ) == RunOutcome.AUTH_EXPIRED
    assert classify_pt_page(
        "https://tracker.test/attendance.php", 200, "获得 [10]", {"success_patterns": ["获得 [10]"]}
    ) == RunOutcome.SUCCESS


@pytest.mark.asyncio
async def test_pt_handler_rejects_cross_domain_before_starting_browser():
    handler = PtSignInHandler()
    context = RunContext(
        execution_id="test",
        config={"url": "https://other.test/attendance.php", "credential_domain": "tracker.test"},
        cookies={"sid": "secret"},
    )

    with pytest.raises(ValueError, match="selected credential domain"):
        await handler.run(context)


@pytest.mark.asyncio
async def test_pt_signin_api_manages_sites_and_history(settings):
    app = create_app(settings)
    assert "pt_signin" in app.state.registry.types()
    credential = app.state.credentials.upsert(
        "cookiecloud:test:tracker.test",
        "tracker.test",
        {"sid": "secret"},
        provider="cookiecloud",
    )
    other = app.state.credentials.upsert(
        "manual",
        "tracker.test",
        {"sid": "secret"},
        provider="manual",
    )
    transport = httpx.ASGITransport(app=app)
    auth = (settings.username, settings.password)
    payload = {
        "name": "Tracker",
        "credential_id": credential.id,
        "url": "https://tracker.test/attendance.php",
        "interval_hours": 24,
        "timeout_seconds": 60,
        "success_patterns": ["签到完成"],
        "already_patterns": ["今天签过了"],
    }

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/api/v1/pt-signin/sites")).status_code == 401
        wrong_provider = await client.post(
            "/api/v1/pt-signin/sites", auth=auth, json={**payload, "credential_id": other.id}
        )
        cross_domain = await client.post(
            "/api/v1/pt-signin/sites", auth=auth,
            json={**payload, "url": "https://other.test/attendance.php"},
        )
        created = await client.post("/api/v1/pt-signin/sites", auth=auth, json=payload)
        assert created.status_code == 201
        site = created.json()
        site_id = site["id"]
        assert site["credential"]["domain"] == "tracker.test"
        assert site["config"]["success_patterns"] == ["签到完成"]

        listed = await client.get("/api/v1/pt-signin/sites", auth=auth)
        disabled = await client.patch(
            f"/api/v1/pt-signin/sites/{site_id}/enabled", auth=auth, json={"enabled": False}
        )
        queued = await client.post(f"/api/v1/pt-signin/sites/{site_id}/run", auth=auth)
        history = await client.get("/api/v1/pt-signin/executions", auth=auth)
        deleted = await client.delete(f"/api/v1/pt-signin/sites/{site_id}", auth=auth)
        empty = await client.get("/api/v1/pt-signin/sites", auth=auth)

    assert wrong_provider.status_code == 422
    assert cross_domain.status_code == 422
    assert listed.json()["items"][0]["id"] == site_id
    assert disabled.json()["enabled"] is False
    assert queued.status_code == 202
    assert history.json()["items"][0]["automation_name"] == "Tracker"
    assert history.json()["items"][0]["status"] == "pending"
    assert deleted.status_code == 204
    assert empty.json()["items"] == []
