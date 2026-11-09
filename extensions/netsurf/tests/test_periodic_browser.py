from pathlib import Path
import json
import shutil

import pytest
from playwright.async_api import async_playwright, expect


@pytest.mark.asyncio
@pytest.mark.parametrize("site_id", ["nodeseek", "invitesfun"])
async def test_periodic_current_site_controls(tmp_path, site_id):
    source = Path(__file__).resolve().parents[1]
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(channel="chromium", headless=True)
        try:
            page = await browser.new_page()
            if site_id == "nodeseek":
                body = '<div class="board"><div class="head-info"><div>今日还未签到， <button class="btn">鸡腿 x 5</button> / <button class="btn">试试手气</button></div></div></div>'
            else:
                body = '<li class="item-forum-checkin App-primaryControl"><button class="Button CheckInButton--green hasIcon disabled" disabled>已签到 1 天</button></li>'
            await page.route("https://**/*", lambda route: route.fulfill(content_type="text/html; charset=utf-8", body=body))
            await page.goto("https://www.nodeseek.com/board" if site_id == "nodeseek" else "https://www.invites.fun/")
            await page.add_script_tag(path=str(source / "periodic.js"))
            await page.evaluate("window.submissions = []; window.chrome = {runtime: {sendMessage: async message => {submissions.push(message); return {accepted: true};}}};")
            state = await page.evaluate("async taskId => await NetSurfPeriodic.pageAction(taskId, 'inspect', null, 1000)", site_id)
            assert state["status"] == ("ready" if site_id == "nodeseek" else "already_done")
            assert await page.evaluate("submissions") == []
            if site_id == "nodeseek":
                await page.locator(".head-info").evaluate("element => element.innerHTML = '今日签到获得鸡腿5个'")
                state = await page.evaluate("async () => await NetSurfPeriodic.pageAction('nodeseek', 'run', 'unused', 1000)")
                assert state["status"] == "already_done"
                await page.locator(".head-info").evaluate("element => element.innerHTML = '正在加载'")
                await page.evaluate("document.body.insertAdjacentHTML('beforeend', '<article>今日已签到，签到成功</article>')")
                state = await page.evaluate("async () => await NetSurfPeriodic.pageAction('nodeseek', 'run', 'unused', 1000)")
                assert state["status"] == "unknown"
            else:
                await page.locator("button").evaluate("element => {element.className = 'CheckInButton--yellow'; element.textContent = '签到';}")
                state = await page.evaluate("async () => await NetSurfPeriodic.pageAction('invitesfun', 'run', 'unused', 1000)")
                assert state["status"] == "unknown"
            assert await page.evaluate("submissions") == []
        finally:
            await browser.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("site_id", ["nodeseek", "invitesfun"])
