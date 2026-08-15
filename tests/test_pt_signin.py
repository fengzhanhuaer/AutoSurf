from datetime import datetime, timedelta
import json
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select

from autosurf.automations.pt_signin import (
    BtschoolAdapter,
    FiftyTwoPtAdapter,
    OpenCdAdapter,
    PtSignInHandler,
    TjuptAdapter,
    classify_pt_page,
    combine_pt_action_results,
    complete_52pt_slider,
    extract_text_signin_history,
    normalize_site_signin_history,
    normalize_pt_profile_stats,
    sanitize_pt_profile_stats,
    profile_url_from_cookies,
    pt_signin_history_url,
    pttime_history_url_from_profile,
)
from autosurf.config import Settings
from autosurf.application.services import reconcile_pt_site_aliases
from autosurf.domain.models import RunContext, RunOutcome, RunResult
from autosurf.domain.models import utc_now
from autosurf.infrastructure.database import AutomationRecord, ExecutionRecord
from autosurf.main import create_app
from autosurf.pt_discovery import discover_pt_site, pt_site_domain_aliases


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
        "https://tracker.test/attendance.php", 200, "今天签到您获得81点魔力值"
    ) == RunOutcome.SUCCESS
    assert classify_pt_page(
        "https://pttime.org/attendance.php", 200, "今天已签到，请勿重复刷新。已刷次数：2次。"
    ) == RunOutcome.ALREADY_DONE
    assert classify_pt_page(
        "https://pttime.org/attendance.php", 200, "拒绝访问：已签到，无需再签"
    ) == RunOutcome.ALREADY_DONE
    assert classify_pt_page(
        "https://ptchdbits.co/bakatest.php", 200, "今天已经签过到了(已连续29天签到)"
    ) == RunOutcome.ALREADY_DONE
    assert classify_pt_page(
        "https://hdarea.club/", 200, "魔力值 [使用] [已签到] (32)"
    ) == RunOutcome.ALREADY_DONE
    assert classify_pt_page(
        "https://hdcity.city/", 200, "assignment_turned_in Checked in"
    ) == RunOutcome.ALREADY_DONE
    interrupted = (
        "已断签2天，当前可补签天数为113天，请点击选择补签弥补连续天数，"
        "或放弃补签重新开始签到。首次签到或重新开始签到可获得100个魔力值"
    )
    assert classify_pt_page(
        "https://tjupt.org/attendance.php", 200, interrupted
    ) == RunOutcome.FAILED


def test_pt_profile_url_and_combined_action_results():
    assert profile_url_from_cookies(
        "https://tracker.test/attendance.php", {"c_secure_uid": "735"}
    ) == "https://tracker.test/userdetails.php?id=735"
    assert profile_url_from_cookies(
        "https://tracker.test/attendance.php", {"c_secure_uid": "encrypted"}
    ) is None

    sign_in = RunResult(RunOutcome.ALREADY_DONE, "今日已经签到", {
        "site_history": [{"date": "2026-08-15", "reward": "81"}],
    })
    refreshed = RunResult(RunOutcome.SUCCESS, "个人信息页刷新成功", {
        "url": "https://tracker.test/userdetails.php?id=735",
    })
    result = combine_pt_action_results(sign_in, refreshed)
    assert result.outcome == RunOutcome.ALREADY_DONE
    assert result.details["actions"]["sign_in"]["enabled"] is True
    assert result.details["actions"]["profile_refresh"]["outcome"] == RunOutcome.SUCCESS
    assert result.details["site_history"][0]["reward"] == "81"


