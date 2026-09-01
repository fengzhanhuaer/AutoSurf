from __future__ import annotations

import os
import re
from pathlib import Path

from autosurf.automations.browser_session import (
    new_browser_session_page,
    persistent_chromium_session,
    validated_http_url,
    with_browser_details,
)
from autosurf.domain.models import RunContext, RunOutcome, RunResult


class BrowserSignInHandler:
    type = "browser_signin"

    async def run(self, context: RunContext) -> RunResult:
        config = context.config
        url = str(config["url"])
        validated_http_url(url)

        from playwright.async_api import TimeoutError as PlaywrightTimeoutError
        from playwright.async_api import async_playwright

        timeout_ms = int(min(max(float(config.get("timeout_seconds", 60)), 1), 180) * 1000)
        screenshot_dir = Path(os.environ.get("AUTOSURF_DATA_DIR", "data")) / "browser-artifacts"
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        screenshot = screenshot_dir / f"{context.execution_id}.png"

        async with async_playwright() as playwright:
            async with persistent_chromium_session(playwright, context, url) as browser_session:
                browser_context = browser_session.context
                page = await new_browser_session_page(browser_session)
                page.set_default_timeout(timeout_ms)
                try:
                    response = await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                    if config.get("wait_for_selector"):
                        await page.locator(str(config["wait_for_selector"])).wait_for(state="visible")
                    status = response.status if response else None
                    body = (await page.locator("body").inner_text())[:1_000_000]
                    details = {"url": page.url, "status_code": status, "clicked": False}
                    already_selector = str(config.get("already_selector") or "").strip()
                    if already_selector and await _selector_is_visible(page, already_selector):
                        details["matched_selector"] = already_selector
                        return with_browser_details(RunResult(
                            RunOutcome.ALREADY_DONE,
                            "site reports this task is already complete",
                            details,
                        ), browser_session)
                    initial_result = _classify_body(config, body, status, before_click=True)
                    if initial_result is not None:
                        return with_browser_details(RunResult(
                            initial_result.outcome, initial_result.message, details,
                        ), browser_session)

                    clicked = False
                    request_config = config.get("browser_request")
                    if isinstance(request_config, dict):
                        request_result = await page.evaluate(
                            """async (options) => {
                              const init = {
                                method: options.method || 'GET',
                                credentials: 'include',
                                headers: {'Accept': 'application/json, text/plain, */*'},
                              };
                              if (options.json !== undefined) {
                                init.headers['Content-Type'] = 'application/json';
                                init.body = JSON.stringify(options.json);
                              }
                              const response = await fetch(options.url, init);
                              return {
                                url: response.url,
                                status: response.status,
                                body: (await response.text()).slice(0, 1000000),
                              };
                            }""",
                            request_config,
                        )
                        body = str(request_result.get("body") or "")
                        status = int(request_result.get("status") or 0) or None
                        details = {
                            "url": str(request_result.get("url") or page.url),
                            "status_code": status,
                            "browser_request": True,
                            "clicked": False,
                        }
                        result = _classify_body(config, body, status, before_click=False)
                        if result is not None:
                            return with_browser_details(RunResult(
                                result.outcome, result.message, details,
                            ), browser_session)
                    elif config.get("click_role") and config.get("click_name"):
                        await page.get_by_role(
                            str(config["click_role"]),
                            name=str(config["click_name"]),
                            exact=bool(config.get("click_exact", False)),
                        ).click()
                        clicked = True
                    elif config.get("click_selector"):
                        await page.locator(str(config["click_selector"])).click()
                        clicked = True
                    if config.get("wait_after_click_ms"):
                        await page.wait_for_timeout(min(max(int(config["wait_after_click_ms"]), 0), 30_000))
                    body = (await page.locator("body").inner_text())[:1_000_000]
                    details = {"url": page.url, "status_code": status, "clicked": clicked}
                    success_selector = str(config.get("success_selector") or "").strip()
                    if success_selector and await _selector_is_visible(page, success_selector):
                        details["matched_selector"] = success_selector
                        return with_browser_details(RunResult(
                            RunOutcome.SUCCESS, "success selector matched", details,
                        ), browser_session)
                    if already_selector and await _selector_is_visible(page, already_selector):
                        details["matched_selector"] = already_selector
                        return with_browser_details(RunResult(
                            RunOutcome.ALREADY_DONE,
                            "site reports this task is already complete",
                            details,
                        ), browser_session)
                    result = _classify_body(config, body, status, before_click=False)
                    if result is not None:
                        return with_browser_details(RunResult(
                            result.outcome, result.message, details,
                        ), browser_session)
                    if not config.get("success_patterns"):
                        return with_browser_details(
                            RunResult(RunOutcome.SUCCESS, "browser automation completed", details),
                            browser_session,
                        )
                    await page.screenshot(path=str(screenshot), full_page=True)
                    details["screenshot"] = str(screenshot)
                    return with_browser_details(RunResult(
                        RunOutcome.FAILED, "no success pattern matched", details,
                    ), browser_session)
                except PlaywrightTimeoutError as exc:
                    await page.screenshot(path=str(screenshot), full_page=True)
                    return with_browser_details(RunResult(
                        RunOutcome.BLOCKED, f"browser operation timed out: {exc}",
                        {"screenshot": str(screenshot)},
                    ), browser_session)


async def _selector_is_visible(page: object, selector: str) -> bool:
    try:
        return bool(await page.locator(selector).first.is_visible())
    except Exception:
        return False


def _classify_body(
    config: dict, body: str, status: int | None, *, before_click: bool,
) -> RunResult | None:
    if status in {401, 403}:
        return RunResult(RunOutcome.AUTH_EXPIRED, f"site returned HTTP {status}")
    for pattern in config.get("auth_expired_patterns", []):
        if re.search(str(pattern), body, re.IGNORECASE):
            return RunResult(RunOutcome.AUTH_EXPIRED, "site reports that login has expired")
    if before_click:
        for pattern in config.get("already_patterns", []):
            if re.search(str(pattern), body, re.IGNORECASE):
                return RunResult(
                    RunOutcome.ALREADY_DONE, "site reports this task is already complete",
                )
        return None
    for pattern in config.get("success_patterns", []):
        if re.search(str(pattern), body, re.IGNORECASE):
            return RunResult(RunOutcome.SUCCESS, "success pattern matched")
    for pattern in config.get("already_patterns", []):
        if re.search(str(pattern), body, re.IGNORECASE):
            return RunResult(RunOutcome.ALREADY_DONE, "site reports this task is already complete")
    return None
