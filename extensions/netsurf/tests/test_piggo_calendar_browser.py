from pathlib import Path
from datetime import datetime
import asyncio
import json
import shutil
from urllib.parse import urlsplit

import pytest
from playwright.async_api import async_playwright


SOURCE = Path(__file__).resolve().parents[1]
ACCOUNT = '<div class="user-strip">饲料 [使用] [勋章]: 1,030,680.6 分享率：9.230 上传量：405.62 GB 下载量：43.95 GB</div>'
NOW = datetime.now()
CALENDAR = f'<button class="cal-cell today on" type="button"><span class="cal-num">{NOW.day}</span></button><header class="cal-toolbar"><div class="cal-yms"><select><option value="{NOW.year}">{NOW.year}</option></select><select><option value="{NOW.month}">{NOW.month}</option></select></div><button class="cal-att-pill act" type="button">签到 · +10</button></header>'


@pytest.mark.asyncio
@pytest.mark.parametrize("change,expected", [
    ("none", "ready"), ("checked", "already_done"), ("history", "unknown"),
    ("makeup", "unknown"), ("duplicate", "ambiguous"), ("pending", "pending"),
    ("toast", "ready"), ("query", "unknown"), ("wrong_origin", "unknown"),
    ("hidden", "unknown"),
    ("yesterday", "unknown"),
])
async def test_calendar_status_is_scoped_to_current_selected_day(change, expected):
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(channel="chromium", headless=True)
        try:
            page = await browser.new_page()
            await page.route("https://**/*", lambda route: route.fulfill(content_type="text/html; charset=utf-8", body=ACCOUNT + CALENDAR))
            await page.goto("https://piggo.me/calendar")
            for name in ("catalog.js", "site-rules.js", "sites.js", "piggo.js"):
                await page.add_script_tag(path=str(SOURCE / name))
            result = await page.evaluate("""change => {
                const pill=document.querySelector('.cal-att-pill');let url=location.href;
                if(change==='checked')pill.outerHTML='<span class="cal-att-pill">已签到 · +10</span>';
                if(change==='history'){document.querySelector('.cal-cell').classList.remove('on');pill.outerHTML='<span class="cal-att-pill">已签到 · +10</span>';}
                if(change==='makeup')pill.textContent='补签 · +10';
                if(change==='duplicate')pill.after(pill.cloneNode(true));
                if(change==='pending')pill.disabled=true;
                if(change==='toast')document.body.append('历史记录：今日已签到；签到成功，累计226天');
                if(change==='query')url+='?day=1';
                if(change==='wrong_origin')url='https://piggo.me.evil.test/calendar';
                if(change==='hidden')pill.hidden=true;
                if(change==='yesterday'){document.querySelector('.cal-num').textContent='0';pill.outerHTML='<span class="cal-att-pill">已签到 · +10</span>';}
                const adapter=NetSurfPiggo.create('https://piggo.me','/calendar');
                const result=adapter.inspect(document,url);
                return {status:result.status,profile:adapter.profile(document)};
            }""", change)
            assert result["status"] == expected
            assert result["profile"]["bonus"] == "1,030,680.6"
            assert result["profile"]["uploaded"] == "405.62 GB"
        finally:
            await browser.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["success", "failure", "readonly", "slow", "blank"])
async def test_rendered_calendar_lifecycle_uses_official_control_once(tmp_path, outcome):
    extension = tmp_path / "extension"
    shutil.copytree(SOURCE, extension, ignore=shutil.ignore_patterns("tests", "__pycache__"))
    requests = []
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            str(tmp_path / "profile"), channel="chromium", headless=True,
            args=[f"--disable-extensions-except={extension}", f"--load-extension={extension}"],
        )
        try:
            async def respond(route):
                path = urlsplit(route.request.url).path
                requests.append((route.request.method, path))
                assert path not in ("/attendance.php", "/index.php")
                if path == "/fixture-attendance":
                    assert route.request.method == "POST"
                    await route.fulfill(status=500 if outcome == "failure" else 200, content_type="application/json", body=json.dumps({"ok": outcome != "failure"}))
                    return
                assert route.request.method == "GET"
                if path == "/calendar":
                    markup = ACCOUNT + CALENDAR
                    handler = """const pill=document.querySelector('.cal-att-pill');pill.addEventListener('click',async()=>{
                        pill.disabled=true; const response=await fetch('/fixture-attendance',{method:'POST'});
                        if(response.ok)pill.outerHTML='<span class="cal-att-pill">已签到 · +10</span>';
                        else {pill.disabled=false;document.body.append('签到失败');}
                    });"""
                else:
                    markup = ACCOUNT + '<div class="account-menu" style="display:none"><a class="nav" href="/calendar">签到/万年历</a></div><a href="/discuss/187">每日签到！</a>'
                    handler = ""
                script = f"document.querySelector('#app').innerHTML={json.dumps(markup)};{handler}"
                if outcome == "blank":
                    script = ""
                elif outcome == "slow" and path == "/calendar":
                    # Account data can render before the lazy calendar component.
                    script = f"document.querySelector('#app').innerHTML={json.dumps(ACCOUNT)};setTimeout(()=>{{document.querySelector('#app').insertAdjacentHTML('beforeend',{json.dumps(CALENDAR)});{handler}}},1100);"
                await route.fulfill(status=404, content_type="text/html; charset=utf-8",
                    body=f'<meta charset="utf-8"><div id="app"></div><script>setTimeout(()=>{{{script}}}, {1100 if outcome == "slow" else 100});</script>')
            await context.route("https://piggo.me/**", respond)
            worker = context.service_workers[0] if context.service_workers else await context.wait_for_event("serviceworker")
            await worker.evaluate("""async () => {
                await chrome.storage.local.set({autoEnabled:false,sites:{piggo:{enabled:true}},scheduleConfig:{timeout:6},refreshSchedule:{day:today()}});
                await reschedule();
            }""")
            page = await context.new_page()
            await page.goto("https://piggo.me/")
            if outcome == "readonly":
                result = await worker.evaluate("async () => await inspectSite('piggo',true)")
                assert result["refreshState"]["status"] == "success"
            elif outcome == "blank":
                result = await asyncio.wait_for(worker.evaluate("async () => await batchSignIn('piggo')"), timeout=12)
                assert result["status"] == "error"
                assert (await worker.evaluate("async () => await readState('piggo')")).get("operation") is None
            else:
                result = await worker.evaluate("async () => await batchSignIn('piggo')")
                assert result["status"] == ("error" if outcome == "failure" else "already_done")
                count = requests.count(("POST", "/fixture-attendance"))
                assert count == 1
                await worker.evaluate("async () => await batchSignIn('piggo')")
                assert requests.count(("POST", "/fixture-attendance")) == count
                state = await worker.evaluate("async () => await readState('piggo')")
                assert state["operation"]["awaitingConfirmation"] is (outcome == "failure")
            assert requests.count(("POST", "/fixture-attendance")) == (0 if outcome in ("readonly", "blank") else 1)
            assert not any(path == "/discuss/187" for _, path in requests)
        finally:
            await context.close()