@pytest.mark.parametrize("outcome", ["success", "blocked", "unconfirmed"])
async def test_daily_navigation_switches_and_signin(tmp_path, site_id, outcome):
    source = Path(__file__).resolve().parents[1]
    extension = tmp_path / "extension"
    shutil.copytree(source, extension, ignore=shutil.ignore_patterns("tests", "__pycache__"))
    manifest_path = extension / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["host_permissions"] = ["https://*/*"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    adapter = extension / "periodic.js"
    adapter.write_text(adapter.read_text(encoding="utf-8").replace("timeout: 60", "timeout: 5", 1), encoding="utf-8")
    submissions = []
    errors = []
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            str(tmp_path / "profile"), channel="chromium", headless=True,
            viewport={"width": 1440, "height": 1000},
            args=[f"--disable-extensions-except={extension}", f"--load-extension={extension}"],
        )
        try:
            async def route_page(route):
                from urllib.parse import urlsplit

                target = urlsplit(route.request.url)
                if target.path == "/api/attendance":
                    assert route.request.method == "POST"
                    assert target.query == "random=false"
                    assert route.request.post_data_json == {"random": False}
                    submissions.append(site_id)
                    await route.fulfill(json={"success": outcome == "success"})
                    return
                if target.path == "/fixture-click":
                    submissions.append(site_id)
                    await route.fulfill(json={"ok": True})
                    return
                if outcome == "blocked":
                    body = "验证您是真人"
                elif site_id == "nodeseek":
                    body = '<div class="board"><div class="head-info"><div>今日还未签到， <button class="btn">鸡腿 x 5</button> / <button class="btn">试试手气</button></div></div></div>'
                else:
                    changed = "this.classList.replace('CheckInButton--yellow','CheckInButton--green');this.textContent='已签到1天';this.disabled=true;" if outcome == "success" else ""
                    body = f'''<div class="item-forum-checkin"><button class="CheckInButton--yellow" onclick="fetch('/fixture-click',{{method:'POST'}});{changed}">签到</button></div>'''
                await route.fulfill(status=200, content_type="text/html; charset=utf-8", body=f'<html><meta charset="utf-8"><body>{body}</body></html>')

            await context.route("https://**/*", route_page)
            worker = context.service_workers[0] if context.service_workers else await context.wait_for_event("serviceworker", timeout=10000)
            await worker.evaluate("""async () => {
                await chrome.storage.local.set({autoEnabled: false, sites: Object.fromEntries(sites.catalog.map(site => [site.id, {enabled: false}]))});
                const createAlarm = chrome.alarms.create.bind(chrome.alarms);
                chrome.alarms.create = (name, options) => createAlarm(name, name.startsWith('netsurf-periodic:') ? {when: Date.now() + 86400000} : options);
            }""")
            user_page = context.pages[0]
            await user_page.goto("https://www.nodeseek.com/post-123")
            await user_page.evaluate("window.userMarker = 'preserve'")
            dashboard = await context.new_page()
            dashboard.on("pageerror", lambda error: errors.append(str(error)))
            extension_id = worker.url.split("/")[2]
            await dashboard.goto(f"chrome-extension://{extension_id}/dashboard.html")
            assert await dashboard.title() == "NetSurf · PT站点"
            nav = dashboard.locator('.sidebar nav .nav-link')
            assert await nav.all_text_contents() == ["PT站点", "定时任务", "设置"]
            await dashboard.get_by_role("link", name="定时任务", exact=True).click()
            await expect(dashboard.locator("#page-title")).to_have_text("概览")
            await expect(dashboard.locator("#secondary-nav a")).to_have_text(["概览", "设置"])
            await expect(dashboard.locator("#view-periodic")).to_be_visible()
            await expect(dashboard.locator("#view-overview")).to_be_hidden()
            await expect(dashboard.locator("#periodic-summary")).to_have_text("2 个任务 · 已启用 0")
            assert await dashboard.locator("#view-periodic input").count() == 0
            assert await dashboard.locator("#periodic-task-list tr").count() == 2
            assert await dashboard.locator('#view-periodic button').all_text_contents() == ["一键执行", "打开", "执行", "打开", "执行"]
            await expect(dashboard.locator("#periodic-run-all")).to_be_disabled()
            await dashboard.locator('#secondary-nav a[href="#periodic-settings"]').click()
            await expect(dashboard.locator("#view-periodic-settings")).to_be_visible()
            await expect(dashboard.locator("#view-periodic")).to_be_hidden()
            assert await dashboard.locator("#view-periodic-settings input").count() == 2
            assert await dashboard.locator('#view-periodic-settings input[type="checkbox"]').count() == 2
            assert await dashboard.locator("#view-periodic-settings button, #view-periodic-settings form").count() == 0
            assert await dashboard.locator(f"#periodic-{site_id}-enabled").evaluate("element => element.getBoundingClientRect().width") == 40
            await dashboard.evaluate("() => { window.periodicPermission = chrome.permissions.request; chrome.permissions.request = async () => false; }")
            await dashboard.locator(f"#periodic-{site_id}-enabled").click()
            await expect(dashboard.locator("#periodic-settings-feedback")).to_have_text("未授权站点访问，任务未启用")
            await expect(dashboard.locator(f"#periodic-{site_id}-enabled")).not_to_be_checked()
            await dashboard.evaluate("() => { chrome.permissions.request = window.periodicPermission; }")
            await dashboard.locator(f"#periodic-{site_id}-enabled").check()
            await expect(dashboard.locator("#periodic-settings-feedback")).to_have_text(f"{'NodeSeek' if site_id == 'nodeseek' else 'InvitesFun'} 每日签到已开启")
            await expect(dashboard.locator("#periodic-summary")).to_have_text("2 个任务 · 已启用 1")
            await dashboard.reload()
            await expect(dashboard.locator(f"#periodic-{site_id}-enabled")).to_be_checked()
            for width in [1440, 390]:
                await dashboard.set_viewport_size({"width": width, "height": 1000})
                assert await dashboard.evaluate("document.documentElement.scrollWidth <= innerWidth")
                if outcome == "success":
                    screenshot = source.parents[1] / "tmp" / "netsurf-qa" / f"periodic-settings-{site_id}-{width}.png"
                    await dashboard.screenshot(path=str(screenshot), full_page=True)
            await dashboard.locator('#secondary-nav a[href="#periodic"]').click()
            await worker.evaluate("async taskId => await periodic.run(taskId, 'inspect')", site_id)
            status = dashboard.locator(f"#periodic-status-{site_id}")
            await expect(status).to_have_text("需验证" if outcome == "blocked" else "待签到")
            assert submissions == []
            await dashboard.locator("#periodic-run-all").click()
            await expect(status).to_have_text({"success": "已完成", "blocked": "需验证", "unconfirmed": "执行失败"}[outcome], timeout=15000)
            await expect(dashboard.locator(f"#periodic-run-{site_id}")).to_be_enabled()
            await dashboard.locator(f"#periodic-run-{site_id}").click()
            await expect(dashboard.locator(f"#periodic-run-{site_id}")).to_be_enabled(timeout=15000)
            assert submissions == ([] if outcome == "blocked" else [site_id])
            stored = await worker.evaluate("async () => await periodic.read()")
            assert bool(stored["states"][site_id].get("completedDay")) == (outcome == "success")
            if outcome == "success":
                next_time = await dashboard.evaluate("timestamp => {const date = new Date(timestamp); return [date.getHours(), date.getMinutes(), date.getDate() !== new Date().getDate()];}", stored["states"][site_id]["nextAt"])
                assert next_time == [8, 0, True]
            assert len(stored["history"]) == 3
            assert await user_page.evaluate("window.userMarker") == "preserve"
            assert set(context.pages) == {user_page, dashboard}
            alarms = await worker.evaluate("async () => (await chrome.alarms.getAll()).filter(alarm => alarm.name.startsWith('netsurf-periodic:')).map(alarm => alarm.name)")
            assert alarms == [f"netsurf-periodic:{site_id}"]
            for width in [1440, 390]:
                await dashboard.set_viewport_size({"width": width, "height": 1000})
                assert await dashboard.evaluate("document.documentElement.scrollWidth <= innerWidth")
                if outcome == "success":
                    screenshot = source.parents[1] / "tmp" / "netsurf-qa" / f"periodic-{site_id}-{width}.png"
                    await dashboard.screenshot(path=str(screenshot), full_page=True)
            await worker.evaluate("async () => await installed({reason:'update'})")
            await expect(dashboard.locator(f"#periodic-{site_id}-enabled")).to_be_checked()
            assert await user_page.evaluate("window.userMarker") == "preserve"
            assert submissions == ([] if outcome == "blocked" else [site_id])
            if outcome == "success":
                await worker.evaluate("async taskId => {const {periodicState} = await chrome.storage.local.get('periodicState'); periodicState[taskId].lastResult = {status:'error',message:'只读检查失败',time:new Date().toISOString()}; await chrome.storage.local.set({periodicState});}", site_id)
                await expect(status).to_have_text("已完成")
                await expect(dashboard.locator(f"#periodic-result-{site_id}")).to_contain_text("只读检查失败")
                await worker.evaluate("async taskId => {const {periodicState} = await chrome.storage.local.get('periodicState'); periodicState[taskId].completedDay = '2000-1-1'; periodicState[taskId].lastResult.status = 'success'; await chrome.storage.local.set({periodicState});}", site_id)
                await expect(status).to_have_text("待签到")
            await dashboard.locator('#secondary-nav a[href="#periodic-settings"]').click()
            await dashboard.locator(f"#periodic-{site_id}-enabled").uncheck()
            await expect(dashboard.locator("#periodic-settings-feedback")).to_have_text(f"{'NodeSeek' if site_id == 'nodeseek' else 'InvitesFun'} 每日签到已关闭")
            assert await worker.evaluate("async () => (await chrome.alarms.getAll()).filter(alarm => alarm.name.startsWith('netsurf-periodic:')).length") == 0
            await dashboard.reload()
            await expect(dashboard.locator(f"#periodic-{site_id}-enabled")).not_to_be_checked()
            assert submissions == ([] if outcome == "blocked" else [site_id])
            assert errors == []
        finally:
            await context.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["query-error", "query-stall", "save-error", "save-stall", "incompatible", "cached-on"])
