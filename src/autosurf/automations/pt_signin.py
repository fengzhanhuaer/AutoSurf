from __future__ import annotations

import os
import re
from contextlib import suppress
from pathlib import Path
from typing import Any, Protocol

from autosurf.automations.browser_session import playwright_cookies, validated_http_url
from autosurf.domain.models import RunContext, RunOutcome, RunResult


DEFAULT_ALREADY_PATTERNS = (
    r"今日已签到",
    r"已经签到",
    r"签到已得",
    r"already\s+(?:checked|signed)",
    r"checked\s+in\s+today",
)
DEFAULT_SUCCESS_PATTERNS = (
    r"签到成功",
    r"本次签到获得",
    r"签到已得",
    r"(?:奖励|获得).{0,24}(?:积分|魔力|金币|上传量)",
    r"(?:check[ -]?in|sign[ -]?in).{0,16}success",
)
AUTH_EXPIRED_PATTERNS = (
    r"请(?:先|重新)?登录",
    r"登录(?:状态)?已失效",
    r"cookie.{0,12}失效",
    r"not\s+logged\s+in",
    r"sign\s+in\s+to\s+continue",
    r"name=[\"'](?:username|user|email)[\"']",
)
CHALLENGE_PATTERNS = (
    r"cf-chl-",
    r"cloudflare\s+ray\s+id",
    r"just\s+a\s+moment",
    r"attention\s+required",
    r"验证您是真人",
)
COMMON_BUTTON_PATTERNS = (
    re.compile(r"^\s*(?:每日|今日)?\s*(?:签到|打卡)(?:领奖)?\s*$", re.IGNORECASE),
    re.compile(r"^\s*(?:check\s*in|sign\s*in)\s*$", re.IGNORECASE),
)


class PtSiteAdapter(Protocol):
    def matches(self, url: str) -> bool: ...

    async def sign_in(self, page: Any, context: RunContext) -> RunResult: ...


class PtSignInHandler:
    type = "pt_signin"

    def __init__(self, adapters: list[PtSiteAdapter] | None = None) -> None:
        self.adapters = adapters or []

    async def run(self, context: RunContext) -> RunResult:
        config = context.config
        url = str(config["url"])
        parsed = validated_http_url(url)
        credential_domain = str(config.get("credential_domain") or "").lower().lstrip(".")
        if credential_domain and not _domain_matches(credential_domain, parsed.hostname or ""):
            raise ValueError("sign-in URL must use the selected credential domain")

        from playwright.async_api import TimeoutError as PlaywrightTimeoutError
        from playwright.async_api import async_playwright

        timeout_ms = int(min(max(float(config.get("timeout_seconds", 60)), 5), 180) * 1000)
        artifact_dir = Path(os.environ.get("AUTOSURF_DATA_DIR", "data")) / "browser-artifacts"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        screenshot = artifact_dir / f"{context.execution_id}.png"

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            browser_context = await browser.new_context(
                locale=str(config.get("locale", "zh-CN")),
                user_agent=config.get("user_agent"),
                viewport={"width": 1365, "height": 768},
            )
            await browser_context.add_cookies(playwright_cookies(context, url))
            page = await browser_context.new_page()
            page.set_default_timeout(timeout_ms)
            try:
                response = await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                adapter = next((item for item in self.adapters if item.matches(url)), None)
                if adapter:
                    return await adapter.sign_in(page, context)
                return await self._generic_sign_in(page, context, response.status if response else None, screenshot)
            except PlaywrightTimeoutError as exc:
                await _save_screenshot(page, screenshot)
                return RunResult(
                    RunOutcome.BLOCKED,
                    "PT 站点响应超时",
                    {"url": page.url or url, "screenshot": str(screenshot), "error": str(exc)[:500]},
                )
            finally:
                await browser_context.close()
                await browser.close()

    async def _generic_sign_in(self, page: Any, context: RunContext, status_code: int | None,
                               screenshot: Path) -> RunResult:
        config = context.config
        body = (await page.locator("body").inner_text())[:1_000_000]
        outcome = classify_pt_page(page.url, status_code, body, config)
        if outcome:
            return _classified_result(outcome, page.url, status_code)

        clicked = False
        selector = str(config.get("click_selector") or "").strip()
        if selector:
            target = page.locator(selector).first
            if not await target.is_visible():
                await _save_screenshot(page, screenshot)
                return RunResult(
                    RunOutcome.FAILED,
                    "未找到配置的签到按钮",
                    {"url": page.url, "status_code": status_code, "screenshot": str(screenshot)},
                )
            await target.click()
            clicked = True
        else:
            clicked = await _click_common_signin_control(page)

        if clicked:
            await page.wait_for_timeout(min(max(int(config.get("wait_after_click_ms", 1500)), 0), 10_000))
            with suppress(Exception):
                await page.wait_for_load_state("networkidle", timeout=5_000)
            body = (await page.locator("body").inner_text())[:1_000_000]
            outcome = classify_pt_page(page.url, None, body, config)
            if outcome:
                return _classified_result(outcome, page.url, status_code, clicked=True)

        await _save_screenshot(page, screenshot)
        message = "页面中没有找到签到入口" if not clicked else "签到后未识别到成功结果"
        return RunResult(
            RunOutcome.FAILED,
            message,
            {"url": page.url, "status_code": status_code, "clicked": clicked, "screenshot": str(screenshot)},
        )


