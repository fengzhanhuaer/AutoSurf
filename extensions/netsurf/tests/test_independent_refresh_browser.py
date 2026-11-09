from pathlib import Path
import json
import shutil

import pytest
from playwright.async_api import async_playwright, expect


@pytest.mark.asyncio
@pytest.mark.parametrize("site_id,host", [("piggo", "piggo.me"), ("hddolby.com", "www.uhddolby.com")])
async def test_failed_signin_refreshes_stats_without_retrying_submission(tmp_path, site_id, host):
    source = Path(__file__).resolve().parents[1]
    extension = tmp_path / "extension"
    shutil.copytree(source, extension, ignore=shutil.ignore_patterns("tests", "__pycache__"))
    manifest = json.loads((extension / "manifest.json").read_text(encoding="utf-8"))
    manifest["host_permissions"] = ["https://*/*"]
    (extension / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    requests = []
    fail = False
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            str(tmp_path / "profile"), channel="chromium", headless=True,
            args=[f"--disable-extensions-except={extension}", f"--load-extension={extension}"],
        )
        try:
            async def respond(route):
                requests.append((route.request.method, route.request.url))
                assert route.request.method == "GET"
                assert route.request.url.endswith(("/", "/index.php"))
                label = "签到得鲸币" if site_id == "hddolby.com" else "签到得U币"
                await route.fulfill(status=500 if fail else 200, content_type="text/html; charset=utf-8",
                    body=f'<div id="info_block">User U币: 456 上传量: 1 TB 下载量: 1 GB</div><a href="/attendance.php">{label}</a>')

            await context.route("https://**/*", respond)
            worker = context.service_workers[0] if context.service_workers else await context.wait_for_event("serviceworker")
            await worker.evaluate("""async siteId => {
                const day=today();
                await chrome.storage.local.set({autoEnabled:false,scheduleConfig:{startTime:'00:00',timeout:5},
                  sites:Object.fromEntries(sites.catalog.map(site=>[site.id,{enabled:site.id===siteId}])),
                  [sites.key('operation',siteId)]:{day,awaitingConfirmation:true,phase:'submitted',startedAt:123},
                  [sites.key('schedule',siteId)]:{day,attempts:4},
                  [sites.key('lastResult',siteId)]:{status:'error',confirmationFailed:true,message:'签到核验失败',time:new Date().toISOString()}});
                await reschedule();
                await chrome.storage.local.set({autoEnabled:true});
            }""", site_id)
            await worker.evaluate("async siteId => await alarmAction({name:alarmName('daily',siteId)})", site_id)
            state = await worker.evaluate("async siteId => await readState(siteId)", site_id)
            assert state["lastResult"]["status"] == "error"
            assert state["lastResult"]["refreshState"]["status"] == "success"
            assert state["lastResult"]["profile"]["uploaded"] == "1 TB"
            assert state["operation"] == {"day": state["operation"]["day"], "awaitingConfirmation": True, "phase": "submitted", "startedAt": 123}
            assert state["schedule"]["attempts"] == 4
            assert requests and all(url.startswith(f"https://{host}/") for _, url in requests)
            count = len(requests)
            await worker.evaluate("""async siteId => {
                await alarmAction({name:alarmName('daily',siteId)});
                await resumeSchedule();
            }""", site_id)
            assert len(requests) == count
            dashboard = await context.new_page()
            await dashboard.goto(f"chrome-extension://{worker.url.split('/')[2]}/dashboard.html")
            suffix = "" if site_id == "piggo" else "-" + site_id
            await expect(dashboard.locator(f'[id="site-status{suffix}"]')).to_have_text("签到失败")
            await expect(dashboard.locator(f'[id="refresh-status{suffix}"]')).to_have_text("已刷新")
            await expect(dashboard.locator("#refresh-count")).to_have_text("1 / 1")
            assert len(requests) == count
            fail = True
            await dashboard.locator(f'[id="refresh{suffix}"]').click()
            await expect(dashboard.locator(f'[id="refresh-status{suffix}"]')).to_have_text("刷新失败", timeout=15000)
            await expect(dashboard.locator(f'[id="site-status{suffix}"]')).to_have_text("签到失败")
            await expect(dashboard.locator(f'[id="profile-uploaded{suffix}"]')).to_have_text("1 TB")
            assert not any(page.url.startswith("https://") for page in context.pages)
        finally:
            await context.close()
