from pathlib import Path
import json
import shutil
import asyncio

import pytest
from playwright.async_api import async_playwright, expect


@pytest.mark.asyncio
async def test_bulk_daily_filter_keepfrds_grade_and_failed_refresh_preserves_data(tmp_path):
    source = Path(__file__).resolve().parents[1]
    extension = tmp_path / "extension"
    shutil.copytree(source, extension, ignore=shutil.ignore_patterns("tests", "__pycache__"))
    manifest_path = extension / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["host_permissions"] = ["https://*/*"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    requests = []
    signed = False
    failed = False
    errors = []
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            str(tmp_path / "profile"), channel="chromium", headless=True,
            args=[f"--disable-extensions-except={extension}", f"--load-extension={extension}"],
        )
        try:
            async def route_page(route):
                from urllib.parse import urlsplit

                nonlocal signed
                target = urlsplit(route.request.url)
                requests.append((target.hostname, target.path))
                if target.path == "/attendance.php":
                    signed = True
                    body = "今日已签到"
                elif target.path == "/userdetails.php":
                    body = '<div id="info_block"><a href="/userdetails.php?id=42">fixture</a>(Insane User)</div><table><tr><td>Class</td><td><img src="/pic/insane.gif"><div>Next class: Veteran UserAccount age (days): 822.10 / 224 (Met) D</div></td></tr><tr><td>Uploaded</td><td>4.087 TiB</td></tr></table>'
                else:
                    attendance = "[签到已得100]" if signed or target.hostname == "piggo.me" else "签到"
                    body = f'<div id="info_block"><a href="/userdetails.php?id=42">fixture</a>(Insane User) 上传量：4.087 TiB 下载量：791.33 GiB</div><a href="/attendance.php">{attendance}</a>'
                if failed:
                    body = '<div id="info_block">用户等级：VIP 上传量：999 TiB</div>'
                await route.fulfill(status=500 if failed else 200, content_type="text/html; charset=utf-8", body=f'<html><meta charset="utf-8"><body>{body}</body></html>')

            await context.route("https://**/*", route_page)
            worker = context.service_workers[0] if context.service_workers else await context.wait_for_event("serviceworker", timeout=10000)
            await worker.evaluate("""async () => {
                const active = ['piggo', 'audiences.me', 'pt.keepfrds.com', '52pt.site'];
                await chrome.storage.local.set({autoEnabled:false, sites:Object.fromEntries(sites.catalog.map(site => [site.id,{enabled:active.includes(site.id)}])), scheduleConfig:{timeout:5}, verifiedDay:today(), lastResult:{status:'already_done',verified:true,time:new Date().toISOString()}, 'lastResult:pt.keepfrds.com':{status:'profile_only',profile:{level:'Next class: Veteran UserAccount age (days): 822.10 / 224 (Met) D',uploaded:'4.087 TiB'}}});
                await reschedule();
            }""")
            dashboard = await context.new_page()
            await dashboard.set_viewport_size({"width": 1680, "height": 1000})
            dashboard.on("pageerror", lambda error: errors.append(str(error)))
            await dashboard.goto(f"chrome-extension://{worker.url.split('/')[2]}/dashboard.html")
            await expect(dashboard.locator("#inspect")).to_be_enabled(timeout=15000)
            await expect(dashboard.locator('[id="profile-level-pt.keepfrds.com"]')).to_have_text("—")
            existing = set(context.pages)
            await dashboard.locator("#inspect").click()
            await expect(dashboard.locator("#inspect")).to_be_enabled(timeout=30000)
            await expect(dashboard.locator('[id="profile-level-pt.keepfrds.com"]')).to_have_text("Insane User")
            await expect(dashboard.locator('[id="profile-uploaded-pt.keepfrds.com"]')).to_have_text("4.087 TiB")
            count = len(requests)
            await dashboard.locator("#inspect").click()
            await expect(dashboard.locator("#inspect")).to_be_enabled(timeout=15000)
            assert len(requests) == count
            assert all(path != "/attendance.php" for host, path in requests)
            assert await dashboard.locator('[id="row-audiences.me"] .site-actions button').all_text_contents() == ["打开", "刷新", "签到"]
            assert await dashboard.locator('[id="row-pt.keepfrds.com"] .site-actions button').all_text_contents() == ["打开", "刷新"]
            assert await dashboard.locator('[id="row-52pt.site"] .site-actions button').all_text_contents() == ["打开", "刷新"]
            requests.clear()
            await dashboard.locator('[id="refresh-audiences.me"]').click()
            await expect(dashboard.locator('[id="refresh-audiences.me"]')).to_be_enabled(timeout=15000)
            assert requests and all(host == "audiences.me" and path != "/attendance.php" for host, path in requests)
            assert set(context.pages) == existing
            failed = True
            await dashboard.locator('[id="run-pt.keepfrds.com"]').click()
            await expect(dashboard.locator('[id="run-pt.keepfrds.com"]')).to_be_enabled(timeout=15000)
            await expect(dashboard.locator('[id="profile-level-pt.keepfrds.com"]')).to_have_text("Insane User")
            await expect(dashboard.locator('[id="profile-uploaded-pt.keepfrds.com"]')).to_have_text("4.087 TiB")
            failed = False
            requests.clear()
            await dashboard.locator("#run-all").click()
            await expect(dashboard.locator("#run-all")).to_be_enabled(timeout=15000)
            await expect(dashboard.locator('[id="site-status-audiences.me"]')).to_have_text("已完成")
            assert requests and all(host == "audiences.me" for host, path in requests)
            assert sum(path == "/attendance.php" for host, path in requests) == 1
            count = len(requests)
            await dashboard.locator("#run-all").click()
            await expect(dashboard.locator("#run-all")).to_be_enabled(timeout=15000)
            assert len(requests) == count
            assert set(context.pages) == existing
            assert errors == []
            await dashboard.screenshot(path=str(tmp_path / "bulk-grade-fixed.png"), full_page=True)
            print(f"QA screenshot: {tmp_path / 'bulk-grade-fixed.png'}")
        finally:
            await context.close()


@pytest.mark.asyncio
async def test_hdcity_recent_page_refresh_recognizes_completion_without_refetching_home(tmp_path):
    source = Path(__file__).resolve().parents[1]
    extension = tmp_path / "extension"
    shutil.copytree(source, extension, ignore=shutil.ignore_patterns("tests", "__pycache__"))
    manifest_path = extension / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["host_permissions"] = ["https://hdcity.city/*", "https://www.hdcity.city/*"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    home_fetches = 0
    errors = []
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            str(tmp_path / "profile"), channel="chromium", headless=True,
            args=[f"--disable-extensions-except={extension}", f"--load-extension={extension}"],
        )
        try:
            async def route_page(route):
                nonlocal home_fetches
                from urllib.parse import urlsplit

                target = urlsplit(route.request.url)
                if target.path == "/index.php" and route.request.resource_type == "fetch":
                    home_fetches += 1
                    await asyncio.sleep(6)
                    await route.fulfill(status=504, content_type="text/plain", body="timeout")
                    return
                body = '''<div class="material-userbar">
                  用户等级: Power User 魔力值: 123.4 做种积分: 456.7
                  上传量: 2.00 TiB 下载量: 1.00 TiB 分享率: 2.000
                  <a href="/userdetails.php?id=42">fixture</a>
                </div><a href="/sign"><i>assignment_turned_in</i>Checked in</a>'''
                await route.fulfill(status=200, content_type="text/html; charset=utf-8", body=f"<html><body>{body}</body></html>")

            await context.route("https://hdcity.city/**", route_page)
            worker = context.service_workers[0] if context.service_workers else await context.wait_for_event("serviceworker", timeout=10000)
            await worker.evaluate("""async () => {
                await chrome.storage.local.set({
                  autoEnabled: false,
                  sites: Object.fromEntries(sites.catalog.map(site => [site.id, {enabled: site.id === 'hdcity.city'}])),
                  scheduleConfig: {timeout: 8}
                });
                await reschedule();
            }""")
            site_page = await context.new_page()
            await site_page.goto("https://hdcity.city/index.php")
            dashboard = await context.new_page()
            dashboard.on("pageerror", lambda error: errors.append(str(error)))
            await dashboard.goto(f"chrome-extension://{worker.url.split('/')[2]}/dashboard.html")
            await expect(dashboard.locator('[id="row-hdcity.city"]')).to_be_visible()
            await dashboard.locator('[id="refresh-hdcity.city"]').click()
            await expect(dashboard.locator('[id="refresh-hdcity.city"]')).to_be_enabled(timeout=15000)
            await expect(dashboard.locator('[id="site-status-hdcity.city"]')).to_have_text("已完成")
            await expect(dashboard.locator('[id="profile-level-hdcity.city"]')).to_have_text("Power User")
            await expect(dashboard.locator('[id="profile-bonus-hdcity.city"]')).to_have_text("123.4")
            await expect(dashboard.locator('[id="profile-seedingPoints-hdcity.city"]')).to_have_text("456.7")
            assert home_fetches == 0
            assert errors == []
            screenshot = tmp_path / "hdcity-recognized.png"
            await dashboard.screenshot(path=str(screenshot), full_page=False)
            print(f"QA screenshot: {screenshot}")
        finally:
            await context.close()


