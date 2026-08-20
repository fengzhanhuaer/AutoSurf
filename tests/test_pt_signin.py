from datetime import datetime, timedelta
import json
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select

from autosurf.automations.pt_signin import (
    BtschoolAdapter,
    FiftyTwoPtAdapter,
    MTeamAdapter,
    OpenCdAdapter,
    OshenPtAdapter,
    PtSignInHandler,
    SoulVoiceAdapter,
    SunnyPtAdapter,
    TjuptAdapter,
    ZhuqueAdapter,
    _classify_pt_homepage,
    _complete_0ff_slider,
    _enrich_0ff_calendar_history,
    _goto_pt_page,
    _open_pt_signin_page,
    _resolve_0ff_slider,
    _submit_nexusphp_captcha,
    classify_cloudflare_upstream_error,
    classify_pt_challenge,
    classify_pt_page,
    combine_pt_action_results,
    complete_52pt_slider,
    confirm_safeline_challenge,
    discover_pt_profile_url,
    extract_site_signin_history,
    extract_text_signin_history,
    normalize_site_signin_history,
    normalize_pt_profile_stats,
    page_body_text,
    playwright_error_result,
    profile_refresh_skip_result,
    sanitize_pt_profile_stats,
    profile_url_from_cookies,
    pt_home_url,
    pt_signin_history_url,
    pttime_history_url_from_profile,
    refresh_pt_profile_page,
    rendered_signin_status_text,
    wait_for_automatic_pt_challenge,
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


def test_pt_challenge_vendor_is_reported_separately():
    assert classify_pt_challenge(
        "安全检测能力由 雷池 WAF 驱动，客户端异常，请确认您是合法用户"
    ) == ("safeline", "站点被雷池 WAF 拦截")
    assert classify_pt_challenge(
        "Just a moment... Cloudflare Ray ID: 123"
    ) == ("cloudflare", "站点被 Cloudflare 人机验证拦截")
    assert classify_pt_challenge(
        "人机验证 验证通过后将自动完成签到"
    ) == ("human_verification", "站点要求完成人机验证")


def test_cloudflare_origin_error_is_not_reported_as_human_verification():
    body = "Connection timed out Error code 522 Cloudflare Working Host Error"
    assert classify_cloudflare_upstream_error(522, body) == (
        "cloudflare_origin",
        "Cloudflare 连接站点源服务器超时（522）",
    )
    assert classify_pt_page(
        "https://www.okpt.net/", 522, body,
    ) == RunOutcome.FAILED
    assert classify_cloudflare_upstream_error(
        None, "connection timed out",
    ) is None


@pytest.mark.asyncio
async def test_wait_for_automatic_pt_challenge_stops_after_browser_is_allowed():
    class Body:
        def __init__(self, page):
            self.page = page

        async def inner_text(self):
            return self.page.body

    class Page:
        body = "安全检测能力由 雷池 WAF 驱动"
        waits = 0

        def locator(self, selector):
            assert selector == "body"
            return Body(self)

        async def wait_for_timeout(self, timeout_ms):
            assert timeout_ms == 500
            self.waits += 1
            if self.waits == 2:
                self.body = "欢迎回来，今日尚未签到"

    page = Page()
    assert await wait_for_automatic_pt_challenge(page, 2_000) is True
    assert page.waits == 3


@pytest.mark.asyncio
async def test_wait_for_automatic_pt_challenge_keeps_unsolved_challenge_blocked():
    class Body:
        async def inner_text(self):
            return "Just a moment... Cloudflare"

    class Page:
        waits = 0

        def locator(self, selector):
            assert selector == "body"
            return Body()

        async def wait_for_timeout(self, timeout_ms):
            assert timeout_ms == 500
            self.waits += 1

    page = Page()
    assert await wait_for_automatic_pt_challenge(page, 1_000) is False
    assert page.waits == 2


@pytest.mark.asyncio
async def test_safeline_confirmation_is_clicked_once_when_explicit():
    class Body:
        def __init__(self, page):
            self.page = page

        async def inner_text(self):
            return self.page.body

    class Button:
        def __init__(self, page):
            self.page = page
            self.first = self

        async def is_visible(self):
            return True

        async def click(self):
            self.page.clicks += 1
            self.page.body = "欢迎回来"

    class Page:
        body = "客户端异常，请确认您是合法用户。安全检测能力由 雷池 WAF 驱动"
        clicks = 0

        def locator(self, selector):
            if selector == "body":
                return Body(self)
            raise AssertionError("fallback locator should not be used")

        def get_by_role(self, role, *, name):
            assert role == "button"
            assert name.search("确认")
            return Button(self)

        def get_by_text(self, _name):
            raise AssertionError("fallback text lookup should not be used")

    page = Page()
    assert await confirm_safeline_challenge(page) is True
    assert page.clicks == 1
    assert page.body == "欢迎回来"


def test_pt_page_classification_distinguishes_common_results():
    assert classify_pt_page(
        "https://tracker.test/attendance.php", 403, "Just a moment... cf-chl-token"
    ) == RunOutcome.BLOCKED


@pytest.mark.asyncio
async def test_homepage_already_done_skips_hdkylin_challenge_page():
    class Locator:
        async def inner_text(self):
            return "控制面板 [签到已得65, 补签卡: 0]"

        async def count(self):
            return 0

    class Page:
        url = "https://www.hdkyl.in/"
        frames = []

        def locator(self, _selector):
            return Locator()

        async def evaluate(self, _script):
            return []

    page = Page()
    page.frames = [page]
    result = await _classify_pt_homepage(
        page,
        RunContext(
            "test", {"url": "https://www.hdkyl.in/attendance.php"}, {"sid": "secret"},
        ),
        200,
    )
    assert result is not None
    assert result.outcome == RunOutcome.ALREADY_DONE
    assert result.details["url"] == "https://www.hdkyl.in/"
    assert page.url == "https://www.hdkyl.in/"


@pytest.mark.asyncio
async def test_u2_homepage_already_done_requires_attendance_page():
    class Locator:
        async def inner_text(self):
            return "历史签到记录 今日已签到"

        async def count(self):
            return 0

    class Page:
        url = "https://u2.dmhy.org/"

        def locator(self, _selector):
            return Locator()

        async def evaluate(self, _script):
            return []

    page = Page()
    page.frames = [page]

    result = await _classify_pt_homepage(
        page,
        RunContext(
            "test", {"url": "https://u2.dmhy.org/attendance.php"}, {"nexusphp_u2": "secret"},
        ),
        200,
    )

    assert result is None


@pytest.mark.asyncio
async def test_0ff_homepage_already_done_is_enriched_from_calendar_page():
    class Locator:
        first = None

        def __init__(self, selector):
            self.selector = selector
            self.first = self

        async def inner_text(self):
            return "今日已签到"

        async def count(self):
            return 0

        async def wait_for(self, **_kwargs):
            return None

    class Response:
        status = 200

    class Page:
        url = "https://pt.0ff.cc/"
        frames = []

        def locator(self, selector):
            return Locator(selector)

        async def evaluate(self, script):
            if "eventSelector" in script:
                return [{"date": "2026-08-16", "reward": "15"}]
            return []

        async def goto(self, url, **_kwargs):
            self.url = url
            return Response()

    page = Page()
    page.frames = [page]

    homepage = await _classify_pt_homepage(
        page,
        RunContext(
            "test", {"url": "https://pt.0ff.cc/attendance.php"}, {"sid": "secret"},
        ),
        200,
    )
    assert homepage is not None

    result = await _enrich_0ff_calendar_history(
        page,
        RunContext(
            "test", {"url": "https://pt.0ff.cc/attendance.php"}, {"sid": "secret"},
        ),
        homepage,
        60_000,
    )

    assert result.outcome == RunOutcome.ALREADY_DONE
    assert result.details["url"] == "https://pt.0ff.cc/attendance.php"
    assert result.details["site_history"] == [{"date": "2026-08-16", "reward": "15"}]
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
        "https://pttime.org/attendance.php", 403, "拒绝访问：已签到，无需再签"
    ) == RunOutcome.ALREADY_DONE
    assert classify_pt_page(
        "https://pttime.org/attendance.php", 403, "Forbidden"
    ) == RunOutcome.AUTH_EXPIRED
    assert classify_pt_page(
        "https://ptchdbits.co/bakatest.php", 200, "今天已经签过到了(已连续29天签到)"
    ) == RunOutcome.ALREADY_DONE
    assert classify_pt_page(
        "https://hdarea.club/", 200, "魔力值 [使用] [已签到] (32)"
    ) == RunOutcome.ALREADY_DONE
    assert classify_pt_page(
        "https://hdcity.city/", 200, "assignment_turned_in Checked in"
    ) == RunOutcome.ALREADY_DONE
    assert classify_pt_page(
        "https://discfan.net/attendance.php", 200,
        "簽到成功，本次簽到獲得 300 個魔力值",
    ) == RunOutcome.SUCCESS
    interrupted = (
        "已断签2天，当前可补签天数为113天，请点击选择补签弥补连续天数，"
        "或放弃补签重新开始签到。首次签到或重新开始签到可获得100个魔力值"
    )
    assert classify_pt_page(
        "https://tjupt.org/attendance.php", 200, interrupted
    ) == RunOutcome.FAILED
    assert classify_pt_page(
        "https://www.hdkyl.in/attendance.php",
        468,
        "安全检测能力由 雷池 WAF 驱动，客户端异常，请确认您是合法用户",
    ) == RunOutcome.BLOCKED
    assert classify_pt_page(
        "https://audiences.me/attendance.php",
        200,
        "人机验证 验证通过后将自动完成签到",
    ) == RunOutcome.BLOCKED
    assert classify_pt_page(
        "https://www.hddolby.com/take2fa.php",
        200,
        "异地登录提醒！两步验证码 完成两步验证登录后才计算为成功登录。",
    ) == RunOutcome.AUTH_EXPIRED


