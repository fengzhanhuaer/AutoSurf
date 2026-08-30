from datetime import datetime, timedelta
import io
import json
import zipfile

import httpx
import pytest
from sqlalchemy import select

from autosurf.config import Settings
from autosurf.domain.models import ExecutionStatus, RunOutcome, RunResult, utc_now
from autosurf.infrastructure.database import AutomationRecord, ExecutionRecord
from autosurf.main import create_app
from autosurf.application.services import (
    reconcile_periodic_signin_templates,
    reconcile_pt_profile_refresh_defaults,
    reconcile_signin_schedules,
)
from autosurf.domain.scheduling import next_signin_run_at


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=tmp_path, secret_key="s" * 32, username="admin", password="password123",
                    worker_poll_seconds=0.01, scheduler_poll_seconds=0.01)


def test_next_signin_run_uses_nine_am_taipei_anchor():
    assert next_signin_run_at(datetime(2026, 8, 20, 0, 30)) == datetime(2026, 8, 20, 1)
    assert next_signin_run_at(datetime(2026, 8, 20, 1)) == datetime(2026, 8, 21, 1)


def test_browser_runtime_reports_configured_google_chrome(tmp_path, monkeypatch):
    from autosurf.api import _browser_runtime

    executable = tmp_path / "google-chrome-stable"
    executable.write_text("", encoding="utf-8")
    monkeypatch.setenv("AUTOSURF_BROWSER_EXECUTABLE_PATH", str(executable))
    monkeypatch.setattr(
        "autosurf.api.subprocess.run",
        lambda *_args, **_kwargs: type(
            "Result", (), {"stdout": "Google Chrome 150.0.1.2\n"}
        )(),
    )

    runtime = _browser_runtime()

    assert runtime["installed"] is True
    assert runtime["browser_name"] == "Google Chrome"
    assert runtime["browser_version"] == "150.0.1.2"



def test_reconcile_signin_schedules_preserves_execution_history(settings):
    app = create_app(settings)
    automation = app.state.automations.create(
        "legacy", "http_signin", 12 * 3600, {"url": "https://example.test/checkin"},
    )
    execution = app.state.queue.enqueue_now(automation.id)

    assert reconcile_signin_schedules(app.state.sessions) == 1

    with app.state.sessions() as session:
        refreshed = session.get(AutomationRecord, automation.id)
        assert refreshed.interval_seconds == 24 * 3600
        assert refreshed.next_run_at.hour == 1
        assert json.loads(refreshed.config_json)["daily_start_time"] == "09:00"
        assert session.get(ExecutionRecord, execution.id) is not None


def test_reconcile_pt_profile_refresh_defaults_runs_once(settings):
    app = create_app(settings)
    automation = app.state.automations.create(
        "legacy-pt", "pt_signin", 24 * 3600, {
            "url": "https://tracker.test/attendance.php",
            "site_domain": "tracker.test",
            "profile_refresh_enabled": False,
            "profile_refresh_supported": False,
        },
    )
    with app.state.sessions.begin() as session:
        session.get(AutomationRecord, automation.id).enabled = False

    assert reconcile_pt_profile_refresh_defaults(app.state.sessions) == 1
    with app.state.sessions() as session:
        record = session.get(AutomationRecord, automation.id)
        config = json.loads(record.config_json)
        assert config["profile_refresh_enabled"] is True
        assert config["profile_refresh_supported"] is True
        assert config["profile_refresh_default_version"] == 1
        assert record.enabled is False

    with app.state.sessions.begin() as session:
        record = session.get(AutomationRecord, automation.id)
        config = json.loads(record.config_json)
        config["profile_refresh_enabled"] = False
        record.config_json = json.dumps(config)

    assert reconcile_pt_profile_refresh_defaults(app.state.sessions) == 0
    with app.state.sessions() as session:
        config = json.loads(session.get(AutomationRecord, automation.id).config_json)
        assert config["profile_refresh_enabled"] is False