@pytest.mark.asyncio
async def test_zhimeng_refresh_then_signin_updates_electricity_and_completion(tmp_path):
    source = Path(__file__).resolve().parents[1]
    extension = tmp_path / "extension"
    shutil.copytree(source, extension, ignore=shutil.ignore_patterns("tests", "__pycache__"))
    manifest_path = extension / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["host_permissions"] = ["https://zmpt.cc/*", "https://www.zmpt.cc/*"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    signed = False
    attendance_requests = 0
    errors = []
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            str(tmp_path / "profile"), channel="chromium", headless=True,
            args=[f"--disable-extensions-except={extension}", f"--load-extension={extension}"],
        )
        try:
            async def route_page(route):
                nonlocal signed, attendance_requests
                from urllib.parse import urlsplit

                target = urlsplit(route.request.url)
                if target.path == "/attendance.php":
                    attendance_requests += 1
                    signed = True
                    body = "签到成功，本次签到获得 100 电力值"
                else:
                    label = "[签到已得100]" if signed else "[签到得电力]"
                    body = f'''<div id="info_block">
                      用户等级: Elite User 电力值: 987.6 做种积分: 1,646,531.5
                      上传量: 16.332 TB 下载量: 294.79 GB 分享率: 56.731
                      <a href="/userdetails.php?id=42">fixture</a>
                      <a class="faqlink" href="/attendance.php">{label}</a>
                    </div>'''
                await route.fulfill(status=200, content_type="text/html; charset=utf-8", body=f"<html><body>{body}</body></html>")

            await context.route("https://zmpt.cc/**", route_page)
            worker = context.service_workers[0] if context.service_workers else await context.wait_for_event("serviceworker", timeout=10000)
            await worker.evaluate("""async () => {
                await chrome.storage.local.set({
                  autoEnabled: false,
                  sites: Object.fromEntries(sites.catalog.map(site => [site.id, {enabled: site.id === 'zmpt.cc'}])),
                  scheduleConfig: {timeout: 8}
                });
                await reschedule();
            }""")
            site_page = await context.new_page()
            await site_page.goto("https://zmpt.cc/index.php")
            dashboard = await context.new_page()
            dashboard.on("pageerror", lambda error: errors.append(str(error)))
            await dashboard.goto(f"chrome-extension://{worker.url.split('/')[2]}/dashboard.html")
            await expect(dashboard.locator('[id="row-zmpt.cc"]')).to_be_visible()
            await dashboard.locator('[id="refresh-zmpt.cc"]').click()
            await expect(dashboard.locator('[id="refresh-zmpt.cc"]')).to_be_enabled(timeout=15000)
            await expect(dashboard.locator('[id="site-status-zmpt.cc"]')).to_have_text("待签到")
            await expect(dashboard.locator('[id="profile-level-zmpt.cc"]')).to_have_text("Elite User")
            await expect(dashboard.locator('[id="profile-bonus-zmpt.cc"]')).to_have_text("987.6")
            await expect(dashboard.locator('[id="profile-seedingPoints-zmpt.cc"]')).to_have_text("1,646,531.5")
            assert attendance_requests == 0
            await dashboard.locator('[id="run-zmpt.cc"]').click()
            await expect(dashboard.locator('[id="run-zmpt.cc"]')).to_be_enabled(timeout=15000)
            await expect(dashboard.locator('[id="site-status-zmpt.cc"]')).to_have_text("已完成")
            assert attendance_requests == 1
            assert errors == []
            screenshot = tmp_path / "zhimeng-refresh-signin.png"
            await dashboard.screenshot(path=str(screenshot), full_page=False)
            print(f"QA screenshot: {screenshot}")
        finally:
            await context.close()


@pytest.mark.asyncio
async def test_weak_network_refresh_retries_and_keeps_old_data_while_waiting(tmp_path):
    source = Path(__file__).resolve().parents[1]
    extension = tmp_path / "extension"
    shutil.copytree(source, extension, ignore=shutil.ignore_patterns("tests", "__pycache__"))
    manifest_path = extension / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["host_permissions"] = ["https://audiences.me/*", "https://www.audiences.me/*"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    home_fetches = 0
    account_fetches = 0
    errors = []
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            str(tmp_path / "profile"), channel="chromium", headless=True,
            args=[f"--disable-extensions-except={extension}", f"--load-extension={extension}"],
        )
        try:
            async def route_page(route):
                from urllib.parse import urlsplit

                nonlocal home_fetches, account_fetches
                target = urlsplit(route.request.url)
                if target.path == "/userdetails.php":
                    account_fetches += 1
                    await asyncio.sleep(5.5)
                    body = '''<main class="profile-layout">fixture (年轻气盛)Power User加入日期：2024-01-01
                      <section class="ud-stat"><span class="ud-stat__value">132.270 TB</span><span class="ud-stat__label">上传量</span></section>
                      <section class="ud-stat"><span class="ud-stat__value">2.041 TB</span><span class="ud-stat__label">下载量</span></section>
                      <section class="ud-stat"><span class="ud-stat__value">64.820</span><span class="ud-stat__label">分享率</span></section>
                      <section class="ud-stat"><span class="ud-stat__value">229786.3</span><span class="ud-stat__label">爆米花</span></section>
                    </main>'''
                    await route.fulfill(status=200, content_type="text/html; charset=utf-8", body=f"<html><body>{body}</body></html>")
                    return
                if target.path == "/index.php" and route.request.resource_type == "fetch":
                    home_fetches += 1
                    if home_fetches == 1:
                        await route.fulfill(status=503, content_type="text/html", body="temporary")
                        return
                body = '<div id="info_block"><a href="/userdetails.php?id=42">fixture</a></div><a href="/attendance.php">签到</a>'
                await route.fulfill(status=200, content_type="text/html; charset=utf-8", body=f"<html><body>{body}</body></html>")

            await context.route("https://audiences.me/**", route_page)
            worker = context.service_workers[0] if context.service_workers else await context.wait_for_event("serviceworker", timeout=10000)
            await worker.evaluate("""async () => {
                await chrome.storage.local.set({
                  autoEnabled: false,
                  sites: Object.fromEntries(sites.catalog.map(site => [site.id, {enabled: false}])),
                  scheduleConfig: {timeout: 8},
                  'lastResult:audiences.me': {siteId:'audiences.me',status:'error',message:'旧检查失败',profile:{level:'User',bonus:'1'},profileTime:'2026-01-01T00:00:00.000Z'}
                });
                await reschedule();
            }""")
            site_page = await context.new_page()
            await site_page.goto("https://audiences.me/")
            dashboard = await context.new_page()
            dashboard.on("pageerror", lambda error: errors.append(str(error)))
            await dashboard.goto(f"chrome-extension://{worker.url.split('/')[2]}/dashboard.html")
            await worker.evaluate("""async () => {
                const state = await chrome.storage.local.get('sites');
                await chrome.storage.local.set({sites:{...state.sites,'audiences.me':{...state.sites['audiences.me'],enabled:true}}});
            }""")
            await expect(dashboard.locator('[id="row-audiences.me"]')).to_be_visible()
            await expect(dashboard.locator('[id="profile-level-audiences.me"]')).to_have_text("User")
            await dashboard.locator('[id="refresh-audiences.me"]').click()
            await expect(dashboard.locator('[id="site-status-audiences.me"]')).to_have_text("刷新中")
            await expect(dashboard.locator('[id="profile-level-audiences.me"]')).to_have_text("User")
            screenshot = tmp_path / "weak-network-refreshing.png"
            await dashboard.screenshot(path=str(screenshot), full_page=True)
            print(f"QA screenshot: {screenshot}")
            await expect(dashboard.locator('[id="refresh-audiences.me"]')).to_be_enabled(timeout=15000)
            await expect(dashboard.locator('[id="profile-level-audiences.me"]')).to_have_text("Power User")
            await expect(dashboard.locator('[id="profile-bonus-audiences.me"]')).to_have_text("229786.3")
            await expect(dashboard.locator('[id="profile-ratio-audiences.me"]')).to_have_text("64.820")
            await expect(dashboard.locator('[id="profile-uploaded-audiences.me"]')).to_have_text("132.270 TB")
            await expect(dashboard.locator('[id="profile-downloaded-audiences.me"]')).to_have_text("2.041 TB")
            stored = await worker.evaluate("async () => (await chrome.storage.local.get('lastResult:audiences.me'))['lastResult:audiences.me']")
            assert stored["diagnostic"]["auxiliary"][0]["profileHints"], stored
            assert home_fetches == 2
            assert account_fetches == 1
            assert errors == []
        finally:
            await context.close()


