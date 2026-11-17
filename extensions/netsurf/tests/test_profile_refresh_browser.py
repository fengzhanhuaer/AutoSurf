from pathlib import Path
import asyncio
import json
import shutil
from urllib.parse import urlsplit

import pytest
from playwright.async_api import async_playwright


@pytest.mark.asyncio
@pytest.mark.parametrize("site_id,theme", [("carpt.net", "legacy"), ("pt.0ff.cc", "legacy"), ("pt.0ff.cc", "n8")])
async def test_profile_refresh_with_slow_home_fetch_or_ambiguous_attendance(tmp_path, site_id, theme):
    source = Path(__file__).resolve().parents[1]
    extension = tmp_path / "extension"
    shutil.copytree(source, extension, ignore=shutil.ignore_patterns("tests", "__pycache__"))
    manifest = json.loads((extension / "manifest.json").read_text(encoding="utf-8"))
    manifest["host_permissions"] = ["https://*/*"]
    (extension / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    header = '''<meta charset="utf-8"><div id="info_block">
      <a href="/userdetails.php?id=42">fixture</a>
      魔力值 [使用]: 1,916,018.7 分享率: 6.526 上传量: 1.156 TB 下载量: 181.34 GB
      </div><a href="/attendance.php">签到得魔力</a>'''
    if site_id == "pt.0ff.cc":
        header += '<a href="/attendance.php">签到得魔力</a>'
    if theme == "n8":
        header = '''<meta charset="utf-8"><section class="n8-hero">
          <a href="/userdetails.php?id=42">个人中心</a><a href="/attendance.php">签到得魔力</a>
          <span class="n8-rank">User</span><div class="n8-deck-grid">
          <div class="n8-cell"><span>上传</span><b>1.156 TB</b></div>
          <div class="n8-cell"><span>下载</span><b>181.34 GB</b></div>
          <div class="n8-cell"><span>分享率</span><b>6.526</b></div>
          <div class="n8-cell"><span>魔力值</span><b>191.6<u>万</u></b></div></div></section>
          <div class="n8-pop-acct"><a href="/attendance.php">签到得魔力</a></div>
          <p>论坛上传量: 999 PB 魔力值: 99999999</p>'''
    details = header + '''<table><tr><td>等级</td><td>User</td></tr>
      <tr><td>魔力值</td><td>1,916,018.7</td></tr>
      <tr><td>做种积分</td><td>1,683,454.6</td></tr></table>'''
    requests = []
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            str(tmp_path / "profile"), channel="chromium", headless=True,
            args=[f"--disable-extensions-except={extension}", f"--load-extension={extension}"],
        )
        try:
            async def respond(route):
                request = route.request
                path = urlsplit(request.url).path
                requests.append((request.method, path, request.is_navigation_request()))
                assert request.method == "GET" and path != "/attendance.php"
                if site_id == "carpt.net" and path == "/index.php" and not request.is_navigation_request():
                    await asyncio.sleep(6)
                await route.fulfill(content_type="text/html; charset=utf-8", body=details if path == "/userdetails.php" else header)

            await context.route(f"https://{site_id}/**", respond)
            worker = context.service_workers[0] if context.service_workers else await context.wait_for_event("serviceworker")
            await worker.evaluate("""async siteId => {
                await chrome.storage.local.set({autoEnabled:false, scheduleConfig:{timeout:5},
                  sites:Object.fromEntries(sites.catalog.map(s=>[s.id,{enabled:s.id===siteId}])),
                  [sites.key('lastResult',siteId)]:{status:'ready',signinState:{status:'ready'}}});
                await reschedule();
            }""", site_id)
            existing = await context.new_page()
            await existing.goto(f"https://{site_id}/userdetails.php?id=42")
            await worker.evaluate("async () => await actionQueue")
            if theme == "n8":
                assert await worker.evaluate("""async () => {
                    const [tab] = await chrome.tabs.query({url:'https://pt.0ff.cc/*'});
                    await ensureContent(tab, 'pt.0ff.cc');
                    const [frame] = await chrome.scripting.executeScript({target:{tabId:tab.id},
                      func:() => NetSurfPiggo.create(location.origin).profile(document).bonus});
                    return frame.result;
                }""") is None
            before = await worker.evaluate("async siteId => (await readState(siteId)).lastResult", site_id)
            result = await worker.evaluate("async siteId => await inspectSite(siteId,true)", site_id)
            assert result["refreshState"]["status"] == "success", result
            assert result["profile"]["uploaded"] == "1.156 TB"
            assert result["profile"]["level"] == "User"
            assert result["profile"]["seedingPoints"] == "1,683,454.6"
            assert result["signinState"]["status"] == before["signinState"]["status"]
            if site_id == "carpt.net":
                assert result["profile"]["bonus"] == "1,916,018.7"
                assert ("GET", "/index.php", True) in requests
                assert ("GET", "/index.php", False) not in requests
            else:
                assert before["signinState"]["status"] == "ambiguous"
                assert result["profile"]["bonus"] == "1,916,018.7"
            assert existing.url == f"https://{site_id}/userdetails.php?id=42"
            assert all(path != "/attendance.php" for _, path, _ in requests)
        finally:
            await context.unroute_all(behavior="wait")
            await context.close()


