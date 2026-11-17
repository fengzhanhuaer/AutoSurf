from pathlib import Path
from datetime import datetime
import asyncio
import json
import shutil
from urllib.parse import urlsplit

import pytest
from playwright.async_api import async_playwright


SOURCE = Path(__file__).resolve().parents[1]
ACCOUNT = '<div class="user-strip">饲料: 123 分享率: 2.0 上传量: 2 TB 下载量: 1 TB</div>'


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", ["native", "spa", "missing", "captcha", "wrong", "foreign", "changed", "invalid", "untrusted", "concurrent", "get", "signin", "query", "disabled"])
async def test_piggo_browser_login_recovers_refresh_once_without_changing_signin(tmp_path, scenario):
    extension = tmp_path / "extension"
    shutil.copytree(SOURCE, extension, ignore=shutil.ignore_patterns("tests", "__pycache__", "login-diagnostic*"))
    logged_in = False
    posts = []
    requests = []
    attendance_posts = []
    action = 'https://other.test/takelogin.php' if scenario == "foreign" else '/takelogin.php'
    extra = '<input name="captcha"><label>验证码</label>' if scenario == "captcha" else ''
    invalid = 'pattern="[0-9]+"' if scenario == "invalid" else ''
    method = "get" if scenario == "get" else "post"
    form = f'''<meta charset="utf-8"><form method="{method}" action="{action}">
      <input name="username" autocomplete="username" required {invalid}>
      <input name="password" type="password" autocomplete="current-password" required>
      {extra}<button type="submit">登录</button></form>'''
    # Simulates Chrome filling late; fixture credentials never enter assertions,
    # extension messages or persisted state.
    fill = """setTimeout(()=>{
      document.querySelector('[name=username]').value='fixture-account';
      document.querySelector('[name=password]').value='fixture-password';
    },350);""" if scenario != "missing" else ""
    if scenario == "spa":
        fill += """document.querySelector('form').addEventListener('submit',async event=>{
          event.preventDefault(); await fetch('/fixture-login',{method:'POST'});
          history.replaceState({},'', '/');
          document.body.innerHTML='<div class="user-strip">饲料: 123 上传量: 2 TB 下载量: 1 TB</div>';
        });"""
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            str(tmp_path / "profile"), channel="chromium", headless=True,
            args=[f"--disable-extensions-except={extension}", f"--load-extension={extension}"],
        )
        try:
            async def respond(route):
                nonlocal logged_in
                path = urlsplit(route.request.url).path
                requests.append((route.request.method, path))
                if path == "/fixture-attendance":
                    attendance_posts.append(path)
                    await route.fulfill(content_type="application/json", body='{"ok":true}')
                    return
                if route.request.method == "POST":
                    posts.append(path)
                    assert path in ("/takelogin.php", "/fixture-login")
                    if scenario == "wrong":
                        await route.fulfill(content_type="text/html; charset=utf-8", body=form+'<p>密码错误</p><script>'+fill+'</script>')
                    else:
                        logged_in = True
                        if path == "/fixture-login":
                            await route.fulfill(content_type="application/json", body='{"ok":true}')
                        else:
                            await route.fulfill(content_type="text/html", body="<script>location.replace('/')</script>")
                elif path in ("/", "/index.php"):
                    if logged_in:
                        await route.fulfill(content_type="text/html; charset=utf-8", body=ACCOUNT+'<div class="account-menu" style="display:none"><a class="nav" href="/calendar">签到/万年历</a></div>')
                    else:
                        target = '/login?return=/' if scenario == 'query' else '/login'
                        await route.fulfill(content_type="text/html", body=f"<script>location.replace('{target}')</script>")
                else:
                    if path == "/calendar":
                        now = datetime.now()
                        calendar = f'''<button class="cal-cell today on" type="button"><span class="cal-num">{now.day}</span></button>
                          <header class="cal-toolbar"><div class="cal-yms"><select><option value="{now.year}">{now.year}</option></select>
                          <select><option value="{now.month}">{now.month}</option></select></div>
                          <button class="cal-att-pill act" type="button">签到 · +10</button></header>'''
                        await route.fulfill(content_type="text/html; charset=utf-8",body=ACCOUNT+calendar+'''<script>
                          document.querySelector('.cal-att-pill').addEventListener('click',async event=>{
                            event.target.disabled=true;await fetch('/fixture-attendance',{method:'POST'});
                            event.target.outerHTML='<span class="cal-att-pill">已签到 · +10</span>';
                          });</script>''')
                        return
                    assert path in ("/login", "/takelogin.php")
                    await route.fulfill(content_type="text/html; charset=utf-8", body=form+'<script>'+fill+'</script>')
            await context.route("https://**/*", respond)
            worker = context.service_workers[0] if context.service_workers else await context.wait_for_event("serviceworker")
            await worker.evaluate("""async () => {
              await chrome.storage.local.set({autoEnabled:false,scheduleConfig:{timeout:5},
                sites:Object.fromEntries(sites.catalog.map(site=>[site.id,{enabled:site.id==='piggo'}])),
                verifiedDay:today(),lastResult:{status:'already_done',verified:true,confirmedDay:today(),
                  profile:{bonus:'100'},signinState:{status:'already_done',verified:true,confirmedDay:today(),message:'prior'}}});
              await reschedule();
              globalThis.loginTrace=[];
              const originalMessage=pageMessage;
              pageMessage=async (...args)=>{
                try {const result=await originalMessage(...args);loginTrace.push({type:args[1].type,status:result?.status,path:result?.path,message:result?.message});return result;}
                catch(error) {loginTrace.push({type:args[1].type,error:error.message});throw error;}
              };
            }""")
            if scenario == "changed":
                await worker.evaluate("""() => {
                  const original=handle;
                  handle=async (message,sender)=>{
                    const result=await original(message,sender);
                    if(message.type==='browser-login-permit' && result.accepted)
                      await chrome.scripting.executeScript({target:{tabId:sender.tab.id},func:()=>document.querySelector('form').action='https://other.test/takelogin.php'});
                    return result;
                  };
                }""")
            if scenario == "disabled":
                await worker.evaluate("""() => {
                  const original=handle;
                  handle=async (message,sender)=>{
                    const result=await original(message,sender);
                    if(message.type==='browser-login-permit' && result.accepted)
                      await chrome.storage.local.set({sites:{piggo:{enabled:false}}});
                    return result;
                  };
                }""")
            if scenario == "concurrent":
                await worker.evaluate("""() => {
                  const original=pageMessage;
                  pageMessage=async (...args)=>args[1].type==='browser-login' ?
                    (await Promise.all([original(...args),original(...args)]))[0] : original(...args);
                }""")
            before = await worker.evaluate("async () => (await readState('piggo')).lastResult.signinState")
            if scenario == "untrusted":
                denied = await worker.evaluate("""async () => handle({type:'browser-login-permit',attemptId:'fake'},
                  {id:chrome.runtime.id,url:'https://piggo.me/login',tab:{id:999}})""")
                assert denied == {"accepted": False}
            if scenario == "signin":
                await worker.evaluate("async () => chrome.storage.local.set({verifiedDay:null,lastResult:null})")
                result = await asyncio.wait_for(worker.evaluate("async () => batchSignIn('piggo')"), timeout=10)
                assert result['status'] == 'already_done', result
                assert len(posts) == 1
                assert len(attendance_posts) == 1
                await worker.evaluate("async () => batchSignIn('piggo')")
                assert len(posts) == 1
                assert len(attendance_posts) == 1
                return
            result = await asyncio.wait_for(worker.evaluate("async () => inspectSite('piggo',true)"), timeout=10)
            success = scenario in ("native", "spa", "untrusted", "concurrent", "query")
            if result['refreshState']['status'] != ('success' if success else 'error'):
                print(json.dumps({'result':result,'trace':await worker.evaluate('loginTrace')}, ensure_ascii=False))
            assert result["refreshState"]["status"] == ("success" if success else "error"), (result, await worker.evaluate("loginTrace"), requests)
            assert result["signinState"] == before
            state = await worker.evaluate("async () => await chrome.storage.local.get(null)")
            # storage.get(null) is a real Chrome API here, not a unit mock.
            assert 'fixture-password' not in str(state)
            assert 'fixture-account' not in str(state)
            assert not state.get("operation")
            assert all('attendance' not in path and path != '/calendar' for _, path in requests)
            if success:
                assert len(posts) == 1
                assert result["profile"]["bonus"] == "123"
                assert state.get('browserLoginAttempt') is None
            elif scenario == "wrong":
                assert len(posts) == 1
                assert state['browserLoginAttempt']['phase'] == 'submitted'
                # A later task must keep the persisted failed attempt.
                await worker.evaluate("async () => inspectSite('piggo',true)")
                assert len(posts) == 1
            elif scenario in ("changed", "disabled"):
                assert not posts
                assert state['browserLoginAttempt']['phase'] == 'submitted'
            else:
                assert not posts
        finally:
            await context.unroute_all(behavior="wait")
            await context.close()
