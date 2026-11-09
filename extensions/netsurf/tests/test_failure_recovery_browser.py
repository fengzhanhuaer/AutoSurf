from pathlib import Path
import asyncio
import json
import shutil

import pytest
from playwright.async_api import async_playwright


@pytest.mark.asyncio
@pytest.mark.parametrize('site_id', ['agsvpt.com', 'pthome.net'])
async def test_readonly_failure_recovery_keeps_user_page_and_never_resubmits(tmp_path, site_id):
    source = Path(__file__).resolve().parents[1]
    extension = tmp_path / 'extension'
    shutil.copytree(source, extension, ignore=shutil.ignore_patterns('tests', '__pycache__'))
    manifest = json.loads((extension / 'manifest.json').read_text(encoding='utf-8'))
    manifest['host_permissions'] = ['https://*/*']
    (extension / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    requests = []
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(str(tmp_path / 'profile'), channel='chromium', headless=True,
            args=[f'--disable-extensions-except={extension}', f'--load-extension={extension}'])
        try:
            worker = context.service_workers[0] if context.service_workers else await context.wait_for_event('serviceworker')
            origin = await worker.evaluate('id => sites.get(id).origin', site_id)
            async def respond(route):
                request = route.request
                requests.append((request.method, request.url, request.is_navigation_request()))
                assert request.method == 'GET' and '/attendance.php' not in request.url
                if site_id == 'agsvpt.com' and not request.is_navigation_request():
                    await asyncio.sleep(7)
                body = '''<table><tr><td>欢迎回来, fixture <div id="info_block">用户等级: Power User 魔力值: 727775 上传量: 2 TB 下载量: 1 GB 分享率: 2048</div>(签到已得20)</td></tr></table>'''
                if site_id == 'agsvpt.com':
                    body += '<a href="/attendance.php">[签到已得90, 补签卡: 19]</a>'
                await route.fulfill(content_type='text/html; charset=utf-8', body=body)
            await context.route(f'{origin}/**', respond)
            await worker.evaluate('''async id => {
                await chrome.storage.local.set({autoEnabled:false,scheduleConfig:{timeout:5},
                    sites:Object.fromEntries(sites.catalog.map(s=>[s.id,{enabled:s.id===id}])),
                    ['operation:'+id]:{day:today(),startedAt:123,phase:'preparing',awaitingConfirmation:id==='pthome.net'},
                    ['lastResult:'+id]:{status:id==='agsvpt.com'?'already_done':'error',verified:id==='agsvpt.com',
                       confirmationFailed:id==='pthome.net',profile:{bonus:'1'},
                       signinState:{status:id==='agsvpt.com'?'success':'error',time:new Date().toISOString(),verified:id==='agsvpt.com'}}});
                if(id==='agsvpt.com') await chrome.storage.local.set({['verifiedDay:'+id]:today()});
                await reschedule();
            }''', site_id)
            user_page = await context.new_page()
            await user_page.goto(origin + '/userdetails.php?id=42')
            result = await worker.evaluate('async id=>await inspectSite(id,id==="agsvpt.com")', site_id)
            assert result['status'] == 'already_done', result
            assert result['profile']['uploaded'] == '2 TB', result
            state = await worker.evaluate('async id=>await readState(id)', site_id)
            assert state['verifiedDay']
            assert state['operation']['startedAt'] == 123
            assert state['operation']['awaitingConfirmation'] is False
            assert user_page.url == origin + '/userdetails.php?id=42'
            assert not user_page.is_closed()
            assert len(context.pages) == 2
            if site_id == 'agsvpt.com':
                assert state['lastResult']['refreshState']['status'] == 'success'
                assert all(navigation for _, _, navigation in requests)
        finally:
            await context.unroute_all(behavior='wait')
            await context.close()
