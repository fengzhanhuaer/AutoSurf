from pathlib import Path
import asyncio
import json
import shutil

import pytest
from playwright.async_api import async_playwright


@pytest.mark.asyncio
async def test_terminal_failure_does_not_reopen_pages_after_auto_alarm_or_restart(tmp_path):
    source = Path(__file__).resolve().parents[1]
    extension = tmp_path / "extension"
    shutil.copytree(source, extension, ignore=shutil.ignore_patterns("tests", "__pycache__"))
    manifest_path = extension / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["host_permissions"] = ["https://*/*"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    requests = []
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            str(tmp_path / "profile"), channel="chromium", headless=True,
            args=[f"--disable-extensions-except={extension}", f"--load-extension={extension}"],
        )
        try:
            async def respond(route):
                requests.append(route.request.url)
                await route.fulfill(content_type="text/html; charset=utf-8", body='<meta charset="utf-8"><div id="info_block">U币: 123 上传量: 1 TB 下载量: 1 GB</div><a href="/attendance.php">签到得U币</a>')
            await context.route("https://**/*", respond)
            worker = context.service_workers[0] if context.service_workers else await context.wait_for_event("serviceworker")
            await worker.evaluate("""async () => {
                const day=sites.day();
                await chrome.storage.local.set({autoEnabled:true,sites:Object.fromEntries(sites.catalog.map(site=>[site.id,{enabled:site.id==='ubits.club'}])),
                    'refreshSchedule:ubits.club':{day},'operation:ubits.club':{day,awaitingConfirmation:true},'schedule:ubits.club':{day,attempts:4,verifyAt:Date.now()-1000},
                    'lastResult:ubits.club':{status:'error',confirmationFailed:true}});
                await reschedule();
            }""")
            site_page = await context.new_page()
            await site_page.goto("https://ubits.club/index.php")
            await site_page.evaluate("window.userMarker='keep'")
            await worker.evaluate("async () => await actionQueue")
            request_count = len(requests)
            page_count = len(context.pages)
            await worker.evaluate("""async () => {
                for(let round=0;round<3;round+=1) {
                    for(const type of ['daily','retry','verify']) await alarmAction({name:`netsurf-${type}:ubits.club`});
                    await resumeSchedule();
                }
            }""")
            assert len(requests) == request_count
            assert len(context.pages) == page_count
            assert await site_page.evaluate("window.userMarker") == "keep"
            state = await worker.evaluate("async () => await readState('ubits.club')")
            assert state["operation"]["awaitingConfirmation"] is True
            assert state["lastResult"]["confirmationFailed"] is True
            assert state["schedule"]["attempts"] == 4
            alarms = await worker.evaluate("async () => (await chrome.alarms.getAll()).map(alarm=>alarm.name)")
            assert "netsurf-retry:ubits.club" not in alarms
            assert "netsurf-verify:ubits.club" not in alarms
            for iteration in range(3):
                dashboard = await context.new_page()
                await dashboard.goto(f"chrome-extension://{worker.url.split('/')[2]}/dashboard.html#overview")
                await worker.evaluate("async () => await actionQueue")
                await dashboard.wait_for_timeout(250)
                assert len(requests) == request_count
                assert len(context.pages) == page_count + 1
                await dashboard.close()
            dashboard = await context.new_page()
            await dashboard.goto(f"chrome-extension://{worker.url.split('/')[2]}/dashboard.html#overview")
            await worker.evaluate("async () => await actionQueue")
            await dashboard.wait_for_function("() => document.querySelector('button[id=\"refresh-ubits.club\"]')?.disabled===false")
            await dashboard.locator('button[id="refresh-ubits.club"]').click()
            await dashboard.wait_for_function("() => document.querySelector('button[id=\"refresh-ubits.club\"]')?.disabled===false")
            await worker.evaluate("async () => await actionQueue")
            assert len(requests) > request_count
            assert await worker.evaluate("async () => (await readState('ubits.club')).operation.awaitingConfirmation") is True
        finally:
            await context.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("site_id,signin_label,reward", [
    ("ubits.club", "[签到得U币]", "25个U币"),
    ("ptsbao.club", "[签到得魔力]", "25个魔力"),
    ("ourbits.club", "签到得魔力", "100 个魔力值"),
    ("ptcafe.club", "[签到得魔力]", "20 个魔力值"),
    ("pttime.org", "签到领魔力", "20 个魔力值"),
])
async def test_loaded_homepage_does_not_refetch_before_single_signin(tmp_path, site_id, signin_label, reward):
    source = Path(__file__).resolve().parents[1]
    extension = tmp_path / "extension"
    shutil.copytree(source, extension, ignore=shutil.ignore_patterns("tests", "__pycache__"))
    manifest_path = extension / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["host_permissions"] = ["https://*/*"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    requests = []
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            str(tmp_path / "profile"), channel="chromium", headless=True,
            args=[f"--disable-extensions-except={extension}", f"--load-extension={extension}"],
        )
        try:
            async def respond(route):
                request = route.request
                requests.append((request.url, request.is_navigation_request()))
                if "/attendance.php" in request.url:
                    if site_id == "ourbits.club":
                        await asyncio.sleep(1)
                    body = f"签到成功，这是您的第374次签到，本次签到获得{reward}。"
                else:
                    if not request.is_navigation_request():
                        await asyncio.sleep(10)
                    target = "/attendance.php?type=sign&uid=42" if site_id == "pttime.org" else "/attendance.php"
                    body = f'<div id="info_block"><a href="/userdetails.php?id=42">fixture</a>魔力值: 123 U币: 123 上传量: 1 TB 下载量: 1 GB</div><a href="{target}">{signin_label}</a>'
                await route.fulfill(content_type="text/html; charset=utf-8", body=body)

            worker = context.service_workers[0] if context.service_workers else await context.wait_for_event("serviceworker")
            origin = await worker.evaluate("siteId => sites.get(siteId).origin", site_id)
            target = origin + ("/attendance.php?type=sign&uid=42" if site_id == "pttime.org" else "/attendance.php")
            await context.route(f"{origin}/**", respond)
            await worker.evaluate("""async siteId => {
                await chrome.storage.local.set({autoEnabled:false,scheduleConfig:{timeout:5},
                    sites:Object.fromEntries(sites.catalog.map(site=>[site.id,{enabled:site.id===siteId}]))});
                await reschedule();
            }""", site_id)
            result = await worker.evaluate("async siteId => await batchSignIn(siteId)", site_id)
            assert result["status"] in ("success", "already_done"), (result, requests, await worker.evaluate("async siteId => await readState(siteId)", site_id))
            assert requests.count((target, True)) == 1
            submission_index = requests.index((target, True))
            assert (f"{origin}/index.php", False) not in requests[:submission_index]
            state = await worker.evaluate("async siteId => await readState(siteId)", site_id)
            assert state["verifiedDay"]
            assert state["operation"]["awaitingConfirmation"] is False
            if site_id == "ourbits.club":
                submissions = requests.count((f"https://{site_id}/attendance.php", True))
                await worker.evaluate("async siteId => await batchSignIn(siteId)", site_id)
                assert requests.count((f"https://{site_id}/attendance.php", True)) == submissions
                assert await worker.evaluate("async siteId => (await readState(siteId)).verifiedDay", site_id)
        finally:
            await context.unroute_all(behavior="wait")
            await context.close()