@pytest.mark.asyncio
async def test_0ff_slider_completion_drags_the_fixed_track():
    class Locator:
        def __init__(self, page, selector):
            self.page = page
            self.selector = selector

        async def is_visible(self):
            return self.page.challenge_visible

        async def bounding_box(self):
            if self.selector == "#dragHandler":
                return {"x": 100, "y": 50, "width": 40, "height": 30}
            return {"x": 100, "y": 50, "width": 304, "height": 30}

    class Mouse:
        def __init__(self, page):
            self.page = page
            self.events = []

        async def move(self, x, y, **kwargs):
            self.events.append(("move", x, y, kwargs))

        async def down(self):
            self.events.append(("down",))

        async def up(self):
            self.events.append(("up",))
            self.page.challenge_visible = False

    class Page:
        def __init__(self):
            self.challenge_visible = True
            self.mouse = Mouse(self)
            self.loaded = False

        def locator(self, selector):
            assert selector in {"#dragHandler", "#dragContainer"}
            return Locator(self, selector)

        async def wait_for_timeout(self, timeout):
            assert timeout == 250

        async def wait_for_load_state(self, state, **kwargs):
            assert state == "domcontentloaded"
            assert kwargs == {"timeout": 10_000}
            self.loaded = True

    page = Page()

    assert await _complete_0ff_slider(page) is True
    assert page.mouse.events == [
        ("move", 120, 65, {}),
        ("down",),
        ("move", 382, 65, {"steps": 32}),
        ("up",),
    ]
    assert page.loaded is True


@pytest.mark.asyncio
async def test_0ff_slider_failure_is_reported_as_blocked(tmp_path):
    class Locator:
        async def is_visible(self):
            return True

        async def bounding_box(self):
            return None

    class Page:
        url = "https://pt.0ff.cc/attendance.php"

        def __init__(self):
            self.screenshot_path = None

        def locator(self, selector):
            assert selector in {"#dragHandler", "#dragContainer"}
            return Locator()

        async def screenshot(self, **kwargs):
            self.screenshot_path = kwargs["path"]

    page = Page()
    screenshot = tmp_path / "0ff-slider.png"
    result = await _resolve_0ff_slider(
        page, "https://pt.0ff.cc/attendance.php", 200, screenshot,
    )

    assert result is not None
    assert result.outcome == RunOutcome.BLOCKED
    assert result.message == "拖动滑块验证未通过"
    assert result.details["screenshot"] == str(screenshot)
    assert page.screenshot_path == str(screenshot)


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


@pytest.mark.asyncio
async def test_profile_refresh_navigates_away_from_blocked_signin_page():
    class Body:
        def __init__(self, page):
            self.page = page

        async def inner_text(self):
            return self.page.body

    class Response:
        status = 200

    class Page:
        url = "https://tracker.test/attendance.php"
        body = "Just a moment... Cloudflare"
        visited = []

        def locator(self, selector):
            assert selector == "body"
            return Body(self)

        async def goto(self, url, **kwargs):
            assert kwargs == {"wait_until": "domcontentloaded", "timeout": 60_000}
            self.visited.append(url)
            self.url = url
            self.body = "用户详情 - mapleren 上传量: 1 TiB"
            return Response()

        async def evaluate(self, _script):
            return {
                "pairs": [["上传量", "1 TiB"]],
                "body": self.body,
                "title": "用户详情 - mapleren",
            }

    page = Page()
    result = await refresh_pt_profile_page(
        page,
        RunContext(
            "test",
            {
                "url": "https://tracker.test/attendance.php",
                "profile_url": "/userdetails.php?id=7",
            },
            {"sid": "secret"},
        ),
        "https://tracker.test/attendance.php",
        "tracker.test",
        60_000,
    )

    assert result.outcome == RunOutcome.SUCCESS
    assert page.visited == ["https://tracker.test/userdetails.php?id=7"]
    assert result.details["profile_stats"]["uploaded"] == "1 TiB"


@pytest.mark.asyncio
async def test_handler_keeps_profile_refresh_after_signin_navigation_error(monkeypatch, tmp_path):
    from playwright.async_api import Error as PlaywrightError

    class Body:
        def __init__(self, page):
            self.page = page

        async def inner_text(self):
            return self.page.body

    class Response:
        status = 200

    class Page:
        url = "about:blank"
        body = ""
        visited = []

        def set_default_timeout(self, _timeout):
            return None

        def locator(self, selector):
            assert selector == "body"
            return Body(self)

        async def goto(self, url, **_kwargs):
            self.visited.append(url)
            self.url = url
            self.body = "用户详情 - mapleren 上传量: 1 TiB"
            return Response()

        async def evaluate(self, _script):
            return {
                "pairs": [["上传量", "1 TiB"]],
                "body": self.body,
                "title": "用户详情 - mapleren",
            }

        async def screenshot(self, **_kwargs):
            return None

    page = Page()

    class BrowserContext:
        pages = [page]

    class BrowserSession:
        context = BrowserContext()
        mode = "persistent_headless"
        profile_key = "shared"

    class SessionManager:
        async def __aenter__(self):
            return BrowserSession()

        async def __aexit__(self, *_args):
            return None

    class PlaywrightManager:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *_args):
            return None

    async def fail_home_navigation(*_args, **_kwargs):
        raise PlaywrightError("Page.goto: net::ERR_HTTP_RESPONSE_CODE_FAILURE")

    monkeypatch.setenv("AUTOSURF_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        "playwright.async_api.async_playwright", lambda: PlaywrightManager(),
    )
    monkeypatch.setattr(
        "autosurf.automations.pt_signin.persistent_chromium_session",
        lambda *_args, **_kwargs: SessionManager(),
    )
    monkeypatch.setattr(
        "autosurf.automations.pt_signin._goto_pt_page", fail_home_navigation,
    )

    result = await PtSignInHandler().run(RunContext(
        "navigation-error",
        {
            "url": "https://u2.dmhy.org/attendance.php",
            "credential_domain": "u2.dmhy.org",
            "profile_url": "/userdetails.php?id=7",
            "sign_in_enabled": True,
            "profile_refresh_enabled": True,
            "profile_refresh_supported": True,
        },
        {"c_secure_uid": "7"},
    ))

    assert result.outcome == RunOutcome.FAILED
    assert result.details["actions"]["sign_in"]["outcome"] == RunOutcome.FAILED
    assert result.details["actions"]["profile_refresh"]["outcome"] == RunOutcome.SUCCESS
    assert page.visited == ["https://u2.dmhy.org/userdetails.php?id=7"]


@pytest.mark.asyncio
async def test_hhanclub_calendar_history_uses_claimed_days_and_rewards():
    class Body:
        async def inner_text(self):
            return ""

    class Page:
        def locator(self, selector):
            assert selector == "body"
            return Body()

        async def evaluate(self, script):
            assert "#day-register .calender-sub" in script
            assert "last-month-day" in script
            assert "claimed !== '已领取'" in script
            assert ".bonus-info p" in script
            return [
                {"date": "2026-07-31", "reward": "80"},
                {"date": "2026-08-01", "reward": "85"},
                {"date": "2026-08-16", "reward": "20"},
            ]

    assert await extract_site_signin_history(Page()) == [
        {"date": "2026-07-31", "reward": "80"},
        {"date": "2026-08-01", "reward": "85"},
        {"date": "2026-08-16", "reward": "20"},
    ]


