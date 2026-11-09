from pathlib import Path
from datetime import datetime
import asyncio
import json
import shutil
from urllib.parse import urlsplit

import pytest
from playwright.async_api import async_playwright


SOURCE = Path(__file__).resolve().parents[1]
ORIGIN = 'https://www.hxpt.org'
# Current-account markup observed in the redesigned site, with a fixture identity.
DROP = '''<div class="usermenu__drop"><div class="usermenu__name-row"><a class="usermenu__name" href="/users/42">fixture</a><span class="sticker">Extreme User</span></div>
<div class="usermenu__subline"><a href="/my-spark" class="bonus-pill"><span>魔力：</span><b class="num">128,282</b></a><button class="usermenu__checkin" type="button">[每日签到]</button></div>
<div class="usermenu__stats"><a class="userstat" href="/my"><span>分享率</span><strong>INF</strong></a><a class="userstat" href="/my"><span>上传量</span><strong>8.7 TB</strong></a><a class="userstat" href="/my"><span>下载量</span><strong>23.4 GB</strong></a></div><nav class="usermenu__links"><a href="/my">个人中心</a></nav></div>'''
ACCOUNT = '<div class="usermenu"><button class="usermenu__trigger" aria-expanded="true">fixture</button>' + DROP + '</div>'
NOW = datetime.now()
DAY = NOW.strftime('%Y-%m-%d')
TODAY = f'<span class="attendance-calendar__day is-missed is-today" title="{DAY} · 未签到"><strong>{NOW.day}</strong><small>未签</small></span>'
CARD = '''<div class="mhome-strip"><button class="mhome-strip__txt"><b>签到得魔力</b><i>今日未签 · 连续签到 0 天 · 累计 360 天</i></button><button class="mhome-strip__btn">立即签到</button></div>
<aside class="brand-panel attendance-card"><header class="brand-panel__head"><h2>签到得魔力</h2><span><button class="brand-button" type="button">立即签到</button><button class="makeup">补签×0</button></span></header><p>2026年11月</p><span>连续签到 0 天</span><span>累计签到 360</span><div>1 +70 2 +75 3 +80 今日已签到</div><div class="attendance-calendar" aria-label="CALENDAR_LABEL">TODAY_CELL</div></aside>'''
CARD = CARD.replace('CALENDAR_LABEL', f'{NOW.year}年{NOW.month}月签到日历').replace('TODAY_CELL', TODAY)


@pytest.mark.asyncio
@pytest.mark.parametrize('change,expected', [
    ('desktop', 'ready'), ('mobile', 'ready'), ('both', 'ready'),
    ('done', 'already_done'), ('history', 'ready'), ('disabled', 'pending'),
    ('duplicate', 'ambiguous'), ('hidden', 'unknown'), ('no_summary', 'ready'),
    ('query', 'unknown'), ('other_path', 'unknown'), ('spoofed', 'unknown'),
    ('conflict', 'unknown'), ('makeup', 'unknown'), ('stale_day', 'unknown'), ('wrong_month', 'unknown'), ('summary_only', 'unknown'), ('official_error', 'error'),
])
async def test_current_account_home_status_is_scoped(change, expected):
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel='chromium', headless=True)
        try:
            page = await browser.new_page()
            await page.route(ORIGIN + '/**', lambda r: r.fulfill(content_type='text/html; charset=utf-8', body=ACCOUNT + CARD))
            await page.goto(ORIGIN)
            for name in ['catalog.js', 'site-rules.js', 'sites.js', 'piggo.js']:
                await page.add_script_tag(path=str(SOURCE / name))
            result = await page.evaluate('''change => {
                let url=location.href;
                const mobile=document.querySelector('.mhome-strip__btn');
                const desktop=document.querySelector('.brand-button');
                if(change!=='both') (change==='mobile'?desktop:mobile).style.display='none';
                if(change==='done'){document.querySelector('.mhome-strip__txt > i').textContent='今日已签到 · 连续签到 1 天 · 累计 361 天';const d=document.querySelector('.is-today');d.classList.replace('is-missed','is-done');d.title=d.title.replace('未签到','已签 +10');}
                if(change==='history')document.body.append('签到成功 今日已签到');
                if(change==='disabled')desktop.disabled=true;
                if(change==='duplicate')desktop.after(desktop.cloneNode(true));
                if(change==='hidden')desktop.hidden=true;
                if(change==='no_summary')document.querySelector('.mhome-strip__txt > i').remove();
                if(change==='query')url+='?day=1';
                if(change==='other_path')url+='/users/999';
                if(change==='spoofed')url='https://www.hxpt.org.evil.test/';
                if(change==='conflict')document.querySelector('.mhome-strip').after(document.querySelector('.mhome-strip').cloneNode(true));
                if(change==='makeup')desktop.textContent='补签';
                if(change==='stale_day')document.querySelector('.is-today').title='2000-01-01 · 已签 +10';
                if(change==='wrong_month')document.querySelector('.attendance-calendar').setAttribute('aria-label','2000年1月签到日历');
                if(change==='summary_only'){document.querySelector('.attendance-calendar').remove();document.querySelector('.mhome-strip__txt > i').textContent='今日已签到 · 连续签到 1 天 · 累计 361 天';}
                if(change==='official_error')document.querySelector('aside.attendance-card').insertAdjacentHTML('beforeend','<p class="attendance-msg">签到失败，请稍后再试</p>');
                const a=NetSurfPiggo.create(location.origin,'/'); const result=a.inspect(document,url);
                return {status:result.status,control:result.control?.className,profile:a.profile(document),account:a.accountLink(document)};
            }''', change)
            assert result['status'] == expected, result
            assert result['profile'] == dict(level='Extreme User', bonus='128,282', uploaded='8.7 TB', downloaded='23.4 GB', ratio='INF', seedingPoints=None)
            assert result['account'] == ORIGIN + '/my'
            if expected == 'ready':
                assert result['control'] == ('mhome-strip__btn' if change == 'mobile' else 'brand-button')
        finally:
            await browser.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['success', 'failure', 'readonly', 'slow', 'pending', 'loading', 'hydrate', 'warm',
    'server_done', 'server_recorded_error', 'status_failed', 'status_invalid', 'status_unauthorized', 'status_redirect', 'server_conflict', 'recover_pending'])
