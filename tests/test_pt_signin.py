from datetime import datetime, timedelta
import json
from uuid import uuid4

import httpx
import pytest

from autosurf.automations.pt_signin import PtSignInHandler, classify_pt_page
from autosurf.config import Settings
from autosurf.domain.models import RunContext, RunOutcome
from autosurf.domain.models import utc_now
from autosurf.infrastructure.database import ExecutionRecord
from autosurf.main import create_app
from autosurf.pt_discovery import discover_pt_site


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


def test_pt_discovery_uses_catalog_and_cookie_signatures_without_guessing_unknown_sites():
    catalog = discover_pt_site(".club.hares.top", {"sid"})
    signature = discover_pt_site("tracker.test", {"C_SECURE_UID", "session"})

    assert catalog is not None
    assert catalog.name == "Hares"
    assert catalog.url == "https://club.hares.top/attendance.php?action=sign"
    assert catalog.supported is True
    assert signature is not None
    assert signature.reason == "cookie_signature"
    assert signature.url == "https://tracker.test/attendance.php"
    assert discover_pt_site("example.com", {"sid", "theme"}) is None


def test_pt_discovery_marks_api_only_sites_for_a_dedicated_adapter():
    discovery = discover_pt_site("zhuque.in", {"c_secure_uid"})

    assert discovery is not None
    assert discovery.strategy == "custom_required"
    assert discovery.supported is False


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
        scheduled = await client.patch(
            f"/api/v1/pt-signin/sites/{site_id}/schedule", auth=auth, json={
                "interval_hours": 12,
                "timeout_seconds": 45,
                "random_delay_minutes": 30,
                "retry_interval_hours": 2,
                "max_retries": 5,
            },
        )
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
    assert scheduled.json()["interval_hours"] == 12
    assert scheduled.json()["config"]["random_delay_minutes"] == 30
    assert scheduled.json()["config"]["retry_interval_hours"] == 2
    assert scheduled.json()["config"]["max_retries"] == 5
    assert disabled.json()["enabled"] is False
    assert queued.status_code == 202
    assert history.json()["items"][0]["automation_name"] == "Tracker"
    assert history.json()["items"][0]["status"] == "pending"
    assert deleted.status_code == 204
    assert empty.json()["items"] == []


@pytest.mark.asyncio
async def test_pt_signin_api_discovers_and_bulk_collects_cookiecloud_sites(settings):
    app = create_app(settings)
    recognized = app.state.credentials.upsert(
        "cookiecloud:test:tracker.test",
        "tracker.test",
        {"c_secure_uid": "1", "sid": "secret"},
        provider="cookiecloud",
    )
    catalog = app.state.credentials.upsert(
        "cookiecloud:test:tjupt.org",
        "tjupt.org",
        {"sid": "secret"},
        provider="cookiecloud",
    )
    unknown = app.state.credentials.upsert(
        "cookiecloud:test:example.com",
        "example.com",
        {"sid": "secret"},
        provider="cookiecloud",
    )
    unsupported = app.state.credentials.upsert(
        "cookiecloud:test:zhuque.in",
        "zhuque.in",
        {"sid": "secret"},
        provider="cookiecloud",
    )
    app.state.credentials.upsert("manual", "manual.test", {"passkey": "secret"}, provider="manual")
    transport = httpx.ASGITransport(app=app)
    auth = (settings.username, settings.password)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        candidates = await client.get("/api/v1/pt-signin/candidates", auth=auth)
        recognized_only = await client.get(
            "/api/v1/pt-signin/candidates?include_unknown=false", auth=auth
        )
        rejected = await client.post("/api/v1/pt-signin/sites/collect", auth=auth, json={
            "credential_ids": [unknown.id], "interval_hours": 12, "timeout_seconds": 45,
        })
        unsupported_result = await client.post("/api/v1/pt-signin/sites/collect", auth=auth, json={
            "credential_ids": [unsupported.id],
        })
        collected = await client.post("/api/v1/pt-signin/sites/collect", auth=auth, json={
            "credential_ids": [recognized.id, recognized.id, catalog.id],
            "interval_hours": 12,
            "timeout_seconds": 45,
        })
        collected_again = await client.post("/api/v1/pt-signin/sites/collect", auth=auth, json={
            "credential_ids": [recognized.id, catalog.id],
        })
        refreshed = await client.get("/api/v1/pt-signin/candidates", auth=auth)

    items = candidates.json()["items"]
    by_id = {item["credential"]["id"]: item for item in items}
    assert set(by_id) == {recognized.id, catalog.id, unknown.id, unsupported.id}
    assert by_id[recognized.id]["reason"] == "cookie_signature"
    assert by_id[catalog.id]["name"] == "TJUPT"
    assert by_id[unknown.id]["recognized"] is False
    assert by_id[unsupported.id]["supported"] is False
    assert "c_secure_uid" not in candidates.text
    assert "secret" not in candidates.text
    assert {item["credential"]["id"] for item in recognized_only.json()["items"]} == {
        recognized.id, catalog.id, unsupported.id,
    }
    assert rejected.status_code == 422
    assert unsupported_result.status_code == 422
    assert "尚需专用适配" in unsupported_result.json()["detail"]
    assert collected.status_code == 201
    assert len(collected.json()["created"]) == 2
    assert {item["interval_hours"] for item in collected.json()["created"]} == {12}
    assert {item["config"]["timeout_seconds"] for item in collected.json()["created"]} == {45}
    assert collected_again.json()["created"] == []
    assert len(collected_again.json()["skipped"]) == 2
    assert sum(item["configured"] for item in refreshed.json()["items"]) == 2


