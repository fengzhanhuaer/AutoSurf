from pathlib import Path
import json
import shutil
from urllib.parse import urlsplit

import pytest
from playwright.async_api import async_playwright, expect

from test_captcha_browser import sample


HOME = '<meta charset="utf-8"><div id="info_block">用户等级: Power User 魔力值: 123 上传量: 1 TB 下载量: 1 GB</div><a href="attendance.php">[签到得魔力]</a>'
FORM = '''<meta charset="utf-8"><form action="attendance.php" method="post">
<img src="image.php?action=regimage&amp;imagehash=fixture-token&amp;secret=">
<input name="imagestring"><input type="hidden" name="imagehash" value="fixture-token">
<input type="submit" value="立即签到"></form>'''


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["success", "unconfirmed", "unreliable", "readonly"])
async def test_ptsbao_uses_local_ocr_and_submits_one_form(tmp_path, outcome):
    source = Path(__file__).resolve().parents[1]
    extension = tmp_path / "extension"
    shutil.copytree(source, extension, ignore=shutil.ignore_patterns("tests", "__pycache__"))
    manifest_path = extension / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["host_permissions"] = ["https://*/*"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    submissions = []
    entries = []
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            str(tmp_path / "profile"), channel="chromium", headless=True,
            args=[f"--disable-extensions-except={extension}", f"--load-extension={extension}"],
        )
        try:
            async def respond(route):
                target = urlsplit(route.request.url)
                if target.path == "/image.php":
                    await route.fulfill(content_type="image/png", body=sample(outcome == "unreliable"))
                elif target.path == "/attendance.php" and route.request.method == "POST":
                    submissions.append(route.request.post_data)
                    await route.fulfill(content_type="text/html; charset=utf-8", body="签到成功，本次签到获得25个魔力。" if outcome == "success" else "未取得明确结果")
                elif target.path == "/attendance.php":
                    entries.append(route.request.url)
                    await route.fulfill(content_type="text/html; charset=utf-8", body=HOME + FORM)
                else:
                    await route.fulfill(content_type="text/html; charset=utf-8", body=HOME)

            await context.route("https://ptsbao.club/**", respond)
            worker = context.service_workers[0] if context.service_workers else await context.wait_for_event("serviceworker")
            await worker.evaluate("""async readOnly => {
                await chrome.storage.local.set({autoEnabled:false,scheduleConfig:{timeout:8},
                    sites:Object.fromEntries(sites.catalog.map(site=>[site.id,{enabled:site.id==='ptsbao.club',refreshOnly:readOnly&&site.id==='ptsbao.club'}]))});
                await syncScripts(await readState());
            }""", outcome == "readonly")
            original = context.pages[0]
            await original.evaluate("window.userMarker='keep'")
            dashboard = await context.new_page()
            await dashboard.goto(f"chrome-extension://{worker.url.split('/')[2]}/dashboard.html#overview")
            button = dashboard.locator('[id="run-ptsbao.club"]')
            await expect(button).to_be_enabled(timeout=15000)
            await button.click()
            await expect(button).to_be_enabled(timeout=20000)
            state = await worker.evaluate("async () => await readState('ptsbao.club')")
            if outcome == "success":
                assert state["lastResult"]["status"] in ("success", "already_done")
                assert state.get("verifiedDay")
                assert state["operation"]["phase"] == "submitted"
                assert state["operation"]["awaitingConfirmation"] is False
            elif outcome == "unconfirmed":
                assert state["lastResult"]["status"] == "error"
                assert not state.get("verifiedDay")
                await button.click()
                await expect(button).to_be_enabled(timeout=20000)
            elif outcome == "unreliable":
                assert state["lastResult"]["status"] == "manual_required"
                assert not state.get("verifiedDay")
            else:
                assert state["lastResult"]["status"] == "refreshed"
            assert len(submissions) == (1 if outcome in ("success", "unconfirmed") else 0)
            assert len(entries) == (0 if outcome == "readonly" else 1)
            if submissions:
                assert "imagestring=ABC123" in submissions[0]
                assert "imagehash=fixture-token" in submissions[0]
            assert "ABC123" not in json.dumps(await worker.evaluate("async () => await chrome.storage.local.get(null)"))
            assert await original.evaluate("window.userMarker") == "keep"
            assert len(context.pages) == 2
            assert await worker.evaluate("async () => (await chrome.runtime.getContexts({contextTypes:['OFFSCREEN_DOCUMENT']})).length") == 0
        finally:
            await context.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["none", "hash", "action", "image", "input_event", "permission", "duplicate", "other_captcha", "password", "method", "extra_field", "submit_override"])
async def test_ptsbao_rejects_changed_form_or_lost_permission(tmp_path, change):
    source = Path(__file__).resolve().parents[1]
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(channel="chromium", headless=True)
        try:
            page = await browser.new_page()

            async def respond(route):
                target = urlsplit(route.request.url)
                if target.path == "/image.php":
                    await route.fulfill(content_type="image/png", body=sample(target.query == "blank"))
                else:
                    await route.fulfill(content_type="text/html; charset=utf-8", body=FORM)

            await page.route("https://ptsbao.club/**", respond)
            await page.goto("https://ptsbao.club/attendance.php")
            await page.add_script_tag(path=str(source / "hdsky.js"))
            await page.add_script_tag(path=str(source / "ptsbao.js"))
            result = await page.evaluate("""async change => {
                window.clicked=0;
                document.querySelector('[type=submit]').addEventListener('click',event=>{event.preventDefault();window.clicked++;});
                if(change==='input_event') document.querySelector('[name=imagestring]').addEventListener('input',()=>{document.querySelector('[name=imagehash]').value='changed';});
                return NetSurfPtsbao.signin(document,location.href,element=>element.getBoundingClientRect().width>0,123,2000,async message=>{
                    if(message.type==='captcha-recognize') {
                        if(change==='hash') document.querySelector('[name=imagehash]').value='changed';
                        if(change==='action') document.forms[0].action='/other';
                        if(change==='image') {document.images[0].src='/image.php?blank';await document.images[0].decode();}
                        if(change==='duplicate') document.forms[0].append(document.querySelector('[type=submit]').cloneNode(true));
                        if(change==='other_captcha') {const extra=document.createElement('input');extra.name='captcha';document.forms[0].append(extra);}
                        if(change==='password') document.querySelector('[name=imagestring]').type='password';
                        if(change==='method') document.forms[0].method='get';
                        if(change==='extra_field') {const extra=document.createElement('input');extra.type='hidden';extra.name='action';extra.value='other';document.forms[0].append(extra);}
                        if(change==='submit_override') document.querySelector('[type=submit]').setAttribute('formaction','https://evil.test/attendance.php');
                        return {accepted:true,answer:'ABC123',ticket:'own'};
                    }
                    return {accepted:change!=='permission'};
                });
            }""", change)
            assert result["status"] == ("pending" if change == "none" else "error" if change == "input_event" else "manual_required")
            assert await page.evaluate("window.clicked") == (1 if change == "none" else 0)
        finally:
            await browser.close()