@pytest.mark.asyncio
async def test_fullcalendar_history_keeps_reward_over_empty_background_event():
    class Body:
        async def inner_text(self):
            return ""

    class Page:
        def locator(self, selector):
            assert selector == "body"
            return Body()

        async def evaluate(self, script):
            assert "const current = entries.get(value)" in script
            assert "if (!text) return" in script
            return [
                {"date": "2026-08-15", "reward": "300"},
                {"date": "2026-08-16", "reward": "300"},
            ]

    assert await extract_site_signin_history(Page()) == [
        {"date": "2026-08-15", "reward": "300"},
        {"date": "2026-08-16", "reward": "300"},
    ]


@pytest.mark.asyncio
async def test_0ff_dynamic_fullcalendar_waits_for_events_and_reads_day_cells():
    class Body:
        async def inner_text(self):
            return ""

    class Event:
        def __init__(self, page):
            self.page = page
            self.first = self

        async def wait_for(self, **kwargs):
            assert kwargs == {"state": "attached", "timeout": 3_000}
            self.page.waited = True

    class Page:
        def __init__(self):
            self.waited = False

        def locator(self, selector):
            if selector == "body":
                return Body()
            assert ".fc-daygrid-event" in selector
            assert "[data-event-id]" in selector
            return Event(self)

        async def evaluate(self, script):
            assert "day.element.querySelectorAll(eventSelector)" in script
            assert "root.querySelectorAll(eventSelector)" in script
            return [
                {"date": "2026-08-15", "reward": "10"},
                {"date": "2026-08-16", "reward": "15"},
            ]

    page = Page()
    assert await extract_site_signin_history(page) == [
        {"date": "2026-08-15", "reward": "10"},
        {"date": "2026-08-16", "reward": "15"},
    ]
    assert page.waited is True


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
    assert sanitize_pt_profile_stats({
        "ratio": "31094.626704335456",
    }) == {"ratio": "31094.627"}
    assert sanitize_pt_profile_stats({
        "ratio": "0.0004",
    }) == {"ratio": "0.0004"}
    assert normalize_pt_profile_stats({
        "pairs": [],
        "body": "",
        "title": "HDVIDEO :: 用户详情 - mapleren - Powered by NexusPHP",
        "profile_username": "上传量: 512.34 GB",
    }) == {"username": "mapleren"}
    assert sanitize_pt_profile_stats({"username": "下载量: 32.38 GB"}) == {}


def test_pt_profile_stats_prefers_structured_cards_and_rejects_navigation_level():
    audiences = normalize_pt_profile_stats({
        "pairs": [
            ["上传量", "10.632 TB"],
            ["下载量", "212.59 GB"],
            ["分享率", "51.213"],
            ["上传量", "212.59 GB"],
            ["下载量", "212.59 GB"],
            ["分享率", "452829.8"],
        ],
        "body": "",
        "title": "",
    })
    assert audiences == {
        "uploaded": "10.632 TB",
        "downloaded": "212.59 GB",
        "ratio": "51.213",
    }

    tjupt = normalize_pt_profile_stats({
        "pairs": [["等级", "等级详情/提升等级"], ["上传量", "5.161 TiB"]],
        "body": "等级: [威震一方]\n活动种子: 0\n魔力值: 723,516.4",
        "title": "",
    })
    assert tjupt == {
        "user_level": "威震一方",
        "uploaded": "5.161 TiB",
        "bonus": "723,516.4",
        "seeding_count": "0",
    }

    zhuque = normalize_pt_profile_stats({
        "pairs": [["用户名", "mapleren"], ["做种体积", "0.00 Byte"], ["当前做种", "0"]],
        "body": "",
        "title": "",
    })
    assert zhuque == {
        "username": "mapleren",
        "seeding_count": "0",
        "seeding_size": "0.00 B",
    }


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
    first_finished_at = utc_now() - timedelta(minutes=1)
    with app.state.sessions.begin() as session:
        record = session.get(ExecutionRecord, execution.id)
        record.status = "succeeded"
        record.finished_at = first_finished_at
        record.result_json = json.dumps({
            "outcome": "success",
            "message": "done",
            "details": {"actions": {"profile_refresh": {"details": {
                "profile_stats": {"username": "mapleren", "uploaded": "32.77 TiB"},
            }}}},
        })
    latest = app.state.queue.enqueue_now(automation.id)
    latest_finished_at = utc_now()
    with app.state.sessions.begin() as session:
        record = session.get(ExecutionRecord, latest.id)
        record.status = "failed"
        record.finished_at = latest_finished_at
        record.result_json = json.dumps({
            "outcome": "auth_expired",
            "message": "expired",
            "details": {"actions": {"profile_refresh": {
                "enabled": True,
                "outcome": "auth_expired",
                "message": "个人信息页要求重新登录",
                "details": {"status_code": 401},
            }}},
        })

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/v1/pt-signin/stats", auth=(settings.username, settings.password)
        )
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["stats"] == {
        "username": "mapleren", "uploaded": "32.77 TiB",
    }
    assert item["refresh_outcome"] == "auth_expired"
    assert item["refresh_message"] == "个人信息页要求重新登录"
    assert item["updated_at"].startswith(first_finished_at.isoformat(timespec="seconds"))
    assert item["refresh_updated_at"].startswith(
        latest_finished_at.isoformat(timespec="seconds")
    )


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
        "https://sunnypt.top/auth/sign-in", 200, ""
    ) == RunOutcome.AUTH_EXPIRED
    skipped_refresh = profile_refresh_skip_result(
        RunResult(RunOutcome.AUTH_EXPIRED, "登录已失效"),
        "https://sunnypt.top/auth/sign-in",
    )
    assert skipped_refresh is not None
    assert skipped_refresh.outcome == RunOutcome.AUTH_EXPIRED
    assert skipped_refresh.message == "登录已失效，未刷新个人信息"
    blocked_refresh = profile_refresh_skip_result(
        RunResult(RunOutcome.BLOCKED, "拖动滑块验证未通过"),
        "https://pt.0ff.cc/attendance.php",
    )
    assert blocked_refresh is None
    assert classify_pt_page(
        "https://tracker.test/attendance.php", 200, "获得 [10]", {"success_patterns": ["获得 [10]"]}
    ) == RunOutcome.SUCCESS


@pytest.mark.asyncio
async def test_pttime_opens_signin_endpoint_instead_of_history_link():
    class Page:
        async def goto(self, url, **kwargs):
            assert url == "https://www.pttime.org/attendance.php"
            assert kwargs == {"wait_until": "domcontentloaded", "timeout": 60_000}
            return "direct-response"

        def locator(self, _selector):
            raise AssertionError("PTTime homepage history link must not be clicked")

    response = await _open_pt_signin_page(
        Page(), "https://www.pttime.org/attendance.php", 60_000,
    )

    assert response == "direct-response"


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


def test_text_signin_history_supports_plain_record_table_rows():
    text = """
    签到记录
    签到时间 签到人 连续天数
    2026-08-20 20:19:09 mapleren 0
    2026-07-25 14:46:55 mapleren 0
    """

    assert extract_text_signin_history(text) == [
        {"date": "2026-07-25", "reward": ""},
        {"date": "2026-08-20", "reward": ""},
    ]


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


def test_pt_signin_urls_keep_homepage_as_the_first_navigation():
    assert pt_home_url(
        "https://pterclub.net/attendance.php"
    ) == "https://pterclub.net/"
    assert pt_home_url(
        "https://club.hares.top/attendance.php?action=sign"
    ) == "https://club.hares.top/"
    assert pt_home_url("https://haidan.cc/") == "https://haidan.cc/"


def test_52pt_discovery_and_adapter_use_the_current_signin_page():
    discovery = discover_pt_site("52pt.site", {"sid"})
    adapter = FiftyTwoPtAdapter()

    assert discovery is not None
    assert discovery.url == "https://52pt.site/52bakatest0818.php"
    assert adapter.matches(discovery.url) is True
    assert adapter.matches("https://www.52pt.site/52bakatest0818.php") is True
    assert adapter.matches("https://not52pt.site/52bakatest0818.php") is False


class MTeamPage:
    url = "https://kp.m-team.cc/"

    def __init__(self, responses):
        self.responses = responses
        self.paths = []

    async def evaluate(self, script, data):
        assert "authorization: auth" in script
        assert data["signatureKey"]
        self.paths.append(data["path"])
        return self.responses[data["path"]]