@pytest.mark.asyncio
async def test_pt_signin_history_groups_latest_execution_by_local_day(settings):
    app = create_app(settings)
    credential = app.state.credentials.upsert(
        "cookiecloud:test:tracker.test", "tracker.test", {"sid": "secret"}, provider="cookiecloud"
    )
    site = app.state.automations.create(
        "Tracker", "pt_signin", 86400,
        {"url": "https://tracker.test/attendance.php", "credential_domain": "tracker.test"},
        credential.id,
    )
    empty_site = app.state.automations.create(
        "Empty", "pt_signin", 86400,
        {"url": "https://tracker.test/attendance.php", "credential_domain": "tracker.test"},
        credential.id,
    )
    offset = timedelta(minutes=480)
    local_today = (utc_now() + offset).date()
    today_start_utc = datetime.combine(local_today, datetime.min.time()) - offset
    yesterday_start_utc = today_start_utc - timedelta(days=1)

    def execution(scheduled_at, status, message=None):
        return ExecutionRecord(
            id=str(uuid4()), automation_id=site.id, scheduled_at=scheduled_at,
            status=status, attempts=1, available_at=scheduled_at,
            result_json=json.dumps({"outcome": "success", "message": message}) if message else None,
            error=None if message else "temporary failure",
        )

    with app.state.sessions.begin() as session:
        session.add_all([
            execution(yesterday_start_utc + timedelta(hours=3), "retry_wait"),
            execution(today_start_utc + timedelta(hours=1), "failed"),
            execution(today_start_utc + timedelta(hours=2), "succeeded", "签到成功"),
        ])

    transport = httpx.ASGITransport(app=app)
    auth = (settings.username, settings.password)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/v1/pt-signin/history?days=7&timezone_offset=480", auth=auth
        )
        invalid = await client.get(
            "/api/v1/pt-signin/history?timezone_offset=900", auth=auth
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["today"] == local_today.isoformat()
    assert len(payload["days"]) == 7
    assert payload["days"][0]["is_today"] is True
    by_id = {item["automation_id"]: item for item in payload["items"]}
    assert by_id[site.id]["record_count"] == 3
    assert by_id[site.id]["executions"][local_today.isoformat()]["status"] == "succeeded"
    assert by_id[site.id]["executions"][local_today.isoformat()]["result"]["message"] == "签到成功"
    assert by_id[empty_site.id]["record_count"] == 0
    assert by_id[empty_site.id]["executions"] == {}
    assert payload["latest_execution"]["automation_name"] == "Tracker"
    assert invalid.status_code == 422
