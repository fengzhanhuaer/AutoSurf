from __future__ import annotations

import re
import os
from pathlib import Path
from urllib.parse import urlparse

from autosurf.domain.models import RunContext, RunOutcome, RunResult


class BrowserSignInHandler:
    type = "browser_signin"

    async def run(self, context: RunContext) -> RunResult:
        config = context.config
        url = str(config["url"])
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("url must be an absolute HTTP(S) URL")

        from playwright.async_api import TimeoutError as PlaywrightTimeoutError
        from playwright.async_api import async_playwright

        timeout_ms = int(min(max(float(config.get("timeout_seconds", 60)), 1), 180) * 1000)
        screenshot_dir = Path(os.environ.get("AUTOSURF_DATA_DIR", "data")) / "browser-artifacts"
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        screenshot = screenshot_dir / f"{context.execution_id}.png"

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            browser_context = await browser.new_context(
                locale=str(config.get("locale", "zh-CN")),
                user_agent=config.get("user_agent"),
                viewport={"width": 1365, "height": 768},
            )
            await browser_context.add_cookies([
                {"name": name, "value": value, "domain": parsed.hostname, "path": "/",
                 "secure": parsed.scheme == "https"}
                for name, value in context.cookies.items()
            ])
            page = await browser_context.new_page()
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
                    return RunResult(RunOutcome.AUTH_EXPIRED, f"site returned HTTP {status}")
                for pattern in config.get("already_patterns", []):
                    if re.search(str(pattern), body, re.IGNORECASE):
                        return RunResult(RunOutcome.ALREADY_DONE, "site reports this task is already complete")
                for pattern in config.get("success_patterns", []):
                    if re.search(str(pattern), body, re.IGNORECASE):
                        return RunResult(RunOutcome.SUCCESS, "success pattern matched")
                if not config.get("success_patterns"):
                    return RunResult(RunOutcome.SUCCESS, "browser automation completed")
                await page.screenshot(path=str(screenshot), full_page=True)
                return RunResult(RunOutcome.FAILED, "no success pattern matched",
                                 {"screenshot": str(screenshot)})
            except PlaywrightTimeoutError as exc:
                await page.screenshot(path=str(screenshot), full_page=True)
                return RunResult(RunOutcome.BLOCKED, f"browser operation timed out: {exc}",
                                 {"screenshot": str(screenshot)})
            finally:
                await browser_context.close()
                await browser.close()
