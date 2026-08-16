from __future__ import annotations

import os
import re
from pathlib import Path

from autosurf.automations.browser_session import (
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
                page = browser_context.pages[0] if browser_context.pages else await browser_context.new_page()
                page.set_default_timeout(timeout_ms)
                try:
                    response = await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                    if config.get("wait_for_selector"):
                        await page.locator(str(config["wait_for_selector"])).wait_for(state="visible")
                    if config.get("click_selector"):
                        await page.locator(str(config["click_selector"])).click()
                    if config.get("wait_after_click_ms"):
                        await page.wait_for_timeout(min(max(int(config["wait_after_click_ms"]), 0), 30_000))
                    body = (await page.locator("body").inner_text())[:1_000_000]
                    status = response.status if response else None
                    if status in {401, 403}:
                        return with_browser_details(
                            RunResult(RunOutcome.AUTH_EXPIRED, f"site returned HTTP {status}"),
                            browser_session,
                        )
                    for pattern in config.get("already_patterns", []):
                        if re.search(str(pattern), body, re.IGNORECASE):
                            return with_browser_details(RunResult(
                                RunOutcome.ALREADY_DONE, "site reports this task is already complete",
                            ), browser_session)
                    for pattern in config.get("success_patterns", []):
                        if re.search(str(pattern), body, re.IGNORECASE):
                            return with_browser_details(
                                RunResult(RunOutcome.SUCCESS, "success pattern matched"), browser_session,
                            )
                    if not config.get("success_patterns"):
                        return with_browser_details(
                            RunResult(RunOutcome.SUCCESS, "browser automation completed"), browser_session,
                        )
                    await page.screenshot(path=str(screenshot), full_page=True)
                    return with_browser_details(RunResult(
                        RunOutcome.FAILED, "no success pattern matched", {"screenshot": str(screenshot)},
                    ), browser_session)
                except PlaywrightTimeoutError as exc:
                    await page.screenshot(path=str(screenshot), full_page=True)
                    return with_browser_details(RunResult(
                        RunOutcome.BLOCKED, f"browser operation timed out: {exc}",
                        {"screenshot": str(screenshot)},
                    ), browser_session)
