from pathlib import Path

import pytest
from playwright.async_api import async_playwright, expect


@pytest.mark.asyncio
async def test_signin_and_refresh_columns_remain_independent(tmp_path):
    source = Path(__file__).resolve().parents[1]
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(channel="chromium", headless=True)
        try:
            page = await browser.new_page(viewport={"width": 1440, "height": 900})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))

            async def serve(route):
                file = source / route.request.url.rsplit("/", 1)[-1]
                if file.is_file():
                    await route.fulfill(path=str(file))
                else:
                    await route.abort()

            await page.route("http://netsurf.test/**", serve)
            await page.add_init_script("""window.listeners=[]; window.updateState=(...args)=>listeners.forEach(callback=>callback(...args)); window.chrome={
              runtime:{getManifest:()=>({version:'test'}),sendMessage:async()=>({results:{}})},
              storage:{onChanged:{addListener:callback=>listeners.push(callback)},local:{get:async()=>{
                const time=new Date().toISOString();
                return {sites:Object.fromEntries(NetSurfSites.catalog.map(site=>[site.id,{enabled:site.id==='piggo'}])),
                  lastResult:{status:'already_done',verified:true,time,profile:{bonus:'123'},
                    refreshState:{status:'error',time,message:'首页请求超时'}}};
              }}}};""")
            await page.goto("http://netsurf.test/dashboard.html")
            await expect(page.locator(".overview-table th")).to_have_count(11)
            await expect(page.locator("#piggo-row td")).to_have_count(11)
            await expect(page.locator("#site-status")).to_have_text("已完成")
            await expect(page.locator("#refresh-status")).to_have_text("刷新失败")
            await page.evaluate("""() => updateState({lastResult:{newValue:{status:'error',confirmationFailed:true,
              time:new Date().toISOString(),profile:{bonus:'123'},refreshState:{status:'success',time:new Date().toISOString()}}}},'local')""")
            await expect(page.locator("#site-status")).to_have_text("签到失败")
            await expect(page.locator("#refresh-status")).to_have_text("已刷新")
            await expect(page.locator("#refresh-count")).to_have_text("1 / 1")
            for width in [1440, 390]:
                await page.set_viewport_size({"width": width, "height": 900})
                assert not await page.evaluate("document.documentElement.scrollWidth > innerWidth")
                await page.screenshot(path=str(tmp_path / f"split-status-{width}.png"))
            await page.evaluate("""() => updateState({sites:{newValue:{piggo:{enabled:true,refreshOnly:true}}}},'local')""")
            await expect(page.locator("#site-status")).to_have_text("无需签到")
            await expect(page.locator("#refresh-status")).to_have_text("已刷新")
            assert not errors
        finally:
            await browser.close()