async def test_daily_switches_recover_from_backend_failure(tmp_path, mode):
    source = Path(__file__).resolve().parents[1]
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(channel="chromium", headless=True)
        try:
            page = await browser.new_page(viewport={"width": 1440, "height": 900})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))

            async def serve_dashboard(route):
                filename = route.request.url.rsplit("/", 1)[-1]
                if filename not in {"dashboard.html", "dashboard.css", "catalog.js", "site-rules.js", "sites.js", "dashboard.js", "periodic.js", "periodic-dashboard.js"}:
                    await route.abort()
                    return
                await route.fulfill(path=str(source / filename))

            await page.route("http://netsurf.test/**", serve_dashboard)
            await page.add_init_script("""mode => {
                window.fixtureMode = mode;
                window.fixtureMessages = [];
                window.fixtureChanges = [];
                window.fixtureStore = {periodicTasks: {nodeseek: {enabled: mode === 'cached-on'}, invitesfun: {enabled: false}}};
                const nativeTimeout = window.setTimeout.bind(window);
                window.setTimeout = (callback, milliseconds, ...args) => nativeTimeout(callback, milliseconds === 10000 ? 200 : milliseconds, ...args);
                window.chrome = {
                    runtime: {getManifest: () => ({version: 'test'}), sendMessage: async message => {
                        fixtureMessages.push(message);
                        if (message.type === 'periodic-list') {
                            if (fixtureMode === 'query-stall') return new Promise(() => {});
                            return null;
                        }
                        if (message.type === 'periodic-settings') {
                            if (fixtureMode === 'save-error') throw new Error('模拟保存失败');
                            if (fixtureMode === 'save-stall') return new Promise(() => {});
                            if (fixtureMode === 'incompatible') return null;
                            fixtureStore.periodicTasks[message.taskId] = {enabled: message.config.enabled};
                            fixtureChanges.forEach(callback => callback({periodicTasks: {newValue: structuredClone(fixtureStore.periodicTasks)}}, 'local'));
                            return {saved: true};
                        }
                        return {results: {}};
                    }},
                    permissions: {request: async () => true},
                    storage: {
                        local: {get: async () => ({...structuredClone(fixtureStore), sites: Object.fromEntries(NetSurfSites.catalog.map(site => [site.id, {enabled: false}]))})},
                        onChanged: {addListener: callback => fixtureChanges.push(callback)}
                    }
                };
            }""".replace("mode => {", "(() => { const mode = " + json.dumps(mode) + ";", 1) + ")()")
            await page.goto("http://netsurf.test/dashboard.html#periodic-settings")
            toggle = page.locator("#periodic-nodeseek-enabled")
            await expect(toggle).to_be_enabled(timeout=1500)
            assert await toggle.is_checked() == (mode == "cached-on")
            await toggle.click()
            feedback = page.locator("#periodic-settings-feedback")
            if mode in {"save-error", "save-stall", "incompatible"}:
                await expect(feedback).to_contain_text({"save-error": "模拟保存失败", "save-stall": "超时", "incompatible": "重新加载"}[mode])
                await expect(toggle).not_to_be_checked()
                await expect(toggle).to_be_enabled()
                await page.evaluate("window.fixtureMode = 'query-error'")
                await toggle.click()
            await expect(feedback).to_have_text("NodeSeek 每日签到已关闭" if mode == "cached-on" else "NodeSeek 每日签到已开启")
            await expect(toggle).to_be_enabled()
            assert await toggle.is_checked() == (mode != "cached-on")
            assert await page.evaluate("fixtureMessages.filter(message => message.type === 'periodic-list').length") == 0
            assert errors == []
        finally:
            await browser.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["success", "partial", "communication", "timeout", "disabled", "completed", "mixed"])