def test_pt_profile_stats_normalization_supports_nexusphp_labels():
    stats = normalize_pt_profile_stats({
        "pairs": [
            ["用户名", "mapleren"],
            ["用户等级", "POWER USER"],
            ["上传量", "32.77 TiB"],
            ["下载量", "60.66 GiB"],
            ["分享率", "553.157"],
            ["魔力值", "3,193,396.1"],
            ["当前做种", "8"],
            ["做种体积", "4.2 TiB"],
        ],
        "body": "",
        "title": "",
    })
    assert stats == {
        "username": "mapleren",
        "user_level": "POWER USER",
        "uploaded": "32.77 TiB",
        "downloaded": "60.66 GiB",
        "ratio": "553.157",
        "bonus": "3,193,396.1",
        "seeding_count": "8",
        "seeding_size": "4.2 TiB",
    }
    assert sanitize_pt_profile_stats({
        "username": "fenger💾[用户可用][考核通过] 修改此项",
        "user_level": "(小学)Power User 🩺校验等级加群参考",
    }) == {"username": "fenger", "user_level": "Power User"}
    assert sanitize_pt_profile_stats({
        "user_level": "[签到得魔力] 当前时间: 0:0",
    }) == {}
    assert sanitize_pt_profile_stats({
        "uploaded": "[签到得魔力] 当前时间: 0 0",
        "bonus": "[签到得魔力] 当前时间: 0 0",
        "seeding_count": "[显示/隐藏] [在种子列表查看]",
    }) == {}
    assert sanitize_pt_profile_stats({
        "uploaded": "上传量 10.92TB",
        "seeding_count": "共有0记录",
    }) == {"uploaded": "10.92TB", "seeding_count": "0"}


@pytest.mark.asyncio
async def test_pt_stats_api_returns_latest_profile_snapshot(settings):
    app = create_app(settings)
    credential = app.state.credentials.upsert(
        "cookiecloud:test:tracker.test", "tracker.test", {"sid": "secret"},
        provider="cookiecloud",
    )
    automation = app.state.automations.create(
        "Tracker", "pt_signin", 86400, {
            "url": "https://tracker.test/attendance.php",
            "credential_domain": "tracker.test",
            "sign_in_enabled": True,
            "profile_refresh_enabled": True,
        }, credential.id,
    )
    execution = app.state.queue.enqueue_now(automation.id)
    with app.state.sessions.begin() as session:
        record = session.get(ExecutionRecord, execution.id)
        record.status = "succeeded"
        record.finished_at = utc_now()
        record.result_json = json.dumps({
            "outcome": "success",
            "message": "done",
            "details": {"actions": {"profile_refresh": {"details": {
                "profile_stats": {"username": "mapleren", "uploaded": "32.77 TiB"},
            }}}},
        })

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/v1/pt-signin/stats", auth=(settings.username, settings.password)
        )
    assert response.status_code == 200
    assert response.json()["items"][0]["stats"] == {
        "username": "mapleren", "uploaded": "32.77 TiB",
    }


def test_site_signin_history_normalization_rejects_invalid_entries():
    assert normalize_site_signin_history([
        {"date": "2026-08-14", "reward": " 160 "},
        {"date": "invalid", "reward": "ignored"},
        {"date": "2026-08-15T12:00:00", "reward": 165},
        "invalid",
    ]) == [
        {"date": "2026-08-14", "reward": "160"},
        {"date": "2026-08-15", "reward": "165"},
    ]
    assert classify_pt_page(
        "https://tracker.test/login.php", 200, "欢迎"
    ) == RunOutcome.AUTH_EXPIRED
    assert classify_pt_page(
        "https://tracker.test/attendance.php", 200, "获得 [10]", {"success_patterns": ["获得 [10]"]}
    ) == RunOutcome.SUCCESS


