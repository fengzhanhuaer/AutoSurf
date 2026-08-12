from datetime import timedelta

import httpx
import pytest

from autosurf.config import Settings
from autosurf.domain.models import ExecutionStatus, utc_now
from autosurf.infrastructure.crypto import SecretBox
from autosurf.infrastructure.database import ExecutionRecord
from autosurf.main import create_app


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=tmp_path, secret_key="s" * 32, api_token="t" * 16,
                    worker_poll_seconds=0.01, scheduler_poll_seconds=0.01)


@pytest.mark.asyncio
async def test_api_creates_and_runs_automation(settings):
    app = create_app(settings)
    transport = httpx.ASGITransport(app=app)
    headers = {"Authorization": f"Bearer {settings.api_token}"}
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        credential = await client.post("/api/v1/credentials", headers=headers, json={
            "name": "example", "domain": "example.test", "cookies": {"sid": "secret"}
        })
        assert credential.status_code == 201
        automation = await client.post("/api/v1/automations", headers=headers, json={
            "name": "test", "handler_type": "http_signin", "interval_seconds": 3600,
            "credential_id": credential.json()["id"],
            "config": {"url": "https://example.test/checkin"},
        })
        assert automation.status_code == 201
        queued = await client.post(f"/api/v1/automations/{automation.json()['id']}/run", headers=headers)
        assert queued.status_code == 202


def test_secret_box_does_not_store_plaintext():
    box = SecretBox("x" * 32)
    encrypted = box.encrypt_json({"sid": "top-secret"})
    assert "top-secret" not in encrypted
    assert box.decrypt_json(encrypted) == {"sid": "top-secret"}


def test_cookiecloud_round_trip(settings):
    app = create_app(settings)
    payload = {"uuid": "browser-key", "encrypted": "opaque-data"}
    app.state.cookiecloud.put(payload)
    assert app.state.cookiecloud.get("browser-key") == payload


def test_expired_running_execution_can_be_reclaimed(settings):
    app = create_app(settings)
    automation = app.state.automations.create("a", "http_signin", 3600, {"url": "https://example.test"})
    execution = app.state.queue.enqueue_now(automation.id)
    claimed = app.state.queue.claim()
    assert claimed and claimed.id == execution.id
    with app.state.sessions.begin() as session:
        row = session.get(ExecutionRecord, execution.id)
        row.lease_until = utc_now() - timedelta(seconds=1)
    reclaimed = app.state.queue.claim()
    assert reclaimed and reclaimed.id == execution.id
    assert reclaimed.status == ExecutionStatus.RUNNING
    assert reclaimed.attempts == 2


def test_execution_keeps_credential_snapshot(settings):
    app = create_app(settings)
    credential = app.state.credentials.upsert("snapshot", "example.test", {"sid": "old"})
    automation = app.state.automations.create("a", "http_signin", 3600,
                                              {"url": "https://example.test"}, credential.id)
    execution = app.state.queue.enqueue_now(automation.id)
    app.state.credentials.upsert("snapshot", "example.test", {"sid": "new"})
    with app.state.sessions() as session:
        row = session.get(ExecutionRecord, execution.id)
        assert app.state.credentials.cookies_from_payload(row.credential_payload) == {"sid": "old"}