@pytest.mark.asyncio
async def test_single_site_signin_opens_and_closes_its_background_page(tmp_path):
    source = Path(__file__).resolve().parents[1]
    extension = tmp_path / "extension"
    shutil.copytree(source, extension, ignore=shutil.ignore_patterns("tests", "__pycache__"))
    manifest_path = extension / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["host_permissions"] = ["https://audiences.me/*", "https://www.audiences.me/*"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    attendance_requests = 0
    errors = []
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            str(tmp_path / "profile"), channel="chromium", headless=True,
            args=[f"--disable-extensions-except={extension}", f"--load-extension={extension}"],
        )
        try:
            async def route_page(route):
                from urllib.parse import urlsplit

                nonlocal attendance_requests
                target = urlsplit(route.request.url)
                if target.path == "/attendance.php":
                    attendance_requests += 1
                    body = "今日已签到"
                else:
                    body = '<div id="info_block">用户等级: User 爆米花系统: 100 上传量: 2 TiB 下载量: 1 TiB</div><a href="/attendance.php">签到</a>'
                await route.fulfill(status=200, content_type="text/html; charset=utf-8", body=f"<html><body>{body}</body></html>")

            await context.route("https://audiences.me/**", route_page)
            worker = context.service_workers[0] if context.service_workers else await context.wait_for_event("serviceworker", timeout=10000)
            await worker.evaluate("""async () => {
                await chrome.storage.local.set({
                  autoEnabled: false,
                  sites: Object.fromEntries(sites.catalog.map(site => [site.id, {enabled: site.id === 'audiences.me'}])),
                  scheduleConfig: {timeout: 8},
                  'lastResult:audiences.me': {siteId:'audiences.me',status:'no_tab',message:'先打开 Audiences 并登录',profile:{level:'User'}}
                });
                await reschedule();
            }""")
            dashboard = await context.new_page()
            dashboard.on("pageerror", lambda error: errors.append(str(error)))
            await dashboard.goto(f"chrome-extension://{worker.url.split('/')[2]}/dashboard.html")
            await expect(dashboard.locator('[id="site-status-audiences.me"]')).to_have_text("未打开")
            pages = set(context.pages)
            await dashboard.locator('[id="run-audiences.me"]').click()
            await expect(dashboard.locator('[id="site-status-audiences.me"]')).to_have_text("签到中")
            await expect(dashboard.locator('[id="run-audiences.me"]')).to_be_enabled(timeout=15000)
            await expect(dashboard.locator('[id="site-status-audiences.me"]')).to_have_text("已完成")
            assert attendance_requests == 1
            assert set(context.pages) == pages
            assert errors == []
        finally:
            await context.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("site_id, api_path", [("zhuque.in", "/api/user/getInfo"), ("kp.m-team.cc", "/api/member/profile"), ("rousi.pro", "/api/v1/me/traffic"), ("sunnypt.top", "/api/v1/user/details/info")])
async def test_api_profile_background_refresh_keeps_stats_on_failure(tmp_path, site_id, api_path):
    source = Path(__file__).resolve().parents[1]
    extension = tmp_path / "extension"
    shutil.copytree(source, extension, ignore=shutil.ignore_patterns("tests", "__pycache__"))
    manifest_path = extension / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["host_permissions"] = ["https://*/*"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    requests = []
    zhuque_headers = []
    failed = False
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            str(tmp_path / "profile"), channel="chromium", headless=True,
            args=[f"--disable-extensions-except={extension}", f"--load-extension={extension}"],
        )
        try:
            async def route_page(route):
                from urllib.parse import urlsplit

                pathname = urlsplit(route.request.url).path
                requests.append((route.request.method, pathname))
                if pathname == api_path:
                    data = {"id": 42, "class": {"name": "Power User"}, "upload": 1073741824, "download": 536870912, "bonus": 123.4, "seedBonus": 567.8}
                    if site_id == "kp.m-team.cc":
                        data = {"id": 42, "memberStatus": {"name": "Power User"}, "memberCount": {"uploaded": 1073741824, "downloaded": 536870912, "bonus": 123.4}}
                    if site_id == "sunnypt.top":
                        data = {"id": 42, "title": "Power User", "uploaded": 1073741824, "downloaded": 536870912, "seed_bonus": 123.4}
                    payload = {"totals": {"credited_uploaded_bytes": 1073741824, "charged_downloaded_bytes": 536870912}} if site_id == "rousi.pro" else {"code": "0", "data": data}
                    if site_id == "zhuque.in":
                        zhuque_headers.append(route.request.headers.get("x-csrf-token"))
                    status = 500 if failed else 400 if site_id == "zhuque.in" and route.request.headers.get("x-csrf-token") != "fictional-csrf" else 200
                    await route.fulfill(status=status, content_type="application/json", headers={"Access-Control-Allow-Origin": f"https://{site_id}", "Access-Control-Allow-Credentials": "true"}, body=json.dumps(payload))
                elif pathname in ["/api/v1/session", "/api/auth/session", "/api/v1/me/economy", "/api/v1/me/attendance", "/api/v1/attendance/status"]:
                    payloads = {"/api/v1/session": {"user": {"id": 42}, "csrf_token": "fictional-csrf"}, "/api/auth/session": {"data": {"accessToken": "fictional-session"}}, "/api/v1/me/economy": {"magic_balance": 123.4, "progress": {"level": 6}}, "/api/v1/me/attendance": {"claimed_today": False}, "/api/v1/attendance/status": {"data": {"checked_in": False}}}
                    await route.fulfill(status=200, content_type="application/json", headers={"Access-Control-Allow-Origin": f"https://{site_id}", "Access-Control-Allow-Credentials": "true"}, body=json.dumps(payloads[pathname]))
                elif route.request.method == "OPTIONS":
                    await route.fulfill(status=204, headers={"Access-Control-Allow-Origin": f"https://{site_id}", "Access-Control-Allow-Credentials": "true", "Access-Control-Allow-Methods": "POST", "Access-Control-Allow-Headers": "authorization,ts,visitorId,version,webVersion"})
                else:
                    await asyncio.sleep(0.5)
                    csrf = '<meta name="x-csrf-token" content="fictional-csrf">' if site_id == "zhuque.in" else ""
                    await route.fulfill(status=200, content_type="text/html", body=f"<html><head>{csrf}</head><body>Application shell</body></html>")

            await context.route("https://**/*", route_page)
            await context.add_init_script("localStorage.setItem('auth', 'fictional-session')")
            worker = context.service_workers[0] if context.service_workers else await context.wait_for_event("serviceworker", timeout=10000)
            await worker.evaluate("""async siteId => {
                const configured = Object.fromEntries(sites.catalog.map(site => [site.id, {enabled: site.id === siteId, refreshOnly: true}]));
                await chrome.storage.local.set({autoEnabled: false, sites: configured, scheduleConfig: {timeout: 5}});
                await reschedule();
            }""", site_id)
            dashboard = await context.new_page()
            await dashboard.goto(f"chrome-extension://{worker.url.split('/')[2]}/dashboard.html")
            await expect(dashboard.locator("#inspect")).to_be_enabled(timeout=15000)
            existing = set(context.pages)
            await dashboard.locator(f'[id="run-{site_id}"]').click()
            await expect(dashboard.locator(f'[id="site-status-{site_id}"]')).to_have_text("已刷新", timeout=15000)
            await expect(dashboard.locator(f'[id="profile-level-{site_id}"]')).to_have_text("Lv. 6" if site_id == "rousi.pro" else "Power User")
            await expect(dashboard.locator(f'[id="profile-uploaded-{site_id}"]')).to_have_text("1.00 GiB")
            if site_id == "zhuque.in":
                await expect(dashboard.locator('[id="profile-seedingPoints-zhuque.in"]')).to_have_text("567.8")
            await worker.evaluate("async () => await actionQueue")
            assert set(context.pages) == existing
            if site_id == "zhuque.in":
                stored = await worker.evaluate("async () => (await chrome.storage.local.get('lastResult:zhuque.in'))['lastResult:zhuque.in']")
                assert stored["diagnostic"]["accountFound"] is True
                assert zhuque_headers == ["fictional-csrf"]
            failed = True
            await dashboard.locator(f'[id="run-{site_id}"]').click()
            await expect(dashboard.locator(f'[id="site-status-{site_id}"]')).to_have_text("检查失败", timeout=15000)
            await expect(dashboard.locator(f'[id="profile-level-{site_id}"]')).to_have_text("Lv. 6" if site_id == "rousi.pro" else "Power User")
            await expect(dashboard.locator(f'[id="profile-uploaded-{site_id}"]')).to_have_text("1.00 GiB")
            await worker.evaluate("async () => await actionQueue")
            assert set(context.pages) == existing
            assert all(method == "GET" or pathname == api_path or method == "OPTIONS" for method, pathname in requests)
            assert all("attendance" not in pathname or method == "GET" and pathname in ["/api/v1/me/attendance", "/api/v1/attendance/status"] for method, pathname in requests)
            stored = await worker.evaluate("async siteId => (await chrome.storage.local.get('lastResult:' + siteId))['lastResult:' + siteId]", site_id)
            assert "fictional-session" not in json.dumps(stored)
        finally:
            await context.close()


