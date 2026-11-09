from pathlib import Path
import asyncio
import json
import shutil
from urllib.parse import urlsplit, parse_qs

import pytest
from playwright.async_api import async_playwright


PT52_FORM = '''<meta charset="utf-8"><form method="post">
<div id="slider-container" style="position:relative;width:260px;height:40px">
<div id="slider-bg"></div><div id="slider-btn" style="position:absolute;width:50px;height:36px;left:2px;top:2px">→</div></div>
<input type="hidden" name="sign_captcha" id="sign_captcha" value="">
<input type="hidden" name="sign_token" value="fixturetoken123456789">
<input type="hidden" name="sign_submit" value="1">
<button type="submit" id="submit-btn" disabled>请先完成滑块</button></form>
<script>const slider=document.getElementById('slider-btn');let dragging=false,startX=0;
slider.addEventListener('mousedown',event=>{dragging=true;startX=event.clientX});
document.addEventListener('mousemove',event=>{if(dragging)slider.style.left=Math.max(0,Math.min(206,2+event.clientX-startX))+'px'});
document.addEventListener('mouseup',()=>{if(!dragging)return;dragging=false;
if(parseInt(slider.style.left)>=196){document.getElementById('sign_captcha').value='7391';const button=document.getElementById('submit-btn');button.disabled=false;button.textContent='提交签到'}});</script>'''
TURNSTILE_FORM = '''<meta charset="utf-8"><div class="attendance-card">每日签到 完成人机验证即可领取今日爆米花奖励
<form id="attendance-form" action="attendance.php" method="post">
<input type="hidden" name="cf-token" id="cf-token" value="">
<div class="cf-turnstile" data-sitekey="0x4AAAAAABfcR5-BOyur3FT4" data-callback="cfCallback"></div></form></div>
<script src="https://challenges.cloudflare.com/turnstile/v0/api.js"></script>'''


@pytest.mark.asyncio
@pytest.mark.parametrize("site_id,outcome", [
    ("52pt.site", "success"), ("52pt.site", "unconfirmed"), ("52pt.site", "readonly"),
    ("52pt.site", "rotating"), ("52pt.site", "false_success"), ("52pt.site", "persistent_form"),
    ("audiences.me", "success"), ("audiences.me", "slow_home"), ("audiences.me", "failure"), ("audiences.me", "timeout"), ("audiences.me", "readonly"),
])
async def test_dual_attendance_lifecycle(tmp_path, site_id, outcome):
    source = Path(__file__).resolve().parents[1]
    extension = tmp_path / "extension"
    shutil.copytree(source, extension, ignore=shutil.ignore_patterns("tests", "__pycache__"))
    manifest_path = extension / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["host_permissions"] = ["https://*/*"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    requests = []
    slow_requests = []
    signed = False
    challenge_number = 0
    successful = ("success", "slow_home", "rotating", "persistent_form")
    home = '<meta charset="utf-8"><div id="info_block">魔力值: 123 上传量: 1 TB 下载量: 1 GB</div>'
    home += '<a href="52bakatestdate0823.php">签到赚魔力</a>' if site_id == "52pt.site" else '<a href="attendance.php">签到</a>'
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            str(tmp_path / "profile"), channel="chromium", headless=True,
            args=[f"--disable-extensions-except={extension}", f"--load-extension={extension}"],
        )
        try:
            async def respond(route):
                nonlocal signed, challenge_number
                target = urlsplit(route.request.url)
                if target.hostname == "challenges.cloudflare.com":
                    script = "setTimeout(()=>document.getElementById('attendance-form').submit(),800)" if outcome in ("success", "slow_home") else "setTimeout(()=>document.querySelector('.attendance-card').append(' 验证失败'),500)" if outcome == "failure" else ""
                    await route.fulfill(content_type="application/javascript", body=script)
                    return
                requests.append((route.request.method, target.path))
                if target.path == "/fixture-slow.js":
                    slow_requests.append(asyncio.current_task())
                    await asyncio.sleep(15)
                    await route.fulfill(content_type="application/javascript", body="")
                    return
                if target.path == "/52bakatestdate0823.php":
                    body = "签到页面已暂停使用"
                elif target.path in ("/bakatest.php", "/attendance.php"):
                    if route.request.method == "POST":
                        signed = outcome in successful
                        if site_id == "52pt.site":
                            fields = parse_qs(route.request.post_data)
                            assert fields["sign_captcha"] == [str(7000 + challenge_number) if outcome == "rotating" else "7391"]
                            if outcome == "rotating":
                                assert fields["sign_token"] == [f"fixturetoken{challenge_number:016d}"]
                        body = home + ("签到成功，本次签到获得20魔力值" if signed else PT52_FORM + "公告：签到成功" if outcome == "false_success" else "处理中")
                    elif signed and outcome != "persistent_form":
                        body = home + "今日已签到"
                    else:
                        challenge_number += 1
                        form = PT52_FORM.replace("fixturetoken123456789", f"fixturetoken{challenge_number:016d}").replace("7391", str(7000 + challenge_number)) if outcome == "rotating" else PT52_FORM
                        body = home + (form if site_id == "52pt.site" else TURNSTILE_FORM)
                else:
                    body = home + ('<script src="/fixture-slow.js"></script>' if outcome == "slow_home" else '')
                await route.fulfill(content_type="text/html; charset=utf-8", body=body)
            await context.route("https://**/*", respond)
            worker = context.service_workers[0] if context.service_workers else await context.wait_for_event("serviceworker")
            await worker.evaluate("""async ({siteId,readOnly})=>{
                await chrome.storage.local.set({autoEnabled:false,scheduleConfig:{timeout:7},
                    sites:Object.fromEntries(sites.catalog.map(site=>[site.id,{enabled:site.id===siteId,refreshOnly:readOnly&&site.id===siteId}]))});
                await syncScripts(await readState());
            }""", {"siteId": site_id, "readOnly": outcome == "readonly"})
            result = await worker.evaluate("async id=>await batchSignIn(id)", site_id)
            state = await worker.evaluate("async id=>await readState(id)", site_id)
            posts = [path for method, path in requests if method == "POST"]
            expected = ["/bakatest.php" if site_id == "52pt.site" else "/attendance.php"] if outcome in (*successful, "unconfirmed", "false_success") else []
            assert posts == expected, (result, requests)
            assert not any(path == "/52bakatestdate0823.php" for method, path in requests)
            if outcome in successful:
                assert result["status"] in ("success", "already_done"), result
                assert state["verifiedDay"]
                assert not state["operation"]["awaitingConfirmation"]
            elif outcome == "readonly":
                assert result["status"] == "refreshed", result
            elif outcome in ("timeout", "failure"):
                assert result["status"] == "blocked", result
                assert not state.get("verifiedDay")
            else:
                assert result["status"] == "error", result
                assert state["operation"]["awaitingConfirmation"]
            if outcome in (*successful, "unconfirmed", "false_success"):
                await worker.evaluate("async id=>await batchSignIn(id)", site_id)
                assert [path for method, path in requests if method == "POST"] == expected
            if outcome == "persistent_form" or site_id == "audiences.me" and outcome in successful:
                refreshed = await worker.evaluate("async id=>await refreshSite(id)", site_id)
                assert refreshed["status"] == "already_done", refreshed
                assert (await worker.evaluate("async id=>await readState(id)", site_id))["verifiedDay"]
            assert len(context.pages) == 1
        finally:
            for pending in slow_requests:
                if not pending.done():
                    pending.cancel()
            await asyncio.gather(*slow_requests, return_exceptions=True)
            await context.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["none", "permission", "token", "form", "geometry", "duplicate", "mid_drag", "mouseup", "expired", "origin", "path"])