@pytest.mark.asyncio
async def test_mteam_adapter_refreshes_profile_without_daily_hello():
    page = MTeamPage({
        "/member/profile": {
            "status": 200,
            "code": 0,
            "message": "SUCCESS",
            "authenticated": True,
            "profile": {
                "username": "mapleren",
                "user_level": "POWER USER",
                "uploaded": 2 * 1024 ** 4,
                "downloaded": 512 * 1024 ** 3,
                "ratio": "",
                "bonus": "3193396.1",
            },
        },
    })
    adapter = MTeamAdapter()

    result = await adapter.refresh_profile(page, RunContext(
        "test", {"url": page.url},
        {"auth": "secret-auth", "did": "device", "visitorId": "visitor"}, [],
    ))

    assert adapter.matches(page.url) is True
    assert adapter.matches("https://not-m-team.cc/") is False
    assert result.outcome == RunOutcome.SUCCESS
    assert result.message == "M-Team 个人信息刷新成功"
    assert result.details["profile_stats"] == {
        "username": "mapleren",
        "user_level": "POWER USER",
        "uploaded": "2 TiB",
        "downloaded": "512 GiB",
        "ratio": "4",
        "bonus": "3193396.1",
    }
    assert page.paths == ["/member/profile"]


@pytest.mark.asyncio
async def test_mteam_adapter_requires_synced_web_credential():
    page = MTeamPage({})

    result = await MTeamAdapter().refresh_profile(
        page, RunContext("test", {"url": page.url}, {}, []),
    )

    assert result.outcome == RunOutcome.AUTH_EXPIRED
    assert result.message == "M-Team Web 凭据尚未同步"
    assert page.paths == []


@pytest.mark.asyncio
@pytest.mark.parametrize(("code", "message"), [
    (401, "請重新登入"),
    (1, "無效的請求"),
])
async def test_mteam_adapter_reports_expired_web_credential(code, message):
    page = MTeamPage({
        "/member/profile": {
            "status": 200, "code": code, "message": message, "authenticated": False,
        },
    })

    result = await MTeamAdapter().refresh_profile(
        page, RunContext("test", {"url": page.url}, {"auth": "expired-auth"}, []),
    )

    assert result.outcome == RunOutcome.AUTH_EXPIRED
    assert result.message == "M-Team Web 凭据已失效"
    assert page.paths == ["/member/profile"]


@pytest.mark.asyncio
async def test_mteam_adapter_does_not_treat_signature_failure_as_success():
    page = MTeamPage({
        "/member/profile": {
            "status": 200, "code": 1, "message": "簽名錯誤", "authenticated": False,
        },
    })

    result = await MTeamAdapter().refresh_profile(
        page, RunContext("test", {"url": page.url}, {"auth": "secret-auth"}, []),
    )

    assert result.outcome == RunOutcome.FAILED
    assert result.message == "M-Team 个人信息刷新失败"
    assert result.details["code"] == 1
    assert page.paths == ["/member/profile"]


@pytest.mark.asyncio
async def test_sunnypt_adapter_uses_current_api_and_returns_monthly_history(monkeypatch):
    calls = []

    async def sunny_api(_page, method, path):
        calls.append((method, path))
        if path == "/api/v1/attendance/status":
            return {
                "status": 200, "authenticated": True,
                "body": {"code": 0, "data": {"checked_in": False}},
            }
        if path == "/api/v1/attendance/check-in":
            return {
                "status": 200, "authenticated": True,
                "body": {"code": 0, "data": {"days": 1, "points": 10}},
            }
        assert path.startswith("/api/v1/attendance/monthly?")
        return {
            "status": 200, "authenticated": True,
            "body": {"code": 0, "data": {"records": [
                {"date": "2026-08-05", "points": 10},
                {"date": "2026-08-08", "points": 10},
            ]}},
        }

    monkeypatch.setattr("autosurf.automations.pt_signin._sunnypt_api", sunny_api)

    class Page:
        url = "https://sunnypt.top/user/attendance"

    page = Page()
    adapter = SunnyPtAdapter()
    result = await adapter.sign_in(
        page, RunContext("test", {"url": page.url}, {"c_secure_uid": "7"}, []),
    )

    assert adapter.matches(page.url) is True
    assert adapter.matches("https://not-sunnypt.top/") is False
    assert result.outcome == RunOutcome.SUCCESS
    assert result.message == "SunnyPT 签到成功"
    assert result.details["clicked"] is True
    assert result.details["site_history"] == [
        {"date": "2026-08-05", "reward": "10"},
        {"date": "2026-08-08", "reward": "10"},
    ]
    assert calls[:2] == [
        ("GET", "/api/v1/attendance/status"),
        ("POST", "/api/v1/attendance/check-in"),
    ]


@pytest.mark.asyncio
async def test_sunnypt_status_api_reports_expired_session(monkeypatch):
    async def sunny_api(_page, _method, _path):
        return {"status": 401, "authenticated": True, "body": None}

    monkeypatch.setattr("autosurf.automations.pt_signin._sunnypt_api", sunny_api)

    class Page:
        url = "https://sunnypt.top/user/attendance"

    result = await SunnyPtAdapter().sign_in(
        Page(), RunContext("test", {"url": Page.url}, {"sid": "expired"}, []),
    )

    assert result.outcome == RunOutcome.AUTH_EXPIRED
    assert result.message == "SunnyPT 登录状态已失效"
    assert result.details["status_code"] == 401
    assert result.details["clicked"] is False


@pytest.mark.asyncio
async def test_sunnypt_does_not_submit_when_status_payload_is_invalid(monkeypatch):
    calls = []

    async def sunny_api(_page, method, path):
        calls.append((method, path))
        return {
            "status": 200, "authenticated": True,
            "body": {"code": 0, "data": {}},
        }

    monkeypatch.setattr("autosurf.automations.pt_signin._sunnypt_api", sunny_api)

    class Page:
        url = "https://sunnypt.top/user/attendance"

    result = await SunnyPtAdapter().sign_in(
        Page(), RunContext("test", {"url": Page.url}, {"sid": "secret"}, []),
    )

    assert result.outcome == RunOutcome.FAILED
    assert result.message == "SunnyPT 签到状态返回无效"
    assert calls == [("GET", "/api/v1/attendance/status")]


@pytest.mark.asyncio
async def test_sunnypt_adapter_refreshes_current_details_api(monkeypatch):
    async def sunny_api(_page, method, path):
        assert (method, path) == ("GET", "/api/v1/user/details/info")
        return {
            "status": 200,
            "authenticated": True,
            "body": {"code": 0, "data": {
                "id": 7,
                "username": "mapleren",
                "title": "Power User",
                "uploaded": "5676238811136",
                "downloaded": "228267147264",
                "ratio": 24.866,
                "seed_bonus": 520,
                "upload_num": 12,
            }},
        }

    monkeypatch.setattr("autosurf.automations.pt_signin._sunnypt_api", sunny_api)

    class Page:
        url = "https://sunnypt.top/user/attendance"

    result = await SunnyPtAdapter().refresh_profile(
        Page(), RunContext("test", {"url": Page.url}, {"sid": "secret"}, []),
    )

    assert result.outcome == RunOutcome.SUCCESS
    assert result.details["profile_stats"] == {
        "username": "mapleren",
        "user_level": "Power User",
        "uploaded": "5.16 TiB",
        "downloaded": "212.59 GiB",
        "ratio": "24.866",
        "bonus": "520",
        "seeding_count": "12",
    }