@pytest.mark.asyncio
async def test_pttime_current_account_entry_during_background_inspection(tmp_path):
    source = Path(__file__).resolve().parents[1]
    extension = tmp_path / "extension"
    shutil.copytree(source, extension, ignore=shutil.ignore_patterns("tests", "__pycache__"))
    manifest_path = extension / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["host_permissions"].extend(["https://www.pttime.org/*", "https://pttime.org/*"])
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    requests = []
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            str(tmp_path / "profile"), channel="chromium", headless=True,
            args=[f"--disable-extensions-except={extension}", f"--load-extension={extension}"],
        )
        try:
            async def route_page(route):
                from urllib.parse import urlsplit

                pathname = urlsplit(route.request.url).path
                requests.append((route.request.method, pathname))
                body = '<div id="info_block"><a href="/userdetails.php?id=42">fixture</a> 用户等级：Power User 魔力值：123.4 上传量：1 GB 下载量：500 MB 分享率：2</div><a href="/attendance.php?type=sign&amp;uid=42">签到领魔力</a>'
                await route.fulfill(status=200, content_type="text/html; charset=utf-8", body=f'<html><meta charset="utf-8"><body>{body}</body></html>')

            await context.route("https://www.pttime.org/**", route_page)
            worker = context.service_workers[0] if context.service_workers else await context.wait_for_event("serviceworker", timeout=10000)
            await worker.evaluate("""async () => {
                await chrome.storage.local.set({autoEnabled: false, sites: {piggo: {enabled: false}, 'pttime.org': {enabled: true}}, scheduleConfig: {timeout: 5}});
                await reschedule();
            }""")
            dashboard = await context.new_page()
            await dashboard.goto(f"chrome-extension://{worker.url.split('/')[2]}/dashboard.html")
            await expect(dashboard.locator("#inspect")).to_be_enabled(timeout=15000)
            existing = set(context.pages)
            await dashboard.locator("#inspect").click()
            await expect(dashboard.locator('[id="site-status-pttime.org"]')).to_have_text("待签到", timeout=15000)
            await expect(dashboard.locator('[id="profile-level-pttime.org"]')).to_have_text("Power User")
            await worker.evaluate("async () => await actionQueue")
            assert set(context.pages) == existing
            assert requests and all(method == "GET" and pathname != "/attendance.php" for method, pathname in requests)
        finally:
            await context.close()


@pytest.mark.asyncio
async def test_52pt_builtin_refresh_profile_slider_and_old_content_upgrade(tmp_path):
    source = Path(__file__).resolve().parents[1]
    extension = tmp_path / "extension"
    shutil.copytree(source, extension, ignore=shutil.ignore_patterns("tests", "__pycache__"))
    manifest_path = extension / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["host_permissions"].extend(["https://52pt.site/*", "https://www.52pt.site/*"])
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    requests = []
    signed = False
    errors = []
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            str(tmp_path / "profile"), channel="chromium", headless=True,
            args=[f"--disable-extensions-except={extension}", f"--load-extension={extension}"],
        )
        try:
            async def route_page(route):
                from urllib.parse import urlsplit

                pathname = urlsplit(route.request.url).path
                requests.append((route.request.method, pathname))
                if pathname == "/userdetails.php":
                    body = '<table><tr><td>等级</td><td><img alt="(幼儿班)User" title="(幼儿班)User"></td></tr><tr><td>魔力值</td><td>1228942.83</td></tr><tr><td>传输</td><td><table><tr><td><strong>分享率</strong>: 192,560.378</td><td>图标</td></tr><tr><td><strong>上传量</strong>: 188.05 GB</td><td><strong>下载量</strong>: 1.00 MB</td></tr></table></td></tr></table>'
                elif pathname == "/bakatest.php":
                    body = "今日已签到" if signed else '<h2>每日签到</h2><div id="slider-container"><button id="slider-btn">→</button></div><button disabled>请先完成滑块</button>'
                elif pathname == "/52bakatestdate0823.php":
                    body = "签到页面已暂停使用，请进入网站签到，谢谢"
                else:
                    body = '<div id="info_block"><a class="User_Name" href="/userdetails.php?id=42">fixture</a><a href="/userdetails.php?id=99">other account</a> 魔力值：1,228,942.8 分享率：无限 上传量：188.05 GB 下载量：1.00 MB [<a id="game" href="/52bakatestdate0823.php">签到赚魔力</a>]</div>'
                await route.fulfill(status=200, content_type="text/html; charset=utf-8", body=f'<html><meta charset="utf-8"><body>{body}</body></html>')

            await context.route("https://52pt.site/**", route_page)
            worker = context.service_workers[0] if context.service_workers else await context.wait_for_event("serviceworker", timeout=10000)
            await worker.evaluate("async () => await chrome.storage.local.set({autoEnabled: false, sites: {piggo: {enabled: false}, '52pt.site': {enabled: false, refreshOnly: false}}})")
            dashboard = await context.new_page()
            await dashboard.set_viewport_size({"width": 1648, "height": 1000})
            dashboard.on("pageerror", lambda error: errors.append(str(error)))
            await dashboard.goto(f"chrome-extension://{worker.url.split('/')[2]}/dashboard.html#sites")
            await expect(dashboard.locator('[id="refresh-only-52pt.site"]')).to_be_checked()
            await expect(dashboard.locator('[id="refresh-only-52pt.site"]')).to_be_disabled()
            existing = set(context.pages)
            await dashboard.locator('[id="enabled-52pt.site"]').check()
            await expect(dashboard.locator("#site-toggle-status")).to_have_text("52PT 已启用")
            await dashboard.locator('#secondary-nav a[href="#overview"]').click()
            overview_box = await dashboard.locator("#view-overview").bounding_box()
            assert overview_box and overview_box["width"] > 1200
            refresh_box = await dashboard.locator('[id="run-52pt.site"]').bounding_box()
            assert refresh_box and refresh_box["x"] + refresh_box["width"] <= 1648
            await dashboard.screenshot(path=str(tmp_path / "wide-overview-fixed.png"), full_page=True)
            await expect(dashboard.locator('[id="site-status-52pt.site"]')).to_have_text("已刷新", timeout=15000)
            await expect(dashboard.locator('[id="profile-level-52pt.site"]')).to_have_text("User")
            await expect(dashboard.locator('[id="profile-ratio-52pt.site"]')).to_have_text("192,560.378")
            await expect(dashboard.locator('[id="profile-bonus-52pt.site"]')).to_have_text("1228942.83")
            await expect(dashboard.locator('[id="profile-seedingPoints-52pt.site"]')).to_have_text("—")
            await expect(dashboard.locator('[id="profile-uploaded-52pt.site"]')).to_have_text("188.05 GB")
            await expect(dashboard.locator('[id="profile-downloaded-52pt.site"]')).to_have_text("1.00 MB")
            await expect(dashboard.locator('[id="run-52pt.site"]')).to_have_text("刷新")
            await worker.evaluate("async () => await actionQueue")
            assert set(context.pages) == existing
            await worker.evaluate("async () => await chrome.scripting.unregisterContentScripts({ids: ['netsurf-pt']})")
            page = await context.new_page()
            await page.goto("https://52pt.site/index.php")
            await worker.evaluate("async () => { const [tab] = await chrome.tabs.query({url: 'https://52pt.site/*'}); await chrome.scripting.executeScript({target: {tabId: tab.id}, func: () => { globalThis.NetSurfContentStarted = true; chrome.runtime.onMessage.addListener((message, sender, respond) => { if (message.type === 'inspect') respond({status: 'already_done'}); }); }}); }")
            await dashboard.locator('[id="run-52pt.site"]').click()
            await expect(dashboard.locator("#inspect")).to_be_enabled(timeout=15000)
            await expect(dashboard.locator('[id="site-status-52pt.site"]')).to_have_text("已刷新")
            assert page.url == "https://52pt.site/index.php"
            revision = await worker.evaluate("async () => { const [tab] = await chrome.tabs.query({url: 'https://52pt.site/*'}); return (await chrome.scripting.executeScript({target: {tabId: tab.id}, func: () => globalThis.NetSurfContentStarted}))[0].result; }")
            assert revision == "2026-10-18-pterclub-v18"
            await dashboard.locator('[id="open-52pt.site"]').click()
            await page.goto("https://52pt.site/bakatest.php")
            await expect(page.locator("#slider-container")).to_be_visible()
            await expect(dashboard.locator("#inspect")).to_be_enabled()
            signed = True
            await dashboard.locator("#inspect").click()
            await expect(dashboard.locator('[id="site-status-52pt.site"]')).to_have_text("已刷新", timeout=15000)
            await expect(dashboard.locator('[id="profile-level-52pt.site"]')).to_have_text("User")
            assert not page.is_closed()
            assert all(method == "GET" for method, pathname in requests)
            assert all(pathname != "/52bakatestdate0823.php" for method, pathname in requests)
            await page.close()
            existing = set(context.pages)
            for attempt in range(2):
                await dashboard.locator('[id="run-52pt.site"]').click()
                await expect(dashboard.locator("#inspect")).to_be_enabled(timeout=15000)
                await expect(dashboard.locator('[id="profile-level-52pt.site"]')).to_have_text("User")
                await expect(dashboard.locator('[id="site-status-52pt.site"]')).to_have_text("已刷新")
                assert set(context.pages) == existing
            assert errors == []
        finally:
            await context.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("anchor_attribute", ["id", "name"])
