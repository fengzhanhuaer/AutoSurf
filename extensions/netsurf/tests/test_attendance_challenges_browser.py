from pathlib import Path
import json
import shutil
from urllib.parse import urlsplit

import pytest
from playwright.async_api import async_playwright


SLIDER = '''<meta charset="utf-8"><style>
#dragContainer{position:relative;width:300px;height:40px;background:#ddd}
#dragHandler{position:absolute;left:0;top:0;width:40px;height:40px;background:#777}
#dragBg{position:absolute;height:40px}#dragText{height:40px;text-align:center}
</style><div id="dragContainer"><div id="dragBg"></div>
<div id="dragText">拖动滑块验证</div><div id="dragHandler" class="dragHandlerBg"></div></div>
<script src="/slide_check_fixture.js"></script>'''
SLIDER_SCRIPT = '''window.onload=()=>{
 const handler=document.getElementById('dragHandler'),container=document.getElementById('dragContainer');
 let dragging=false,submitted=false;
 handler.addEventListener('mousedown',()=>{dragging=true});
 document.addEventListener('mousemove',event=>{
  if(dragging)handler.style.left=Math.max(0,Math.min(container.clientWidth-handler.clientWidth,event.clientX-container.getBoundingClientRect().left-handler.clientWidth/2))+'px';
 });
 document.addEventListener('mouseup',async()=>{
  if(!dragging||submitted)return;dragging=false;
  if(handler.offsetLeft<container.clientWidth-handler.clientWidth)return;
  submitted=true;await fetch('/fixture-verify');location.reload();
 });
};'''

HAIDAN_HOME = '''<meta charset="utf-8"><style>.modal{display:none}</style>
<div id="info_block">魔力值: 7,824 上传量: 1 TB 下载量: 1 GB <span id="magic_num">123(0/h)</span></div>
<input type="submit" id="modalBtn" class="dt_button" value="每日打卡">
<div id="simpleModal" class="modal">恭喜您,获得了10魔力值奖励!</div>
<div id="signinFailModal" class="modal">小海胆开小差了，刷新后再来试试吧!</div>
<script>document.getElementById('modalBtn').addEventListener('click',async()=>{
 const response=await fetch('/signin.php');
 if(response.ok){modalBtn.value='已经打卡';modalBtn.disabled=true;simpleModal.style.display='block'}
 else signinFailModal.style.display='block';
});</script>'''


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["success", "false_success", "http_error", "already_done", "readonly"])
async def test_haidan_native_button_requires_server_confirmation(tmp_path, outcome):
    source = Path(__file__).resolve().parents[1]
    extension = tmp_path / "extension"
    shutil.copytree(source, extension, ignore=shutil.ignore_patterns("tests", "__pycache__"))
    manifest_path = extension / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["host_permissions"] = ["https://*/*"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    submissions = []
    signed = outcome == "already_done"
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            str(tmp_path / "profile"), channel="chromium", headless=True,
            args=[f"--disable-extensions-except={extension}", f"--load-extension={extension}"],
        )
        try:
            async def respond(route):
                nonlocal signed
                if urlsplit(route.request.url).path == "/signin.php":
                    submissions.append(route.request.method)
                    signed = outcome == "success"
                    await route.fulfill(status=500 if outcome == "http_error" else 200, body="")
                else:
                    body = '<meta charset="utf-8"><div id="info_block">魔力值: 7,824 上传量: 1 TB 下载量: 1 GB <span id="magic_num">133(0/h)</span></div><input type="submit" id="modalBtn" class="dt_button" disabled value="已经打卡">' if signed else HAIDAN_HOME
                    await route.fulfill(content_type="text/html; charset=utf-8", body=body)
            await context.route("https://**/*", respond)
            worker = context.service_workers[0] if context.service_workers else await context.wait_for_event("serviceworker")
            await worker.evaluate("""async readOnly=>{
                await chrome.storage.local.set({autoEnabled:false,scheduleConfig:{timeout:5},
                    sites:Object.fromEntries(sites.catalog.map(site=>[site.id,{enabled:site.id==='haidan.cc',refreshOnly:readOnly&&site.id==='haidan.cc'}]))});
                await syncScripts(await readState());
            }""", outcome == "readonly")
            user_page = context.pages[0]
            await user_page.evaluate("window.userMarker='keep'")
            result = await worker.evaluate("async()=>await batchSignIn('haidan.cc')")
            state = await worker.evaluate("async()=>await readState('haidan.cc')")
            if outcome in ("success", "already_done"):
                assert result["status"] == "already_done", result
                assert state["verifiedDay"]
                assert result["profile"]["bonus"] == "133"
                assert not (state.get("operation") or {}).get("awaitingConfirmation", False)
            elif outcome == "readonly":
                assert result["status"] == "refreshed", result
                assert not state.get("verifiedDay")
            else:
                assert result["status"] == "error", result
                assert not state.get("verifiedDay")
                assert state["operation"]["awaitingConfirmation"] is True
            expected = [] if outcome in ("already_done", "readonly") else ["GET"]
            assert submissions == expected
            await worker.evaluate("async()=>await batchSignIn('haidan.cc')")
            assert submissions == expected
            assert await user_page.evaluate("window.userMarker") == "keep"
            assert len(context.pages) == 1
        finally:
            await context.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["none", "duplicate", "form", "hidden", "wrong_label", "other_site", "other_path", "query", "success_modal", "done_button", "failure_modal", "server_done"])
