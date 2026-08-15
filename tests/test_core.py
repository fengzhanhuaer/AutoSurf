from datetime import timedelta

import httpx
import pytest
from sqlalchemy import select

from autosurf.config import Settings
from autosurf.domain.models import ExecutionStatus, RunOutcome, RunResult, utc_now
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
async def test_management_uses_dedicated_login_page_and_docs_require_session(settings):
    app = create_app(settings)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        for path in ("/docs", "/openapi.json"):
            response = await client.get(path)
            assert response.status_code == 401

        root = await client.get("/")
        page = await client.get("/app", follow_redirects=False)
        login_page = await client.get("/login")
        css = await client.get("/assets/admin.css")
        javascript = await client.get("/assets/admin.js")
        login_css = await client.get("/assets/login.css")
        login_javascript = await client.get("/assets/login.js")

    assert root.status_code == 307
    assert root.headers["location"] == "/app"
    assert page.status_code == 307
    assert page.headers["location"] == "/login?next=/app"
    assert login_page.status_code == 200
    assert "登录管理控制台" in login_page.text
    assert "CookieCloud" not in login_page.text
    assert css.status_code == 200
    assert javascript.status_code == 200
    assert login_css.status_code == 200
    assert login_javascript.status_code == 200


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
        app_page = await client.get("/app", follow_redirects=False)
        login_page = await client.get("/login", follow_redirects=False)
        credentials = await client.get("/api/v1/credentials")
        docs = await client.get("/docs")
        schema = await client.get("/openapi.json")
        assert session.json() == {"username": settings.username}
        assert app_page.status_code == 200
        assert "CookieCloud" in app_page.text
        assert "PT 站点" in app_page.text
        assert "站点签到" in app_page.text
        assert "系统升级" in app_page.text
        assert "系统设置" in app_page.text
        assert 'id="settings-tab-cookiecloud"' in app_page.text
        assert 'id="settings-tab-upgrade"' in app_page.text
        assert 'id="upgrade-dialog"' not in app_page.text
        assert "login-form" not in app_page.text
        assert login_page.status_code == 307
        assert login_page.headers["location"] == "/app"
        assert credentials.status_code == 200
        assert docs.status_code == 200
        assert schema.json()["info"]["title"] == "AutoSurf"

        client.cookies.set("autosurf_session", client.cookies["autosurf_session"] + "tampered")
        assert (await client.get("/api/auth/session")).status_code == 401

        await client.post("/api/auth/login", json={"username": settings.username, "password": settings.password})
        logged_out = await client.post("/api/auth/logout")
        assert logged_out.status_code == 204
        assert (await client.get("/api/auth/session")).status_code == 401


@pytest.mark.asyncio
async def test_authenticated_web_upgrade_is_fixed_and_single_flight(settings, tmp_path, monkeypatch):
    repository = tmp_path / "program"
    repository.joinpath(".git").mkdir(parents=True)
    captured = []

    class FakeProcess:
        def poll(self):
            return None

    def fake_popen(command, **kwargs):
        captured.append((command, kwargs))
        return FakeProcess()

    monkeypatch.setattr("autosurf.api._program_repository", lambda: repository)
    monkeypatch.setattr("autosurf.api._upgrade_command", lambda: ["fixed-upgrade-helper"])
    monkeypatch.setattr("autosurf.api._program_revision", lambda _repository: "a" * 40)
    monkeypatch.setattr("autosurf.api._remote_revision", lambda _repository, _branch: ("b" * 40, None))
    monkeypatch.setattr("autosurf.api._browser_runtime", lambda: {
        "installed": True, "playwright_version": "1.61.0", "persistent": True,
    })
    monkeypatch.setattr("autosurf.api._python_dependencies", lambda _repository: {
        "checked": True, "satisfied": True, "total": 9, "issue_count": 0, "issues": [], "error": None,
    })
    monkeypatch.setattr("autosurf.api.subprocess.Popen", fake_popen)

    app = create_app(settings)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/api/v1/system/upgrade")).status_code == 401
        auth = (settings.username, settings.password)
        status_response = await client.get("/api/v1/system/upgrade", auth=auth)
        started = await client.post("/api/v1/system/upgrade", auth=auth)
        duplicate = await client.post("/api/v1/system/upgrade", auth=auth)

    assert status_response.json()["local_revision"] == "a" * 40
    assert status_response.json()["remote_revision"] == "b" * 40
    assert status_response.json()["update_available"] is True
    assert status_response.json()["can_upgrade"] is True
    assert status_response.json()["browser"]["persistent"] is True
    assert started.status_code == 202
    assert started.json()["running"] is True
    assert duplicate.status_code == 409
    assert len(captured) == 1
    assert "fixed-upgrade-helper" in captured[0][0]
    assert captured[0][1]["stdin"] is not None