def test_reconcile_pt_catalog_corrections_updates_known_legacy_urls(settings):
    app = create_app(settings)
    sites = {
        "hdfans": app.state.automations.create(
            "HDFans", "pt_signin", 86400, {
                "url": "https://www.hdfans.org/attendance.php", "site_domain": "www.hdfans.org",
                "profile_refresh_default_version": 1,
            },
        ),
        "ssd": app.state.automations.create(
            "SSD", "pt_signin", 86400, {
                "url": "https://springsunday.net/attendance.php",
                "site_domain": "springsunday.net", "profile_refresh_default_version": 1,
            },
        ),
        "jpopsuki": app.state.automations.create(
            "JPopsuki", "pt_signin", 86400, {
                "url": "https://jpopsuki.eu/", "site_domain": "jpopsuki.eu",
                "profile_refresh_default_version": 1,
            },
        ),
    }

    assert reconcile_pt_profile_refresh_defaults(app.state.sessions) == 3

    with app.state.sessions() as session:
        configs = {
            key: json.loads(session.get(AutomationRecord, record.id).config_json)
            for key, record in sites.items()
        }
    assert configs["hdfans"]["url"] == "https://hdfans.org/attendance.php"
    assert configs["ssd"]["url"] == "https://springsunday.net/"
    assert configs["ssd"]["sign_in_supported"] is False
    assert configs["jpopsuki"]["profile_url"] == "https://jpopsuki.eu/bonus.php"


@pytest.mark.asyncio
async def test_web_api_aligns_all_signin_schedules_without_deleting_history(settings):
    app = create_app(settings)
    first = app.state.automations.create(
        "pt", "pt_signin", 12 * 3600, {"url": "https://pt.test/attendance.php"},
    )
    second = app.state.automations.create(
        "periodic", "http_signin", 6 * 3600, {"url": "https://example.test/checkin"},
    )
    execution = app.state.queue.enqueue_now(second.id)
    transport = httpx.ASGITransport(app=app)
    auth = (settings.username, settings.password)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.patch("/api/v1/signin/schedule", auth=auth, json={})

    assert response.status_code == 200
    assert response.json()["updated"] == 2
    assert response.json()["daily_start_time"] == "09:00"
    assert datetime.fromisoformat(response.json()["next_run_at"]).hour == 1
    with app.state.sessions() as session:
        for automation_id in (first.id, second.id):
            record = session.get(AutomationRecord, automation_id)
            assert record.interval_seconds == 24 * 3600
            assert record.next_run_at.hour == 1
        assert session.get(ExecutionRecord, execution.id) is not None


@pytest.mark.asyncio
async def test_api_creates_and_runs_automation(settings):
    app = create_app(settings)
    transport = httpx.ASGITransport(app=app)
    auth = (settings.username, settings.password)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        automation = await client.post("/api/v1/automations", auth=auth, json={
            "name": "test", "handler_type": "http_signin", "interval_seconds": 3600,
            "config": {"url": "https://example.test/checkin"},
        })
        assert automation.status_code == 201
        queued = await client.post(f"/api/v1/automations/{automation.json()['id']}/run", auth=auth)
        assert queued.status_code == 202


@pytest.mark.asyncio
async def test_periodic_signin_api_manages_nodeseek_task(settings):
    app = create_app(settings)
    transport = httpx.ASGITransport(app=app)
    auth = (settings.username, settings.password)
    payload = {
        "name": "NodeSeek",
        "handler_type": "browser_signin",
        "template_key": "nodeseek",
        "url": "https://www.nodeseek.com/board",
        "interval_hours": 24,
        "timeout_seconds": 60,
        "random_delay_minutes": 30,
        "retry_interval_hours": 2,
        "max_retries": 5,
        "wait_for_selector": ".head-info",
        "click_role": "button",
        "click_name": "鸡腿 x 5",
        "click_exact": True,
        "wait_after_click_ms": 2000,
        "success_patterns": [r"今日签到获得鸡腿\d+个"],
        "already_patterns": [r"今日签到获得鸡腿\d+个"],
        "auth_expired_patterns": ["登录后签到"],
    }
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        rejected = await client.post(
            "/api/v1/periodic-signin/sites", auth=auth,
            json={**payload, "url": "https://example.test/board"},
        )
        created = await client.post("/api/v1/periodic-signin/sites", auth=auth, json=payload)
        assert created.json()["config"]["daily_start_time"] == "09:00"
        assert datetime.fromisoformat(created.json()["next_run_at"]).hour == 1
        site_id = created.json()["id"]
        listed = await client.get("/api/v1/periodic-signin/sites", auth=auth)
        scheduled = await client.patch(
            f"/api/v1/periodic-signin/sites/{site_id}/schedule", auth=auth,
            json={"interval_hours": 12, "timeout_seconds": 45, "random_delay_minutes": 10,
                  "retry_interval_hours": 1, "max_retries": 3},
        )
        disabled = await client.patch(
            f"/api/v1/periodic-signin/sites/{site_id}/enabled", auth=auth, json={"enabled": False},
        )
        queued = await client.post(f"/api/v1/periodic-signin/sites/{site_id}/run", auth=auth)
        deleted = await client.delete(f"/api/v1/periodic-signin/sites/{site_id}", auth=auth)

    assert rejected.status_code == 422
    assert created.status_code == 201
    assert listed.json()["items"][0]["template_key"] == "nodeseek"
    assert listed.json()["items"][0]["handler_type"] == "browser_signin"
    assert listed.json()["items"][0]["url"] == "https://www.nodeseek.com/board"
    assert listed.json()["items"][0]["site_url"] == "https://www.nodeseek.com/board"
    assert listed.json()["items"][0]["config"]["browser_request"]["method"] == "POST"
    assert scheduled.json()["interval_hours"] == 12
    assert scheduled.json()["config"]["daily_start_time"] == "09:00"
    assert datetime.fromisoformat(scheduled.json()["next_run_at"]).hour == 1
    assert disabled.json()["enabled"] is False
    assert queued.status_code == 202
    assert deleted.status_code == 204