def test_text_signin_history_supports_pttime_records():
    text = """
    7天签到记录（补签卡剩余：29）
    时间：2026-08-15 15:15:33 获得魔力值：600 连续天数：31天
    时间：2026-08-14 16:00:23 获得魔力值：600 连续天数：30天
    前30天签到记录
    连续天数：31 签到日：20260815
    连续天数：29 签到日：20260813
    """
    assert extract_text_signin_history(text) == [
        {"date": "2026-08-13", "reward": ""},
        {"date": "2026-08-14", "reward": "600"},
        {"date": "2026-08-15", "reward": "600"},
    ]
    assert pt_signin_history_url(
        "https://www.pttime.org/attendance.php", {"c_secure_uid": "94806"}
    ) == "https://www.pttime.org/attendance.php?type=sign&uid=94806"
    assert pt_signin_history_url(
        "https://tracker.test/attendance.php", {"c_secure_uid": "94806"}
    ) is None
    assert pttime_history_url_from_profile(
        "https://www.pttime.org/attendance.php",
        "/userdetails.php?id=94806",
    ) == "https://www.pttime.org/attendance.php?type=sign&uid=94806"


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


def test_52pt_discovery_and_adapter_use_the_current_signin_page():
    discovery = discover_pt_site("52pt.site", {"sid"})
    adapter = FiftyTwoPtAdapter()

    assert discovery is not None
    assert discovery.url == "https://52pt.site/52bakatest0818.php"
    assert adapter.matches(discovery.url) is True
    assert adapter.matches("https://www.52pt.site/52bakatest0818.php") is True
    assert adapter.matches("https://not52pt.site/52bakatest0818.php") is False


@pytest.mark.asyncio
async def test_btschool_adapter_treats_authenticated_empty_reward_as_already_done():
    class Body:
        async def inner_text(self):
            return "BTSCHOOL 欢迎回来, mapleren"

    class Page:
        url = "https://pt.btschool.club/index.php?action=addbonus"

        def locator(self, _selector):
            return Body()

    adapter = BtschoolAdapter()
    result = await adapter.sign_in(Page(), RunContext(
        "test", {"url": Page.url}, {"sid": "secret"},
    ))

    assert adapter.matches(Page.url) is True
    assert result.outcome == RunOutcome.ALREADY_DONE


@pytest.mark.asyncio
async def test_opencd_adapter_reports_image_captcha_as_blocked():
    class Locator:
        first = None

        def __init__(self, body=""):
            self.body = body
            self.first = self

        def filter(self, **_kwargs):
            return self

        async def inner_text(self):
            return self.body

        async def is_visible(self):
            return True

        async def click(self):
            return None

    class Response:
        url = "https://open.cd/plugin_sign-in.php"
        status = 200

        async def text(self):
            return '<input name="imagehash"><input name="imagestring">'

    class Pending:
        @property
        def value(self):
            async def response():
                return Response()
            return response()

    class ResponseContext:
        async def __aenter__(self):
            return Pending()

        async def __aexit__(self, *_args):
            return None

    class Page:
        url = "https://open.cd/"

        def locator(self, selector):
            return Locator("OpenCD 欢迎回来") if selector == "body" else Locator()

        def expect_response(self, _predicate):
            return ResponseContext()

    result = await OpenCdAdapter().sign_in(Page(), RunContext(
        "test", {"url": Page.url}, {"sid": "secret"},
    ))

    assert result.outcome == RunOutcome.BLOCKED
    assert result.message == "OpenCD 签到需要图片验证码"


def test_known_pt_routes_and_adapter_domains_are_explicit():
    expected = {
        "pt.btschool.club": "https://pt.btschool.club/index.php?action=addbonus",
        "ptchdbits.co": "https://ptchdbits.co/bakatest.php",
        "hdarea.club": "https://hdarea.club/",
        "hdcity.city": "https://hdcity.city/",
        "hdsky.me": "https://hdsky.me/",
        "open.cd": "https://open.cd/",
    }
    for domain, url in expected.items():
        discovery = discover_pt_site(domain, {"sid"})
        assert discovery is not None
        assert discovery.url == url

    assert BtschoolAdapter().matches(expected["pt.btschool.club"])
    assert OpenCdAdapter().matches(expected["open.cd"])
    assert TjuptAdapter().matches("https://tjupt.org/attendance.php")