async def test_refresh_only_and_tjupt_current_rank_in_chromium(tmp_path, anchor_attribute):
    source = Path(__file__).resolve().parents[1]
    extension = tmp_path / "extension"
    shutil.copytree(source, extension, ignore=shutil.ignore_patterns("tests", "__pycache__"))
    manifest_path = extension / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["host_permissions"].extend(["https://tjupt.org/*", "https://www.tjupt.org/*"])
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    requests = []
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

                url = urlsplit(route.request.url)
                requests.append(url.path)
                if url.path == "/userdetails.php":
                    body = '<table><tr><td>等级</td><td><a href="/classes.php#6">等级详情/提升等级</a></td></tr><tr><td>魔力值</td><td>755150.4 <a href="/bonus.php">[明细]</a></td></tr></table>'
                elif url.path == "/classes.php":
                    body = f'<table><tr><td><a {anchor_attribute}="7"></a>橫扫群雄<br>Extreme User</td><td>升级所需魔力：755150.4/400000</td><td><a href="/upgrade.php">点击此处升级</a></td></tr><tr><td><a {anchor_attribute}="6"></a>威震一方<br>Veteran User<br>目前人数：2805人</td><td>升级所需魔力：755150.4/300000</td><td>已达到此等级</td></tr><tr><td><a {anchor_attribute}="5"></a>小有名气<br>Insane User</td><td>升级所需魔力：755150.4/150000</td><td>已达到此等级</td></tr></table>'
                elif url.path == "/attendance.php":
                    submissions.append(url.hostname)
                    body = "今日已签到"
                else:
                    body = '<div id="info_block"><a href="/userdetails.php?id=42">fixture</a> <img title="做种积分">123.45 上传量：5.176 TiB</div><a href="/attendance.php">[签到]</a>'
                await route.fulfill(status=200, content_type="text/html; charset=utf-8", body=f'<html><meta charset="utf-8"><body>{body}</body></html>')

            await context.route("https://tjupt.org/**", route_page)
            await context.route("https://piggo.me/**", route_page)
            worker = context.service_workers[0] if context.service_workers else await context.wait_for_event("serviceworker", timeout=10000)
            await worker.evaluate("async () => await chrome.storage.local.set({sites: {piggo: {enabled: false}}})")
            dashboard = await context.new_page()
            dashboard.on("pageerror", lambda error: errors.append(str(error)))
            await dashboard.goto(f"chrome-extension://{worker.url.split('/')[2]}/dashboard.html#sites")
            await expect(dashboard.locator("#refresh-only")).to_have_count(0)
            await expect(dashboard.locator('[id^="refresh-only-"]')).to_have_count(64)
            assert sorted(await dashboard.locator('[id^="refresh-only-"]:checked').evaluate_all("elements => elements.map(element => element.id)")) == ["refresh-only-52pt.site", "refresh-only-open.cd", "refresh-only-u2.dmhy.org"]
            for site_id in ["52pt.site", "open.cd", "u2.dmhy.org"]:
                await expect(dashboard.locator(f'[id="refresh-only-{site_id}"]')).to_be_checked()
                await expect(dashboard.locator(f'[id="refresh-only-{site_id}"]')).to_be_disabled()
            await dashboard.locator('[id="refresh-only-tjupt.org"]').check()
            await expect(dashboard.locator("#site-toggle-status")).to_have_text("TJUPT 仅刷新已开启")
            await dashboard.reload()
            await expect(dashboard.locator('[id="refresh-only-tjupt.org"]')).to_be_checked()
            await expect(dashboard.locator('[id="refresh-only-piggo"]')).not_to_be_checked()
            await expect(dashboard.locator('[id="enabled-tjupt.org"]')).not_to_be_checked()
            await expect(dashboard.locator("#auto")).not_to_be_checked()
            existing = set(context.pages)
            await dashboard.locator('[id="enabled-tjupt.org"]').check()
            await expect(dashboard.locator("#site-toggle-status")).to_have_text("TJUPT 已启用")
            await dashboard.locator('#secondary-nav a[href="#overview"]').click()
            await expect(dashboard.locator('[id="profile-level-tjupt.org"]')).to_have_text("Veteran User")
            await expect(dashboard.locator('[id="profile-bonus-tjupt.org"]')).to_have_text("755150.4")
            await expect(dashboard.locator('[id="profile-seedingPoints-tjupt.org"]')).to_have_text("123.45")
            await expect(dashboard.locator('[id="run-tjupt.org"]')).to_have_text("刷新")
            await worker.evaluate("async () => await actionQueue")
            assert set(context.pages) == existing
            assert "/classes.php" in requests
            assert "/attendance.php" not in requests
            assert "/upgrade.php" not in requests
            page = await context.new_page()
            await page.goto("https://tjupt.org/index.php")
            await dashboard.locator('[id="run-tjupt.org"]').click()
            await expect(dashboard.locator("#inspect")).to_be_enabled()
            assert "/attendance.php" not in requests
            assert not page.is_closed()
            await dashboard.locator('#secondary-nav a[href="#sites"]').click()
            await dashboard.locator("#site-enabled").check()
            await expect(dashboard.locator("#site-toggle-status")).to_have_text("PigGo 已启用")
            other_page = await context.new_page()
            await other_page.goto("https://piggo.me/index.php")
            await dashboard.locator('#secondary-nav a[href="#overview"]').click()
            await expect(dashboard.locator("#run")).to_have_text("签到")
            await expect(dashboard.locator('[id="run-tjupt.org"]')).to_have_text("刷新")
            await dashboard.locator("#run").click()
            await other_page.wait_for_url("https://piggo.me/attendance.php")
            await expect(dashboard.locator("#site-status")).to_have_text("已完成")
            assert submissions == ["piggo.me"]
            await dashboard.locator('#secondary-nav a[href="#sites"]').click()
            await dashboard.locator('[id="refresh-only-tjupt.org"]').uncheck()
            await expect(dashboard.locator("#site-toggle-status")).to_have_text("TJUPT 仅刷新已关闭")
            await expect(dashboard.locator('[id="enabled-tjupt.org"]')).to_be_checked()
            await dashboard.locator('#secondary-nav a[href="#overview"]').click()
            await expect(dashboard.locator('[id="run-tjupt.org"]')).to_have_text("签到")
            await dashboard.locator('[id="run-tjupt.org"]').click()
            await page.wait_for_url("https://tjupt.org/attendance.php")
            await expect(dashboard.locator('[id="site-status-tjupt.org"]')).to_have_text("已完成")
            assert submissions == ["piggo.me", "tjupt.org"]
            assert errors == []
        finally:
            await context.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("yesterday_signed", [False, True])