async def test_haidan_button_scope_and_hidden_templates(change):
    source = Path(__file__).resolve().parents[1]
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(channel="chromium", headless=True)
        try:
            page = await browser.new_page()
            await page.route("https://**/*", lambda route: route.fulfill(content_type="text/html; charset=utf-8", body=HAIDAN_HOME))
            await page.goto("https://www.haidan.cc/index.php")
            for script in ("catalog.js", "site-rules.js", "sites.js", "piggo.js"):
                await page.add_script_tag(path=str(source / script))
            result = await page.evaluate("""change=>{
                let url=location.href;
                if(change==='duplicate')document.body.append(modalBtn.cloneNode());
                if(change==='form'){const form=document.createElement('form');document.body.append(form);form.append(modalBtn)}
                if(change==='hidden')modalBtn.style.display='none';
                if(change==='wrong_label')modalBtn.value='确认删除';
                if(change==='other_site')url='https://evil.test/index.php';
                if(change==='other_path')url='https://www.haidan.cc/userdetails.php';
                if(change==='query')url+='?action=delete';
                if(['done_button','success_modal','server_done'].includes(change)){modalBtn.value='已经打卡';modalBtn.disabled=true}
                if(change==='success_modal')simpleModal.style.display='block';
                if(change==='failure_modal')signinFailModal.style.display='block';
                if(change==='server_done'){simpleModal.remove();signinFailModal.remove()}
                const adapter=NetSurfPiggo.create('https://www.haidan.cc','/');
                const snapshot=change==='server_done'?new DOMParser().parseFromString(document.documentElement.outerHTML,'text/html'):document;
                return {status:adapter.inspect(snapshot,url).status,action:!!adapter.action(snapshot,url)};
            }""", change)
            expected = {"none": "ready", "done_button": "pending", "server_done": "already_done", "success_modal": "pending", "failure_modal": "error"}.get(change, "unknown")
            assert result == {"status": expected, "action": change == "none"}
        finally:
            await browser.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("site_id,outcome", [
    ("piggo", "success"), ("piggo", "blocked"), ("piggo", "timeout"),
    ("pt.0ff.cc", "success"), ("pt.0ff.cc", "unconfirmed"), ("pt.0ff.cc", "readonly"),
])
async def test_attendance_challenge_lifecycle(tmp_path, site_id, outcome):
    source = Path(__file__).resolve().parents[1]
    extension = tmp_path / "extension"
    shutil.copytree(source, extension, ignore=shutil.ignore_patterns("tests", "__pycache__"))
    manifest_path = extension / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["host_permissions"] = ["https://*/*"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    host = "piggo.me" if site_id == "piggo" else site_id
    entries = []
    verifications = []
    signed = False
    challenge_passed = False
    home = '<meta charset="utf-8"><div id="info_block">魔力值: 123 上传量: 1 TB 下载量: 1 GB</div><a href="attendance.php">[签到得魔力]</a>'
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            str(tmp_path / "profile"), channel="chromium", headless=True,
            args=[f"--disable-extensions-except={extension}", f"--load-extension={extension}"],
        )
        try:
            async def respond(route):
                nonlocal signed, challenge_passed
                target = urlsplit(route.request.url)
                if target.hostname == "challenge.rivers.chaitin.cn":
                    body = "setTimeout(()=>location.reload(),900)" if outcome == "success" else ""
                    if outcome == "success":
                        challenge_passed = True
                    await route.fulfill(content_type="application/javascript", body=body)
                    return
                if target.path == "/slide_check_fixture.js":
                    await route.fulfill(content_type="application/javascript", body=SLIDER_SCRIPT)
                    return
                if target.path == "/fixture-verify":
                    verifications.append(route.request.method)
                    challenge_passed = True
                    signed = outcome == "success"
                    body = "ok"
                elif target.path == "/attendance.php":
                    entries.append(route.request.method)
                    if site_id == "piggo":
                        if challenge_passed:
                            signed = True
                            body = home + "签到成功，本次签到获得15个魔力值。"
                        else:
                            body = '安全检测能力由 雷池 WAF 驱动<script src="https://challenge.rivers.chaitin.cn/challenge/v2/challenge.js"></script>'
                            if outcome == "blocked":
                                body += "无法连接人机验证服务"
                    elif not challenge_passed:
                        body = SLIDER
                    else:
                        body = home + ("签到成功，本次签到获得10个魔力值。" if signed else "处理中")
                else:
                    body = home.replace("[签到得魔力]", "[签到已得15]") if signed else home
                await route.fulfill(content_type="text/html; charset=utf-8", body=body)

            await context.route("https://**/*", respond)
            worker = context.service_workers[0] if context.service_workers else await context.wait_for_event("serviceworker")
            await worker.evaluate("""async ({siteId,readOnly})=>{
                await chrome.storage.local.set({autoEnabled:false,scheduleConfig:{timeout:5},
                    sites:Object.fromEntries(sites.catalog.map(site=>[site.id,{enabled:site.id===siteId,refreshOnly:readOnly&&site.id===siteId}]))});
                await syncScripts(await readState());
            }""", {"siteId": site_id, "readOnly": outcome == "readonly"})
            user_page = context.pages[0]
            await user_page.evaluate("window.userMarker='keep'")
            result = await worker.evaluate("async id=>await batchSignIn(id)", site_id)
            state = await worker.evaluate("async id=>await readState(id)", site_id)
            if outcome == "success":
                assert result["status"] in ("success", "already_done"), result
                assert state["verifiedDay"]
                assert state["operation"]["awaitingConfirmation"] is False
            elif outcome in ("blocked", "timeout"):
                assert result["status"] == "blocked", result
                assert not state.get("verifiedDay")
                assert ("无法连接" if outcome == "blocked" else "超时") in result["message"]
            elif outcome == "readonly":
                assert result["status"] == "refreshed", result
            else:
                assert result["status"] == "error", result
                assert state["operation"]["awaitingConfirmation"] is True
            assert verifications == (["GET"] if site_id == "pt.0ff.cc" and outcome != "readonly" else [])
            assert entries == (["GET", "GET"] if outcome in ("success", "unconfirmed") else [] if outcome == "readonly" else ["GET"])
            count = len(entries), len(verifications)
            if outcome in ("success", "unconfirmed"):
                await worker.evaluate("async id=>await batchSignIn(id)", site_id)
                assert (len(entries), len(verifications)) == count
            assert await user_page.evaluate("window.userMarker") == "keep"
            assert len(context.pages) == 1
        finally:
            await context.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["none", "permission", "script", "geometry", "duplicate", "form", "iframe", "origin", "path", "mid_drag", "background_timer", "expired", "last_move"])