@pytest.mark.asyncio
async def test_52pt_slider_uses_rendered_geometry_and_requires_completion():
    class Element:
        def __init__(self, box=None, value="", disabled=False):
            self.first = self
            self.box = box
            self.value = value
            self.disabled = disabled

        async def is_visible(self):
            return self.box is not None

        async def bounding_box(self):
            return self.box

        async def input_value(self):
            return self.value

        async def is_disabled(self):
            return self.disabled

    class Mouse:
        def __init__(self):
            self.calls = []

        async def move(self, x, y, steps=1):
            self.calls.append(("move", x, y, steps))

        async def down(self):
            self.calls.append(("down",))

        async def up(self):
            self.calls.append(("up",))

    class Page:
        def __init__(self):
            self.mouse = Mouse()
            self.elements = {
                "#slider-container": Element({"x": 100, "y": 50, "width": 300, "height": 40}),
                "#slider-btn": Element({"x": 102, "y": 52, "width": 50, "height": 36}),
                "#submit-btn": Element({"x": 100, "y": 100, "width": 300, "height": 40}, disabled=False),
                "#sign_captcha": Element({"x": 0, "y": 0, "width": 0, "height": 0}, value="generated"),
            }

        def locator(self, selector):
            return self.elements[selector]

        async def wait_for_timeout(self, _milliseconds):
            return None

    page = Page()

    assert await complete_52pt_slider(page) is True
    assert page.mouse.calls == [
        ("move", 127.0, 70.0, 1),
        ("down",),
        ("move", 373.0, 70.0, 24),
        ("up",),
    ]


def test_hhan_domains_share_one_site_key_and_cookie_alias_group():
    domains = ("hhan.club", "hhanclub.net", "hhanclub.top")
    discoveries = [discover_pt_site(domain, {"c_secure_uid"}) for domain in domains]

    assert all(discovery is not None for discovery in discoveries)
    assert {discovery.site_key for discovery in discoveries} == {"hhan.club"}
    assert {discovery.name for discovery in discoveries} == {"HhanClub"}
    assert set(pt_site_domain_aliases("hhanclub.top")) == {
        "hhan.club", "www.hhan.club",
        "hhanclub.net", "www.hhanclub.net",
        "hhanclub.top", "www.hhanclub.top",
    }


@pytest.mark.parametrize(
    ("current_domain", "old_domain", "name"),
    [
        ("pterclub.net", "pterclub.com", "PterClub"),
        ("rousi.pro", "rousi.zip", "Rousi"),
        ("haidan.cc", "haidan.video", "Haidan"),
    ],
)
def test_retired_domains_resolve_to_current_site(current_domain, old_domain, name):
    current = discover_pt_site(current_domain, {"c_secure_uid"})
    old = discover_pt_site(old_domain, {"c_secure_uid"})

    assert current is not None
    assert old is not None
    assert current.site_key == old.site_key == current_domain
    assert current.name == old.name == name
    assert current.url.startswith(f"https://{current_domain}/")
    assert old.url.startswith(f"https://{current_domain}/")
    assert set(pt_site_domain_aliases(old_domain)) == {
        current_domain,
        f"www.{current_domain}",
        old_domain,
        f"www.{old_domain}",
    }


def test_pt_discovery_distinguishes_refresh_only_and_dedicated_adapter_sites():
    discovery = discover_pt_site("zhuque.in", {"c_secure_uid"})
    rousi = discover_pt_site("rousi.pro", {"sid"})
    mteam = discover_pt_site("kp.m-team.cc", {"token"})

    assert discovery is not None
    assert discovery.strategy == "profile_refresh_only"
    assert discovery.supported is True
    assert discovery.sign_in_supported is False
    assert discovery.profile_refresh_supported is True
    assert discovery.default_profile_refresh_enabled is True
    assert discovery.profile_url == "https://zhuque.in/user/info"
    assert rousi is not None
    assert rousi.name == "Rousi"
    assert rousi.strategy == "custom_required"
    assert mteam is not None
    assert mteam.name == "M-Team"
    assert mteam.strategy == "custom_required"