@pytest.mark.asyncio
async def test_hxpt_server_rendered_mobile_account_refresh_does_not_wait_for_menu_hydration(tmp_path):
    source = Path(__file__).resolve().parents[1]
    extension = tmp_path / "extension"
    shutil.copytree(source, extension, ignore=shutil.ignore_patterns("tests", "__pycache__"))
    manifest = json.loads((extension / "manifest.json").read_text(encoding="utf-8"))
    manifest["host_permissions"] = ["https://*/*"]
    (extension / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    html = '''<meta charset="utf-8"><span class="usermenu__trigger">fixture</span>
      <div class="mhome-hero md:hidden"><dl class="mhome-hero__spark num">
      <div><dt>魔力</dt><dd>★ 131,996</dd></div></dl><dl class="mhome-hero__stats num">
      <div><dt>上传</dt><dd>↑ 8.7 TB</dd></div><div><dt>下载</dt><dd>↓ 23.4 GB</dd></div>
      <div><dt>分享率</dt><dd>∑ INF</dd></div></dl>
      <p class="mhome-gauge__note">分享率 380.48 高于观察期阈值 0.40</p></div>
      <p>全站上传量: 999 PB 魔力值: 99999999</p><img src="/slow-image">'''
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
                assert route.request.method == "GET" and path in ["/", "/slow-image"]
                if path == "/slow-image":
                    await asyncio.sleep(7)
                    await route.abort()
                else:
                    await route.fulfill(content_type="text/html; charset=utf-8", body=html)

            await context.route("https://www.hxpt.org/**", respond)
            worker = context.service_workers[0] if context.service_workers else await context.wait_for_event("serviceworker")
            await worker.evaluate("""async () => {
                await chrome.storage.local.set({autoEnabled:false, scheduleConfig:{timeout:5},
                  sites:Object.fromEntries(sites.catalog.map(s=>[s.id,{enabled:s.id==='hxpt.org'}])),
                  'lastResult:hxpt.org':{status:'unknown',profile:{level:'Extreme User',seedingPoints:'99,448.5'}}});
                await reschedule();
            }""")
            result = await worker.evaluate("async () => await inspectSite('hxpt.org',true)")
            assert result["refreshState"]["status"] == "success", result
            assert result["profile"] == {"bonus": "131,996", "uploaded": "8.7 TB", "downloaded": "23.4 GB", "ratio": "INF", "level": "Extreme User", "seedingPoints": "99,448.5"}
            assert requests.count(("GET", "/")) == 1
        finally:
            await context.unroute_all(behavior="wait")
            await context.close()