async def test_daily_bulk_execution(tmp_path, mode):
    source = Path(__file__).resolve().parents[1]
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(channel="chromium", headless=True)
        try:
            page = await browser.new_page(viewport={"width": 1440, "height": 900})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))

            async def serve_dashboard(route):
                filename = route.request.url.rsplit("/", 1)[-1]
                if filename not in {"dashboard.html", "dashboard.css", "catalog.js", "site-rules.js", "sites.js", "dashboard.js", "periodic.js", "periodic-dashboard.js"}:
                    await route.abort()
                    return
                await route.fulfill(path=str(source / filename))

            await page.route("http://netsurf.test/**", serve_dashboard)
            await page.add_init_script("""(() => {
                const mode = MODE;
                window.fixtureMessages = [];
                window.fixtureChanges = [];
                window.fixtureActive = 0;
                window.fixtureMaxActive = 0;
                window.fixtureStore = {periodicTasks: {nodeseek: {enabled: mode !== 'disabled'}, invitesfun: {enabled: mode !== 'disabled'}}, periodicState: {}};
                const nativeTimeout = window.setTimeout.bind(window);
                window.setTimeout = (callback, milliseconds, ...args) => nativeTimeout(callback, milliseconds === 70000 ? 500 : milliseconds, ...args);
                window.chrome = {
                    runtime: {getManifest: () => ({version: 'test'}), sendMessage: async message => {
                        if (message.type !== 'periodic-run') return {};
                        fixtureMessages.push(message);
                        fixtureActive++;
                        fixtureMaxActive = Math.max(fixtureMaxActive, fixtureActive);
                        await new Promise(resolve => {window.fixtureRelease = resolve;});
                        fixtureActive--;
                        if (mode === 'communication') throw new Error('模拟通信失败');
                        if (mode === 'timeout') return new Promise(() => {});
                        const failed = mode === 'partial' && message.taskId === 'nodeseek';
                        const result = {status: failed ? 'blocked' : 'success', message: failed ? '需验证' : '签到成功', time: new Date().toISOString()};
                        fixtureStore.periodicState[message.taskId] = {lastResult: result, ...(failed ? {} : {completedDay: NetSurfPeriodic.day()})};
                        fixtureChanges.forEach(callback => callback({periodicState: {}}, 'local'));
                        return result;
                    }},
                    permissions: {request: async () => true},
                    storage: {
                        local: {get: async () => ({...structuredClone(fixtureStore), sites: Object.fromEntries(NetSurfSites.catalog.map(site => [site.id, {enabled: false}]))})},
                        onChanged: {addListener: callback => fixtureChanges.push(callback)}
                    }
                };
                document.addEventListener('DOMContentLoaded', () => {
                    if (mode === 'completed' || mode === 'mixed') {
                        fixtureStore.periodicState = Object.fromEntries((mode === 'mixed' ? ['nodeseek'] : ['nodeseek', 'invitesfun']).map(taskId => [taskId, {completedDay: NetSurfPeriodic.day()}]));
                        fixtureChanges.forEach(callback => callback({periodicState: {}}, 'local'));
                    }
                });
            })()""".replace("MODE", json.dumps(mode), 1))
            await page.goto("http://netsurf.test/dashboard.html#periodic")
            assert await page.title() == "NetSurf · PT站点"
            await expect(page.locator("#view-periodic")).to_be_visible()
            assert await page.locator('#view-periodic button').all_text_contents() == ["一键执行", "打开", "执行", "打开", "执行"]
            bulk = page.get_by_role("button", name="一键执行", exact=True)
            if mode == "disabled":
                await expect(bulk).to_be_disabled()
                assert await page.evaluate("fixtureMessages") == []
                return
            await expect(bulk).to_be_enabled()
            await bulk.click()
            if mode != "completed":
                await expect(bulk).to_be_disabled()
                assert await page.locator('#view-periodic button:enabled').count() == 0
                await page.evaluate("document.getElementById('periodic-run-all').click()")
                assert await page.evaluate("fixtureMessages.length") == 1
                await page.evaluate("fixtureRelease()")
                if mode not in {"communication", "timeout", "mixed"}:
                    await page.wait_for_function("fixtureMessages.length === 2")
                    await page.evaluate("fixtureRelease()")
            await expect(bulk).to_be_enabled()
            feedback = page.locator("#periodic-feedback")
            if mode in {"communication", "timeout"}:
                await expect(feedback).to_contain_text("一键执行已停止，剩余任务未执行")
                await expect(feedback).to_contain_text("模拟通信失败" if mode == "communication" else "超时")
            else:
                await expect(feedback).to_have_text({"success": "执行结束：完成 2，未完成 0，今日已完成跳过 0", "partial": "执行结束：完成 1，未完成 1，今日已完成跳过 0", "completed": "执行结束：完成 0，未完成 0，今日已完成跳过 2", "mixed": "执行结束：完成 1，未完成 0，今日已完成跳过 1"}[mode])
            expected = [] if mode == "completed" else ["nodeseek"] if mode in {"communication", "timeout"} else ["invitesfun"] if mode == "mixed" else ["nodeseek", "invitesfun"]
            assert await page.evaluate("fixtureMessages.map(message => message.taskId)") == expected
            assert await page.evaluate("fixtureMaxActive") <= 1
            if mode == "success":
                await bulk.click()
                await expect(feedback).to_have_text("执行结束：完成 0，未完成 0，今日已完成跳过 2")
                assert await page.evaluate("fixtureMessages.length") == 2
                for width in [1440, 390]:
                    await page.set_viewport_size({"width": width, "height": 900})
                    assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                    await page.screenshot(path=str(source.parents[1] / "tmp" / "netsurf-qa" / f"periodic-bulk-{width}.png"), full_page=True)
            assert errors == []
        finally:
            await browser.close()
