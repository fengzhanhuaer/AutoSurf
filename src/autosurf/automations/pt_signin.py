from __future__ import annotations

import os
import re
from contextlib import suppress
from datetime import date
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import parse_qs, urljoin, urlparse

from autosurf.automations.browser_session import playwright_cookies, validated_http_url
from autosurf.domain.models import RunContext, RunOutcome, RunResult
from autosurf.pt_discovery import discover_pt_site


DEFAULT_ALREADY_PATTERNS = (
    r"今日已签到",
    r"今天已签到",
    r"已经签到",
    r"今天已经签过到了",
    r"\[已签到\]",
    r"已签到.{0,20}无需再签",
    r"签到已得",
    r"already\s+(?:checked|signed)",
    r"checked\s+in\s+today",
    r"\bchecked\s+in\b",
)
DEFAULT_SUCCESS_PATTERNS = (
    r"签到成功",
    r"本次签到获得",
    r"今天签到您获得.{0,24}(?:积分|魔力值?|金币|上传量)",
    r"签到已得",
    r"(?:check[ -]?in|sign[ -]?in).{0,16}success",
)
SIGNIN_ACTION_REQUIRED_PATTERNS = (
    r"已断签\s*\d+\s*天",
    r"请选择补签",
    r"放弃补签重新开始签到",
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
    r"雷池\s*WAF",
    r"客户端异常.{0,24}合法用户",
)
COMMON_BUTTON_PATTERNS = (
    re.compile(r"^\s*(?:每日|今日|立即)?\s*(?:签到|簽到|打卡)(?:领奖)?\s*$", re.IGNORECASE),
    re.compile(r"^\s*(?:check\s*in|sign\s*in)\s*$", re.IGNORECASE),
)


class PtSiteAdapter(Protocol):
    def matches(self, url: str) -> bool: ...

    async def sign_in(self, page: Any, context: RunContext) -> RunResult: ...


class FiftyTwoPtAdapter:
    def matches(self, url: str) -> bool:
        parsed = urlparse(url)
        hostname = (parsed.hostname or "").lower().rstrip(".")
        return hostname == "52pt.site" or hostname.endswith(".52pt.site")

    async def sign_in(self, page: Any, context: RunContext) -> RunResult:
        body = (await page.locator("body").inner_text())[:1_000_000]
        outcome = classify_pt_page(page.url, None, body, context.config)
        if outcome:
            return await _classified_page_result(page, outcome, page.url, None, context=context)

        sign_in_paused = "签到页面已暂停使用" in body
        if sign_in_paused or not await page.locator("#slider-btn").count():
            parsed = validated_http_url(str(context.config["url"]))
            origin = f"{parsed.scheme}://{parsed.netloc}/"
            await page.goto(origin, wait_until="domcontentloaded")
            signin_link = page.locator("#game").first
            if not await signin_link.is_visible():
                if sign_in_paused and await discover_pt_profile_url(page):
                    return _classified_result(
                        RunOutcome.ALREADY_DONE, page.url, None, clicked=False,
                    )
                return RunResult(RunOutcome.FAILED, "52PT 首页没有找到签到入口", {"url": page.url})
            href = str(await signin_link.get_attribute("href") or "")
            target = urljoin(page.url, href)
            target_host = (urlparse(target).hostname or "").lower().rstrip(".")
            if target_host != "52pt.site" and not target_host.endswith(".52pt.site"):
                return RunResult(RunOutcome.FAILED, "52PT 签到入口指向了站外地址", {"url": target})
            await signin_link.click()
            await page.wait_for_load_state("domcontentloaded")

        body = (await page.locator("body").inner_text())[:1_000_000]
        outcome = classify_pt_page(page.url, None, body, context.config)
        if outcome:
            return await _classified_page_result(page, outcome, page.url, None, context=context)
        if not await complete_52pt_slider(page):
            return RunResult(RunOutcome.FAILED, "52PT 滑块验证未完成", {"url": page.url})

        submit = page.locator("#submit-btn").first
        async with page.expect_navigation(wait_until="domcontentloaded") as navigation:
            await submit.click()
        response = await navigation.value
        status_code = response.status if response else None
        body = (await page.locator("body").inner_text())[:1_000_000]
        outcome = classify_pt_page(page.url, status_code, body, context.config)
        if outcome:
            return await _classified_page_result(
                page, outcome, page.url, status_code, clicked=True, context=context,
            )
        return RunResult(RunOutcome.FAILED, "52PT 提交签到后未识别到结果", {
            "url": page.url, "status_code": status_code, "clicked": True,
        })