async def test_dashboard_in_isolated_chromium(tmp_path, yesterday_signed):
    extension = Path(__file__).resolve().parents[1]
    attendance_requests = []
    errors = []
    server = {"signed": yesterday_signed}
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            str(tmp_path / "profile"), channel="chromium", headless=True,
            args=[f"--disable-extensions-except={extension}", f"--load-extension={extension}"],
        )
        try:
            async def route_page(route):
                profile = '<div id="info_block">欢迎回来 <a href="/userdetails.php?id=42">fixture</a> 魔力值: 1234.50 <img title="上传量"> 2 TiB 下载量: 1 TiB 分享率: 2.000</div>'
                if route.request.url.endswith("/attendance.php"):
                    attendance_requests.append(route.request.url)
                    server["signed"] = True
                    body = "<p>今日已签到</p>"
                elif "/userdetails.php" in route.request.url:
                    amount = "18,142,137.0" if yesterday_signed else "1,358,325.6"
                    body = f'<table><tr><td>用户等级</td><td><span>(小学)Power User</span> 🔗 <a href="/forums.php">校验等级加群参考《规则&amp;教程》第二部分第4条，等级参考第五部分。</a></td></tr><tr><td>魔力值</td><td>{amount} <a href="/bonus.php">[明细]</a></td></tr><tr><td>做种积分</td><td>123.45 <a href="/bonus.php">[明细]</a></td></tr><tr><td>上传量</td><td>2 TiB</td></tr></table>'
                elif server["signed"]:
                    body = '<a href="/attendance.php">[签到已得130, 补签卡: 25]</a>'
                else:
                    body = '<p>聊天记录：今日已签到；签到成功；签到已得130</p><a href="/attendance.php">[签到]</a>'
                await route.fulfill(status=200, content_type="text/html; charset=utf-8", body=f'<html><meta charset="utf-8"><body>{profile}{body}</body></html>')

            await context.route("https://piggo.me/**", route_page)
            worker = context.service_workers[0] if context.service_workers else await context.wait_for_event("serviceworker", timeout=10000)
            extension_id = worker.url.split("/")[2]
            page = context.pages[0] if context.pages else await context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            await page.goto("https://piggo.me/")
            server["signed"] = False
            async with context.expect_page() as created:
                await worker.evaluate("async () => { const [tab] = await chrome.tabs.query({url: 'https://piggo.me/*'}); await openDashboard(tab); }")
            dashboard = await created.value
            dashboard.on("pageerror", lambda error: errors.append(str(error)))
            await dashboard.wait_for_url(f"chrome-extension://{extension_id}/dashboard.html")
            await dashboard.set_viewport_size({"width": 1440, "height": 1000})
            await expect(dashboard.locator("#status")).to_have_text("可以尝试签到")
            await expect(dashboard.locator("#completed-count")).to_have_text("0 / 1")
            await expect(dashboard.locator("#profile-level")).to_have_text("Power User")
            await expect(dashboard.locator("#profile-bonus")).to_have_text("18,142,137.0" if yesterday_signed else "1,358,325.6")
            await expect(dashboard.locator("#profile-seedingPoints")).to_have_text("123.45")
            await expect(dashboard.locator(".overview-table th")).to_have_count(10)
            await expect(dashboard.locator("#profile-uploaded")).to_have_text("2 TiB")
            await expect(dashboard.locator("#profile-downloaded")).to_have_text("1 TiB")
            columns_aligned = await dashboard.evaluate("""() => {
                const headings = [...document.querySelector('.overview-table thead tr').children];
                const cells = [...document.querySelector('#piggo-row').children];
                return headings.every((heading, index) => Math.abs(heading.getBoundingClientRect().left - cells[index].getBoundingClientRect().left) < 1);
            }""")
            assert columns_aligned
            assert attendance_requests == []
            await expect(dashboard.locator(".nav-link")).to_have_count(2)
            await expect(dashboard.locator('[data-group="pt"]')).to_have_text("PT站点")
            await dashboard.locator('#secondary-nav a[href="#sites"]').click()
            await worker.evaluate("async () => { const [tab] = await chrome.tabs.query({url: 'https://piggo.me/*'}); await openDashboard(tab); await openDashboard(tab); }")
            dashboards = await worker.evaluate("async () => (await chrome.runtime.getContexts({contextTypes: ['TAB']})).filter(context => context.documentUrl.split('#')[0] === chrome.runtime.getURL('dashboard.html')).length")
            assert dashboards == 1
            assert len(context.pages) == 2
            await expect(dashboard.locator("#page-title")).to_have_text("站点管理")
            await expect(dashboard.locator("#secondary-nav a")).to_have_count(2)
            await dashboard.locator("#start-time").fill("00:00")
            await dashboard.locator("#retry-interval").fill("90")
            await dashboard.locator("#retry-count").fill("2")
            await dashboard.locator("#timeout").fill("15")
            await dashboard.locator("#site-enabled").uncheck()
            await dashboard.locator("#save-site").click()
            await expect(dashboard.locator("#site-settings-status")).to_have_text("签到设置已保存，所有站点共用")
            await dashboard.locator('#secondary-nav a[href="#overview"]').click()
            await expect(dashboard.locator("#piggo-row")).to_be_hidden()
            await expect(dashboard.locator("#overview-empty")).to_be_visible()
            await expect(dashboard.locator("#completed-count")).to_have_text("0 / 0")
            assert (await worker.evaluate("async () => await handle({type: 'run'}, {url: chrome.runtime.getURL('dashboard.html')})"))["status"] == "disabled"
            assert attendance_requests == []
            await dashboard.locator('#secondary-nav a[href="#sites"]').click()
            await dashboard.locator("#site-enabled").check()
            await worker.evaluate("async () => await chrome.storage.local.set({lastResult: {status: 'ready', message: '可以尝试签到', verified: true, time: new Date().toISOString()}})")
            await expect(dashboard.locator("#retry-interval")).to_have_value("90")
            await expect(dashboard.locator("#site-enabled")).to_be_checked()
            await dashboard.locator("#save-site").click()
            await expect(dashboard.locator("#site-settings-status")).to_have_text("签到设置已保存，所有站点共用")
            await expect(dashboard.locator("#site-list tr")).to_have_count(64)
            shared_box = await dashboard.locator("#site-form").bounding_box()
            list_box = await dashboard.locator("#site-list").bounding_box()
            assert shared_box["y"] + shared_box["height"] < list_box["y"]
            effective = await worker.evaluate("async () => await readState()")
            assert all(config["timeout"] == 15 and config["retryInterval"] == 90 for config in effective["sites"].values())
            await dashboard.evaluate("window.scrollTo(0, 0)")
            await dashboard.screenshot(path=str(tmp_path / "site-management.png"))
            await dashboard.locator('#secondary-nav a[href="#overview"]').click()
            await dashboard.locator("#open").click()
            assert not dashboard.is_closed()
            await dashboard.bring_to_front()
            await dashboard.locator("#run").click()
            await page.wait_for_url("https://piggo.me/attendance.php")
            await expect(dashboard.locator("#status")).to_have_text("今日已签到")
            await dashboard.locator("#run").click()
            await expect(dashboard.locator("#status")).to_have_text("今日已签到")
            assert len(attendance_requests) == 1
            await dashboard.locator('[data-group="settings"]').click()
            await expect(dashboard.locator("#secondary-nav a")).to_have_count(2)
            await expect(dashboard.locator("#view-automation")).to_be_visible()
            await dashboard.locator("#auto").check()
            await expect(dashboard.locator("#settings-status")).to_have_text("已保存：自动签到已开启")
            assert await worker.evaluate("async () => (await chrome.storage.local.get('autoEnabled')).autoEnabled") is True
            await dashboard.locator('#secondary-nav a[href="#about"]').click()
            assert (await worker.evaluate("async () => await chrome.alarms.get('netsurf-daily')"))["name"] == "netsurf-daily"
            await dashboard.evaluate("chrome.permissions.request = async () => false")
            await dashboard.locator('#secondary-nav a[href="#automation"]').click()
            await dashboard.locator("#backup").click()
            await expect(dashboard.locator("#backup-status")).to_have_text("未授权 Cookie 访问，操作已取消")
            await dashboard.screenshot(path=str(tmp_path / "settings.png"), full_page=True)
            await dashboard.locator('#secondary-nav a[href="#about"]').click()
            await expect(dashboard.locator("#about-version")).to_have_text("0.4.41")
            await dashboard.locator('[data-group="pt"]').click()
            await expect(dashboard.locator("#completed-count")).to_have_text("1 / 1")
            await dashboard.screenshot(path=str(tmp_path / "dashboard-desktop.png"), full_page=True)
            await dashboard.set_viewport_size({"width": 390, "height": 844})
            assert await dashboard.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            await dashboard.screenshot(path=str(tmp_path / "dashboard-mobile.png"), full_page=True)
            await dashboard.locator('#secondary-nav a[href="#sites"]').click()
            assert await dashboard.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            await dashboard.screenshot(path=str(tmp_path / "site-management-mobile.png"))
            if yesterday_signed:
                output = Path(__file__).resolve().parents[3] / "tmp" / "netsurf-qa"
                output.mkdir(parents=True, exist_ok=True)
                shutil.copy(tmp_path / "dashboard-desktop.png", output / "dashboard-desktop.png")
                shutil.copy(tmp_path / "dashboard-mobile.png", output / "dashboard-mobile.png")
                shutil.copy(tmp_path / "site-management.png", output / "site-management.png")
                shutil.copy(tmp_path / "site-management-mobile.png", output / "site-management-mobile.png")
                shutil.copy(tmp_path / "settings.png", output / "settings.png")
            assert errors == []
        finally:
            await context.close()


