from pathlib import Path
import base64
import json
import shutil

import cv2
import numpy as np
import pytest
from playwright.async_api import async_playwright, expect


def sample(blank=False):
    image = np.full((64, 260, 3), 255, np.uint8)
    if not blank:
        cv2.putText(image, "ABC123", (8, 47), cv2.FONT_HERSHEY_SIMPLEX, 1.3, (0, 0, 0), 2, cv2.LINE_AA)
    return cv2.imencode(".png", image)[1].tobytes()


@pytest.mark.asyncio
async def test_bundled_offscreen_wasm_model(tmp_path):
    source = Path(__file__).resolve().parents[1]
    extension = tmp_path / "extension"
    shutil.copytree(source, extension, ignore=shutil.ignore_patterns("tests", "__pycache__"))
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            str(tmp_path / "profile"), channel="chromium", headless=True,
            args=[f"--disable-extensions-except={extension}", f"--load-extension={extension}"],
        )
        try:
            worker = context.service_workers[0] if context.service_workers else await context.wait_for_event("serviceworker")
            for blank in [False, True]:
                payload = "data:image/png;base64," + base64.b64encode(sample(blank)).decode()
                result = await worker.evaluate("""async image => {
                    await chrome.offscreen.createDocument({url: 'ocr.html', reasons: ['BLOBS'], justification: 'Test local PNG decoding and OCR'});
                    try { return await chrome.runtime.sendMessage({type: 'netsurf-ocr-infer', image}); }
                    finally { await chrome.offscreen.closeDocument(); }
                }""", payload)
                assert result == {"answer": None if blank else "ABC123"}
                assert await worker.evaluate("async () => (await chrome.runtime.getContexts({contextTypes:['OFFSCREEN_DOCUMENT']})).length") == 0
        finally:
            await context.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["image", "permission", "input_event", "completed"])
async def test_hdsky_rejects_stale_image_or_permit(tmp_path, change):
    source = Path(__file__).resolve().parents[1]
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(channel="chromium", headless=True)
        try:
            page = await browser.new_page()
            async def respond(route):
                if route.request.url.endswith(".png"):
                    await route.fulfill(content_type="image/png", body=sample("blank" in route.request.url))
                else:
                    await route.fulfill(content_type="text/html; charset=utf-8", body='<a id="showup">签到</a><img id="showupimg" src="/sample.png"><input id="imagestring"><button id="showupbutton" onclick="window.clicked++">Let\'s Go</button>')
            await page.route("https://hdsky.me/**", respond)
            await page.goto("https://hdsky.me/")
            await page.add_script_tag(path=str(source / "hdsky.js"))
            result = await page.evaluate("""async change => {
                window.clicked = 0;
                const image = document.getElementById('showupimg');
                const replace = async () => {image.src='/blank.png'; await image.decode();};
                if (change === 'input_event') document.getElementById('imagestring').addEventListener('input', () => {image.src='/blank.png';});
                return await NetSurfHdsky.signin(document, location.href, element => element.getBoundingClientRect().width > 0, 123, 3000, async message => {
                    if (message.type === 'captcha-recognize') {if (change === 'image') await replace(); if (change === 'completed') document.getElementById('showup').textContent='已签到'; return {accepted:true, answer:'ABC123', ticket:'own'};}
                    return {accepted:change!=='permission'};
                });
            }""", change)
            assert result["status"] == ("already_done" if change == "completed" else "error" if change == "input_event" else "manual_required")
            assert await page.evaluate("window.clicked") == 0
        finally:
            await browser.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["success", "unconfirmed", "unreliable", "readonly"])
async def test_hdsky_local_ocr_signin(tmp_path, outcome):
    source = Path(__file__).resolve().parents[1]
    extension = tmp_path / "extension"
    shutil.copytree(source, extension, ignore=shutil.ignore_patterns("tests", "__pycache__"))
    manifest_path = extension / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["host_permissions"] = ["https://*/*"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    submissions = []
    errors = []
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            str(tmp_path / "profile"), channel="chromium", headless=True,
            args=[f"--disable-extensions-except={extension}", f"--load-extension={extension}"],
        )
        try:
            async def route_page(route):
                from urllib.parse import urlsplit

                target = urlsplit(route.request.url)
                if target.path == "/image.php":
                    await route.fulfill(content_type="image/png", body=sample(outcome == "unreliable"))
                elif target.path == "/fixture-submit":
                    submissions.append(route.request.post_data)
                    await route.fulfill(json={"ok": True})
                else:
                    completed = "document.getElementById('showup').textContent='已签到(Showed Up)';document.getElementById('popup').hidden=true;" if outcome == "success" else ""
                    body = f'''<meta charset="utf-8"><div id="info_block"><a href="/userdetails.php?id=42">fixture</a>魔力值: 123 上传量: 1 TB 下载量: 1 GB</div>
                    <a href="#" id="showup" onclick="document.getElementById('popup').hidden=false;return false">签到(Show Up)</a>
                    <div id="popup" hidden><img id="showupimg" alt="CAPTCHA" src="/image.php"><input id="imagestring" name="imagestring">
                    <button id="showupbutton" onclick="fetch('/fixture-submit',{{method:'POST',body:document.getElementById('imagestring').value}}).then(()=>{{{completed}}})">Let's Go</button></div>'''
                    await route.fulfill(content_type="text/html; charset=utf-8", body=body)

            await context.route("https://**/*", route_page)
            worker = context.service_workers[0] if context.service_workers else await context.wait_for_event("serviceworker")
            await worker.evaluate("""async readOnly => {
                await chrome.storage.local.set({autoEnabled:false, sites:Object.fromEntries(sites.catalog.map(site => [site.id,{enabled:site.id==='hdsky.me',refreshOnly:readOnly&&site.id==='hdsky.me'}])),scheduleConfig:{timeout:8}});
                await syncScripts(await readState());
            }""", outcome == "readonly")
            site_page = await context.new_page()
            await site_page.goto("https://hdsky.me/")
            await site_page.evaluate("window.userMarker = 'keep'")
            dashboard = await context.new_page()
            dashboard.on("pageerror", lambda error: errors.append(str(error)))
            await dashboard.goto(f"chrome-extension://{worker.url.split('/')[2]}/dashboard.html#overview")
            button = dashboard.locator('[id="run-hdsky.me"]')
            await expect(button).to_be_enabled(timeout=15000)
            await button.click()
            await expect(button).to_be_enabled(timeout=20000)
            state = await worker.evaluate("async () => await readState('hdsky.me')")
            if outcome == "success":
                assert state["lastResult"]["status"] in ["success", "already_done"]
                assert state.get("verifiedDay")
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
                assert not await site_page.locator("#popup").is_visible()
            assert submissions == (["ABC123"] if outcome in ["success", "unconfirmed"] else [])
            assert "ABC123" not in json.dumps(await worker.evaluate("async () => await chrome.storage.local.get(null)"))
            assert await site_page.evaluate("window.userMarker") == "keep"
            assert not site_page.is_closed()
            assert await worker.evaluate("async () => (await chrome.runtime.getContexts({contextTypes:['OFFSCREEN_DOCUMENT']})).length") == 0
            assert not errors
        finally:
            await context.close()
