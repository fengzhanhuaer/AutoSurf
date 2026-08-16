import json
import re

import httpx
import pytest
from sqlalchemy import select

from autosurf.automations.browser_session import playwright_cookies
from autosurf.automations.pt_signin import RousiAdapter, web_storage_init_script
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
        first_key = re.search(r'"uploadKey": "([^"]+)"', script).group(1)
        denied = await client.post(
            "/api/web-credentials/rousi/values",
            headers={"Authorization": "Bearer wrong"},
            json={"values": {"token": token}},
        )
        uploaded = await client.post(
            "/api/web-credentials/rousi/values",
            headers={"Authorization": f"Bearer {first_key}"},
            json={"values": {"token": token}},
        )
        status = await client.get("/api/v1/web-credentials/rousi", auth=auth)
        candidates = await client.get("/api/v1/pt-signin/candidates", auth=auth)
        sites = await client.get("/api/v1/pt-signin/sites", auth=auth)
        regenerated = await client.post(
            "/api/v1/web-credentials/rousi/userscript",
            auth=auth,
            json={"base_url": "https://autosurf.example.test"},
        )
        second_key = re.search(r'"uploadKey": "([^"]+)"', regenerated.text).group(1)
        old_key = await client.post(
            "/api/web-credentials/rousi/values",
            headers={"Authorization": f"Bearer {first_key}"},
            json={"values": {"token": token}},
        )
        new_key = await client.post(
            "/api/web-credentials/rousi/values",
            headers={"Authorization": f"Bearer {second_key}"},
            json={"values": {"token": token}},
        )

    assert initial.json()["token_configured"] is False
    assert generated.status_code == 200
    assert 'filename="autosurf-web-credential-sync.user.js"' in generated.headers["content-disposition"]
    assert "// @name         AutoSurf Web 凭据同步" in script
    assert "// @version      1.2.0" in script
    assert "// @match        https://rousi.pro/*" in script
    assert "// @match        https://kp.m-team.cc/*" in script
    assert '"name": "Rousi"' in script
    assert '"name": "M-Team"' in script
    assert "// @connect      192.168.1.50" in script
    assert "http://192.168.1.50:18980/api/web-credentials/rousi/values" in script
    assert "http://192.168.1.50:18980/api/web-credentials/mteam/values" in script
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
    assert rebound_site["config"]["profile_refresh_supported"] is True
    assert rebound_site["config"]["profile_refresh_enabled"] is True
    assert first_key != second_key
    assert old_key.status_code == 401
    assert new_key.status_code == 200

    rousi = next(item for item in candidates.json()["items"] if item["site_key"] == "rousi.pro")
    assert rousi["credential"]["provider"] == "web_storage"
    assert rousi["strategy"] == "web_storage_browser"
    assert rousi["supported"] is True
    assert rousi["configured"] is True
    assert rousi["profile_refresh_supported"] is True
    assert rousi["default_profile_refresh_enabled"] is True

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
        rebound_config = json.loads(rebound.config_json)
        assert rebound_config["profile_refresh_supported"] is True
        assert rebound_config["profile_refresh_enabled"] is True