async def complete_52pt_slider(page: Any) -> bool:
    container = page.locator("#slider-container").first
    slider = page.locator("#slider-btn").first
    submit = page.locator("#submit-btn").first
    captcha = page.locator("#sign_captcha").first
    if not await container.is_visible() or not await slider.is_visible():
        return False
    container_box = await container.bounding_box()
    slider_box = await slider.bounding_box()
    if not container_box or not slider_box:
        return False

    start_x = slider_box["x"] + slider_box["width"] / 2
    start_y = slider_box["y"] + slider_box["height"] / 2
    end_x = container_box["x"] + container_box["width"] - slider_box["width"] / 2 - 2
    if end_x <= start_x:
        return False
    await page.mouse.move(start_x, start_y)
    await page.mouse.down()
    await page.mouse.move(end_x, start_y, steps=24)
    await page.mouse.up()
    await page.wait_for_timeout(100)
    return bool(await captcha.input_value()) and not await submit.is_disabled()


class BtschoolAdapter:
    def matches(self, url: str) -> bool:
        hostname = (urlparse(url).hostname or "").lower().rstrip(".")
        return hostname == "btschool.club" or hostname.endswith(".btschool.club")

    async def sign_in(self, page: Any, context: RunContext) -> RunResult:
        body = (await page.locator("body").inner_text())[:1_000_000]
        outcome = classify_pt_page(page.url, None, body, context.config)
        if outcome:
            return await _classified_page_result(page, outcome, page.url, None, context=context)
        if "欢迎回来" in body and "action=addbonus" in page.url.lower():
            return await _classified_page_result(
                page, RunOutcome.ALREADY_DONE, page.url, None, context=context,
            )
        return RunResult(
            RunOutcome.FAILED,
            "BTSchool 签到接口没有返回可识别结果",
            {"url": page.url},
        )


class OpenCdAdapter:
    def matches(self, url: str) -> bool:
        hostname = (urlparse(url).hostname or "").lower().rstrip(".")
        return hostname == "open.cd" or hostname.endswith(".open.cd")

    async def sign_in(self, page: Any, context: RunContext) -> RunResult:
        body = (await page.locator("body").inner_text())[:1_000_000]
        outcome = classify_pt_page(page.url, None, body, context.config)
        if outcome:
            return await _classified_page_result(page, outcome, page.url, None, context=context)
        target = page.locator("a").filter(has_text=re.compile(r"^\s*簽到\s*$")).first
        if not await target.is_visible():
            return RunResult(RunOutcome.FAILED, "OpenCD 首页没有找到签到入口", {"url": page.url})
        async with page.expect_response(
            lambda response: response.url.endswith("/plugin_sign-in.php")
        ) as pending:
            await target.click()
        response = await pending.value
        response_body = (await response.text())[:1_000_000]
        if "name=\"imagehash\"" in response_body and "name=\"imagestring\"" in response_body:
            return RunResult(
                RunOutcome.BLOCKED,
                "OpenCD 签到需要图片验证码",
                {"url": response.url, "status_code": response.status},
            )
        outcome = classify_pt_page(response.url, response.status, response_body, context.config)
        if outcome:
            return _classified_result(outcome, response.url, response.status, clicked=True)
        return RunResult(
            RunOutcome.FAILED,
            "OpenCD 签到接口没有返回可识别结果",
            {"url": response.url, "status_code": response.status, "clicked": True},
        )


class TjuptAdapter:
    def matches(self, url: str) -> bool:
        hostname = (urlparse(url).hostname or "").lower().rstrip(".")
        return hostname == "tjupt.org" or hostname.endswith(".tjupt.org")

    async def sign_in(self, page: Any, context: RunContext) -> RunResult:
        body = (await page.locator("body").inner_text())[:1_000_000]
        outcome = classify_pt_page(page.url, None, body, context.config)
        if outcome != RunOutcome.FAILED:
            if outcome:
                return await _classified_page_result(page, outcome, page.url, None, context=context)
            return RunResult(RunOutcome.FAILED, "TJUPT 签到页面没有返回可识别结果", {"url": page.url})

        supplement = page.locator('a[href*="action=confirm"]').first
        if not await supplement.is_visible():
            return await _classified_page_result(page, outcome, page.url, None, context=context)
        async with page.expect_navigation(wait_until="domcontentloaded") as navigation:
            await supplement.click()
        response = await navigation.value
        status_code = response.status if response else None
        body = (await page.locator("body").inner_text())[:1_000_000]
        outcome = classify_pt_page(page.url, status_code, body, context.config)
        if outcome:
            return await _classified_page_result(
                page, outcome, page.url, status_code, clicked=True, context=context,
            )
        if status_code is None or 200 <= status_code < 400:
            return await _classified_page_result(
                page, RunOutcome.SUCCESS, page.url, status_code, clicked=True, context=context,
            )
        return RunResult(
            RunOutcome.FAILED,
            "TJUPT 补签后没有返回可识别结果",
            {"url": page.url, "status_code": status_code, "clicked": True},
        )