async def test_freefarm_slider_scope_and_mutation(tmp_path, change):
    source = Path(__file__).resolve().parents[1]
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(channel="chromium", headless=True)
        try:
            page = await browser.new_page()
            await page.route("https://**/*", lambda route: route.fulfill(content_type="application/javascript" if route.request.url.endswith(".js") else "text/html; charset=utf-8", body="" if route.request.url.endswith(".js") else SLIDER))
            await page.goto("https://pt.0ff.cc/attendance.php")
            await page.add_script_tag(path=str(source / "freefarm.js"))
            result = await page.evaluate("""async change=>{
                const visible=element=>element.getBoundingClientRect().width>0;
                let permissions=0,downs=0,ups=0;
                document.addEventListener('mousedown',()=>{downs++});
                document.addEventListener('mouseup',()=>{ups++});
                let url=location.href;
                if(change==='duplicate')document.body.append(document.querySelector('#dragHandler').cloneNode());
                if(change==='form')document.body.append(document.createElement('form'));
                if(change==='iframe')document.body.append(document.createElement('iframe'));
                if(change==='origin')url='https://evil.test/attendance.php';
                if(change==='path')url='https://pt.0ff.cc/logout.php';
                if(change==='mid_drag')document.addEventListener('mousemove',()=>{document.body.append(document.createElement('form'))},{once:true});
                if(change==='last_move'){
                    let moves=0;
                    document.addEventListener('mousemove',()=>{if(++moves===32)document.body.append(document.createElement('form'))});
                }
                if(change==='background_timer')window.setTimeout=()=>{throw new Error('Inactive page timers are throttled')};
                const clock=Date.now.bind(Date);
                const result=await NetSurfFreeFarm.signin(document,url,visible,42,3000,async()=>{
                    permissions++;
                    if(change==='script')document.querySelector('script[src]').src='/other.js';
                    if(change==='geometry')document.querySelector('#dragContainer').style.width='400px';
                    if(change==='expired')Date.now=()=>clock()+5000;
                    return {accepted:change!=='permission'};
                });
                return {result,permissions,downs,ups};
            }""", change)
            assert result["result"]["status"] == ("pending" if change in ("none", "background_timer") else "manual_required")
            assert result["ups"] == (1 if change in ("none", "background_timer") else 0)
            assert result["downs"] == (1 if change in ("none", "mid_drag", "background_timer", "last_move") else 0)
        finally:
            await browser.close()