@pytest.mark.asyncio
async def test_bundled_userscript_syncs_mteam_storage_and_rebinds_task(settings):
    app = create_app(settings)
    legacy = app.state.credentials.upsert(
        "manual:kp.m-team.cc", "kp.m-team.cc", {}, provider="manual",
    )
    task = app.state.automations.create(
        "M-Team", "pt_signin", 86400, {
            "url": "https://kp.m-team.cc/",
            "credential_domain": "kp.m-team.cc",
            "discovery_strategy": "custom_required",
            "sign_in_supported": False,
            "profile_refresh_supported": False,
            "sign_in_enabled": False,
            "profile_refresh_enabled": False,
            "discovered": True,
        }, legacy.id,
    )
    with app.state.sessions.begin() as session:
        session.get(AutomationRecord, task.id).enabled = False

    transport = httpx.ASGITransport(app=app)
    auth = (settings.username, settings.password)
    values = {"auth": "mteam-auth-token-value", "did": "device-123", "visitorId": "visitor-456"}
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        generated = await client.post(
            "/api/v1/web-credentials/userscript", auth=auth,
            json={"base_url": "http://192.168.1.50:18980"},
        )
        script = generated.text
        mteam_key = re.search(
            r'"key": "mteam".*?"uploadKey": "([^"]+)"', script,
        ).group(1)
        rejected = await client.post(
            "/api/web-credentials/mteam/values",
            headers={"Authorization": f"Bearer {mteam_key}"},
            json={"values": {**values, "unexpected": "value"}},
        )
        uploaded = await client.post(
            "/api/web-credentials/mteam/values",
            headers={"Authorization": f"Bearer {mteam_key}"},
            json={"values": values},
        )
        statuses = await client.get("/api/v1/web-credentials", auth=auth)
        candidates = await client.get("/api/v1/pt-signin/candidates", auth=auth)

    assert generated.status_code == 200
    assert "// @match        https://rousi.pro/*" in script
    assert "// @match        https://kp.m-team.cc/*" in script
    assert "auth" in script and "did" in script and "visitorId" in script
    assert all(value not in script for value in values.values())
    assert rejected.status_code == 422
    assert uploaded.status_code == 200
    mteam_status = next(item for item in statuses.json()["items"] if item["source_key"] == "mteam")
    assert mteam_status["credential_configured"] is True
    assert mteam_status["configured_keys"] == ["auth", "did", "visitorId"]
    mteam = next(item for item in candidates.json()["items"] if item["site_key"] == "kp.m-team.cc")
    assert mteam["strategy"] == "web_storage_profile_refresh_only"
    assert mteam["supported"] is True
    assert mteam["sign_in_supported"] is False
    assert mteam["profile_refresh_supported"] is True
    assert mteam["default_profile_refresh_enabled"] is True

    with app.state.sessions() as session:
        record = session.scalar(select(CredentialRecord).where(
            CredentialRecord.name == "web-storage:kp.m-team.cc",
        ))
        assert record is not None
        assert all(value not in record.encrypted_payload for value in values.values())
        decrypted, browser_cookies = app.state.credentials.credential_values_from_payload(
            record.encrypted_payload,
        )
        assert decrypted == values
        assert browser_cookies == []
        rebound = session.get(AutomationRecord, task.id)
        assert rebound.credential_id == record.id
        assert rebound.enabled is True
        config = json.loads(rebound.config_json)
        assert config["discovery_strategy"] == "web_storage_profile_refresh_only"
        assert config["sign_in_supported"] is False
        assert config["sign_in_enabled"] is False
        assert config["profile_refresh_supported"] is True
        assert config["profile_refresh_enabled"] is True


def test_web_storage_init_script_injects_all_values_for_target_host():
    script = web_storage_init_script(
        "https://kp.m-team.cc/", {"auth": "secret-auth", "did": "device"},
    )
    assert '"hostname": "kp.m-team.cc"' in script
    assert '"auth": "secret-auth"' in script
    assert '"did": "device"' in script
    assert "localStorage.setItem(key, value)" in script


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
            return {
                "status": 200 if self.authenticated else 401,
                "body": {
                    "role": "member",
                    "stats": {
                        "username": "fenger",
                        "uploaded": 2886753265554,
                        "downloaded": 252573177082,
                        "ratio": 11.429,
                        "karma": 2269129.9,
                        "level": 2,
                    },
                    "seeding_leeching_data": {"seeding_count": 0, "seeding_size": 0},
                },
            }
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


@pytest.mark.asyncio
async def test_rousi_adapter_refreshes_profile_from_me_api():
    page = RousiPage()

    result = await RousiAdapter().refresh_profile(
        page,
        RunContext("test", {"url": page.url}, {"token": "header.payload.signature"}, []),
    )

    assert result.outcome == RunOutcome.SUCCESS
    assert result.details["profile_stats"] == {
        "username": "fenger",
        "user_level": "2",
        "uploaded": "2.63 TiB",
        "downloaded": "235.23 GiB",
        "ratio": "11.429",
        "bonus": "2269129.9",
        "seeding_count": "0",
        "seeding_size": "0 B",
    }