class PtSignInHandler:
    type = "pt_signin"

    def __init__(self, adapters: list[PtSiteAdapter] | None = None) -> None:
        self.adapters = adapters or []

    async def run(self, context: RunContext) -> RunResult:
        config = context.config
        url = str(config["url"])
        parsed = validated_http_url(url)
        discovery = discover_pt_site(parsed.hostname or "", set(context.cookies))
        catalog_sign_in_supported = discovery.sign_in_supported if discovery else True
        catalog_profile_refresh_supported = discovery.profile_refresh_supported if discovery else True
        sign_in_supported = bool(config.get(
            "sign_in_supported", catalog_sign_in_supported,
        )) and catalog_sign_in_supported
        profile_refresh_supported = bool(config.get(
            "profile_refresh_supported", catalog_profile_refresh_supported,
        )) and catalog_profile_refresh_supported
        sign_in_enabled = bool(config.get("sign_in_enabled", True)) and sign_in_supported
        profile_refresh_enabled = (
            bool(config.get("profile_refresh_enabled", False)) and profile_refresh_supported
        )
        if (
            discovery
            and discovery.default_profile_refresh_enabled
            and "profile_refresh_supported" not in config
        ):
            profile_refresh_enabled = True
        if not sign_in_enabled and not profile_refresh_enabled:
            return RunResult(RunOutcome.FAILED, "PT 站点未启用签到或个人信息刷新")
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
                sign_in_result = None
                if sign_in_enabled:
                    response = await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                    adapter = next((item for item in self.adapters if item.matches(url)), None)
                    if adapter:
                        sign_in_result = await adapter.sign_in(page, context)
                    else:
                        sign_in_result = await self._generic_sign_in(
                            page, context, response.status if response else None, screenshot
                        )
                else:
                    origin = f"{parsed.scheme}://{parsed.netloc}/"
                    await page.goto(origin, wait_until="domcontentloaded", timeout=timeout_ms)

                profile_result = None
                if profile_refresh_enabled:
                    profile_result = await refresh_pt_profile_page(
                        page, context, url, credential_domain, timeout_ms
                    )
                return combine_pt_action_results(sign_in_result, profile_result)
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
        body = await page_body_text(page)
        body += "\n" + await rendered_signin_status_text(page)
        outcome = classify_pt_page(page.url, status_code, body, config)
        if outcome:
            return await _classified_page_result(
                page, outcome, page.url, status_code, context=context
            )

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
            body = await page_body_text(page)
            body += "\n" + await rendered_signin_status_text(page)
            outcome = classify_pt_page(page.url, None, body, config)
            if outcome:
                return await _classified_page_result(
                    page, outcome, page.url, status_code, clicked=True, context=context
                )
        else:
            # Some trackers render their user/status toolbar after DOMContentLoaded.
            # Recheck once before declaring that no sign-in state or control exists.
            await page.wait_for_timeout(1_500)
            with suppress(Exception):
                await page.wait_for_load_state("networkidle", timeout=3_000)
            body = await page_body_text(page)
            body += "\n" + await rendered_signin_status_text(page)
            outcome = classify_pt_page(page.url, status_code, body, config)
            if outcome:
                return await _classified_page_result(
                    page, outcome, page.url, status_code, context=context
                )

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
    if _matches(body, SIGNIN_ACTION_REQUIRED_PATTERNS):
        return RunOutcome.FAILED
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
                       clicked: bool = False,
                       site_history: list[dict[str, str]] | None = None) -> RunResult:
    messages = {
        RunOutcome.SUCCESS: "PT 站签到成功",
        RunOutcome.ALREADY_DONE: "PT 站今日已经签到",
        RunOutcome.AUTH_EXPIRED: "Cookie 已失效或站点要求重新登录",
        RunOutcome.BLOCKED: "站点启用了 Cloudflare 或人机验证",
        RunOutcome.FAILED: "站点显示签到已中断，需要人工选择补签或重新开始",
    }
    details: dict[str, Any] = {"url": url, "status_code": status_code, "clicked": clicked}
    if site_history:
        details["site_history"] = site_history
    return RunResult(outcome, messages[outcome], details)