async def test_rendered_home_lifecycle_never_uses_legacy_php_or_resubmits(tmp_path, mode):
    extension = tmp_path / 'extension'
    shutil.copytree(SOURCE, extension, ignore=shutil.ignore_patterns('tests', '__pycache__'))
    manifest = json.loads((extension / 'manifest.json').read_text(encoding='utf-8'))
    manifest['host_permissions'] = ['https://*/*']
    (extension / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    requests = []
    checked_today = mode in ['server_done', 'recover_pending']
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(str(tmp_path / 'profile'), channel='chromium', headless=True,
            args=[f'--disable-extensions-except={extension}', f'--load-extension={extension}'])
        try:
            async def route(r):
                nonlocal checked_today
                path = urlsplit(r.request.url).path
                requests.append((r.request.method, path))
                if path == '/api/v1/attendance':
                    assert r.request.method == 'GET'
                    if mode == 'status_redirect':
                        await r.fulfill(status=302, headers={'Location': ORIGIN + '/login'})
                    else:
                        await r.fulfill(status=503 if mode == 'status_failed' else 401 if mode == 'status_unauthorized' else 200,
                            content_type='application/json', body=json.dumps({'code':0,'data':{'checked_today':'true' if mode == 'status_invalid' else checked_today}}))
                    return
                if path == '/slow-image':
                    await asyncio.sleep(8)
                    await r.abort()
                    return
                if path == '/fixture-submit':
                    assert r.request.method == 'POST'
                    checked_today = mode != 'failure'
                    await r.fulfill(status=400 if mode == 'server_recorded_error' else 500 if mode == 'failure' else 200, body='fixture')
                    return
                assert r.request.method == 'GET' and path in ['/', '/keep-user-page'], (r.request.method, path)
                markup = '<div class="usermenu"><button class="usermenu__trigger" aria-expanded="false">fixture</button></div>' + CARD
                # Dropdown is lazy-mounted by the official menu trigger; refresh may open it,
                # but must never touch the menu's check-in, makeup or historical cells.
                js = f'''document.querySelector('.usermenu__trigger').onclick=()=>{{
                    const t=document.querySelector('.usermenu__trigger');t.setAttribute('aria-expanded','true');
                    t.insertAdjacentHTML('afterend',{json.dumps(DROP)});
                }};
                document.querySelector('.usermenu').addEventListener('click',e=>{{if(e.target.closest('.usermenu__checkin'))throw Error('menu checkin clicked');}});
                document.querySelector('.makeup').onclick=()=>{{throw Error('makeup clicked')}};
                for(const b of document.querySelectorAll('button.brand-button,button.mhome-strip__btn'))b.onclick=async()=>{{
                    for(const x of document.querySelectorAll('button.brand-button,button.mhome-strip__btn'))x.disabled=true;
                    const r=await fetch('/fixture-submit',{{method:'POST'}});
                    if(r.ok){{document.querySelector('.mhome-strip__txt > i').textContent='今日已签到 · 连续签到 1 天 · 累计 361 天';const d=document.querySelector('.is-today');d.classList.replace('is-missed','is-done');d.title=d.title.replace('未签到','已签 +10');}}
                    else {{for(const x of document.querySelectorAll('button.brand-button,button.mhome-strip__btn'))x.disabled=false;document.querySelector('aside.attendance-card').insertAdjacentHTML('beforeend','<p class="attendance-msg">签到失败，请稍后再试</p>');}}
                }};'''
                if mode == 'server_conflict':
                    js += "document.querySelector('.mhome-strip__txt > i').textContent='今日已签到 · 连续签到 1 天 · 累计 361 天';const d=document.querySelector('.is-today');d.classList.replace('is-missed','is-done');d.title=d.title.replace('未签到','已签 +10');"
                if mode == 'hydrate':
                    js = 'setTimeout(()=>{' + js + '},900);'
                await r.fulfill(content_type='text/html; charset=utf-8', body='<style>.mhome-strip__btn{display:none}</style><div id="app"></div>'+('<img src="/slow-image">' if mode == 'loading' else '')+'<script>setTimeout(()=>{document.querySelector("#app").innerHTML=' + json.dumps(markup) + ';' + js + '},' + ('1100' if mode == 'slow' else '50') + ')</script>')
            await context.route(ORIGIN + '/**', route)
            worker = context.service_workers[0] if context.service_workers else await context.wait_for_event('serviceworker')
            await worker.evaluate('''async mode => {
                await chrome.storage.local.set({autoEnabled:false,scheduleConfig:{timeout:5},
                    sites:Object.fromEntries(sites.catalog.map(s=>[s.id,{enabled:s.id==='hxpt.org'}]))});
                if(['pending','recover_pending'].includes(mode))await chrome.storage.local.set({'operation:hxpt.org':{day:today(),startedAt:123,phase:'submitted',awaitingConfirmation:true},
                    'lastResult:hxpt.org':{status:'error',confirmationFailed:true,signinState:{status:'error',time:new Date().toISOString()}}});
                await reschedule();
            }''', mode)
            user = await context.new_page()
            user_path = '/' if mode in ['warm', 'recover_pending', 'server_conflict'] else '/keep-user-page'
            await user.goto(ORIGIN + user_path, wait_until='domcontentloaded')
            if mode in ['warm', 'recover_pending', 'server_conflict']:
                await user.wait_for_load_state('load')
                await user.locator('.usermenu__trigger').wait_for()
                assert await worker.evaluate("async () => (await chrome.tabs.query({url:'https://www.hxpt.org/'}))[0].status") == 'complete'
            if mode == 'recover_pending':
                result = await worker.evaluate("async () => await inspectSite('hxpt.org')")
                assert result['status'] == 'already_done', result
                state = await worker.evaluate("async () => await readState('hxpt.org')")
                assert state['operation']['startedAt'] == 123
                assert state['operation']['awaitingConfirmation'] is False
                assert state['lastResult']['signinState']['status'] == 'already_done'
                assert state['lastResult']['refreshState']['status'] == 'success'
            elif mode in ['readonly', 'pending']:
                result = await worker.evaluate("async () => await inspectSite('hxpt.org',true)")
                assert result['refreshState']['status'] == 'success', result
                assert result['profile']['level'] == 'Extreme User'
                if mode == 'pending':
                    state = await worker.evaluate("async () => await readState('hxpt.org')")
                    assert state['operation']['startedAt'] == 123
                    assert state['operation']['awaitingConfirmation'] is True
                    assert state['lastResult']['signinState']['status'] == 'error'
            else:
                result = await asyncio.wait_for(worker.evaluate("async () => await batchSignIn('hxpt.org')"), timeout=15)
                no_submit = mode in ['server_done', 'status_failed', 'status_invalid', 'status_unauthorized', 'status_redirect', 'server_conflict']
                expected = 'unknown' if no_submit and mode != 'server_done' else 'error' if mode == 'failure' else 'already_done'
                assert result['status'] == expected, result
                assert requests.count(('POST', '/fixture-submit')) == (0 if no_submit else 1)
                repeated = await worker.evaluate("async () => await batchSignIn('hxpt.org')")
                if expected == 'unknown':
                    assert repeated['status'] == 'unknown', repeated
                assert requests.count(('POST', '/fixture-submit')) == (0 if no_submit else 1)
                state = await worker.evaluate("async () => await readState('hxpt.org')")
                if not no_submit:
                    assert state['operation']['phase'] == 'submitted'
                    assert state['operation']['awaitingConfirmation'] is (mode == 'failure')
                if expected == 'already_done':
                    assert state['verifiedDay'] is not None
                if expected == 'unknown':
                    assert state.get('verifiedDay') is None
                if mode == 'server_recorded_error':
                    assert '官网当日签到状态' in result['message']
            assert not user.is_closed() and user.url == ORIGIN + user_path
            if mode in ['warm', 'recover_pending', 'server_conflict']:
                assert requests.count(('GET', '/')) == 1
            assert len(context.pages) == 2
            assert requests.count(('POST', '/fixture-submit')) == (0 if mode in ['readonly', 'pending', 'server_done', 'status_failed', 'status_invalid', 'status_unauthorized', 'status_redirect', 'server_conflict', 'recover_pending'] else 1)
            if mode in ['readonly', 'pending']:
                assert ('GET', '/api/v1/attendance') not in requests
        finally:
            await context.unroute_all(behavior='wait')
            await context.close()