@pytest.mark.asyncio
async def test_zhuque_adapter_refreshes_profile_from_site_api():
    class Request:
        method = "GET"

    class Response:
        url = "https://zhuque.in/api/user/getInfo"
        status = 200
        request = Request()

        async def json(self):
            return {"data": {
                "id": 7,
                "username": "mapleren",
                "class": {"name": "烧包"},
                "upload": 5 * 1024 ** 4,
                "download": 200 * 1024 ** 3,
                "bonus": 723516.4,
                "seeding": 0,
                "seedSize": 0,
            }}

    class Pending:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        @property
        def value(self):
            async def resolve():
                return Response()
            return resolve()

    class Page:
        url = "https://zhuque.in/"

        def expect_response(self, predicate, **kwargs):
            assert predicate(Response()) is True
            assert kwargs == {"timeout": 30_000}
            return Pending()

        async def goto(self, url, **_kwargs):
            assert url == "https://zhuque.in/user/info"
            self.url = url

    result = await ZhuqueAdapter().refresh_profile(
        Page(), RunContext("test", {"url": Page.url}, {"sid": "secret"}, []),
    )

    assert result.outcome == RunOutcome.SUCCESS
    assert result.details["profile_stats"] == {
        "username": "mapleren",
        "user_level": "烧包",
        "uploaded": "5 TiB",
        "downloaded": "200 GiB",
        "ratio": "25.6",
        "bonus": "723516.4",
        "seeding_count": "0",
        "seeding_size": "0 B",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter", [SunnyPtAdapter(), ZhuqueAdapter()])
async def test_site_profile_api_reports_expired_login(adapter):
    class Request:
        method = "GET"

    class Response:
        url = "https://tracker.test/api/user/getInfo"
        status = 401
        request = Request()

        async def json(self):
            return {"status": "unauthorized"}

    class Pending:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        @property
        def value(self):
            async def resolve():
                return Response()
            return resolve()

    class Page:
        url = "https://tracker.test/"

        async def evaluate(self, _script, *_args):
            return {"status": 401, "authenticated": False, "profile": None}

        def expect_response(self, predicate, **kwargs):
            assert predicate(Response()) is True
            assert kwargs == {"timeout": 30_000}
            return Pending()

        async def goto(self, url, **_kwargs):
            self.url = url

    result = await adapter.refresh_profile(
        Page(), RunContext("test", {"url": Page.url}, {"sid": "expired"}, []),
    )

    assert result.outcome == RunOutcome.AUTH_EXPIRED


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
async def test_52pt_missing_home_entry_after_paused_page_is_already_done():
    class Locator:
        first = None

        def __init__(self, page, selector):
            self.page = page
            self.selector = selector
            self.first = self

        async def inner_text(self):
            return "签到页面已暂停使用" if self.page.url.endswith("52bakatest0818.php") else "欢迎回来"

        async def count(self):
            return 0

        async def is_visible(self):
            return False

    class Page:
        url = "https://52pt.site/52bakatest0818.php"
        frames = None

        def locator(self, selector):
            return Locator(self, selector)

        async def goto(self, url, **_kwargs):
            self.url = url

        async def evaluate(self, _script):
            return "https://52pt.site/userdetails.php?id=7"

    page = Page()
    result = await FiftyTwoPtAdapter().sign_in(page, RunContext(
        "test", {"url": page.url}, {"sid": "secret"},
    ))

    assert result.outcome == RunOutcome.ALREADY_DONE


@pytest.mark.asyncio
async def test_profile_refresh_reports_login_redirect_as_auth_expired():
    class Locator:
        def __init__(self, selector):
            self.selector = selector

        async def inner_text(self):
            return "请登录 用户名 密码"

        async def count(self):
            return 0

    class Page:
        url = "https://www.haidan.cc/login.php"
        frames = None

        def locator(self, selector):
            return Locator(selector)

        async def evaluate(self, _script):
            return ""

    result = await refresh_pt_profile_page(
        Page(),
        RunContext("test", {"url": "https://haidan.cc/"}, {"sid": "secret"}),
        "https://haidan.cc/",
        "haidan.cc",
        30_000,
    )

    assert result.outcome == RunOutcome.AUTH_EXPIRED


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


@pytest.mark.asyncio
async def test_opencd_adapter_routes_captcha_page_to_local_ocr(monkeypatch):
    captured = {}

    async def submit(page, context, site_name, response_suffix=None):
        captured.update({
            "page": page,
            "context": context,
            "site_name": site_name,
            "response_suffix": response_suffix,
        })
        return RunResult(
            RunOutcome.SUCCESS,
            "PT 站签到成功",
            {"url": "https://open.cd/plugin_sign-in.php", "clicked": True},
        )

    monkeypatch.setattr(
        "autosurf.automations.pt_signin._submit_nexusphp_captcha", submit,
    )

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

        async def wait_for_load_state(self, *_args, **_kwargs):
            return None

    page = Page()
    context = RunContext("test", {"url": page.url}, {"sid": "secret"})
    result = await OpenCdAdapter().sign_in(page, context)

    assert result.outcome == RunOutcome.SUCCESS
    assert captured == {
        "page": page,
        "context": context,
        "site_name": "OpenCD",
        "response_suffix": "/plugin_sign-in.php",
    }


@pytest.mark.asyncio
async def test_opencd_adapter_uses_today_record_when_home_entry_disappears():
    today = datetime.now().date().isoformat()

    class Locator:
        first = None

        def __init__(self, page, kind):
            self.page = page
            self.kind = kind
            self.first = self

        def filter(self, *, has_text):
            return Locator(
                self.page,
                "history" if "記记" in has_text.pattern else "signin",
            )

        async def inner_text(self):
            return self.page.body

        async def is_visible(self):
            return self.kind == "history"

        async def get_attribute(self, name):
            assert name == "href"
            return "/attendance.php?type=record"

    class Response:
        status = 200

    class Page:
        url = "https://open.cd/"
        body = "OpenCD 欢迎回来 查看签到记录"
        waits = 0

        def locator(self, selector):
            return Locator(self, "body" if selector == "body" else "links")

        async def goto(self, url, **kwargs):
            assert url == "https://open.cd/attendance.php?type=record"
            assert kwargs == {"wait_until": "domcontentloaded"}
            self.url = url
            self.body = "签到记录 签到时间 签到人 连续天数"
            return Response()

        async def wait_for_timeout(self, timeout):
            assert timeout == 500
            self.waits += 1
            self.body = f"签到记录 签到时间 签到人 连续天数\n{today} 20:19:09 mapleren 0"

    page = Page()
    result = await OpenCdAdapter().sign_in(page, RunContext(
        "test", {"url": page.url}, {"sid": "secret"},
    ))

    assert result.outcome == RunOutcome.ALREADY_DONE
    assert result.details["site_history"] == [{"date": today, "reward": ""}]
    assert page.waits == 1


@pytest.mark.asyncio
async def test_nexusphp_captcha_supports_ajax_controls_outside_form(monkeypatch):
    monkeypatch.setattr(
        "autosurf.automations.pt_signin.recognize_nexusphp_captcha",
        lambda _image: "8C32MN",
    )

    class Element:
        first = None

        def __init__(self, page, kind):
            self.page = page
            self.kind = kind
            self.first = self

        def locator(self, selector):
            if self.kind == "answer":
                if selector == "xpath=preceding::*[self::img or self::canvas][1]":
                    return Element(self.page, "captcha")
                if selector.startswith("xpath=following::"):
                    return Element(self.page, "submit")
            return Element(self.page, "missing")

        async def is_visible(self):
            return self.kind != "missing"

        async def bounding_box(self):
            return {
                "captcha": {"x": 100, "y": 50, "width": 150, "height": 40},
                "answer": {"x": 100, "y": 95, "width": 80, "height": 22},
                "submit": {"x": 190, "y": 95, "width": 44, "height": 22},
            }.get(self.kind)

        async def wait_for(self, **_kwargs):
            return None

        async def screenshot(self, **_kwargs):
            return b"captcha-image"

        async def fill(self, value):
            self.page.answer = value

        async def click(self):
            self.page.submitted = True

        async def inner_text(self):
            return "签到成功，本次签到获得 10 魔力值" if self.page.submitted else "首页"

    class Response:
        url = "https://open.cd/plugin_sign-in.php"
        status = 200

        async def text(self):
            return "签到成功，本次签到获得 10 魔力值"

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
        frames = None

        def __init__(self):
            self.url = "https://open.cd/"
            self.answer = None
            self.submitted = False

        def locator(self, selector):
            if selector.startswith("form:"):
                return Element(self, "missing")
            if selector == "body":
                return Element(self, "body")
            if 'input[name="imagestring"]' in selector:
                return Element(self, "answer")
            return Element(self, "missing")

        def expect_response(self, predicate, **kwargs):
            assert predicate(Response()) is True
            assert kwargs == {"timeout": 30_000}
            return ResponseContext()

        async def wait_for_timeout(self, _milliseconds):
            return None

    page = Page()
    result = await _submit_nexusphp_captcha(
        page,
        RunContext("test", {"url": page.url}, {"sid": "secret"}),
        "OpenCD",
        response_suffix="/plugin_sign-in.php",
    )

    assert result is not None
    assert result.outcome == RunOutcome.SUCCESS
    assert result.details["clicked"] is True
    assert page.answer == "8C32MN"
    assert "8C32MN" not in json.dumps(result.details)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("adapter", "url"),
    [
        (OshenPtAdapter(), "https://www.oshen.win/attendance.php"),
        (SoulVoiceAdapter(), "https://pt.soulvoice.club/attendance.php"),
    ],
)
async def test_nexusphp_captcha_adapter_recognizes_and_confirms_success(
    monkeypatch, adapter, url,
):
    monkeypatch.setattr(
        "autosurf.automations.pt_signin.recognize_nexusphp_captcha",
        lambda _image: "MEP5MP",
    )

    class Locator:
        first = None

        def __init__(self, page, kind):
            self.page = page
            self.kind = kind
            self.first = self

        def locator(self, selector):
            if "img" in selector:
                return Locator(self.page, "captcha")
            if "imagestring" in selector:
                return Locator(self.page, "answer")
            return Locator(self.page, "submit")

        async def inner_text(self):
            return "签到成功，本次签到获得 10 魔力值" if self.page.submitted else "签到"

        async def is_visible(self):
            return self.kind != "captcha" or self.page.captcha_ready

        async def wait_for(self, *, state, timeout):
            assert self.kind == "captcha"
            assert state == "visible"
            assert timeout == 5_000
            self.page.captcha_ready = True

        async def screenshot(self, **_kwargs):
            return b"captcha-image"

        async def fill(self, value):
            self.page.answer = value

        async def click(self):
            self.page.submitted = True

    class Response:
        status = 200

    class Navigation:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        @property
        def value(self):
            async def resolve():
                return Response()
            return resolve()

    class Page:
        frames = None

        def __init__(self):
            self.url = url
            self.answer = None
            self.captcha_ready = False
            self.submitted = False

        def locator(self, selector):
            return Locator(self, "body" if selector == "body" else "form")

        def expect_navigation(self, **_kwargs):
            return Navigation()

    page = Page()
    result = await adapter.sign_in(
        page, RunContext("test", {"url": page.url}, {"sid": "secret"}, []),
    )

    assert result.outcome == RunOutcome.SUCCESS
    assert result.message == "PT 站签到成功"
    assert result.details["clicked"] is True
    assert page.answer == "MEP5MP"
    assert page.captcha_ready is True
    assert "MEP5MP" not in json.dumps(result.details)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("adapter", "url", "expected_message"),
    [
        (
            OshenPtAdapter(), "https://www.oshen.win/attendance.php",
            "OshenPT 图片验证码未能可靠识别",
        ),
        (
            SoulVoiceAdapter(), "https://pt.soulvoice.club/attendance.php",
            "SoulVoice 图片验证码未能可靠识别",
        ),
    ],
)
async def test_nexusphp_captcha_adapter_does_not_submit_unreliable_value(
    monkeypatch, adapter, url, expected_message,
):
    monkeypatch.setattr(
        "autosurf.automations.pt_signin.recognize_nexusphp_captcha",
        lambda _image: None,
    )

    class Locator:
        first = None

        def __init__(self, kind):
            self.kind = kind
            self.first = self

        def locator(self, selector):
            if "img" in selector:
                return Locator("captcha")
            if "imagestring" in selector:
                return Locator("answer")
            return Locator("submit")

        async def inner_text(self):
            return "签到"

        async def is_visible(self):
            return True

        async def screenshot(self, **_kwargs):
            return b"captcha-image"

        async def click(self):
            raise AssertionError("unreliable captcha must not be submitted")

    class Page:
        frames = None

        def __init__(self):
            self.url = url

        def locator(self, selector):
            return Locator("body" if selector == "body" else "form")

    page = Page()
    result = await adapter.sign_in(
        page, RunContext("test", {"url": page.url}, {"sid": "secret"}, []),
    )

    assert result.outcome == RunOutcome.BLOCKED
    assert result.message == expected_message
    assert result.details["clicked"] is False