def classify_pt_page(url: str, status_code: int | None, body: str,
                     config: dict[str, Any] | None = None) -> RunOutcome | None:
    config = config or {}
    if status_code == 401:
        return RunOutcome.AUTH_EXPIRED
    lowered_url = url.lower()
    if _matches(body, CHALLENGE_PATTERNS):
        return RunOutcome.BLOCKED
    if status_code == 403:
        return RunOutcome.AUTH_EXPIRED
    if any(value in lowered_url for value in ("login.php", "takelogin", "/login?", "/login/")):
        return RunOutcome.AUTH_EXPIRED
    if _matches(body, DEFAULT_ALREADY_PATTERNS) or _contains_any(body, config.get("already_patterns", [])):
        return RunOutcome.ALREADY_DONE
    if _matches(body, DEFAULT_SUCCESS_PATTERNS) or _contains_any(body, config.get("success_patterns", [])):
        return RunOutcome.SUCCESS
    if _matches(body, AUTH_EXPIRED_PATTERNS):
        return RunOutcome.AUTH_EXPIRED
    return None


def _matches(value: str, patterns: tuple[Any, ...]) -> bool:
    return any(re.search(str(pattern), value, re.IGNORECASE) for pattern in patterns if str(pattern))


def _contains_any(value: str, patterns: list[str]) -> bool:
    lowered = value.casefold()
    return any(pattern.strip().casefold() in lowered for pattern in patterns if pattern.strip())


def _domain_matches(credential_domain: str, hostname: str) -> bool:
    hostname = hostname.lower().rstrip(".")
    return hostname == credential_domain or hostname.endswith(f".{credential_domain}")


def _classified_result(outcome: RunOutcome, url: str, status_code: int | None,
                       clicked: bool = False) -> RunResult:
    messages = {
        RunOutcome.SUCCESS: "PT 站签到成功",
        RunOutcome.ALREADY_DONE: "PT 站今日已经签到",
        RunOutcome.AUTH_EXPIRED: "Cookie 已失效或站点要求重新登录",
        RunOutcome.BLOCKED: "站点启用了 Cloudflare 或人机验证",
    }
    return RunResult(outcome, messages[outcome], {"url": url, "status_code": status_code, "clicked": clicked})


async def _click_common_signin_control(page: Any) -> bool:
    controls = page.locator("button, a, input[type=button], input[type=submit]")
    for index in range(min(await controls.count(), 120)):
        control = controls.nth(index)
        if not await control.is_visible() or not await control.is_enabled():
            continue
        text = ((await control.inner_text()) or await control.get_attribute("value") or "").strip()
        if any(pattern.search(text) for pattern in COMMON_BUTTON_PATTERNS):
            await control.click()
            return True
    return False


async def _save_screenshot(page: Any, path: Path) -> None:
    with suppress(Exception):
        await page.screenshot(path=str(path), full_page=True)