@pytest.mark.asyncio
async def test_web_upgrade_rejects_current_version_and_remote_check_failure(settings, tmp_path, monkeypatch):
    repository = tmp_path / "program"
    repository.joinpath(".git").mkdir(parents=True)
    revision = "a" * 40
    monkeypatch.setattr("autosurf.api._program_repository", lambda: repository)
    monkeypatch.setattr("autosurf.api._upgrade_command", lambda: ["fixed-upgrade-helper"])
    monkeypatch.setattr("autosurf.api._program_revision", lambda _repository: revision)
    monkeypatch.setattr("autosurf.api._browser_runtime", lambda: {
        "installed": True, "playwright_version": "1.61.0", "persistent": True,
    })
    dependency_status = {
        "checked": True, "satisfied": True, "total": 9, "issue_count": 0, "issues": [], "error": None,
    }
    monkeypatch.setattr("autosurf.api._python_dependencies", lambda _repository: dependency_status)

    app = create_app(settings)
    transport = httpx.ASGITransport(app=app)
    auth = (settings.username, settings.password)
    monkeypatch.setattr("autosurf.api._remote_revision", lambda _repository, _branch: (revision, None))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        current = await client.get("/api/v1/system/upgrade", auth=auth)
        rejected = await client.post("/api/v1/system/upgrade", auth=auth)
    assert current.json()["update_available"] is False
    assert current.json()["can_upgrade"] is False
    assert rejected.status_code == 409
    assert rejected.json()["detail"] == "当前已是最新版本"

    monkeypatch.setattr("autosurf.api._remote_revision", lambda _repository, _branch: (None, "远端版本检查超时"))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        failed = await client.get("/api/v1/system/upgrade", auth=auth)
        unavailable = await client.post("/api/v1/system/upgrade", auth=auth)
    assert failed.json()["can_upgrade"] is False
    assert failed.json()["version_check_error"] == "远端版本检查超时"
    assert unavailable.status_code == 503


def test_python_dependency_status_checks_declared_constraints(tmp_path, monkeypatch):
    from autosurf.api import _python_dependencies

    tmp_path.joinpath("pyproject.toml").write_text(
        """[project]
dependencies = [
  "present>=1,<2",
  "wrong>=2,<3",
  "missing==1.0",
  "ignored>=1; python_version < '2'",
]
""",
        encoding="utf-8",
    )

    def installed_version(name):
        if name == "present":
            return "1.5"
        if name == "wrong":
            return "3.0"
        raise __import__("importlib.metadata").metadata.PackageNotFoundError(name)

    monkeypatch.setattr("autosurf.api.version", installed_version)
    result = _python_dependencies(tmp_path)

    assert result["checked"] is True
    assert result["satisfied"] is False
    assert result["total"] == 3
    assert result["issue_count"] == 2
    assert result["issues"] == [
        {"name": "wrong", "required": "<3,>=2", "installed": "3.0", "status": "incompatible"},
        {"name": "missing", "required": "==1.0", "installed": None, "status": "missing"},
    ]