@pytest.mark.asyncio
async def test_tjupt_broken_streak_opens_restart_captcha_without_spending_makeup():
    class Locator:
        first = None

        def __init__(self, page, body=False):
            self.page = page
            self.body = body
            self.first = self

        async def inner_text(self):
            if self.page.restarted:
                return "签到验证码 请选择与左侧图片对应的影视名称"
            return "已断签 2 天，请点击选择补签或放弃补签重新开始签到"

        async def is_visible(self):
            return "action=cancel" in self.page.last_selector

        async def click(self):
            self.page.restarted = True
            self.page.url = "https://tjupt.org/attendance.php?action=cancel"

    class Response:
        status = 200

    class Navigation:
        @property
        def value(self):
            async def response():
                return Response()
            return response()

    class NavigationContext:
        async def __aenter__(self):
            return Navigation()

        async def __aexit__(self, *_args):
            return None

    class Page:
        url = "https://tjupt.org/attendance.php"
        restarted = False
        last_selector = ""
        frames = None

        def locator(self, selector):
            self.last_selector = selector
            return Locator(self, body=selector == "body")

        def expect_navigation(self, **_kwargs):
            return NavigationContext()

        async def evaluate(self, _script):
            return []

    page = Page()
    result = await TjuptAdapter().sign_in(page, RunContext(
        "test", {"url": page.url}, {"sid": "secret"},
    ))

    assert result.outcome == RunOutcome.BLOCKED
    assert result.message == "TJUPT 重新签到需要图片验证码"
    assert result.details["clicked"] is True
    assert page.restarted is True
    assert page.url.endswith("action=cancel")


@pytest.mark.asyncio
async def test_tjupt_today_history_does_not_restart_or_open_captcha():
    today = datetime.now().date().isoformat()

    class Locator:
        first = None

        def __init__(self, page):
            self.page = page
            self.first = self

        async def inner_text(self):
            return f"签到记录 签到时间 签到人\n{today} 09:01:02 mapleren"

        async def is_visible(self):
            raise AssertionError("today's record must be checked before restart controls")

    class Page:
        url = "https://tjupt.org/attendance.php"

        def locator(self, _selector):
            return Locator(self)

    result = await TjuptAdapter().sign_in(Page(), RunContext(
        "test", {"url": Page.url}, {"sid": "secret"},
    ))

    assert result.outcome == RunOutcome.ALREADY_DONE
    assert result.details["site_history"] == [{"date": today, "reward": ""}]


@pytest.mark.asyncio
async def test_frame_text_and_profile_discovery_include_child_frames():
    class Body:
        def __init__(self, value):
            self.value = value

        async def inner_text(self):
            return self.value

    class Frame:
        def __init__(self, body, profile=None):
            self.body = body
            self.profile = profile

        def locator(self, _selector):
            return Body(self.body)

        async def evaluate(self, _script):
            return self.profile

    child = Frame("mapleren Checked in", "https://hdcity.city/user.php?id=7")
    page = Frame("home")
    page.frames = [page, child]

    assert await page_body_text(page) == "home\nmapleren Checked in"
    assert await discover_pt_profile_url(page) == "https://hdcity.city/user.php?id=7"


@pytest.mark.asyncio
async def test_generic_signin_rechecks_dynamically_rendered_status(tmp_path):
    class Body:
        def __init__(self, page):
            self.page = page

        async def inner_text(self):
            return "Checked in" if self.page.waited else "Home"

    class MissingControls:
        first = None

        def __init__(self):
            self.first = self

        def filter(self, **_kwargs):
            return self

        async def count(self):
            return 0

    class Page:
        url = "https://hdcity.city/"
        frames = None
        waited = False

        def locator(self, selector):
            return Body(self) if selector == "body" else MissingControls()

        async def wait_for_timeout(self, _milliseconds):
            self.waited = True

        async def wait_for_load_state(self, *_args, **_kwargs):
            return None

        async def evaluate(self, _script):
            return []

    page = Page()
    result = await PtSignInHandler()._generic_sign_in(
        page,
        RunContext("test", {"url": page.url}, {"sid": "secret"}),
        200,
        tmp_path / "failed.png",
    )

    assert result.outcome == RunOutcome.ALREADY_DONE


@pytest.mark.asyncio
async def test_rendered_signin_status_reads_frame_attributes_and_pseudo_content():
    class Frame:
        def __init__(self, value):
            self.value = value

        async def evaluate(self, script):
            assert "已经打卡" in script
            return self.value

    page = Frame("")
    page.frames = [page, Frame("已经打卡")]

    assert await rendered_signin_status_text(page) == "已经打卡"


@pytest.mark.asyncio
async def test_rendered_signin_status_uses_playwright_text_locator_for_shadow_dom():
    class Locator:
        async def count(self):
            return 1

    class Frame:
        frames = None

        def locator(self, selector):
            assert "checked" in selector
            return Locator()

    assert await rendered_signin_status_text(Frame()) == "Checked in"


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
    assert {discovery.site_key for discovery in discoveries} == {"hhanclub.net"}
    assert {discovery.name for discovery in discoveries} == {"HhanClub"}
    assert set(pt_site_domain_aliases("hhanclub.top")) == {
        "hhan.club", "www.hhan.club",
        "hhanclub.net", "www.hhanclub.net",
        "hhanclub.top", "www.hhanclub.top",
    }


def test_haidan_supports_daily_checkin_and_completed_label():
    discovery = discover_pt_site("www.haidan.cc", {"c_secure_uid"})

    assert discovery is not None
    assert discovery.site_key == "haidan.cc"
    assert discovery.url == "https://www.haidan.cc/"
    assert discovery.sign_in_supported is True
    assert discovery.profile_refresh_supported is True
    assert classify_pt_page(
        "https://www.haidan.cc/index.php", 200, "每日打卡 已经打卡", {},
    ) == RunOutcome.ALREADY_DONE


