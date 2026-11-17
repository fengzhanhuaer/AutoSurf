from pathlib import Path
import asyncio
import shutil
from urllib.parse import urlsplit

import pytest
from playwright.async_api import async_playwright


SOURCE = Path(__file__).resolve().parents[1]
ACCOUNT = '<div class="user-strip">饲料: 123 上传量: 2 TB 下载量: 1 TB</div>'


@pytest.mark.asyncio
@pytest.mark.parametrize('scenario', ['success', 'wrong', 'missing', 'captcha', 'foreign', 'unknown', 'no-handler', 'concurrent'])
async def test_official_idle_unlock_uses_autofilled_password_once_without_native_get(tmp_path, scenario):
    extension = tmp_path / 'extension'
    shutil.copytree(SOURCE, extension, ignore=shutil.ignore_patterns('tests', '__pycache__', 'login-diagnostic*'))
    unlocked = False
    unlock_posts = []
    requests = []
    action = ' action="https://other.test/locked"' if scenario == 'foreign' else ''
    heading = '未知页面' if scenario == 'unknown' else '页面已锁定'
    extra = '<input name="captcha"><label>验证码</label>' if scenario == 'captcha' else ''
    form = f'''<meta charset="utf-8"><div id="app"><h1 id="idle-lock-title">{heading}</h1>
      <form class="step-up"{action}>
      <input class="username-a11y" type="text" name="username" autocomplete="username" readonly value="fixture-account" style="position:absolute;width:1px;height:1px;opacity:0">
      <label class="field">当前密码<input class="cell-input" type="password" name="password" autocomplete="current-password webauthn" required placeholder="当前密码"></label>
      {extra}<button class="btn" type="submit">解锁</button></form></div>'''
    script = '''const password=document.querySelector('[name=password]');let model='';
      password.addEventListener('input',()=>model=password.value);'''
    if scenario != 'missing':
        script += "setTimeout(()=>password.value='fixture-password',350);"
    if scenario != 'no-handler':
        script += '''document.querySelector('form').addEventListener('submit',async event=>{
          event.preventDefault();if(!model)return;
          const response=await fetch('/fixture-unlock',{method:'POST'});
          if(response.ok){history.replaceState({},'', '/');document.querySelector('#app').innerHTML=''' + repr(ACCOUNT) + ''';}
          else document.body.append('密码错误');
        });'''
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            str(tmp_path / 'profile'), channel='chromium', headless=True,
            args=[f'--disable-extensions-except={extension}', f'--load-extension={extension}'],
        )
        try:
            async def respond(route):
                nonlocal unlocked
                parsed = urlsplit(route.request.url)
                assert not parsed.query, 'native GET must never expose fields in the URL'
                requests.append((route.request.method, parsed.path))
                if parsed.path == '/fixture-unlock':
                    assert route.request.method == 'POST'
                    unlock_posts.append(parsed.path)
                    unlocked = scenario != 'wrong'
                    await route.fulfill(status=200 if unlocked else 403, body='{}', content_type='application/json')
                elif parsed.path == '/':
                    await route.fulfill(content_type='text/html; charset=utf-8', body=ACCOUNT if unlocked else "<script>location.replace('/locked')</script>")
                else:
                    assert parsed.path == '/locked'
                    await route.fulfill(content_type='text/html; charset=utf-8', body=form+'<script>'+script+'</script>')
            await context.route('https://**/*', respond)
            worker = context.service_workers[0] if context.service_workers else await context.wait_for_event('serviceworker')
            await worker.evaluate('''async () => {
              await chrome.storage.local.set({autoEnabled:false,scheduleConfig:{timeout:5},
                sites:Object.fromEntries(sites.catalog.map(site=>[site.id,{enabled:site.id==='piggo'}])),
                lastResult:{status:'already_done',signinState:{status:'already_done',message:'prior'},profile:{bonus:'100'}}});
              await reschedule();
            }''')
            if scenario == 'concurrent':
                await worker.evaluate('''() => {
                  const original=pageMessage;
                  pageMessage=async (...args)=>args[1].type==='browser-login' ?
                    (await Promise.all([original(...args),original(...args)]))[0] : original(...args);
                }''')
            result = await asyncio.wait_for(worker.evaluate("async () => inspectSite('piggo',true)"), timeout=12)
            success = scenario in ('success', 'concurrent')
            assert result['refreshState']['status'] == ('success' if success else 'error'), result
            assert result['signinState'] == {'status':'already_done','message':'prior'}
            state = await worker.evaluate('async () => chrome.storage.local.get(null)')
            assert 'fixture-password' not in str(state)
            assert 'fixture-account' not in str(state)
            assert not state.get('operation')
            assert not any(path in ('/login','/calendar','/attendance.php') for _, path in requests)
            if success:
                assert len(unlock_posts) == 1
                assert result['profile']['bonus'] == '123'
                assert state.get('browserLoginAttempt') is None
            elif scenario == 'wrong':
                assert len(unlock_posts) == 1
                assert state['browserLoginAttempt']['phase'] == 'submitted'
                await worker.evaluate("async () => inspectSite('piggo',true)")
                assert len(unlock_posts) == 1
            else:
                assert not unlock_posts
                if scenario == 'no-handler':
                    assert state['browserLoginAttempt']['phase'] == 'submitted'
                    assert requests.count(('GET','/locked')) == 1
        finally:
            await context.unroute_all(behavior='wait')
            await context.close()