@pytest.mark.asyncio
async def test_periodic_candidates_collect_templates_and_expose_execution_history(settings):
    app = create_app(settings)
    transport = httpx.ASGITransport(app=app)
    auth = (settings.username, settings.password)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        candidates = await client.get("/api/v1/periodic-signin/candidates", auth=auth)
        rejected = await client.post("/api/v1/periodic-signin/sites/collect", auth=auth, json={
            "site_keys": ["unknown"],
        })
        collected = await client.post("/api/v1/periodic-signin/sites/collect", auth=auth, json={
            "site_keys": ["nodeseek"],
            "interval_hours": 12,
            "timeout_seconds": 45,
            "random_delay_minutes": 10,
            "retry_interval_hours": 1,
            "max_retries": 3,
        })
        site = collected.json()["created"][0]
        queued = await client.post(
            f"/api/v1/periodic-signin/sites/{site['id']}/run", auth=auth,
        )
        history = await client.get("/api/v1/periodic-signin/executions", auth=auth)
        configured = await client.get("/api/v1/periodic-signin/candidates", auth=auth)

    candidate = candidates.json()["items"][0]
    assert candidates.status_code == 200
    assert len(candidates.json()["items"]) == 1
    assert candidate["template_key"] == "nodeseek"
    assert candidate["site_key"] == "nodeseek"
    assert candidate["configured"] is False
    assert rejected.status_code == 422
    assert collected.status_code == 201
    assert site["handler_type"] == "browser_signin"
    assert site["interval_hours"] == 12
    assert queued.status_code == 202
    assert history.json()["items"][0]["automation_name"] == "NodeSeek"
    assert history.json()["items"][0]["domain"] == "www.nodeseek.com"
    assert configured.json()["items"][0]["configured"] is True


@pytest.mark.asyncio
async def test_periodic_run_all_queues_enabled_tasks_once(settings):
    app = create_app(settings)
    enabled = app.state.automations.create(
        "Enabled", "http_signin", 86400, {"url": "https://enabled.test/"},
    )
    disabled = app.state.automations.create(
        "Disabled", "http_signin", 86400, {"url": "https://disabled.test/"},
    )
    with app.state.sessions.begin() as session:
        session.get(AutomationRecord, disabled.id).enabled = False

    transport = httpx.ASGITransport(app=app)
    auth = (settings.username, settings.password)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.post("/api/v1/periodic-signin/run-all", auth=auth)
        second = await client.post("/api/v1/periodic-signin/run-all", auth=auth)

    assert first.status_code == 202
    assert [item["automation_id"] for item in first.json()["queued"]] == [enabled.id]
    assert [item["automation_id"] for item in first.json()["skipped"]] == [disabled.id]
    assert second.json()["queued"] == []
    assert [item["automation_id"] for item in second.json()["skipped_active"]] == [enabled.id]