@pytest.mark.parametrize(
    ("current_domain", "old_domain", "name", "target_domain"),
    [
        ("pterclub.net", "pterclub.com", "PterClub", "pterclub.net"),
        ("rousi.pro", "rousi.zip", "Rousi", "rousi.pro"),
        ("haidan.cc", "haidan.video", "Haidan", "www.haidan.cc"),
    ],
)
def test_retired_domains_resolve_to_current_site(
    current_domain, old_domain, name, target_domain,
):
    current = discover_pt_site(current_domain, {"c_secure_uid"})
    old = discover_pt_site(old_domain, {"c_secure_uid"})

    assert current is not None
    assert old is not None
    assert current.site_key == old.site_key == current_domain
    assert current.name == old.name == name
    assert current.url.startswith(f"https://{target_domain}/")
    assert old.url.startswith(f"https://{target_domain}/")
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
    rousi_authenticated = discover_pt_site("rousi.pro", {"token"})
    assert rousi_authenticated is not None
    assert rousi_authenticated.strategy == "web_storage_browser"
    assert rousi_authenticated.sign_in_supported is True
    assert rousi_authenticated.profile_refresh_supported is True
    assert rousi_authenticated.default_profile_refresh_enabled is True
    assert mteam is not None
    assert mteam.name == "M-Team"
    assert mteam.strategy == "custom_required"

    mteam_authenticated = discover_pt_site("kp.m-team.cc", {"auth", "did", "visitorId"})
    assert mteam_authenticated is not None
    assert mteam_authenticated.strategy == "web_storage_profile_refresh_only"
    assert mteam_authenticated.sign_in_supported is False
    assert mteam_authenticated.profile_refresh_supported is True
    assert mteam_authenticated.default_profile_refresh_enabled is True


def test_pt_catalog_uses_confirmed_ttg_and_sunny_routes():
    ttg = discover_pt_site("totheglory.im", {"c_secure_uid"})
    sunny = discover_pt_site("sunnypt.top", {"c_secure_uid"})

    assert ttg is not None
    assert ttg.url == "https://totheglory.im/"
    assert sunny is not None
    assert sunny.name == "SunnyPT"
    assert sunny.url == "https://sunnypt.top/user/attendance"
    assert sunny.profile_url is None


def test_oshen_soulvoice_and_0ff_are_cataloged_with_expected_actions():
    oshen = discover_pt_site("www.oshen.win", {"c_secure_uid"})
    soulvoice = discover_pt_site("pt.soulvoice.club", {"c_secure_uid"})
    zeroff = discover_pt_site("pt.0ff.cc", {"c_secure_uid"})

    assert oshen is not None
    assert oshen.site_key == "oshen.win"
    assert oshen.name == "OshenPT"
    assert oshen.url == "https://www.oshen.win/attendance.php"
    assert soulvoice is not None
    assert soulvoice.site_key == "pt.soulvoice.club"
    assert soulvoice.name == "SoulVoice"
    assert soulvoice.url == "https://pt.soulvoice.club/attendance.php"
    assert zeroff is not None
    assert zeroff.sign_in_supported is True
    assert zeroff.profile_refresh_supported is True
    assert zeroff.default_profile_refresh_enabled is True


@pytest.mark.parametrize(
    "domain", ["www.ptlover.cc", "raingfh.top", "lemonhd.club", "pt.gtk.pw"],
)
@pytest.mark.asyncio
async def test_dead_pt_site_is_excluded_even_with_pt_cookie_markers(settings, domain):
    app = create_app(settings)
    app.state.credentials.upsert(
        f"cookiecloud:test:{domain}", domain, {"c_secure_uid": "7"},
        provider="cookiecloud",
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/v1/pt-signin/candidates?include_unknown=true",
            auth=(settings.username, settings.password),
        )

    assert response.status_code == 200
    assert all(item["credential"]["domain"] != domain for item in response.json()["items"])


@pytest.mark.asyncio
@pytest.mark.parametrize("domain", ["raingfh.top", "lemonhd.club", "pt.gtk.pw"])
async def test_dead_pt_site_existing_task_is_disabled_and_rejected(settings, domain):
    app = create_app(settings)
    credential = app.state.credentials.upsert(
        f"cookiecloud:test:{domain}", domain, {"c_secure_uid": "7"},
        provider="cookiecloud",
    )
    task = app.state.automations.create(
        domain, "pt_signin", 86400, {
            "url": f"https://{domain}/attendance.php",
            "credential_domain": domain,
            "sign_in_enabled": True,
            "profile_refresh_enabled": False,
            "discovered": True,
        }, credential.id,
    )
    execution = app.state.queue.enqueue_now(task.id)

    reconcile_pt_site_aliases(app.state.sessions, app.state.credentials)

    with app.state.sessions() as session:
        stored_task = session.get(AutomationRecord, task.id)
        config = json.loads(stored_task.config_json)
        stored_execution = session.get(ExecutionRecord, execution.id)
        assert stored_task.enabled is False
        assert config["sign_in_enabled"] is False
        assert config["sign_in_supported"] is False
        assert stored_execution.status == "cancelled"
        assert stored_execution.error == "站点已停用"

    result = await PtSignInHandler().run(RunContext(
        "dead-site", {"url": f"https://{domain}/attendance.php"}, {}, [],
    ))
    assert result.outcome == RunOutcome.FAILED
    assert result.message == "PT 站点已停用"


@pytest.mark.parametrize(
    ("error", "message"),
    [
        ("Page.goto: net::ERR_NAME_NOT_RESOLVED", "PT 站域名无法解析"),
        ("Page.goto: net::ERR_CONNECTION_REFUSED", "PT 站拒绝连接"),
        ("Page.goto: net::ERR_HTTP_RESPONSE_CODE_FAILURE", "PT 站返回了浏览器无法处理的 HTTP 响应"),
        ("Page.goto: net::ERR_TIMED_OUT", "PT 站网络连接超时"),
    ],
)
def test_playwright_navigation_errors_are_structured(error, message):
    result = playwright_error_result("https://tracker.example/", RuntimeError(error))

    assert result.outcome == RunOutcome.FAILED
    assert result.message == message
    assert error in result.details["error"]


@pytest.mark.asyncio
async def test_pt_navigation_tolerates_only_usable_same_origin_partial_page():
    from playwright.async_api import TimeoutError as PlaywrightTimeoutError

    class Body:
        def __init__(self, text):
            self.text = text

        async def count(self):
            return 1

        async def inner_text(self):
            return self.text

    class Page:
        def __init__(self, current_url, body):
            self.url = current_url
            self.body = body

        async def goto(self, *_args, **_kwargs):
            raise PlaywrightTimeoutError("DOMContentLoaded timed out")

        def locator(self, selector):
            assert selector == "body"
            return Body(self.body)

    assert await _goto_pt_page(
        Page("https://sunnypt.top/", "SUNNYPT 扬帆启航"),
        "https://sunnypt.top/",
        60_000,
    ) is None
    with pytest.raises(PlaywrightTimeoutError):
        await _goto_pt_page(
            Page("about:blank", ""),
            "https://u2.dmhy.org/",
            60_000,
        )


def test_hdvideo_uses_current_catalog_domain():
    discovery = discover_pt_site("www.hdvideo.top", {"c_secure_uid"})

    assert discovery is not None
    assert discovery.site_key == "hdvideo.top"
    assert discovery.name == "HDVideo"
    assert discovery.url == "https://hdvideo.top/attendance.php"


def test_hdvideo_discovered_task_migrates_to_attendance_page(settings):
    app = create_app(settings)
    credential = app.state.credentials.upsert(
        "cookiecloud:test:hdvideo.top", "hdvideo.top", {"c_secure_uid": "7"},
        provider="cookiecloud",
    )
    task = app.state.automations.create(
        "HDVideo", "pt_signin", 86400, {
            "url": "https://hdvideo.top/",
            "credential_domain": "hdvideo.top",
            "discovered": True,
        }, credential.id,
    )

    reconcile_pt_site_aliases(app.state.sessions, app.state.credentials)

    with app.state.sessions() as session:
        config = json.loads(session.get(AutomationRecord, task.id).config_json)
        assert config["url"] == "https://hdvideo.top/attendance.php"


def test_sunnypt_discovered_task_migrates_current_attendance_route(settings):
    app = create_app(settings)
    credential = app.state.credentials.upsert(
        "cookiecloud:test:sunnypt.top", "sunnypt.top", {"c_secure_uid": "7"},
        provider="cookiecloud",
    )
    task = app.state.automations.create(
        "sunnypt.top", "pt_signin", 86400, {
            "url": "https://sunnypt.top/attendance.php",
            "credential_domain": "sunnypt.top",
            "discovered": True,
        }, credential.id,
    )

    reconcile_pt_site_aliases(app.state.sessions, app.state.credentials)

    with app.state.sessions() as session:
        record = session.get(AutomationRecord, task.id)
        config = json.loads(record.config_json)
        assert record.name == "SunnyPT"
        assert config["url"] == "https://sunnypt.top/user/attendance"
        assert config.get("profile_url") is None
        assert config["discovery_strategy"] == "generic_browser"