async def test_pt52_slider_mutation(change):
    source = Path(__file__).resolve().parents[1]
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(channel="chromium", headless=True)
        try:
            page = await browser.new_page()
            await page.route("https://**/*", lambda route: route.fulfill(content_type="text/html; charset=utf-8", body=PT52_FORM))
            await page.goto("https://52pt.site/bakatest.php")
            await page.add_script_tag(path=str(source / "pt52.js"))
            result = await page.evaluate("""async change=>{
                let clicks=0,downs=0;document.querySelector('form').addEventListener('submit',event=>{event.preventDefault();clicks++});
                document.addEventListener('mousedown',()=>downs++);
                if(change==='duplicate')document.body.append(document.getElementById('slider-btn').cloneNode());
                if(change==='mid_drag')document.addEventListener('mousemove',()=>document.querySelector('[name=sign_token]').value='changedtoken123456789',{once:true});
                if(change==='mouseup')document.addEventListener('mouseup',()=>document.querySelector('form').action='/logout.php',{once:true});
                let url=location.href;if(change==='origin')url='https://evil.test/bakatest.php';if(change==='path')url='https://52pt.site/logout.php';
                const clock=Date.now.bind(Date);
                const result=await NetSurfPt52.signin(document,url,element=>element.getBoundingClientRect().width>0,42,3000,async()=>{
                    if(change==='token')document.querySelector('[name=sign_token]').value='changedtoken123456789';
                    if(change==='form')document.querySelector('form').action='/logout.php';
                    if(change==='geometry')document.getElementById('slider-container').style.width='400px';
                    if(change==='expired')Date.now=()=>clock()+5000;
                    return {accepted:change!=='permission'};
                });return {result,clicks,downs};
            }""", change)
            assert result["result"]["status"] == ("pending" if change == "none" else "manual_required")
            assert result["clicks"] == (1 if change == "none" else 0)
        finally:
            await browser.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["none", "key", "method", "action", "script", "duplicate", "failure", "origin", "query"])
async def test_audiences_waits_only_for_its_known_official_widget(change):
    source = Path(__file__).resolve().parents[1]
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(channel="chromium", headless=True)
        try:
            page = await browser.new_page()
            await page.route("https://**/*", lambda route: route.fulfill(content_type="application/javascript" if route.request.url.endswith(".js") else "text/html; charset=utf-8", body="" if route.request.url.endswith(".js") else TURNSTILE_FORM))
            await page.goto("https://audiences.me/attendance.php")
            for script in ("catalog.js", "site-rules.js", "sites.js", "piggo.js"):
                await page.add_script_tag(path=str(source / script))
            result = await page.evaluate("""change=>{
                const form=document.getElementById('attendance-form');let url=location.href;
                if(change==='key')form.querySelector('.cf-turnstile').dataset.sitekey='unknown';
                if(change==='method')form.method='get';
                if(change==='action')form.action='/logout.php';
                if(change==='script')document.querySelector('script[src]').src='https://evil.test/api.js';
                if(change==='duplicate')document.body.append(form.cloneNode(true));
                if(change==='failure')document.querySelector('.attendance-card').append(' 验证失败');
                if(change==='origin')url='https://evil.test/attendance.php';
                if(change==='query')url+='?action=delete';
                const result=NetSurfPiggo.create('https://audiences.me').inspect(document,url);
                return {status:result.status,pending:result.challengePending===true};
            }""", change)
            assert result == {"status": "unknown" if change == "origin" else "blocked", "pending": change == "none"}
        finally:
            await browser.close()