def test_hdvideo_uses_current_catalog_domain():
    discovery = discover_pt_site("www.hdvideo.top", {"c_secure_uid"})

    assert discovery is not None
    assert discovery.site_key == "hdvideo.top"
    assert discovery.name == "HDVideo"
    assert discovery.url == "https://hdvideo.top/"


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
        refreshed_only = await client.patch(
            f"/api/v1/pt-signin/sites/{site_id}/actions", auth=auth, json={
                "sign_in_enabled": False,
                "profile_refresh_enabled": True,
            },
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
    assert refreshed_only.json()["enabled"] is True
    assert refreshed_only.json()["config"]["sign_in_enabled"] is False
    assert refreshed_only.json()["config"]["profile_refresh_enabled"] is True
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
    refresh_only = app.state.credentials.upsert(
        "cookiecloud:test:zhuque.in", "zhuque.in", {"sid": "secret"}, provider="cookiecloud",
    )
    unsupported = app.state.credentials.upsert(
        "cookiecloud:test:rousi.pro",
        "rousi.pro",
        {"sid": "secret"},
        provider="cookiecloud",
    )
    pttime_root = app.state.credentials.upsert_cookie_records(
        "cookiecloud:test:pttime.org", "pttime.org", [{
            "name": "cf_clearance", "value": "clear", "domain": ".pttime.org", "path": "/",
        }], provider="cookiecloud",
    )
    pttime_www = app.state.credentials.upsert_cookie_records(
        "cookiecloud:test:www.pttime.org", "www.pttime.org", [{
            "name": "c_secure_uid", "value": "1", "domain": "www.pttime.org", "path": "/",
        }, {
            "name": "c_secure_pass", "value": "pass", "domain": "www.pttime.org", "path": "/",
        }], provider="cookiecloud",
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
            "credential_ids": [
                recognized.id, recognized.id, catalog.id, refresh_only.id,
                pttime_root.id, pttime_www.id,
            ],
            "interval_hours": 12,
            "timeout_seconds": 45,
        })
        created_zhuque = next(
            item for item in collected.json()["created"] if item["name"] == "Zhuque"
        )
        rejected_sign_in = await client.patch(
            f"/api/v1/pt-signin/sites/{created_zhuque['id']}/actions",
            auth=auth,
            json={"sign_in_enabled": True, "profile_refresh_enabled": True},
        )
        collected_again = await client.post("/api/v1/pt-signin/sites/collect", auth=auth, json={
            "credential_ids": [recognized.id, catalog.id],
        })
        refreshed = await client.get("/api/v1/pt-signin/candidates", auth=auth)

    items = candidates.json()["items"]
    by_id = {item["credential"]["id"]: item for item in items}
    assert set(by_id) == {
        recognized.id, catalog.id, unknown.id, refresh_only.id, unsupported.id, pttime_www.id,
    }
    assert by_id[recognized.id]["reason"] == "cookie_signature"
    assert by_id[catalog.id]["name"] == "TJUPT"
    assert by_id[unknown.id]["recognized"] is False
    assert by_id[unsupported.id]["supported"] is False
    assert by_id[refresh_only.id]["supported"] is True
    assert by_id[refresh_only.id]["sign_in_supported"] is False
    assert by_id[refresh_only.id]["profile_refresh_supported"] is True
    assert by_id[refresh_only.id]["profile_url"] == "https://zhuque.in/user/info"
    assert by_id[pttime_www.id]["name"] == "PTTime"
    assert by_id[pttime_www.id]["url"] == "https://pttime.org/attendance.php"
    assert set(by_id[pttime_www.id]["credential_ids"]) == {pttime_root.id, pttime_www.id}
    assert "c_secure_uid" not in candidates.text
    assert "secret" not in candidates.text
    assert {item["credential"]["id"] for item in recognized_only.json()["items"]} == {
        recognized.id, catalog.id, refresh_only.id, unsupported.id, pttime_www.id,
    }
    assert rejected.status_code == 422
    assert unsupported_result.status_code == 422
    assert "尚需专用适配" in unsupported_result.json()["detail"]
    assert collected.status_code == 201
    assert len(collected.json()["created"]) == 4
    assert {item["interval_hours"] for item in collected.json()["created"]} == {12}
    assert {item["config"]["timeout_seconds"] for item in collected.json()["created"]} == {45}
    assert collected_again.json()["created"] == []
    assert len(collected_again.json()["skipped"]) == 2
    assert sum(item["configured"] for item in refreshed.json()["items"]) == 4
    assert rejected_sign_in.status_code == 422
    assert "没有签到功能" in rejected_sign_in.json()["detail"]

    pttime_site = next(item for item in collected.json()["created"] if item["name"] == "PTTime")
    zhuque_site = next(item for item in collected.json()["created"] if item["name"] == "Zhuque")
    assert zhuque_site["config"]["sign_in_enabled"] is False
    assert zhuque_site["config"]["profile_refresh_enabled"] is True
    assert zhuque_site["config"]["sign_in_supported"] is False
    assert zhuque_site["url"] == "https://zhuque.in/"
    execution = app.state.queue.enqueue_now(pttime_site["id"])
    with app.state.sessions() as session:
        snapshot = session.get(ExecutionRecord, execution.id).credential_payload
    _, browser_cookies = app.state.credentials.credential_values_from_payload(snapshot)
    assert {(cookie["name"], cookie["domain"]) for cookie in browser_cookies} == {
        ("cf_clearance", ".pttime.org"),
        ("c_secure_uid", "www.pttime.org"),
        ("c_secure_pass", "www.pttime.org"),
    }