def test_pttime_discovered_task_migrates_to_www_cookie_scope(settings):
    app = create_app(settings)
    credential = app.state.credentials.upsert_cookie_records(
        "cookiecloud:test:www.pttime.org", "www.pttime.org", [{
            "name": "c_secure_uid", "value": "7",
            "domain": ".www.pttime.org", "path": "/",
        }], provider="cookiecloud",
    )
    task = app.state.automations.create(
        "PTTime", "pt_signin", 86400, {
            "url": "https://pttime.org/attendance.php",
            "credential_domain": "pttime.org",
            "discovered": True,
            "discovery_reason": "site_catalog",
        }, credential.id,
    )

    reconcile_pt_site_aliases(app.state.sessions, app.state.credentials)

    with app.state.sessions() as session:
        config = json.loads(session.get(AutomationRecord, task.id).config_json)
        assert config["url"] == "https://www.pttime.org/attendance.php"
        assert config["credential_domain"] == "pttime.org"


def test_soulvoice_discovered_task_migrates_to_catalog(settings):
    app = create_app(settings)
    credential = app.state.credentials.upsert(
        "cookiecloud:test:pt.soulvoice.club", "pt.soulvoice.club",
        {"c_secure_uid": "7"}, provider="cookiecloud",
    )
    task = app.state.automations.create(
        "pt.soulvoice.club", "pt_signin", 86400, {
            "url": "https://pt.soulvoice.club/attendance.php",
            "credential_domain": "pt.soulvoice.club",
            "discovered": True,
            "discovery_reason": "cookie_signature",
            "sign_in_enabled": True,
            "profile_refresh_enabled": True,
            "sign_in_supported": True,
            "profile_refresh_supported": True,
        }, credential.id,
    )

    reconcile_pt_site_aliases(app.state.sessions, app.state.credentials)

    with app.state.sessions() as session:
        record = session.get(AutomationRecord, task.id)
        config = json.loads(record.config_json)
        assert record.name == "SoulVoice"
        assert config["url"] == "https://pt.soulvoice.club/attendance.php"
        assert config["discovery_reason"] == "site_catalog"
        assert config["sign_in_enabled"] is True
        assert config["profile_refresh_enabled"] is True


def test_newly_cataloged_0ff_task_enables_profile_refresh_once(settings):
    app = create_app(settings)
    credential = app.state.credentials.upsert(
        "cookiecloud:test:pt.0ff.cc", "pt.0ff.cc", {"c_secure_uid": "7"},
        provider="cookiecloud",
    )
    task = app.state.automations.create(
        "pt.0ff.cc", "pt_signin", 86400, {
            "url": "https://pt.0ff.cc/attendance.php",
            "credential_domain": "pt.0ff.cc",
            "discovered": True,
            "discovery_reason": "cookie_signature",
            "sign_in_enabled": True,
            "profile_refresh_enabled": False,
            "sign_in_supported": True,
            "profile_refresh_supported": True,
        }, credential.id,
    )

    reconcile_pt_site_aliases(app.state.sessions, app.state.credentials)

    with app.state.sessions() as session:
        config = json.loads(session.get(AutomationRecord, task.id).config_json)
        assert config["profile_refresh_enabled"] is True
        assert config["discovery_reason"] == "site_catalog"

    with app.state.sessions.begin() as session:
        record = session.get(AutomationRecord, task.id)
        config = json.loads(record.config_json)
        config["profile_refresh_enabled"] = False
        record.config_json = json.dumps(config)
    reconcile_pt_site_aliases(app.state.sessions, app.state.credentials)
    with app.state.sessions() as session:
        config = json.loads(session.get(AutomationRecord, task.id).config_json)
        assert config["profile_refresh_enabled"] is False


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
    handler = app.state.registry.get("pt_signin")
    assert any(isinstance(adapter, MTeamAdapter) for adapter in handler.adapters)
    assert any(isinstance(adapter, OshenPtAdapter) for adapter in handler.adapters)
    assert any(isinstance(adapter, SoulVoiceAdapter) for adapter in handler.adapters)
    assert any(isinstance(adapter, SunnyPtAdapter) for adapter in handler.adapters)
    assert any(isinstance(adapter, ZhuqueAdapter) for adapter in handler.adapters)
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
        assert site["config"]["daily_start_time"] == "09:00"
        assert datetime.fromisoformat(site["next_run_at"]).hour == 1

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
    assert scheduled.json()["config"]["daily_start_time"] == "09:00"
    assert datetime.fromisoformat(scheduled.json()["next_run_at"]).hour == 1
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
    assert by_id[pttime_www.id]["url"] == "https://www.pttime.org/attendance.php"
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


def test_pt_reconciliation_rebinds_old_task_to_current_domain_credential(settings):
    app = create_app(settings)
    old = app.state.credentials.upsert(
        "cookiecloud:test:www.haidan.video", "www.haidan.video", {"sid": "old"},
        provider="cookiecloud",
    )
    current = app.state.credentials.upsert(
        "cookiecloud:test:www.haidan.cc", "www.haidan.cc",
        {"c_secure_uid": "7", "sid": "current"}, provider="cookiecloud",
    )
    task = app.state.automations.create(
        "Haidan (旧域名)", "pt_signin", 86400, {
            "url": "https://www.haidan.video/attendance.php",
            "credential_domain": "www.haidan.video",
            "sign_in_enabled": True,
            "profile_refresh_enabled": True,
            "discovered": True,
        }, old.id,
    )

    reconcile_pt_site_aliases(app.state.sessions, app.state.credentials)

    with app.state.sessions() as session:
        migrated = session.get(AutomationRecord, task.id)
        config = json.loads(migrated.config_json)
        assert migrated.name == "Haidan"
        assert migrated.credential_id == current.id
        assert migrated.credential.domain == "www.haidan.cc"
        assert config["url"] == "https://www.haidan.cc/"
        assert config["credential_domain"] == "haidan.cc"
        assert config["sign_in_enabled"] is True
        assert config["sign_in_supported"] is True
        assert config["profile_refresh_enabled"] is True


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
                "discovered": True,
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
        assert remaining[0].credential.domain == "hhanclub.net"
        assert {item.automation_id for item in history} == {remaining[0].id}
        assert {item.id for item in history} == {item.id for item in executions}
        config = json.loads(remaining[0].config_json)
        assert config["url"] == "https://hhanclub.net/attendance.php"
        assert config["credential_domain"] == "hhanclub.net"
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
    refresh_credential = app.state.credentials.upsert(
        "cookiecloud:test:nanyangpt.com", "nanyangpt.com", {"sid": "secret"},
        provider="cookiecloud",
    )
    refresh_only = app.state.automations.create(
        "NanyangPT", "pt_signin", 86400, {
            "url": "https://nanyangpt.com/",
            "credential_domain": "nanyangpt.com",
            "sign_in_enabled": False,
            "profile_refresh_enabled": True,
            "sign_in_supported": False,
            "profile_refresh_supported": True,
        }, refresh_credential.id,
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
            ExecutionRecord(
                id=str(uuid4()), automation_id=site.id,
                scheduled_at=today_start_utc - timedelta(days=2), status="succeeded",
                attempts=1, available_at=today_start_utc - timedelta(days=2),
                result_json=json.dumps({
                    "outcome": "success", "message": "旧记录", "details": None,
                }),
            ),
            execution(yesterday_start_utc + timedelta(hours=3), "retry_wait"),
            execution(today_start_utc + timedelta(hours=1), "failed"),
            execution(today_start_utc + timedelta(hours=2), "succeeded", "签到成功", [
                {"date": local_today.isoformat(), "reward": "165"},
                {"date": (local_today - timedelta(days=1)).isoformat(), "reward": "160"},
            ]),
            ExecutionRecord(
                id=str(uuid4()), automation_id=refresh_only.id,
                scheduled_at=today_start_utc + timedelta(hours=3), status="succeeded",
                attempts=1, available_at=today_start_utc + timedelta(hours=3),
                result_json=json.dumps({
                    "outcome": "success",
                    "message": "PT 站个人信息页刷新成功",
                    "details": {"actions": {
                        "sign_in": {"enabled": False},
                        "profile_refresh": {
                            "enabled": True,
                            "outcome": "success",
                            "message": "PT 站个人信息页刷新成功",
                        },
                    }},
                }),
            ),
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
    assert by_id[site.id]["record_count"] == 4
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
    refresh_history = by_id[refresh_only.id]
    assert refresh_history["history_action"] == "profile_refresh"
    assert refresh_history["record_count"] == 1
    refresh_execution = refresh_history["executions"][local_today.isoformat()]
    assert refresh_execution["action_type"] == "profile_refresh"
    assert refresh_execution["result"]["message"] == "PT 站个人信息页刷新成功"
    assert payload["latest_execution"]["automation_name"] == "NanyangPT"
    assert invalid.status_code == 422