@pytest.mark.asyncio
async def test_shared_schedule_and_independent_sites_in_chromium(tmp_path):
    source = Path(__file__).resolve().parents[1]
    extension = tmp_path / "extension"
    shutil.copytree(source, extension, ignore=shutil.ignore_patterns("tests", "__pycache__"))
    manifest_path = extension / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["host_permissions"].extend(["https://audiences.me/*", "https://www.audiences.me/*"])
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    signed = {"piggo.me": False, "audiences.me": False}
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

                url = urlsplit(route.request.url)
                host = url.hostname
                if url.path == "/attendance.php":
                    submissions.append(host)
                    signed[host] = True
                    body = "今日已签到"
                else:
                    body = '<a href="/attendance.php">[签到已得130]</a>' if signed[host] else '<a href="/attendance.php">[签到]</a>'
                profile = f'<div id="info_block">魔力值: {200 if host == "audiences.me" else 100} 上传量: 2 TiB 下载量: 1 TiB</div>'
                await route.fulfill(status=200, content_type="text/html; charset=utf-8", body=f'<html><meta charset="utf-8"><body>{profile}{body}</body></html>')

            await context.route("https://piggo.me/**", route_page)
            await context.route("https://audiences.me/**", route_page)
            worker = context.service_workers[0] if context.service_workers else await context.wait_for_event("serviceworker", timeout=10000)
            piggo_page = context.pages[0]
            await piggo_page.goto("https://piggo.me/")
            other_page = await context.new_page()
            await other_page.goto("https://audiences.me/")
            dashboard = await context.new_page()
            dashboard.on("pageerror", lambda error: errors.append(str(error)))
            await dashboard.goto(f"chrome-extension://{worker.url.split('/')[2]}/dashboard.html#sites")
            await expect(dashboard.locator("#save-site")).to_be_enabled()
            await expect(dashboard.locator("#site-list tr")).to_have_count(64)
            await dashboard.locator("#start-time").fill("00:00")
            await dashboard.locator("#retry-interval").fill("90")
            await dashboard.locator("#timeout").fill("15")
            await dashboard.locator("#save-site").click()
            await expect(dashboard.locator("#site-settings-status")).to_have_text("签到设置已保存，所有站点共用")
            await dashboard.locator('[id="enabled-audiences.me"]').check()
            await expect(dashboard.locator("#site-toggle-status")).to_have_text("Audiences 已启用")
            registered = await worker.evaluate("async () => await chrome.scripting.getRegisteredContentScripts({ids: ['netsurf-pt']})")
            assert set(registered[0]["matches"]) == {"https://audiences.me/*", "https://www.audiences.me/*"}
            await dashboard.locator('#secondary-nav a[href="#overview"]').click()
            await dashboard.locator("#inspect").click()
            await expect(dashboard.locator("#overview-body tr")).to_have_count(2)
            await expect(dashboard.locator("#inspect")).to_be_enabled(timeout=20000)
            stored_profiles = await worker.evaluate("async () => await chrome.storage.local.get(['lastResult', 'lastResult:audiences.me'])")
            assert stored_profiles["lastResult:audiences.me"]["profile"]["bonus"] == "200", stored_profiles
            await expect(dashboard.locator('[id="profile-bonus-audiences.me"]')).to_have_text("200")
            await expect(dashboard.locator("#profile-bonus")).to_have_text("100")
            await expect(dashboard.locator('[id="site-status-audiences.me"]')).to_have_text("待签到")
            await dashboard.locator('[id="run-audiences.me"]').click()
            await other_page.wait_for_url("https://audiences.me/attendance.php")
            await expect(dashboard.locator('[id="site-status-audiences.me"]')).to_have_text("已完成")
            await expect(dashboard.locator("#site-status")).to_have_text("待签到")
            await dashboard.locator('[id="run-audiences.me"]').click()
            await expect(dashboard.locator("#inspect")).to_be_enabled()
            assert submissions == ["audiences.me"]
            stored = await worker.evaluate("async () => await chrome.storage.local.get(['verifiedDay', 'verifiedDay:audiences.me', 'scheduleConfig'])")
            assert "verifiedDay:audiences.me" in stored
            assert not stored.get("verifiedDay")
            assert stored["scheduleConfig"]["timeout"] == 15
            await dashboard.locator('#secondary-nav a[href="#sites"]').click()
            await dashboard.locator('[id="enabled-audiences.me"]').uncheck()
            await expect(dashboard.locator("#site-toggle-status")).to_have_text("Audiences 已停用")
            assert await worker.evaluate("async () => (await chrome.scripting.getRegisteredContentScripts({ids: ['netsurf-pt']})).length") == 0
            await dashboard.locator('#secondary-nav a[href="#overview"]').click()
            await expect(dashboard.locator("#overview-body tr")).to_have_count(1)
            assert errors == []
        finally:
            await context.close()


@pytest.mark.asyncio
async def test_switch_clicks_save_during_slow_initial_inspection(tmp_path):
    extension = Path(__file__).resolve().parents[1]
    checking = asyncio.Event()
    release = asyncio.Event()
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            str(tmp_path / "profile"), channel="chromium", headless=True,
            args=[f"--disable-extensions-except={extension}", f"--load-extension={extension}"],
        )
        try:
            async def route_page(route):
                if route.request.url.endswith("/index.php"):
                    checking.set()
                    await release.wait()
                await route.fulfill(status=200, content_type="text/html; charset=utf-8", body='<html><meta charset="utf-8"><body>fixture without sign-in controls</body></html>')

            await context.route("https://piggo.me/**", route_page)
            worker = context.service_workers[0] if context.service_workers else await context.wait_for_event("serviceworker", timeout=10000)
            await context.pages[0].goto("https://piggo.me/")
            await worker.evaluate("""async () => {
                for (let attempt = 0; attempt < 40; attempt += 1) {
                    if ((await chrome.storage.local.get('lastResult')).lastResult) break;
                    await new Promise(resolve => setTimeout(resolve, 50));
                }
                await chrome.storage.local.set({lastResult: {status: 'already_done', verified: true, time: new Date().toISOString()}});
            }""")
            dashboard = await context.new_page()
            await dashboard.goto(f"chrome-extension://{worker.url.split('/')[2]}/dashboard.html#automation")
            await asyncio.wait_for(checking.wait(), timeout=5)
            await dashboard.locator('[data-group="pt"]').click()
            await expect(dashboard.locator("#site-status")).to_have_text("已完成")
            await expect(dashboard.locator("#inspect")).to_be_disabled()
            await dashboard.locator('[data-group="settings"]').click()
            await expect(dashboard.locator("#auto")).to_be_enabled()
            await dashboard.locator("#auto").click(position={"x": 8, "y": 12})
            await expect(dashboard.locator("#settings-status")).to_have_text("已保存：自动签到已开启")
            await expect(dashboard.locator("#auto")).to_be_checked()
            assert await worker.evaluate("async () => (await chrome.storage.local.get('autoEnabled')).autoEnabled") is True
            await dashboard.reload()
            await expect(dashboard.locator("#auto")).to_be_checked()
            await expect(dashboard.locator("#auto-mode")).to_have_text("已开启")
            await dashboard.locator('[data-group="pt"]').click()
            await expect(dashboard.locator("#site-status")).to_have_text("已完成")
            await dashboard.locator('[data-group="settings"]').click()
            await dashboard.locator("#auto").click()
            await expect(dashboard.locator("#settings-status")).to_have_text("已保存：自动签到已关闭")
            await dashboard.locator('[data-group="pt"]').click()
            await dashboard.locator('#secondary-nav a[href="#sites"]').click()
            await expect(dashboard.locator("#site-enabled")).to_be_enabled()
            await dashboard.locator("#site-enabled").click()
            await expect(dashboard.locator("#site-toggle-status")).to_have_text("PigGo 已停用")
            await dashboard.locator("#site-enabled").click(position={"x": 8, "y": 12})
            await expect(dashboard.locator("#site-toggle-status")).to_have_text("PigGo 已启用")
            await dashboard.reload()
            await expect(dashboard.locator("#site-enabled")).to_be_checked()
            await dashboard.evaluate("chrome.permissions.request = async () => false")
            await dashboard.locator("#site-search").fill("Audiences")
            await dashboard.locator('[id="enabled-audiences.me"]').click()
            await expect(dashboard.locator("#site-toggle-status")).to_have_text("未授权站点访问，启用已取消")
            await expect(dashboard.locator('[id="enabled-audiences.me"]')).not_to_be_checked()
            feedback = await dashboard.locator("#site-toggle-status").bounding_box()
            row = await dashboard.locator("#site-list tr").bounding_box()
            assert feedback["y"] < row["y"]
        finally:
            release.set()
            await context.close()


@pytest.mark.asyncio
async def test_cookie_backup_restore_with_pregranted_permission(tmp_path):
    source = Path(__file__).resolve().parents[1]
    extension = tmp_path / "extension"
    shutil.copytree(source, extension, ignore=shutil.ignore_patterns("tests", "__pycache__"))
    manifest_path = extension / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["permissions"].append("cookies")
    manifest["optional_permissions"] = []
    manifest["host_permissions"].extend(manifest["optional_host_permissions"])
    manifest["optional_host_permissions"] = []
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            str(tmp_path / "profile"), channel="chromium", headless=True,
            args=[f"--disable-extensions-except={extension}", f"--load-extension={extension}"], accept_downloads=True,
        )
        try:
            worker = context.service_workers[0] if context.service_workers else await context.wait_for_event("serviceworker", timeout=10000)
            await context.add_cookies([
                {"name": "netsurf-fixture", "value": "fixture-only", "url": "https://piggo.me/", "httpOnly": True, "secure": True, "sameSite": "Lax"},
                {"name": "ordinary", "value": "other-site-only", "domain": ".ordinary.test", "path": "/account", "httpOnly": True, "secure": True, "sameSite": "Strict"},
                {"name": "local", "value": "http-only", "url": "http://localhost/", "httpOnly": False, "secure": False, "sameSite": "Lax"},
            ])
            await worker.evaluate("async () => await chrome.cookies.set({url: 'https://cdn.ordinary.test/', name: 'partitioned', value: 'partition-fixture', secure: true, httpOnly: true, sameSite: 'no_restriction', partitionKey: {topLevelSite: 'https://parent.test', hasCrossSiteAncestor: true}})")
            dashboard = context.pages[0]
            await dashboard.goto(f"chrome-extension://{worker.url.split('/')[2]}/dashboard.html#automation")
            await expect(dashboard.locator("#backup")).to_be_enabled()
            async with dashboard.expect_download() as downloaded:
                await dashboard.locator("#backup").click()
            download = await downloaded.value
            file_path = await download.path()
            document = json.loads(Path(file_path).read_text(encoding="utf-8"))
            assert document["format"] == "netsurf-backup"
            assert len(document["cookies"]) == 4
            by_name = {cookie["name"]: cookie for cookie in document["cookies"]}
            assert by_name["netsurf-fixture"]["httpOnly"] is True
            assert by_name["netsurf-fixture"]["value"] == "fixture-only"
            assert by_name["partitioned"]["partitionKey"]["topLevelSite"] == "https://parent.test"
            assert by_name["ordinary"]["domain"] == ".ordinary.test"
            assert by_name["local"]["secure"] is False
            assert document["cookieScope"] == "all-sites"
            assert len(document["settings"]["sites"]) == 64
            assert "operation" not in document["settings"]
            await context.clear_cookies()
            document["settings"]["sites"]["piggo"]["enabled"] = False
            document["settings"]["scheduleConfig"]["timeout"] = 45
            await dashboard.locator("#restore-file").set_input_files({"name": "fixture-backup.json", "mimeType": "application/json", "buffer": json.dumps(document).encode()})
            await expect(dashboard.locator("#backup-status")).to_contain_text("还原完成：4 条 Cookie 已恢复")
            restored_all = await worker.evaluate("async () => await chrome.cookies.getAll({partitionKey: {}})")
            assert len(restored_all) == 4
            for original in document["cookies"]:
                restored_cookie = next(cookie for cookie in restored_all if cookie["name"] == original["name"])
                for field in ["domain", "path", "value", "secure", "httpOnly", "sameSite", "hostOnly", "session", "partitionKey"]:
                    assert restored_cookie.get(field) == original.get(field)
            restored = await context.cookies("https://piggo.me/")
            assert restored[0]["value"] == "fixture-only"
            assert restored[0]["httpOnly"] is True
            assert restored[0]["sameSite"] == "Lax"
            await dashboard.locator('[data-group="pt"]').click()
            await expect(dashboard.locator("#piggo-row")).to_be_hidden()
            await dashboard.locator('#secondary-nav a[href="#sites"]').click()
            await expect(dashboard.locator("#timeout")).to_have_value("45")
            await dashboard.locator('[data-group="settings"]').click()
            invalid = {**document, "version": 99}
            await dashboard.locator("#restore-file").set_input_files({"name": "invalid.json", "mimeType": "application/json", "buffer": json.dumps(invalid).encode()})
            await expect(dashboard.locator("#backup-status")).to_have_text("不是受支持的 NetSurf 备份文件")
        finally:
            await context.close()