@pytest.mark.asyncio
async def test_execution_config_override_is_applied_without_changing_automation(settings):
    seen = []

    class CaptureHandler:
        type = "capture_override"

        async def run(self, context):
            seen.append(context.config)
            return RunResult(RunOutcome.SUCCESS, "done")

    app = create_app(settings)
    app.state.registry.register(CaptureHandler())
    automation = app.state.automations.create(
        "capture", "capture_override", 86400, {"mode": "scheduled", "kept": True},
    )
    execution = app.state.queue.enqueue_now(automation.id, {"mode": "batch"})

    assert await app.state.execution.run_one() is True
    assert seen == [{"mode": "batch", "kept": True}]
    with app.state.sessions() as session:
        stored_execution = session.get(ExecutionRecord, execution.id)
        stored_automation = session.get(AutomationRecord, automation.id)
        assert json.loads(stored_execution.config_override_json) == {"mode": "batch"}
        assert json.loads(stored_automation.config_json) == {"mode": "scheduled", "kept": True}


def test_periodic_template_reconciliation_migrates_nodeseek_only(settings):
    app = create_app(settings)
    nodeseek = app.state.automations.create(
        "NodeSeek", "browser_signin", 86400,
        {"template_key": "nodeseek", "url": "https://www.nodeseek.com/board"},
    )
    custom = app.state.automations.create(
        "HTTP", "http_signin", 3600, {"url": "https://example.test/checkin"},
    )

    assert reconcile_periodic_signin_templates(app.state.sessions) == 1

    with app.state.sessions() as session:
        migrated = session.get(AutomationRecord, nodeseek.id)
        untouched = session.get(AutomationRecord, custom.id)
        migrated_config = json.loads(migrated.config_json)
        assert migrated.handler_type == "browser_signin"
        assert migrated_config["url"] == "https://www.nodeseek.com/board"
        assert migrated_config["browser_request"]["method"] == "POST"
        assert r"今日签到获得鸡腿\d+个" in migrated_config["already_patterns"]
        assert untouched.handler_type == "http_signin"
        assert json.loads(untouched.config_json) == {"url": "https://example.test/checkin"}


@pytest.mark.asyncio
async def test_site_settings_backup_and_restore_round_trip(settings):
    app = create_app(settings)
    automation = app.state.automations.create(
        "saved-task", "http_signin", 3600, {"url": "https://example.test/checkin"},
    )
    app.state.queue.enqueue_now(automation.id)
    transport = httpx.ASGITransport(app=app)
    auth = (settings.username, settings.password)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        backup = await client.get("/api/v1/site-settings/backup", auth=auth)
        app.state.automations.create(
            "extra", "http_signin", 3600, {"url": "https://extra.test/checkin"},
        )
        restored = await client.post(
            "/api/v1/site-settings/restore", auth=auth,
            content=backup.content, headers={"Content-Type": "application/zip"},
        )

    assert backup.status_code == 200
    assert backup.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(backup.content)) as archive:
        exported = json.loads(archive.read("site-settings.json"))
    assert exported["schema_version"] == 2
    assert set(exported) == {"schema_version", "exported_at", "automations"}
    assert restored.json() == {
        "restored": True, "automation_count": 1,
    }
    with app.state.sessions() as session:
        assert [item.name for item in session.scalars(select(AutomationRecord)).all()] == ["saved-task"]
        assert session.scalars(select(ExecutionRecord)).all() == []


@pytest.mark.asyncio
async def test_management_is_lan_only_and_allows_198_18_network(settings):
    app = create_app(settings)
    public_transport = httpx.ASGITransport(app=app, client=("203.0.113.10", 12345))
    benchmark_transport = httpx.ASGITransport(app=app, client=("198.18.1.20", 12345))
    async with httpx.AsyncClient(transport=public_transport, base_url="http://test") as client:
        blocked = await client.get("/login")
    async with httpx.AsyncClient(transport=benchmark_transport, base_url="http://test") as client:
        allowed = await client.get("/login")
    assert blocked.status_code == 403
    assert blocked.json()["detail"] == "当前站点仅允许局域网访问"
    assert allowed.status_code == 200


