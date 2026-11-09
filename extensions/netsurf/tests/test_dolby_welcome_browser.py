from pathlib import Path

import pytest
from playwright.async_api import async_playwright


@pytest.mark.asyncio
@pytest.mark.parametrize("host", ["uhddolby.com", "www.uhddolby.com"])
async def test_dolby_uses_current_welcome_reward_and_whale_balance(host):
    source = Path(__file__).resolve().parents[1]
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(channel="chromium", headless=True)
        try:
            page = await browser.new_page()
            await page.route("https://**/*", lambda route: route.fulfill(content_type="text/html; charset=utf-8", body='''
                <table><tr id="welcome"><td>欢迎回来, fixture
                <font class="color_bonus">鲸币</font>[<a href="mybonus.php">使用</a>]: 11,383,551.8&nbsp;(签到已得300)
                <br>做种积分: 3,758,387.4 上传量: 34.199 TB 下载量: 50.160 TB</td></tr></table>
                <aside>昨天签到成功，公告：今日已签到</aside>'''))
            await page.goto(f"https://{host}/index.php")
            for name in ("catalog.js", "site-rules.js", "sites.js", "piggo.js"):
                await page.add_script_tag(path=str(source / name))
            result = await page.evaluate("""() => {
                const adapter=NetSurfPiggo.create(location.origin,'/attendance.php');
                const result={status:adapter.inspect(document,location.href).status,profile:adapter.profile(document)};
                document.querySelector('#welcome').remove();
                result.history=adapter.inspect(document,location.href).status;
                return result;
            }""")
            assert result["status"] == "already_done"
            assert result["profile"]["bonus"] == "11,383,551.8"
            assert result["profile"]["seedingPoints"] == "3,758,387.4"
            assert result["history"] == "unknown"
        finally:
            await browser.close()