async def refresh_pt_profile_page(page: Any, context: RunContext, site_url: str,
                                  credential_domain: str, timeout_ms: int) -> RunResult:
    current_body = await page_body_text(page)
    current_outcome = classify_pt_page(page.url, None, current_body, context.config)
    if current_outcome in {RunOutcome.AUTH_EXPIRED, RunOutcome.BLOCKED}:
        return _classified_result(current_outcome, page.url, None)

    configured = str(context.config.get("profile_url") or "").strip()
    if not configured:
        discovery = discover_pt_site(urlparse(site_url).hostname or "", set(context.cookies))
        configured = discovery.profile_url if discovery and discovery.profile_url else ""
    profile_url = urljoin(site_url, configured) if configured else await discover_pt_profile_url(page)
    if not profile_url:
        profile_url = profile_url_from_cookies(site_url, context.cookies)
    if not profile_url:
        return RunResult(RunOutcome.FAILED, "未找到 PT 站个人信息页", {"url": page.url})

    parsed = validated_http_url(profile_url)
    if credential_domain and not _domain_matches(credential_domain, parsed.hostname or ""):
        return RunResult(RunOutcome.FAILED, "个人信息页不属于当前 PT 站点", {"url": profile_url})

    response = await page.goto(profile_url, wait_until="domcontentloaded", timeout=timeout_ms)
    status_code = response.status if response else None
    body = (await page.locator("body").inner_text())[:1_000_000]
    if _matches(body, CHALLENGE_PATTERNS):
        return RunResult(RunOutcome.BLOCKED, "个人信息页触发了人机验证", {
            "url": page.url, "status_code": status_code,
        })
    if (
        status_code in {401, 403}
        or any(value in page.url.lower() for value in ("login.php", "takelogin", "/login?", "/login/"))
        or _matches(body, AUTH_EXPIRED_PATTERNS)
    ):
        return RunResult(RunOutcome.AUTH_EXPIRED, "个人信息页要求重新登录", {
            "url": page.url, "status_code": status_code,
        })
    if status_code is not None and status_code >= 400:
        return RunResult(RunOutcome.FAILED, "个人信息页刷新失败", {
            "url": page.url, "status_code": status_code,
        })
    stats = await extract_pt_profile_stats(page)
    return RunResult(RunOutcome.SUCCESS, "PT 站个人信息页刷新成功", {
        "url": page.url, "status_code": status_code, "profile_stats": stats,
    })


async def discover_pt_profile_url(page: Any) -> str | None:
    frames = getattr(page, "frames", None) or [page]
    for frame in frames:
        with suppress(Exception):
            result = await frame.evaluate(r"""() => {
          const anchors = [...document.querySelectorAll('a[href]')];
          const candidates = anchors.map((anchor) => {
            const href = anchor.href || '';
            const text = (anchor.innerText || anchor.textContent || '').trim();
            let score = 0;
            if (/userdetails\.php\?[^#]*\bid=/i.test(href)) score = 100;
            else if (/(?:^|\/)user\.php\?[^#]*\b(?:id|uid)=/i.test(href)) score = 75;
            else if (/\/(?:users?|profile)\//i.test(href)) score = 60;
            if (/个人(?:资料|信息|主页)|用户详情|my\s*profile/i.test(text)) score += 30;
            const container = anchor.closest('nav, header, footer, tr, td, div');
            const context = (container?.innerText || container?.textContent || '');
            if (/logout|退出|checked\s+in/i.test(context)) score += 40;
            return {href, score};
          }).filter((item) => item.score > 0);
          candidates.sort((left, right) => right.score - left.score);
          return candidates[0]?.href || null;
        }""")
            if isinstance(result, str) and result:
                return result
    return None