@pytest.mark.asyncio
async def test_lan_access_can_be_disabled_and_persists(settings):
    app = create_app(settings)
    lan_transport = httpx.ASGITransport(app=app, client=("198.18.1.20", 12345))
    public_transport = httpx.ASGITransport(app=app, client=("203.0.113.10", 12345))
    auth = (settings.username, settings.password)
    async with httpx.AsyncClient(transport=lan_transport, base_url="http://test") as client:
        current = await client.get("/api/v1/system/access", auth=auth)
        disabled = await client.patch(
            "/api/v1/system/access", auth=auth, json={"lan_only": False},
        )
    async with httpx.AsyncClient(transport=public_transport, base_url="http://test") as client:
        public_login = await client.get("/login")
        protected = await client.get("/api/v1/automations")

    assert current.json() == {"lan_only": True}
    assert disabled.json() == {"lan_only": False}
    assert public_login.status_code == 200
    assert protected.status_code == 401

    restarted_app = create_app(settings)
    restarted_transport = httpx.ASGITransport(
        app=restarted_app, client=("203.0.113.10", 12345),
    )
    async with httpx.AsyncClient(transport=restarted_transport, base_url="http://test") as client:
        persisted = await client.get("/api/v1/system/access", auth=auth)
        enabled = await client.patch(
            "/api/v1/system/access", auth=auth, json={"lan_only": True},
        )
        blocked = await client.get("/login")

    assert persisted.json() == {"lan_only": False}
    assert enabled.json() == {"lan_only": True}
    assert blocked.status_code == 403


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
    assert css.headers["cache-control"] == "no-store"
    assert javascript.headers["cache-control"] == "no-store"
    assert 'const ACTIVE_EXECUTION_STATUSES = new Set(["pending", "running", "retry_wait"])' in javascript.text
    assert "window.setInterval(refreshExecutionStates, 15_000)" in javascript.text
    assert 'api("/api/v1/periodic-signin/sites")' in javascript.text
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
        automations = await client.get("/api/v1/automations")
        docs = await client.get("/docs")
        schema = await client.get("/openapi.json")
        assert session.json() == {"username": settings.username}
        assert app_page.status_code == 200
        assert "CookieCloud" not in app_page.text
        assert "PT 站点" in app_page.text
        assert "站点签到" in app_page.text
        assert "周期任务" in app_page.text
        assert "周期签到" not in app_page.text
        assert "系统升级" in app_page.text
        assert "系统设置" in app_page.text
        assert 'id="settings-tab-cookiecloud"' not in app_page.text
        assert 'id="settings-tab-web-credentials"' not in app_page.text
        assert 'id="settings-tab-site-settings"' in app_page.text
        assert 'id="settings-tab-logs"' in app_page.text
        assert 'id="logs-settings-panel"' in app_page.text
        assert 'id="debug-log-rows"' in app_page.text
        assert 'id="debug-log-dialog"' in app_page.text
        assert 'id="periodic-signin-panel"' in app_page.text
        assert 'id="periodic-site-form"' in app_page.text
        assert 'id="periodic-site-rows"' in app_page.text
        assert 'id="periodic-candidate-rows"' in app_page.text
        assert 'id="periodic-history-rows"' in app_page.text
        assert 'id="pt-run-all-signin"' in app_page.text
        assert 'id="pt-run-all-refresh"' in app_page.text
        assert 'id="periodic-run-all"' in app_page.text
        assert 'id="token-sync-base-url"' not in app_page.text
        assert 'id="token-script-button"' not in app_page.text
        assert 'id="token-script-copy-button"' not in app_page.text
        assert 'id="site-backup-button"' in app_page.text
        assert 'id="site-restore-button"' in app_page.text
        assert 'id="lan-only-access"' in app_page.text
        assert 'id="web-credential-rows"' not in app_page.text
        assert "M-Team" not in app_page.text
        assert 'id="copy-uuid-button"' not in app_page.text
        assert 'id="copy-password-button"' not in app_page.text
        assert 'id="settings-tab-upgrade"' in app_page.text
        assert 'id="upgrade-dialog"' not in app_page.text
        assert "login-form" not in app_page.text
        assert login_page.status_code == 307
        assert login_page.headers["location"] == "/app"
        assert automations.status_code == 200
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
async def test_windows_supervisor_receives_upgrade_request(settings, tmp_path, monkeypatch):
    repository = tmp_path / "program"
    repository.joinpath(".git").mkdir(parents=True)
    request_file = tmp_path / "data" / "upgrade-request.json"
    monkeypatch.setenv("AUTOSURF_UPGRADE_REQUEST_FILE", str(request_file))
    monkeypatch.setenv("AUTOSURF_UPGRADE_LOCK_FILE", str(tmp_path / "data" / "upgrade.lock"))
    monkeypatch.setattr("autosurf.api._program_repository", lambda: repository)
    monkeypatch.setattr("autosurf.api._upgrade_command", lambda: None)
    monkeypatch.setattr("autosurf.api._program_revision", lambda _repository: "a" * 40)
    monkeypatch.setattr("autosurf.api._remote_revision", lambda _repository, _branch: ("b" * 40, None))
    monkeypatch.setattr("autosurf.api._browser_runtime", lambda: {"installed": True})
    monkeypatch.setattr("autosurf.api._python_dependencies", lambda _repository: {
        "checked": True, "satisfied": True, "total": 9,
        "issue_count": 0, "issues": [], "error": None,
    })

    app = create_app(settings)
    transport = httpx.ASGITransport(app=app)
    auth = (settings.username, settings.password)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        started = await client.post("/api/v1/system/upgrade", auth=auth)
        duplicate = await client.post("/api/v1/system/upgrade", auth=auth)

    assert started.status_code == 202
    assert duplicate.status_code == 409
    assert request_file.is_file()
    assert "requested_at" in json.loads(request_file.read_text(encoding="utf-8"))


