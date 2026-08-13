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
    return Settings(data_dir=tmp_path, secret_key="s" * 32, username="admin", password="password123",
                    worker_poll_seconds=0.01, scheduler_poll_seconds=0.01)


@pytest.mark.asyncio
async def test_api_creates_and_runs_automation(settings):
    app = create_app(settings)
    transport = httpx.ASGITransport(app=app)
    auth = (settings.username, settings.password)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/api/v1/credentials")).status_code == 401
        credential = await client.post("/api/v1/credentials", auth=auth, json={
            "name": "example", "domain": "example.test", "cookies": {"sid": "secret"}
        })
        assert credential.status_code == 201
        automation = await client.post("/api/v1/automations", auth=auth, json={
            "name": "test", "handler_type": "http_signin", "interval_seconds": 3600,
            "credential_id": credential.json()["id"],
            "config": {"url": "https://example.test/checkin"},
        })
        assert automation.status_code == 201
        queued = await client.post(f"/api/v1/automations/{automation.json()['id']}/run", auth=auth)
        assert queued.status_code == 202


@pytest.mark.asyncio
async def test_management_page_loads_login_ui_and_docs_require_session(settings):
    app = create_app(settings)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        for path in ("/docs", "/openapi.json"):
            response = await client.get(path)
            assert response.status_code == 401

        root = await client.get("/")
        page = await client.get("/app")
        css = await client.get("/assets/admin.css")
        javascript = await client.get("/assets/admin.js")

    assert root.status_code == 307
    assert root.headers["location"] == "/app"
    assert page.status_code == 200
    assert "登录 AutoSurf" in page.text
    assert css.status_code == 200
    assert javascript.status_code == 200


@pytest.mark.asyncio
async def test_management_session_login_and_logout(settings):
    app = create_app(settings)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        wrong = await client.post("/api/auth/login", json={"username": settings.username, "password": "wrong"})
        assert wrong.status_code == 401
        assert (await client.get("/api/auth/session", auth=(settings.username, settings.password))).status_code == 401

        logged_in = await client.post("/api/auth/login", json={
            "username": settings.username, "password": settings.password,
        })
        assert logged_in.status_code == 200
        cookie = logged_in.headers["set-cookie"]
        assert "HttpOnly" in cookie
        assert "SameSite=strict" in cookie
        assert settings.password not in cookie

        session = await client.get("/api/auth/session")
        credentials = await client.get("/api/v1/credentials")
        docs = await client.get("/docs")
        schema = await client.get("/openapi.json")
        assert session.json() == {"username": settings.username}
        assert credentials.status_code == 200
        assert docs.status_code == 200
        assert schema.json()["info"]["title"] == "AutoSurf"

        client.cookies.set("autosurf_session", client.cookies["autosurf_session"] + "tampered")
        assert (await client.get("/api/auth/session")).status_code == 401

        await client.post("/api/auth/login", json={"username": settings.username, "password": settings.password})
        logged_out = await client.post("/api/auth/logout")
        assert logged_out.status_code == 204
        assert (await client.get("/api/auth/session")).status_code == 401



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
