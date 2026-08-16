import re

import httpx
import pytest
from sqlalchemy import select

from autosurf.automations.browser_session import playwright_cookies
from autosurf.automations.pt_signin import RousiAdapter
from autosurf.config import Settings
from autosurf.domain.models import RunContext, RunOutcome
from autosurf.infrastructure.database import AutomationRecord, CredentialRecord
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


@pytest.mark.asyncio
async def test_rousi_userscript_rotates_write_key_and_encrypts_token(settings):
    app = create_app(settings)
    legacy = app.state.credentials.upsert(
        "cookiecloud:test:rousi.pro", "rousi.pro", {"sid": "legacy"}, provider="cookiecloud",
    )
    legacy_task = app.state.automations.create(
        "Rousi", "pt_signin", 86400, {
            "url": "https://rousi.pro/",
            "credential_domain": "rousi.pro",
            "sign_in_supported": False,
            "profile_refresh_supported": False,
            "sign_in_enabled": False,
            "profile_refresh_enabled": False,
            "discovered": True,
        }, legacy.id,
    )
    with app.state.sessions.begin() as session:
        session.get(AutomationRecord, legacy_task.id).enabled = False
    transport = httpx.ASGITransport(app=app)
    auth = (settings.username, settings.password)
    token = "header.payload.signature-for-rousi"
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/api/v1/web-credentials/rousi")).status_code == 401
        initial = await client.get("/api/v1/web-credentials/rousi", auth=auth)
        generated = await client.post(
            "/api/v1/web-credentials/rousi/userscript",
            auth=auth,
            json={"base_url": "http://192.168.1.50:18980"},
        )
        script = generated.text
        first_key = re.search(r'const uploadKey = "([^"]+)";', script).group(1)
        denied = await client.post(
            "/api/web-credentials/rousi/token",
            headers={"Authorization": "Bearer wrong"},
            json={"token": token},
        )
        uploaded = await client.post(
            "/api/web-credentials/rousi/token",
            headers={"Authorization": f"Bearer {first_key}"},
            json={"token": token},
        )
        status = await client.get("/api/v1/web-credentials/rousi", auth=auth)
        candidates = await client.get("/api/v1/pt-signin/candidates", auth=auth)
        sites = await client.get("/api/v1/pt-signin/sites", auth=auth)
        regenerated = await client.post(
            "/api/v1/web-credentials/rousi/userscript",
            auth=auth,
            json={"base_url": "https://autosurf.example.test"},
        )
        second_key = re.search(r'const uploadKey = "([^"]+)";', regenerated.text).group(1)
        old_key = await client.post(
            "/api/web-credentials/rousi/token",
            headers={"Authorization": f"Bearer {first_key}"},
            json={"token": token},
        )
        new_key = await client.post(
            "/api/web-credentials/rousi/token",
            headers={"Authorization": f"Bearer {second_key}"},
            json={"token": token},
        )

    assert initial.json()["token_configured"] is False
    assert generated.status_code == 200
    assert 'filename="autosurf-web-credential-sync.user.js"' in generated.headers["content-disposition"]
    assert "// @name         AutoSurf Web 凭据同步" in script
    assert "// @match        https://rousi.pro/*" in script
    assert 'const sourceName = "Rousi";' in script
    assert "// @connect      192.168.1.50" in script
    assert "http://192.168.1.50:18980/api/web-credentials/rousi/token" in script
    assert 'class="trigger"' in script
    assert 'class="token" type="password"' in script
    assert "AutoSurf Web 凭据同步" in script
    assert token not in script
    assert denied.status_code == 401
    assert uploaded.json()["changed"] is True
    assert status.json()["token_configured"] is True
    assert status.json()["last_sync_at"]
    rebound_site = next(item for item in sites.json()["items"] if item["id"] == legacy_task.id)
    assert rebound_site["config"]["sign_in_supported"] is True
    assert rebound_site["config"]["sign_in_enabled"] is True
    assert first_key != second_key
    assert old_key.status_code == 401
    assert new_key.status_code == 200

    rousi = next(item for item in candidates.json()["items"] if item["site_key"] == "rousi.pro")
    assert rousi["credential"]["provider"] == "web_storage"
    assert rousi["strategy"] == "web_storage_browser"
    assert rousi["supported"] is True
    assert rousi["configured"] is True

    with app.state.sessions() as session:
        record = session.scalar(select(CredentialRecord).where(
            CredentialRecord.provider == "web_storage",
        ))
        assert record is not None
        assert token not in record.encrypted_payload
        assert first_key not in record.encrypted_payload
        values, browser_cookies = app.state.credentials.credential_values_from_payload(
            record.encrypted_payload,
        )
        assert values == {"token": token}
        assert browser_cookies == []
        assert playwright_cookies(
            RunContext("test", {}, values, browser_cookies), "https://rousi.pro/",
        ) == []
        rebound = session.get(AutomationRecord, legacy_task.id)
        assert rebound.credential_id == record.id
        assert rebound.enabled is True


@pytest.mark.asyncio
async def test_rousi_userscript_rejects_non_root_upload_address(settings):
    app = create_app(settings)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/web-credentials/rousi/userscript",
            auth=(settings.username, settings.password),
            json={"base_url": "http://127.0.0.1:18980/app"},
        )
    assert response.status_code == 422
    assert response.json()["detail"] == "上送地址必须是 HTTP(S) 服务根地址"


class RousiPage:
    def __init__(self, *, attended=False, authenticated=True):
        self.url = "https://rousi.pro/"
        self.attended = attended
        self.authenticated = authenticated
        self.clicked = False

    async def evaluate(self, _script, data):
        if data["path"] == "/api/me":
            return {"status": 200 if self.authenticated else 401, "body": {"username": "user"}}
        dates = ["2026-08-16"] if self.attended else []
        return {
            "status": 200,
            "body": {"attendance": {"server_today": "2026-08-16", "attended_dates": dates}},
        }

    def get_by_role(self, _role, name):
        assert name.search("签到")
        return self

    @property
    def first(self):
        return self

    async def is_visible(self):
        return True

    async def wait_for(self, **_kwargs):
        return None

    async def click(self):
        self.clicked = True
        self.attended = True

    async def wait_for_timeout(self, _milliseconds):
        return None


@pytest.mark.asyncio
async def test_rousi_adapter_requires_api_confirmation_after_real_button_click():
    page = RousiPage()
    result = await RousiAdapter().sign_in(
        page,
        RunContext("test", {"url": page.url}, {"token": "header.payload.signature"}, []),
    )
    assert result.outcome == RunOutcome.SUCCESS
    assert page.clicked is True
    assert result.details["site_history"] == [{"date": "2026-08-16", "reward": ""}]

    already = RousiPage(attended=True)
    result = await RousiAdapter().sign_in(
        already,
        RunContext("test", {"url": already.url}, {"token": "header.payload.signature"}, []),
    )
    assert result.outcome == RunOutcome.ALREADY_DONE
    assert already.clicked is False

    expired = RousiPage(authenticated=False)
    result = await RousiAdapter().sign_in(
        expired,
        RunContext("test", {"url": expired.url}, {"token": "expired-token-value-123"}, []),
    )
    assert result.outcome == RunOutcome.AUTH_EXPIRED
    assert expired.clicked is False