@pytest.mark.asyncio
async def test_web_upgrade_settles_stale_running_status(settings, tmp_path, monkeypatch):
    repository = tmp_path / "program"
    repository.joinpath(".git").mkdir(parents=True)
    revision = "a" * 40
    status_file = settings.data_dir / "upgrade-status.json"
    status_file.write_text(
        '{"state":"running","updated_at":"2026-08-15T08:43:17Z"}\n',
        encoding="utf-8",
    )

    monkeypatch.setattr("autosurf.api._program_repository", lambda: repository)
    monkeypatch.setattr("autosurf.api._upgrade_command", lambda: ["fixed-upgrade-helper"])
    monkeypatch.setattr("autosurf.api._upgrade_running", lambda _request: False)
    monkeypatch.setattr("autosurf.api._program_revision", lambda _repository: revision)
    monkeypatch.setattr("autosurf.api._remote_revision", lambda _repository, _branch: (revision, None))
    monkeypatch.setattr("autosurf.api._browser_runtime", lambda: {
        "installed": True, "playwright_version": "1.61.0", "persistent": True,
    })
    monkeypatch.setattr("autosurf.api._python_dependencies", lambda _repository: {
        "checked": True, "satisfied": True, "total": 9, "issue_count": 0, "issues": [], "error": None,
    })

    app = create_app(settings)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/v1/system/upgrade", auth=(settings.username, settings.password),
        )

    assert response.status_code == 200
    assert response.json()["running"] is False
    assert response.json()["last_upgrade"]["state"] == "complete"
    assert '"state": "complete"' in status_file.read_text(encoding="utf-8")


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


def test_success_clears_error_from_an_earlier_retry(settings):
    app = create_app(settings)
    automation = app.state.automations.create(
        "retry", "http_signin", 3600, {"url": "https://example.test"}
    )
    execution = app.state.queue.enqueue_now(automation.id)
    with app.state.sessions.begin() as session:
        row = session.get(ExecutionRecord, execution.id)
        row.error = "earlier failure"

    app.state.queue.succeed(execution.id, {"outcome": "success", "message": "done"})

    with app.state.sessions() as session:
        row = session.get(ExecutionRecord, execution.id)
        assert row.status == ExecutionStatus.SUCCEEDED
        assert row.error is None


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


def test_immediate_run_creates_new_execution_after_terminal_result(settings):
    app = create_app(settings)
    automation = app.state.automations.create(
        "retry", "http_signin", 3600, {"url": "https://example.test"}
    )
    completed = app.state.queue.enqueue_now(automation.id)
    app.state.queue.fail(completed.id, "failed", max_attempts=0)

    retried = app.state.queue.enqueue_now(automation.id)

    assert retried.id != completed.id
    assert retried.status == ExecutionStatus.PENDING
    with app.state.sessions() as session:
        records = session.scalars(select(ExecutionRecord).where(
            ExecutionRecord.automation_id == automation.id
        )).all()
        assert {record.status for record in records} == {
            ExecutionStatus.FAILED, ExecutionStatus.PENDING,
        }


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
