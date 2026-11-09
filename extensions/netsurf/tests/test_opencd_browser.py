from pathlib import Path
import json
import shutil
from urllib.parse import urlsplit

import pytest
from playwright.async_api import async_playwright, expect

from test_captcha_browser import sample


HOME = '''<meta charset="utf-8"><div id="info_block"><a href="/userdetails.php?id=42">fixture</a>魔力值: 123 上传量: 1 TB 下载量: 1 GB</div>
<a href="#" onclick="javascript:signin(this);">簽到</a>
<script>
function signin(source) {
  source.id='sign_in_span';
  const frame=document.createElement('iframe');frame.id='i_signin';frame.src='/plugin_sign-in.php';document.body.append(frame);
}
function do_signin(form) {
  fetch(form.action,{method:'POST',body:new URLSearchParams(new FormData(form))}).then(response=>response.json()).then(data=>{
    document.getElementById('i_signin').remove();
    if(data.state==='success') {const entry=document.getElementById('sign_in_span');entry.removeAttribute('onclick');entry.href='/plugin_sign-in.php?cmd=show-log';entry.textContent='已签到';}
  });
}
</script>'''

FORM = '''<meta charset="utf-8"><form id="frmSignin" action="plugin_sign-in.php?cmd=signin" method="post">
<input type="hidden" name="imagehash" value="fixture-token"><img src="/image.php?action=regimage&amp;imagehash=fixture-token">
<input id="imagestring" name="imagestring">
<button id="ok" onclick="javascript:do_signin(this);return false;">签到</button>
<button type="submit" onclick="parent.cancelled=true;return false;">算了</button></form>
<script>function do_signin(source){parent.do_signin(document.getElementById('frmSignin'));}</script>'''


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["success", "unconfirmed", "unreliable", "readonly"])
async def test_opencd_iframe_local_ocr(tmp_path, outcome):
    source = Path(__file__).resolve().parents[1]
    extension = tmp_path / "extension"
    shutil.copytree(source, extension, ignore=shutil.ignore_patterns("tests", "__pycache__"))
    manifest_path = extension / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["host_permissions"] = ["https://*/*"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    submissions = []
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
                elif target.path == "/plugin_sign-in.php" and route.request.method == "POST":
                    submissions.append(route.request.post_data)
                    await route.fulfill(json={"state": "success" if outcome == "success" else "unknown"})
                else:
                    await route.fulfill(content_type="text/html; charset=utf-8", body=FORM if target.path == "/plugin_sign-in.php" else HOME)

            await context.route("https://**/*", respond)
            worker = context.service_workers[0] if context.service_workers else await context.wait_for_event("serviceworker")
            await worker.evaluate("""async readOnly => {
                await chrome.storage.local.set({autoEnabled:false, sites:Object.fromEntries(sites.catalog.map(site=>[site.id,{enabled:site.id==='open.cd',refreshOnly:readOnly&&site.id==='open.cd'}])),scheduleConfig:{timeout:8}});
                await syncScripts(await readState());
            }""", outcome == "readonly")
            site_page = await context.new_page()
            await site_page.goto("https://open.cd/")
            await site_page.evaluate("window.userMarker='keep'")
            dashboard = await context.new_page()
            await dashboard.goto(f"chrome-extension://{worker.url.split('/')[2]}/dashboard.html#overview")
            button = dashboard.locator('[id="run-open.cd"]')
            await expect(button).to_be_enabled(timeout=15000)
            await button.click()
            await expect(button).to_be_enabled(timeout=20000)
            state = await worker.evaluate("async () => await readState('open.cd')")
            if outcome == "success":
                assert state["lastResult"]["status"] == "already_done"
                assert state.get("verifiedDay")
                assert state["operation"]["phase"] == "submitted"
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
                assert await site_page.locator("#i_signin").count() == 0
            assert len(submissions) == (1 if outcome in ["success", "unconfirmed"] else 0)
            if submissions:
                assert "imagestring=ABC123" in submissions[0]
            assert "ABC123" not in json.dumps(await worker.evaluate("async () => await chrome.storage.local.get(null)"))
            assert await site_page.evaluate("window.userMarker") == "keep"
            assert not await site_page.evaluate("Boolean(window.cancelled)")
            assert not site_page.is_closed()
            assert await worker.evaluate("async () => (await chrome.runtime.getContexts({contextTypes:['OFFSCREEN_DOCUMENT']})).length") == 0
        finally:
            await context.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["none", "hash", "action", "image", "frame", "input_event", "permission", "duplicate", "other_captcha", "password"])
async def test_opencd_rejects_changed_iframe_form(tmp_path, change):
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
                    await route.fulfill(content_type="text/html; charset=utf-8", body=FORM if target.path == "/plugin_sign-in.php" else HOME)
            await page.route("https://open.cd/**", respond)
            await page.goto("https://open.cd/")
            await page.locator("a[onclick]").click()
            await expect(page.frame_locator("#i_signin").locator("#ok")).to_be_visible()
            await page.add_script_tag(path=str(source / "hdsky.js"))
            await page.add_script_tag(path=str(source / "opencd.js"))
            result = await page.evaluate("""async change => {
                window.clicked=0;window.do_signin=()=>window.clicked++;
                const frame=document.getElementById('i_signin');const nested=frame.contentDocument;
                if(change==='input_event') nested.getElementById('imagestring').addEventListener('input',()=>{nested.querySelector('[name=imagehash]').value='changed';});
                return NetSurfOpenCd.signin(document,location.href,element=>element.getBoundingClientRect().width>0,123,2000,async message=>{
                    if(message.type==='captcha-recognize') {
                        if(change==='hash') nested.querySelector('[name=imagehash]').value='changed';
                        if(change==='action') nested.forms[0].action='/other';
                        if(change==='image') {nested.images[0].src='/image.php?blank';await nested.images[0].decode();}
                        if(change==='frame') frame.src='/other';
                        if(change==='duplicate') nested.body.append(nested.getElementById('ok').cloneNode(true));
                        if(change==='other_captcha') {const extra=nested.createElement('input');extra.name='recaptcha_response_field';nested.body.append(extra);}
                        if(change==='password') nested.getElementById('imagestring').type='password';
                        return {accepted:true,answer:'ABC123',ticket:'own'};
                    }
                    return {accepted:change!=='permission'};
                });
            }""", change)
            assert result["status"] == ("pending" if change == "none" else "error" if change == "input_event" else "manual_required")
            assert await page.evaluate("window.clicked") == (1 if change == "none" else 0)
            assert not await page.evaluate("Boolean(window.cancelled)")
        finally:
            await browser.close()