@pytest.mark.asyncio
async def test_current_program_can_repair_python_dependencies(settings, tmp_path, monkeypatch):
    repository = tmp_path / "program"
    repository.joinpath(".git").mkdir(parents=True)
    revision = "a" * 40
    monkeypatch.setattr("autosurf.api._program_repository", lambda: repository)
    monkeypatch.setattr("autosurf.api._upgrade_command", lambda: ["fixed-upgrade-helper"])
    monkeypatch.setattr("autosurf.api._program_revision", lambda _repository: revision)
    monkeypatch.setattr("autosurf.api._remote_revision", lambda _repository, _branch: (revision, None))
    monkeypatch.setattr("autosurf.api._browser_runtime", lambda: {"installed": True})
    monkeypatch.setattr("autosurf.api._python_dependencies", lambda _repository: {
        "checked": True,
        "satisfied": False,
        "total": 9,
        "issue_count": 1,
        "issues": [{
            "name": "httpx", "required": "<1,>=0.28", "installed": "0.27.0", "status": "incompatible",
        }],
        "error": None,
    })

    app = create_app(settings)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/v1/system/upgrade", auth=(settings.username, settings.password),
        )

    assert response.status_code == 200
    assert response.json()["update_available"] is False
    assert response.json()["can_upgrade"] is True
    assert response.json()["python_dependencies"]["issues"][0]["name"] == "httpx"

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


def test_pt_scheduled_execution_is_randomized_and_immediate_run_is_deduplicated(settings):
    app = create_app(settings)
    automation = app.state.automations.create(
        "pt", "pt_signin", 86400,
        {"url": "https://example.test/attendance.php", "random_delay_minutes": 30},
    )
    before = utc_now()

    assert app.state.queue.enqueue_due() == 1
    with app.state.sessions() as session:
        scheduled = session.scalar(select(ExecutionRecord).where(
            ExecutionRecord.automation_id == automation.id
        ))
        assert scheduled is not None
        assert before <= scheduled.available_at <= utc_now() + timedelta(minutes=30)

    immediate = app.state.queue.enqueue_now(automation.id)
    with app.state.sessions() as session:
        records = session.scalars(select(ExecutionRecord).where(
            ExecutionRecord.automation_id == automation.id
        )).all()
        assert len(records) == 1
        assert records[0].id == immediate.id == scheduled.id
        assert records[0].available_at <= utc_now()


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


@pytest.mark.asyncio
async def test_failed_handler_outcome_is_not_recorded_as_success(settings):
    class FailedHandler:
        type = "test_failed"

        async def run(self, _context):
            return RunResult(RunOutcome.AUTH_EXPIRED, "Cookie expired")

    app = create_app(settings)
    app.state.registry.register(FailedHandler())
    automation = app.state.automations.create("failure", "test_failed", 3600, {})
    execution = app.state.queue.enqueue_now(automation.id)

    assert await app.state.execution.run_one() is True
    with app.state.sessions() as session:
        record = session.get(ExecutionRecord, execution.id)
        assert record.status == ExecutionStatus.RETRY_WAIT
        assert record.error == "Cookie expired"
        assert record.result_json is not None
        assert __import__("json").loads(record.result_json)["outcome"] == "auth_expired"


@pytest.mark.asyncio
async def test_pt_retry_policy_uses_configured_fixed_interval_and_retry_count(settings):
    class FailedPtHandler:
        type = "pt_signin"

        async def run(self, _context):
            return RunResult(RunOutcome.AUTH_EXPIRED, "Cookie expired")

    app = create_app(settings)
    app.state.registry._handlers["pt_signin"] = FailedPtHandler()
    automation = app.state.automations.create(
        "failure", "pt_signin", 86400,
        {"url": "https://example.test", "max_retries": 5, "retry_interval_minutes": 120},
    )
    execution = app.state.queue.enqueue_now(automation.id)

    assert await app.state.execution.run_one() is True
    with app.state.sessions() as session:
        first_retry = session.get(ExecutionRecord, execution.id)
        assert first_retry.status == ExecutionStatus.RETRY_WAIT
        assert timedelta(minutes=119) <= first_retry.available_at - utc_now() <= timedelta(minutes=120)

    for _ in range(5):
        with app.state.sessions.begin() as session:
            session.get(ExecutionRecord, execution.id).available_at = utc_now() - timedelta(seconds=1)
        assert await app.state.execution.run_one() is True

    with app.state.sessions() as session:
        record = session.get(ExecutionRecord, execution.id)
        assert record.status == ExecutionStatus.FAILED
        assert record.attempts == 6