@pytest.mark.asyncio
async def test_update_handler_refreshes_existing_dashboard_and_preserves_settings(tmp_path):
    source = Path(__file__).resolve().parents[1]
    extension = tmp_path / "extension"
    shutil.copytree(source, extension, ignore=shutil.ignore_patterns("tests", "__pycache__"))
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            str(tmp_path / "profile"), channel="chromium", headless=True,
            args=[f"--disable-extensions-except={extension}", f"--load-extension={extension}"],
        )
        try:
            await context.route("https://fixture.test/**", lambda route: route.fulfill(status=200, content_type="text/html", body="<html><body>fixture</body></html>"))
            ordinary = context.pages[0]
            await ordinary.goto("https://fixture.test/")
            await ordinary.evaluate("window.fixtureKeep = 'unchanged'")
            worker = context.service_workers[0] if context.service_workers else await context.wait_for_event("serviceworker", timeout=10000)
            await worker.evaluate("async () => await chrome.storage.local.set({autoEnabled: false, sites: {piggo: {enabled: false}}, scheduleConfig: {startTime: '10:15', retryInterval: 90, retryCount: 2, timeout: 15}})")
            dashboard = await context.new_page()
            await dashboard.goto(f"chrome-extension://{worker.url.split('/')[2]}/dashboard.html#sites")
            await expect(dashboard.locator("#version")).to_have_text("v0.4.41")
            await dashboard.evaluate("window.fixtureBeforeReload = true; document.getElementById('version').textContent = 'v0.2.0'")
            await worker.evaluate("async () => await installed({reason: 'update'})")
            await expect(dashboard.locator("#version")).to_have_text("v0.4.41", timeout=15000)
            assert await dashboard.evaluate("window.fixtureBeforeReload === undefined")
            assert dashboard.url.endswith("#sites")
            await expect(dashboard.locator("#start-time")).to_have_value("10:15")
            await expect(dashboard.locator("#site-enabled")).not_to_be_checked()
            assert await ordinary.evaluate("window.fixtureKeep") == "unchanged"
            await dashboard.locator('[data-group="settings"]').click()
            await dashboard.locator("#auto").click()
            await expect(dashboard.locator("#settings-status")).to_have_text("已保存：自动签到已开启")
            await dashboard.reload()
            await expect(dashboard.locator("#auto")).to_be_checked()
        finally:
            await context.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("confirmed", [True, False])
async def test_automatic_sites_finish_and_close_before_next_site(tmp_path, confirmed):
    source = Path(__file__).resolve().parents[1]
    extension = tmp_path / "extension"
    shutil.copytree(source, extension, ignore=shutil.ignore_patterns("tests", "__pycache__"))
    manifest_path = extension / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["host_permissions"] = ["https://*/*"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    submissions = []
    signed = False
    lifecycle = []
    live_tasks = set()
    maximum_tasks = 0
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            str(tmp_path / "profile"), channel="chromium", headless=True,
            args=[f"--disable-extensions-except={extension}", f"--load-extension={extension}"],
        )
        try:
            async def route_page(route):
                nonlocal signed
                from urllib.parse import urlsplit

                url = urlsplit(route.request.url)
                if url.hostname == "audiences.me":
                    body = "<p>安全验证</p><script src='https://challenges.cloudflare.com/fixture'></script>"
                    status = 403
                elif url.path == "/attendance.php":
                    submissions.append(url.hostname)
                    await asyncio.sleep(0.3)
                    signed = confirmed
                    body = "今日已签到" if confirmed else "<p>处理中</p>"
                    status = 200
                elif url.hostname == "piggo.me":
                    body = '<a href="/attendance.php">[签到已得130]</a>' if signed else '<a href="/attendance.php">[签到]</a>'
                    status = 200
                else:
                    body = "<p>用户原有网页</p>"
                    status = 200
                await route.fulfill(status=status, content_type="text/html; charset=utf-8", body=f'<html><meta charset="utf-8"><body>{body}</body></html>')

            await context.route("https://**/*", route_page)
            worker = context.service_workers[0] if context.service_workers else await context.wait_for_event("serviceworker", timeout=10000)
            user_page = context.pages[0]
            await user_page.goto("https://hdsky.me/")
            await user_page.evaluate("window.userMarker = 'keep'")
            dashboard = await context.new_page()
            await dashboard.goto(f"chrome-extension://{worker.url.split('/')[2]}/dashboard.html#sites")
            existing = set(context.pages)

            def opened(page):
                nonlocal maximum_tasks
                if page in existing:
                    return
                live_tasks.add(page)
                maximum_tasks = max(maximum_tasks, len(live_tasks))
                lifecycle.append("open")
                page.on("close", lambda: (live_tasks.discard(page), lifecycle.append("close")))

            context.on("page", opened)
            await worker.evaluate("""async () => {
                const configured = Object.fromEntries(sites.catalog.map(site => [site.id, {enabled: ['piggo', 'audiences.me'].includes(site.id)}]));
                await chrome.storage.local.set({autoEnabled: true, sites: configured, scheduleConfig: {startTime: '00:00', retryInterval: 30, retryCount: 1, timeout: 5}});
                await syncScripts(await readState());
                for (const name of ['netsurf-daily', 'netsurf-daily:audiences.me']) {
                    actionQueue = actionQueue.catch(() => {}).then(() => withWorkerAlive(() => alarmAction({name})));
                }
                await actionQueue;
            }""")
            await expect(dashboard.locator("#version")).to_have_text("v0.4.41")
            stored = await worker.evaluate("async () => await chrome.storage.local.get(['lastResult', 'lastResult:audiences.me', 'verifiedDay'])")
            assert submissions == ["piggo.me"], stored
            assert stored["lastResult"]["status"] in (["already_done", "success"] if confirmed else ["pending"])
            assert bool(stored.get("verifiedDay")) == confirmed
            assert stored["lastResult:audiences.me"]["status"] in ["blocked", "manual_required"]
            assert await worker.evaluate("async () => (await chrome.storage.session.get('taskTab')).taskTab === undefined")
            assert not await worker.evaluate("async () => await chrome.alarms.get('netsurf-verify')")
            for attempt in range(20):
                if lifecycle == ["open", "close", "open", "close"]:
                    break
                await asyncio.sleep(0.05)
            assert lifecycle == ["open", "close", "open", "close"]
            assert maximum_tasks == 1
            assert set(context.pages) == existing
            assert await user_page.evaluate("window.userMarker") == "keep"
            assert not dashboard.is_closed()
            previous_time = stored["lastResult"]["time"]
            await dashboard.goto(f"chrome-extension://{worker.url.split('/')[2]}/dashboard.html#overview")
            await expect(dashboard.locator("#site-status")).to_have_text("已完成" if confirmed else "待确认")
            await dashboard.locator("#inspect").click()
            await expect(dashboard.locator("#inspect")).to_be_enabled(timeout=15000)
            refreshed = await worker.evaluate("async () => (await chrome.storage.local.get('lastResult')).lastResult")
            assert refreshed["time"] != previous_time
            assert refreshed["status"] == stored["lastResult"]["status"]
            assert submissions == ["piggo.me"]
            assert maximum_tasks == 1
            await worker.evaluate("async () => await installed({reason: 'update'})")
            await expect(dashboard.locator("#site-status")).to_have_text("已完成" if confirmed else "待确认")
            assert set(context.pages) == existing
        finally:
            await context.close()
