from pathlib import Path
import json
import shutil

import pytest
from playwright.async_api import async_playwright
from playwright.async_api import Error as PlaywrightError


@pytest.mark.asyncio
@pytest.mark.parametrize("site_id,mode", [
    ("hdvideo.top", "inspect"), ("hdvideo.top", "run"),
    ("ptsbao.club", "inspect"), ("ptsbao.club", "run"),
    ("52pt.site", "inspect"), ("52pt.site", "run"),
    ("pt.btschool.club", "inspect"), ("pt.btschool.club", "run"),
])
async def test_failed_sites_stop_with_precise_reason_and_preserve_profile(tmp_path, site_id, mode):
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
                requests.append((route.request.method, route.request.url))
                assert route.request.method == "GET"
                assert route.request.url.endswith(("/", "/index.php"))
                body = "站点关闭维护中，请稍后再访问...谢谢"
                if site_id == "52pt.site":
                    body = '<div id="info_block">魔力值: 123 上传量: 1 TB 下载量: 1 GB</div><a id="game" href="bakatestfinal.php">做种会员签到处</a>'
                if site_id == "pt.btschool.club":
                    body = '<title>btschool.club | 502: Bad gateway</title>Bad gateway Error code 502 You Browser Working Cloudflare Working pt.btschool.club Host Error Cloudflare Ray ID: fixture'
                await route.fulfill(status=502 if site_id == "pt.btschool.club" else 200, content_type="text/html; charset=utf-8", body=body)

            await context.route(f"https://{site_id}/**", respond)
            worker = context.service_workers[0] if context.service_workers else await context.wait_for_event("serviceworker")
            await worker.evaluate("""async siteId => {
                await chrome.storage.local.set({autoEnabled:false,scheduleConfig:{timeout:5},
                    sites:Object.fromEntries(sites.catalog.map(site=>[site.id,{enabled:site.id===siteId}])),
                    [sites.key('lastResult',siteId)]:{status:'error',profile:{level:'KEEP',bonus:'555'},profileTime:'2026-10-20T00:00:00Z'}});
                await reschedule();
            }""", site_id)
            result = await worker.evaluate("""async ({siteId,mode}) => mode==='run' ? await batchSignIn(siteId) : await refreshSite(siteId)""", {"siteId": site_id, "mode": mode})
            assert result["status"] == ("manual_required" if site_id == "52pt.site" else "error")
            assert ("限制脚本" if site_id == "52pt.site" else "HTTP 502" if site_id == "pt.btschool.club" else "维护") in result["message"]
            state = await worker.evaluate("async siteId => await readState(siteId)", site_id)
            assert state.get("verifiedDay") is None
            assert state.get("operation") is None
            assert state["lastResult"]["profile"]["level"] == "KEEP"
            assert state["lastResult"]["profile"]["bonus"] == "555"
            assert all(request[0] == "GET" and request[1].endswith(("/", "/index.php")) for request in requests)
            assert not any(page.url.startswith("https://") for page in context.pages)
        finally:
            await context.close()


@pytest.mark.asyncio
async def test_discfan_refresh_recovers_without_reusing_or_overwriting_chrome_error_page(tmp_path):
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
                requests.append((route.request.method, route.request.url))
                if len(requests) == 1:
                    await route.abort("connectionfailed")
                    return
                assert route.request.method == "GET"
                assert route.request.url.endswith(("/", "/index.php"))
                await route.fulfill(content_type="text/html; charset=utf-8", body='<meta charset="utf-8"><div id="info_block">魔力值: 123 上传量: 1 TB 下载量: 1 GB</div><a href="/attendance.php">[签到已得10]</a>')

            await context.route("https://discfan.net/**", respond)
            worker = context.service_workers[0] if context.service_workers else await context.wait_for_event("serviceworker")
            await worker.evaluate("""async () => {
                const day=sites.day();
                await chrome.storage.local.set({autoEnabled:false,scheduleConfig:{timeout:5},
                    sites:Object.fromEntries(sites.catalog.map(site=>[site.id,{enabled:site.id==='discfan.net'}])),
                    'operation:discfan.net':{day,awaitingConfirmation:true},
                    'lastResult:discfan.net':{status:'error',confirmationFailed:true}});
                await reschedule();
            }""")
            broken_page = await context.new_page()
            with pytest.raises(PlaywrightError):
                await broken_page.goto("https://discfan.net/index.php")
            await worker.evaluate("async () => await actionQueue")
            result = await worker.evaluate("async () => await refreshSite('discfan.net')")
            assert result["status"] == "already_done"
            state = await worker.evaluate("async () => await readState('discfan.net')")
            assert state["verifiedDay"]
            assert state["operation"]["awaitingConfirmation"] is False
            assert not broken_page.is_closed()
            assert len(context.pages) == 2
            assert all(method == "GET" and url.endswith(("/", "/index.php")) for method, url in requests)
        finally:
            await context.close()


@pytest.mark.asyncio
async def test_pterclub_confirms_server_completion_when_ajax_leaves_the_homepage_unchanged(tmp_path):
    source = Path(__file__).resolve().parents[1]
    extension = tmp_path / "extension"
    shutil.copytree(source, extension, ignore=shutil.ignore_patterns("tests", "__pycache__"))
    manifest_path = extension / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["host_permissions"] = ["https://*/*"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    requests = []
    signed = False
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            str(tmp_path / "profile"), channel="chromium", headless=True,
            args=[f"--disable-extensions-except={extension}", f"--load-extension={extension}"],
        )
        try:
            async def respond(route):
                nonlocal signed
                request = route.request
                requests.append((request.url, request.is_navigation_request()))
                if request.url.endswith("/attendance-ajax.php"):
                    signed = True
                    await route.fulfill(content_type="application/json", body='{"status":1}')
                    return
                body = '<meta charset="utf-8"><div id="info_block">猫粮: 123 上传量: 1 TB 下载量: 1 GB</div>'
                if signed:
                    body += '<table><tr><td>欢迎回来 fixture 猫粮: 148 (签到已得25)</td></tr></table>'
                else:
                    body += '''<a id="do-attendance" href="#">签到得猫粮</a><script>
document.getElementById('do-attendance').addEventListener('click',event=>{
event.preventDefault();fetch('/attendance-ajax.php',{credentials:'include'});
});</script>'''
                await route.fulfill(content_type="text/html; charset=utf-8", body=body)

            await context.route("https://pterclub.net/**", respond)
            worker = context.service_workers[0] if context.service_workers else await context.wait_for_event("serviceworker")
            await worker.evaluate("""async () => {
                await chrome.storage.local.set({autoEnabled:false,scheduleConfig:{timeout:5},
                    sites:Object.fromEntries(sites.catalog.map(site=>[site.id,{enabled:site.id==='pterclub.net'}]))});
                await reschedule();
            }""")
            result = await worker.evaluate("async () => await batchSignIn('pterclub.net')")
            assert result["status"] in ("already_done", "success")
            submission = ("https://pterclub.net/attendance-ajax.php", False)
            assert requests.count(submission) == 1
            submitted_at = requests.index(submission)
            assert ("https://pterclub.net/index.php", False) not in requests[:submitted_at]
            assert ("https://pterclub.net/index.php", False) in requests[submitted_at:]
            state = await worker.evaluate("async () => await readState('pterclub.net')")
            assert state["operation"]["awaitingConfirmation"] is False
            assert state["verifiedDay"]
            assert not any(page.url.startswith("https://pterclub.net") for page in context.pages)
        finally:
            await context.close()