@pytest.mark.asyncio
async def test_existing_zhuque_task_migrates_to_refresh_only_and_can_be_disabled(settings):
    app = create_app(settings)
    credential = app.state.credentials.upsert(
        "cookiecloud:test:zhuque.in", "zhuque.in", {"sid": "secret"},
        provider="cookiecloud",
    )
    task = app.state.automations.create(
        "Zhuque", "pt_signin", 86400, {
            "url": "https://zhuque.in/",
            "credential_domain": "zhuque.in",
            "sign_in_enabled": True,
            "profile_refresh_enabled": False,
        }, credential.id,
    )
    transport = httpx.ASGITransport(app=app)
    auth = (settings.username, settings.password)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        before = await client.get("/api/v1/pt-signin/sites", auth=auth)
        disabled = await client.patch(
            f"/api/v1/pt-signin/sites/{task.id}/actions", auth=auth,
            json={"sign_in_enabled": False, "profile_refresh_enabled": False},
        )
        after = await client.get("/api/v1/pt-signin/sites", auth=auth)

    before_config = before.json()["items"][0]["config"]
    assert before_config["sign_in_enabled"] is False
    assert before_config["profile_refresh_enabled"] is True
    assert before_config["sign_in_supported"] is False
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False
    assert after.json()["items"][0]["config"]["profile_refresh_enabled"] is False