async def page_body_text(page: Any) -> str:
    frames = getattr(page, "frames", None) or [page]
    parts: list[str] = []
    total = 0
    for frame in frames:
        with suppress(Exception):
            value = await frame.locator("body").inner_text()
            if not value:
                continue
            remaining = 1_000_000 - total
            if remaining <= 0:
                break
            text = str(value)[:remaining]
            parts.append(text)
            total += len(text)
    return "\n".join(parts)


async def rendered_signin_status_text(page: Any) -> str:
    frames = getattr(page, "frames", None) or [page]
    parts: list[str] = []
    for frame in frames:
        with suppress(Exception):
            locator = frame.locator(
                "text=/checked\\s+in|今日已签到|今天已签到|\\[已签到\\]/i"
            )
            if await locator.count():
                parts.append("Checked in")
                continue
        with suppress(Exception):
            value = await frame.evaluate(r"""() => {
              const status = /(?:checked\s+in|今日已签到|今天已签到|\[已签到\])/i;
              const result = [];
              for (const element of document.querySelectorAll('*')) {
                const values = [
                  element.getAttribute('title'),
                  element.getAttribute('aria-label'),
                  element.getAttribute('value'),
                  element.getAttribute('data-original-title'),
                  getComputedStyle(element, '::before').content,
                  getComputedStyle(element, '::after').content,
                ];
                for (const item of values) {
                  if (item && status.test(item)) result.push(item);
                }
                if (result.length >= 20) break;
              }
              return result.join('\n');
            }""")
            if isinstance(value, str) and value:
                parts.append(value)
    return "\n".join(parts)


def profile_url_from_cookies(site_url: str, cookies: dict[str, str]) -> str | None:
    for name in ("c_secure_uid", "nexusphp_u"):
        user_id = str(cookies.get(name) or "").strip()
        if user_id.isdigit():
            parsed = urlparse(site_url)
            return f"{parsed.scheme}://{parsed.netloc}/userdetails.php?id={user_id}"
    return None


async def extract_pt_profile_stats(page: Any) -> dict[str, str]:
    with suppress(Exception):
        raw = await page.evaluate(r"""() => {
          const pairs = [];
          const addPair = (label, value) => {
            const key = String(label || '').replace(/\s+/g, ' ').trim();
            const text = String(value || '').replace(/\s+/g, ' ').trim();
            if (key && text && key !== text) pairs.push([key, text]);
          };
          for (const row of document.querySelectorAll('tr')) {
            const cells = [...row.querySelectorAll(':scope > th, :scope > td')]
              .map((cell) => (cell.innerText || cell.textContent || '').trim())
              .filter(Boolean);
            if (cells.length >= 2) addPair(cells[0], cells.slice(1).join(' '));
          }
          const terms = [...document.querySelectorAll('dt')];
          for (const term of terms) {
            const value = term.nextElementSibling;
            if (value?.matches('dd')) addPair(term.innerText, value.innerText);
          }
          const currentUrl = location.href.split('#')[0];
          const profileLink = [...document.querySelectorAll('a[href*="userdetails.php?id="]')]
            .filter((anchor) => anchor.href.split('#')[0] === currentUrl)
            .map((anchor) => {
              const text = (anchor.innerText || anchor.textContent || '').replace(/\s+/g, ' ').trim();
              const parent = (anchor.parentElement?.innerText || anchor.parentElement?.textContent || '')
                .replace(/\s+/g, ' ').trim();
              const usernameLike = /^[\p{L}\p{N}_.-]{2,40}$/u.test(text);
              const fieldLabel = /^(?:上传量|上傳量|下载量|下載量|分享率|魔力值?|积分|電影票|电影票|H&R)$/i.test(text);
              let score = usernameLike && !fieldLabel ? 1 : 0;
              if (score && parent === text) score += 100;
              if (score && /欢迎回来|歡迎回來|welcome\s+back/i.test(parent)) score += 80;
              return {anchor, score};
            })
            .sort((left, right) => right.score - left.score)
            .find((item) => item.score > 0)?.anchor;
          return {
            pairs,
            body: (document.body?.innerText || '').slice(0, 100000),
            title: document.title || '',
            profile_username: (profileLink?.innerText || profileLink?.textContent || '').trim(),
          };
        }""")
        return normalize_pt_profile_stats(raw)
    return {}