def test_pt_alias_reconciliation_merges_tasks_history_and_active_executions(settings):
    app = create_app(settings)
    root = app.state.credentials.upsert_cookie_records(
        "cookiecloud:test:pttime.org", "pttime.org", [{
            "name": "cf_clearance", "value": "clear", "domain": ".pttime.org", "path": "/",
        }], provider="cookiecloud",
    )
    www = app.state.credentials.upsert_cookie_records(
        "cookiecloud:test:www.pttime.org", "www.pttime.org", [{
            "name": "c_secure_uid", "value": "1", "domain": "www.pttime.org", "path": "/",
        }], provider="cookiecloud",
    )
    root_task = app.state.automations.create(
        "PTTime", "pt_signin", 86400,
        {"url": "https://pttime.org/attendance.php", "credential_domain": "pttime.org"}, root.id,
    )
    www_task = app.state.automations.create(
        "PTTime", "pt_signin", 86400,
        {"url": "https://www.pttime.org/attendance.php", "credential_domain": "www.pttime.org"}, www.id,
    )
    root_execution = app.state.queue.enqueue_now(root_task.id)
    www_execution = app.state.queue.enqueue_now(www_task.id)

    assert reconcile_pt_site_aliases(app.state.sessions, app.state.credentials) == 1

    with app.state.sessions() as session:
        tasks = session.scalars(select(AutomationRecord).where(
            AutomationRecord.handler_type == "pt_signin"
        )).all()
        executions = session.scalars(select(ExecutionRecord).order_by(ExecutionRecord.id)).all()
        assert len(tasks) == 1
        assert tasks[0].id == www_task.id
        assert tasks[0].credential_id == www.id
        assert {execution.id for execution in executions} == {root_execution.id, www_execution.id}
        assert {execution.automation_id for execution in executions} == {www_task.id}
        assert sorted(execution.status for execution in executions) == ["cancelled", "pending"]
        pending = next(execution for execution in executions if execution.status == "pending")
        _, browser_cookies = app.state.credentials.credential_values_from_payload(
            pending.credential_payload
        )
        assert {cookie["name"] for cookie in browser_cookies} == {"cf_clearance", "c_secure_uid"}
        assert json.loads(tasks[0].config_json)["credential_aliases_merged"] is True


def test_pt_reconciliation_updates_catalog_url_only_for_discovered_tasks(settings):
    app = create_app(settings)
    credential = app.state.credentials.upsert(
        "cookiecloud:test:52pt.site", "52pt.site", {"sid": "secret"},
        provider="cookiecloud",
    )
    discovered = app.state.automations.create(
        "52PT", "pt_signin", 86400,
        {
            "url": "https://52pt.site/attendance.php",
            "credential_domain": "52pt.site",
            "discovered": True,
        },
        credential.id,
    )
    reconcile_pt_site_aliases(app.state.sessions, app.state.credentials)

    with app.state.sessions.begin() as session:
        discovered_config = json.loads(session.get(AutomationRecord, discovered.id).config_json)
        assert discovered_config["url"] == "https://52pt.site/52bakatest0818.php"
        discovered_config["url"] = "https://52pt.site/custom-signin.php"
        discovered_config["discovered"] = False
        session.get(AutomationRecord, discovered.id).config_json = json.dumps(discovered_config)

    reconcile_pt_site_aliases(app.state.sessions, app.state.credentials)

    with app.state.sessions() as session:
        manual_config = json.loads(session.get(AutomationRecord, discovered.id).config_json)
        assert manual_config["url"] == "https://52pt.site/custom-signin.php"


def test_pt_reconciliation_migrates_capabilities_and_current_domain(settings):
    app = create_app(settings)
    refresh_credential = app.state.credentials.upsert(
        "cookiecloud:test:nanyangpt.com", "nanyangpt.com", {"sid": "secret"},
        provider="cookiecloud",
    )
    old_domain_credential = app.state.credentials.upsert(
        "cookiecloud:test:pterclub.com", "pterclub.com", {"sid": "secret"},
        provider="cookiecloud",
    )
    refresh_task = app.state.automations.create(
        "nanyangpt.com", "pt_signin", 86400, {
            "url": "https://nanyangpt.com/attendance.php",
            "credential_domain": "nanyangpt.com",
            "sign_in_enabled": True,
            "profile_refresh_enabled": False,
            "sign_in_supported": True,
            "profile_refresh_supported": True,
            "discovered": True,
        }, refresh_credential.id,
    )
    old_domain_task = app.state.automations.create(
        "PterClub", "pt_signin", 86400, {
            "url": "https://pterclub.com/attendance.php",
            "credential_domain": "pterclub.com",
            "sign_in_enabled": True,
            "profile_refresh_enabled": True,
            "sign_in_supported": True,
            "profile_refresh_supported": True,
            "discovered": True,
        }, old_domain_credential.id,
    )
    old_domain_execution = app.state.queue.enqueue_now(old_domain_task.id)

    reconcile_pt_site_aliases(app.state.sessions, app.state.credentials)

    with app.state.sessions() as session:
        refreshed = session.get(AutomationRecord, refresh_task.id)
        refresh_config = json.loads(refreshed.config_json)
        migrated = session.get(AutomationRecord, old_domain_task.id)
        migrated_config = json.loads(migrated.config_json)
        execution = session.get(ExecutionRecord, old_domain_execution.id)
        assert refresh_config["url"] == "https://nanyangpt.com/"
        assert refresh_config["sign_in_enabled"] is False
        assert refresh_config["profile_refresh_enabled"] is True
        assert refresh_config["sign_in_supported"] is False
        assert migrated.enabled is True
        assert migrated.name == "PterClub"
        assert migrated_config["url"] == "https://pterclub.net/attendance.php"
        assert migrated_config["sign_in_supported"] is True
        assert migrated_config["profile_refresh_supported"] is True
        assert execution.status == "pending"