def normalize_pt_profile_stats(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    pairs = value.get("pairs") if isinstance(value.get("pairs"), list) else []
    normalized_pairs: list[tuple[str, str]] = []
    for item in pairs[:300]:
        if not isinstance(item, list) or len(item) < 2:
            continue
        label = re.sub(r"[\s:：]+", "", str(item[0])).casefold()
        text = re.sub(r"\s+", " ", str(item[1])).strip()[:160]
        if label and text:
            normalized_pairs.append((label, text))

    aliases = {
        "username": ("用户名", "用戶名", "username"),
        "user_level": ("用户等级", "用戶等級", "用户组", "用戶組", "等级", "等級", "class"),
        "uploaded": ("上传量", "上傳量", "uploaded"),
        "downloaded": ("下载量", "下載量", "downloaded"),
        "ratio": ("分享率", "分享比率", "ratio"),
        "bonus": ("魔力值", "魔力", "积分", "積分", "bonus"),
        "seeding_count": ("做种数", "做種數", "当前做种", "當前做種", "seeding"),
        "seeding_size": ("做种体积", "做種體積", "做种大小", "做種大小", "seedsize"),
    }
    result: dict[str, str] = {}
    for key, labels in aliases.items():
        for label, text in normalized_pairs:
            if any(alias.casefold() == label for alias in labels):
                result[key] = text
                break

    username = _sanitize_pt_username(result.get("username"))
    if username:
        result["username"] = username
    else:
        result.pop("username", None)
    if not result.get("username"):
        username = _sanitize_pt_username(value.get("profile_username"))
        if username:
            result["username"] = username
    body = str(value.get("body") or "")
    title = str(value.get("title") or "")
    if not result.get("username"):
        match = re.search(
            r"(?:用户详情|用戶詳情)\s*[-:：]\s*([^\s|:：–—-]{1,40})",
            title,
            re.IGNORECASE,
        )
        if match:
            username = _sanitize_pt_username(match.group(1))
            if username:
                result["username"] = username
    if not result.get("username"):
        match = re.search(r"([^\s|_-]{1,40})\s*(?:的|之)\s*(?:个人资料|個人資料|个人信息)", f"{title}\n{body}")
        if match:
            username = _sanitize_pt_username(match.group(1))
            if username:
                result["username"] = username

    fallback_patterns = {
        "uploaded": r"(?:上传量|上傳量|Uploaded)\s*[:：]?\s*([\d,.]+\s*[KMGTPE]?i?B)",
        "downloaded": r"(?:下载量|下載量|Downloaded)\s*[:：]?\s*([\d,.]+\s*[KMGTPE]?i?B)",
        "ratio": r"(?:分享率|分享比率|Ratio)\s*[:：]?\s*([\d,.]+|∞|Inf)",
        "bonus": r"(?:魔力值|魔力|Bonus)\s*[:：]?\s*([\d,.]+)",
    }
    for key, pattern in fallback_patterns.items():
        if key in result:
            continue
        match = re.search(pattern, body, re.IGNORECASE)
        if match:
            result[key] = match.group(1).strip()
    return sanitize_pt_profile_stats(result)


def _sanitize_pt_username(value: Any) -> str | None:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text or re.match(
        r"^(?:上传量|上傳量|下载量|下載量|分享率|分享比率|魔力值?|积分|積分|"
        r"电影票|電影票|邀请|邀請|当前活动|當前活動|可连接|可連接|连接数|連接數|"
        r"H&R|认领|認領)(?:\s*[:：]|$)",
        text,
        re.IGNORECASE,
    ):
        return None
    match = re.match(r"[\w.-]{1,40}", text, re.UNICODE)
    return match.group(0) if match else None


def sanitize_pt_profile_stats(value: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    allowed = {
        "username", "user_level", "uploaded", "downloaded", "ratio",
        "bonus", "seeding_count", "seeding_size",
    }
    for key, raw in value.items():
        if key not in allowed or raw is None:
            continue
        text = re.sub(r"\s+", " ", str(raw)).strip()
        if not text:
            continue
        if key == "username":
            username = _sanitize_pt_username(text)
            if not username:
                continue
            text = username
        elif key == "user_level":
            text = re.split(
                r"签到(?:得)?魔力|当前时间|校验等级|等级参考|修改此项|参考《|"
                r"[\U0001F000-\U0001FAFF]",
                text,
                maxsplit=1,
            )[0].strip(" []【】|·:：-")
            text = re.sub(r"^[（(][^()（）]{1,20}[)）]\s*", "", text)
            if not text or len(text) > 60 or not re.search(r"[\w\u4e00-\u9fff]", text):
                continue
        elif re.search(r"签到(?:得)?魔力|当前时间|显示/隐藏|种子列表查看", text):
            continue
        elif key in {"uploaded", "downloaded", "seeding_size"}:
            match = re.search(r"\d[\d,.]*\s*[KMGTPE](?:i?B)?", text, re.IGNORECASE)
            if not match:
                continue
            text = match.group(0)
        elif key in {"ratio", "bonus"}:
            match = re.search(r"(?:\d[\d,.]*|∞|Inf)", text, re.IGNORECASE)
            if not match:
                continue
            text = match.group(0)
        elif key == "seeding_count":
            match = re.search(r"\d+", text)
            if not match:
                continue
            text = match.group(0)
        else:
            text = text[:80]
        result[key] = text
    return result


def combine_pt_action_results(sign_in: RunResult | None,
                              profile_refresh: RunResult | None) -> RunResult:
    if sign_in is None and profile_refresh is None:
        return RunResult(RunOutcome.FAILED, "PT 站点没有可执行的操作")
    if sign_in is None:
        return _with_action_details(profile_refresh, None, profile_refresh)
    if profile_refresh is None:
        return _with_action_details(sign_in, sign_in, None)

    failed = next((item for item in (sign_in, profile_refresh) if item.outcome not in {
        RunOutcome.SUCCESS, RunOutcome.ALREADY_DONE,
    }), None)
    selected = failed or sign_in
    message = f"{sign_in.message}；{profile_refresh.message}"
    combined = RunResult(selected.outcome, message, dict(selected.details or {}))
    return _with_action_details(combined, sign_in, profile_refresh)


def _with_action_details(result: RunResult | None, sign_in: RunResult | None,
                         profile_refresh: RunResult | None) -> RunResult:
    assert result is not None
    details = dict(result.details or {})
    details["actions"] = {
        "sign_in": _action_result_view(sign_in),
        "profile_refresh": _action_result_view(profile_refresh),
    }
    if sign_in and sign_in.details and sign_in.details.get("site_history"):
        details["site_history"] = sign_in.details["site_history"]
    return RunResult(result.outcome, result.message, details)


def _action_result_view(result: RunResult | None) -> dict[str, Any]:
    if result is None:
        return {"enabled": False}
    return {
        "enabled": True,
        "outcome": result.outcome,
        "message": result.message,
        "details": result.details,
    }


async def _classified_page_result(page: Any, outcome: RunOutcome, url: str,
                                  status_code: int | None,
                                  clicked: bool = False,
                                  context: RunContext | None = None) -> RunResult:
    site_history = None
    if outcome in {RunOutcome.SUCCESS, RunOutcome.ALREADY_DONE}:
        history_url = await discover_pt_signin_history_url(
            page, url, context.cookies if context else {}
        )
        if history_url and page.url != history_url:
            with suppress(Exception):
                await page.goto(history_url, wait_until="domcontentloaded")
        site_history = await extract_site_signin_history(page)
    return _classified_result(outcome, url, status_code, clicked, site_history)


def pt_signin_history_url(site_url: str, cookies: dict[str, str]) -> str | None:
    parsed = urlparse(site_url)
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if hostname != "pttime.org" and not hostname.endswith(".pttime.org"):
        return None
    user_id = str(cookies.get("c_secure_uid") or "").strip()
    if not user_id.isdigit():
        return None
    return urljoin(site_url, f"/attendance.php?type=sign&uid={user_id}")


async def discover_pt_signin_history_url(page: Any, site_url: str,
                                         cookies: dict[str, str]) -> str | None:
    direct = pt_signin_history_url(site_url, cookies)
    if direct:
        return direct
    parsed = urlparse(site_url)
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if hostname != "pttime.org" and not hostname.endswith(".pttime.org"):
        return None
    with suppress(Exception):
        await page.goto(urljoin(site_url, "/"), wait_until="domcontentloaded")
        profile = page.locator('a[href*="userdetails.php?id="]').first
        href = await profile.get_attribute("href")
        return pttime_history_url_from_profile(site_url, href)
    return None


def pttime_history_url_from_profile(site_url: str, profile_url: str | None) -> str | None:
    if not profile_url:
        return None
    absolute = urljoin(site_url, profile_url)
    user_ids = parse_qs(urlparse(absolute).query).get("id", [])
    user_id = str(user_ids[0]).strip() if user_ids else ""
    if not user_id.isdigit():
        return None
    return urljoin(site_url, f"/attendance.php?type=sign&uid={user_id}")


async def extract_site_signin_history(page: Any) -> list[dict[str, str]]:
    raw: Any = []
    with suppress(Exception):
        raw = await page.evaluate("""() => {
          const roots = [...document.querySelectorAll('.fc, #calendar, [class*="fullcalendar"]')];
          const entries = new Map();
          const add = (date, reward) => {
            const value = String(date || '').slice(0, 10);
            if (!/^\\d{4}-\\d{2}-\\d{2}$/.test(value)) return;
            const text = String(reward || '').replace(/\\s+/g, ' ').trim().slice(0, 100);
            entries.set(value, {date: value, reward: text});
          };

          for (const root of roots) {
            try {
              if (window.jQuery && window.jQuery.fn && window.jQuery.fn.fullCalendar) {
                const events = window.jQuery(root).fullCalendar('clientEvents') || [];
                for (const event of events) {
                  const start = event.start;
                  const eventDate = start && typeof start.format === 'function'
                    ? start.format('YYYY-MM-DD')
                    : String(start || '').slice(0, 10);
                  add(eventDate, event.title);
                }
              }
            } catch (_) {}

            const days = [...root.querySelectorAll('[data-date]')].map((element) => ({
              element,
              date: element.getAttribute('data-date'),
              rect: element.getBoundingClientRect(),
            })).filter((item) => /^\\d{4}-\\d{2}-\\d{2}$/.test(item.date || ''));

            for (const event of root.querySelectorAll('.fc-event')) {
              const directDay = event.closest('[data-date]');
              if (directDay) {
                add(directDay.getAttribute('data-date'), event.innerText || event.textContent);
                continue;
              }
              const rect = event.getBoundingClientRect();
              const x = rect.left + Math.min(rect.width / 2, 8);
              const y = rect.top + rect.height / 2;
              const day = days.find((item) => (
                x >= item.rect.left && x <= item.rect.right
                && y >= item.rect.top && y <= item.rect.bottom
              ));
              if (day) add(day.date, event.innerText || event.textContent);
            }
          }
          return [...entries.values()].sort((left, right) => left.date.localeCompare(right.date));
        }""")
    merged = {item["date"]: item for item in normalize_site_signin_history(raw)}
    with suppress(Exception):
        body = (await page.locator("body").inner_text())[:1_000_000]
        for item in extract_text_signin_history(body):
            current = merged.get(item["date"])
            if current is None or (item["reward"] and not current.get("reward")):
                merged[item["date"]] = item
    return [merged[key] for key in sorted(merged)[-62:]]


def extract_text_signin_history(value: str) -> list[dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    detailed_pattern = re.compile(
        r"时间\s*[:：]\s*(\d{4}[-/.]\d{1,2}[-/.]\d{1,2})[\s\S]{0,120}?"
        r"获得(?:魔力值|积分|積分|金币|金幣)?\s*[:：]?\s*([\d,.]+)",
        re.IGNORECASE,
    )
    for match in detailed_pattern.finditer(value):
        day = _normalize_history_date(match.group(1))
        if day:
            result[day] = {"date": day, "reward": match.group(2).strip()}
    for match in re.finditer(
        r"签到日(?:期)?\s*[:：]\s*(\d{8}|\d{4}[-/.]\d{1,2}[-/.]\d{1,2})",
        value,
        re.IGNORECASE,
    ):
        day = _normalize_history_date(match.group(1))
        if day:
            result.setdefault(day, {"date": day, "reward": ""})
    return [result[key] for key in sorted(result)[-62:]]


def _normalize_history_date(value: str) -> str | None:
    normalized = value.strip().replace("/", "-").replace(".", "-")
    if re.fullmatch(r"\d{8}", normalized):
        normalized = f"{normalized[:4]}-{normalized[4:6]}-{normalized[6:]}"
    with suppress(ValueError):
        return date.fromisoformat(normalized).isoformat()
    return None


def normalize_site_signin_history(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    result: dict[str, dict[str, str]] = {}
    for item in value[:62]:
        if not isinstance(item, dict):
            continue
        day = str(item.get("date") or "")[:10]
        try:
            date.fromisoformat(day)
        except ValueError:
            continue
        result[day] = {
            "date": day,
            "reward": str(item.get("reward") or "").strip()[:100],
        }
    return [result[key] for key in sorted(result)]


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