def test_hhan_alias_reconciliation_merges_three_domains_and_preserves_history(settings):
    app = create_app(settings)
    tasks = []
    executions = []
    for index, domain in enumerate(("hhan.club", "hhanclub.net", "hhanclub.top")):
        credential = app.state.credentials.upsert(
            f"cookiecloud:test:{domain}", domain,
            {"c_secure_uid": str(index + 1)}, provider="cookiecloud",
        )
        task = app.state.automations.create(
            domain, "pt_signin", 86400,
            {
                "url": f"https://{domain}/attendance.php",
                "credential_domain": domain,
                "sign_in_enabled": index != 0,
                "profile_refresh_enabled": index == 0,
            },
            credential.id,
        )
        tasks.append(task)
        executions.append(app.state.queue.enqueue_now(task.id))

    assert reconcile_pt_site_aliases(app.state.sessions, app.state.credentials) == 2

    with app.state.sessions() as session:
        remaining = session.scalars(select(AutomationRecord).where(
            AutomationRecord.handler_type == "pt_signin"
        )).all()
        history = session.scalars(select(ExecutionRecord)).all()
        assert len(remaining) == 1
        assert remaining[0].name == "HhanClub"
        assert {item.automation_id for item in history} == {remaining[0].id}
        assert {item.id for item in history} == {item.id for item in executions}
        config = json.loads(remaining[0].config_json)
        assert config["sign_in_enabled"] is True
        assert config["profile_refresh_enabled"] is True


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

    def execution(scheduled_at, status, message=None, site_history=None):
        result = {"outcome": "success", "message": message}
        if site_history:
            result["details"] = {"site_history": site_history}
        return ExecutionRecord(
            id=str(uuid4()), automation_id=site.id, scheduled_at=scheduled_at,
            status=status, attempts=1, available_at=scheduled_at,
            result_json=json.dumps(result) if message else None,
            error=None if message else "temporary failure",
        )

    with app.state.sessions.begin() as session:
        session.add_all([
            execution(yesterday_start_utc + timedelta(hours=3), "retry_wait"),
            execution(today_start_utc + timedelta(hours=1), "failed"),
            execution(today_start_utc + timedelta(hours=2), "succeeded", "签到成功", [
                {"date": local_today.isoformat(), "reward": "165"},
                {"date": (local_today - timedelta(days=1)).isoformat(), "reward": "160"},
            ]),
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
    assert by_id[site.id]["site_history"] == {
        local_today.isoformat(): {"date": local_today.isoformat(), "reward": "165"},
        (local_today - timedelta(days=1)).isoformat(): {
            "date": (local_today - timedelta(days=1)).isoformat(), "reward": "160",
        },
    }
    assert by_id[empty_site.id]["record_count"] == 0
    assert by_id[empty_site.id]["executions"] == {}
    assert payload["latest_execution"]["automation_name"] == "Tracker"
    assert invalid.status_code == 422
