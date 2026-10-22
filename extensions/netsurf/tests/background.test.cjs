const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

function harness({tabs = [], initial = {}, sessionInitial = {}, registeredScripts = [], inspect = "ready", inspectWait = null, scriptWait = null, navigate = false, signinError = false, cookiePermission = true, cookies = [], cookieFailure = false, schedulingError = false} = {}) {
  const state = {sites: {piggo: {startTime: "00:00"}}, ...initial};
  const session = {...sessionInitial};
  let nextTabId = 100;
  const actions = [];
  const cookieQueries = [];
  const alarms = new Map();
  const intervals = new Set();
  let keepAlivePings = 0;
  let listener;
  let actionListener;
  let alarmListener;
  let startupListener;
  let installedListener;
  const context = vm.createContext({URL, Date, console, setTimeout, clearTimeout, setInterval: callback => { intervals.add(callback); return callback; }, clearInterval: callback => { intervals.delete(callback); }});
  const extensionId = "netsurf-test";
  const send = (message, tab) => new Promise(resolve => listener(message, {id: extensionId, url: `chrome-extension://${extensionId}/dashboard.html`, ...(tab ? {tab, url: tab.url} : {})}, resolve));
  context.chrome = {
    action: {onClicked: {addListener: callback => { actionListener = callback; }}},
    runtime: {id: extensionId, getPlatformInfo: async () => { keepAlivePings += 1; }, getURL: filename => `chrome-extension://${extensionId}/${filename}`, getContexts: async () => tabs.filter(tab => tab.url.startsWith(`chrome-extension://${extensionId}/`)).map(tab => ({documentUrl: tab.url, tabId: tab.id, windowId: tab.windowId})), onMessage: {addListener: callback => { listener = callback; }}, onInstalled: {addListener: callback => { installedListener = callback; }}, onStartup: {addListener: callback => { startupListener = callback; }}},
    alarms: {getAll: async () => [...alarms.keys()].map(name => ({name})), create: async (name, info) => { alarms.set(name, info); }, clear: async name => alarms.delete(name), onAlarm: {addListener: callback => { alarmListener = callback; }}},
    scripting: {getRegisteredContentScripts: async ({ids}) => { if (schedulingError) throw new Error("fixture scheduling unavailable"); return registeredScripts.filter(script => ids.includes(script.id)); }, unregisterContentScripts: async ({ids}) => { registeredScripts = registeredScripts.filter(script => !ids.includes(script.id)); actions.push(["unregister"]); }, registerContentScripts: async scripts => { registeredScripts = [...registeredScripts, ...scripts]; actions.push(["register", scripts]); }, executeScript: async () => { if (scriptWait) await scriptWait; }},
    permissions: {contains: async () => cookiePermission},
    cookies: {getAll: async query => { cookieQueries.push(query); return cookies; }, set: async details => { actions.push(["cookie", details]); if (cookieFailure) throw new Error("Cookie unavailable"); return details; }},
    storage: {session: {
      get: async key => ({[key]: session[key]}),
      set: async values => { Object.assign(session, JSON.parse(JSON.stringify(values))); },
      remove: async key => { delete session[key]; }
    }, local: {
      get: async keys => Object.fromEntries((Array.isArray(keys) ? keys : [keys]).map(key => [key, state[key]])),
      set: async values => { Object.assign(state, JSON.parse(JSON.stringify(values))); }
    }},
    windows: {update: async (...args) => { actions.push(["window", ...args]); }},
    tabs: {
      remove: async tabId => { actions.push(["remove", tabId]); const index = tabs.findIndex(item => item.id === tabId); if (index >= 0) tabs.splice(index, 1); },
      reload: async (...args) => { actions.push(["reload", ...args]); },
      query: async options => tabs.filter(tab => !options.url || [options.url].flat().some(pattern => tab.url.startsWith(pattern.replace(/\*$/, "")))).map(tab => ({...tab})),
      update: async (tabId, options) => { actions.push(["update", tabId, options]); Object.assign(tabs.find(item => item.id === tabId) || {}, options); },
      create: async options => { actions.push(["create", options]); const created = {...options, id: nextTabId++, windowId: options.windowId ?? 5}; tabs.push(created); return created; },
      sendMessage: async (tabId, incoming) => {
        const message = {...incoming, type: incoming.type.replace(/^netsurf-/, "")};
        actions.push([message.type, tabId, message]);
        const pageUrl = tabs.find(item => item.id === tabId)?.url || "https://piggo.me/";
        const site = context.NetSurfSites.resolve(pageUrl);
        const page = site ? context.NetSurfPiggo.create(new URL(pageUrl).origin, site.signinPath, site.mode === "profile", site.name) : context.NetSurfPiggo;
        if (message.type === "inspect") { if (inspectWait) await inspectWait; const status = typeof inspect === "function" ? inspect(tabId, message, actions) : inspect; if (status instanceof Error) throw status; return status && typeof status === "object" ? status : page.result(status, pageUrl); }
        if (navigate) await send({type: "observed", result: {status: "already_done"}}, tabs[0]);
        if (navigate || signinError) throw new Error("Receiving page unloaded");
        return context.NetSurfPiggo.result("pending", "https://piggo.me/");
      }
    }
  };
  context.importScripts = (...filenames) => filenames.forEach(filename => vm.runInContext(fs.readFileSync(path.join(__dirname, "..", filename), "utf8"), context));
  vm.runInContext(fs.readFileSync(path.join(__dirname, "..", "background.js"), "utf8"), context);
  return {state, actions, alarms, cookieQueries, send, intervals, evaluate: source => vm.runInContext(source, context), drain: () => vm.runInContext("actionQueue", context), installed: installedListener, keepAlivePings: () => keepAlivePings, clickAction: actionListener, startup: startupListener, alarm: async name => { alarmListener({name}); await vm.runInContext("actionQueue", context); }};
}

const tab = {id: 12, windowId: 5, active: true, url: "https://piggo.me/"};

const automaticSettings = {autoEnabled: true, scheduleConfig: {startTime: "00:00", retryInterval: 30, retryCount: 1, timeout: 5}, sites: {piggo: {enabled: true}, "audiences.me": {enabled: true}}};

test("bulk refresh skips only today's successful refreshes, not yesterday or failed attempts", async () => {
  const day = require("../sites.js").day();
  const runtime = harness({initial: {...automaticSettings, refreshedDay: day}});
  const result = await runtime.send({type: "inspect-all", background: true});
  assert.equal(result.skipped, 1);
  assert.deepEqual(Object.keys(result.results), ["audiences.me"]);
  assert.equal(runtime.actions.filter(action => action[0] === "create").length, 1);
  const previous = harness({initial: {...automaticSettings, refreshedDay: "2000-1-1"}});
  assert.equal(Object.keys((await previous.send({type: "inspect-all", background: true})).results).length, 2);
});

test("failed fresh results cannot overwrite account fields or advance the successful refresh day", async () => {
  const runtime = harness({initial: {lastResult: {profile: {level: "User", bonus: "123"}, profileTime: "2000-01-01T00:00:00Z"}}});
  await runtime.evaluate("save({status:'error',time:new Date().toISOString(),profile:{level:'VIP',bonus:'999'}},12,true)");
  assert.equal(runtime.state.lastResult.profile.level, "User");
  assert.equal(runtime.state.lastResult.profile.bonus, "123");
  assert.equal(runtime.state.lastResult.profileTime, "2000-01-01T00:00:00Z");
  assert.equal(runtime.state.refreshedDay, undefined);
});

test("bulk sign-in skips today's completion and profile/refresh-only sites even with automation off", async () => {
  const day = require("../sites.js").day();
  const runtime = harness({inspect: (tabId, message, actions) => actions.some(action => action[0] === "signin") ? "already_done" : "ready", initial: {autoEnabled: false, verifiedDay: day, sites: {piggo: {enabled: true}, 'audiences.me': {enabled: true}, 'et8.org': {enabled: true}, '52pt.site': {enabled: true}}}});
  const result = await runtime.send({type: "run-all"});
  assert.equal(result.skipped, 3);
  assert.deepEqual(Object.keys(result.results), ["audiences.me"]);
  assert.equal(runtime.actions.filter(action => action[0] === "signin").length, 1);
  assert.equal(runtime.actions.filter(action => action[0] === "create").length, 1);
  assert.equal(runtime.actions.filter(action => action[0] === "remove").length, 1);
  assert.equal(runtime.state.autoEnabled, false);
  const repeated = await runtime.send({type: "run-all"});
  assert.equal(repeated.skipped, 4);
  assert.equal(runtime.actions.filter(action => action[0] === "signin").length, 1);
});

test("successful profile refreshes skip repeats while failures remain retryable", async () => {
  const runtime = harness({initial: {lastResult: {profile: {level: "User", bonus: "123"}}}});
  await runtime.evaluate("save({status:'ready',time:new Date().toISOString(),profile:{bonus:'456'}},12,true)");
  assert.equal((await runtime.send({type: "inspect-all", background: true})).skipped, 1);
  const failed = harness({inspect: "error"});
  await failed.send({type: "inspect-all", background: true});
  await failed.send({type: "inspect-all", background: true});
  assert.equal(failed.actions.filter(action => action[0] === "create").length, 2);
  assert.equal(failed.state.refreshedDay, undefined);
});

test("bulk sign-in closes each owned page in sequence and never resubmits pending results", async () => {
  const runtime = harness({initial: {autoEnabled: false, sites: automaticSettings.sites}, inspect: (tabId, message, actions) => actions.some(action => action[0] === "signin" && action[1] === tabId) ? "already_done" : "ready"});
  await runtime.send({type: "run-all"});
  assert.deepEqual(runtime.actions.filter(action => ["create", "remove"].includes(action[0])).map(action => action[0]), ["create", "remove", "create", "remove"]);
  const pending = harness({initial: {lastResult: {status: "pending"}, operation: {day: require("../sites.js").day()}}});
  await pending.send({type: "run-all"});
  assert.equal(pending.actions.length, 0);
});

test("updating content modules replaces persisted scripts even when site permissions are unchanged", async () => {
  const site = require("../sites.js").get("audiences.me");
  const runtime = harness({initial: automaticSettings, registeredScripts: [{id: "netsurf-pt", matches: require("../sites.js").origins(site), js: ["catalog.js", "site-rules.js", "sites.js", "piggo.js", "content.js"]}]});
  await runtime.send({type: "settings", enabled: false});
  const registration = runtime.actions.find(action => action[0] === "register");
  assert.ok(registration[1][0].js.includes("profile-api.js"));
  const count = runtime.actions.filter(action => action[0] === "register").length;
  await runtime.send({type: "settings", enabled: false});
  assert.equal(runtime.actions.filter(action => action[0] === "register").length, count);
});

test("a read-only task's automatic announcement cannot enqueue a sign-in", async () => {
  const runtime = harness({tabs: [{...tab}], initial: automaticSettings, sessionInitial: {taskTab: {tabId: tab.id, siteId: "piggo", purpose: "refresh"}}});
  assert.equal(await runtime.send({type: "auto"}, tab), null);
  assert.equal(runtime.actions.length, 0);
  assert.equal(runtime.state.operation, undefined);
});

test("an automatic announcement from a task that has closed cannot start another task", async () => {
  const runtime = harness({initial: automaticSettings});
  assert.equal(await runtime.send({type: "auto"}, tab), null);
  assert.equal(runtime.actions.length, 0);
});

test("refresh-only manual and scheduled runs inspect without submitting or acquiring a lock", async () => {
  for (const automatic of [false, true]) {
    const runtime = harness({tabs: [{...tab}], initial: {...automaticSettings, sites: {piggo: {enabled: true, refreshOnly: true}}, verifiedDay: require("../sites.js").day()}});
    if (automatic) await runtime.alarm("netsurf-daily");
    else assert.equal((await runtime.send({type: "run"})).status, "ready");
    assert.ok(runtime.actions.some(action => action[0] === "inspect" && action[2].fresh));
    assert.equal(runtime.actions.some(action => action[0] === "signin"), false);
    assert.equal(runtime.state.operation, undefined);
    assert.equal(runtime.actions.some(action => action[0] === "remove"), false);
  }
});

test("52PT built-in refresh-only survives attempts to disable it and never submits", async () => {
  const ownTab = {id: 52, windowId: 5, active: true, url: "https://52pt.site/index.php"};
  const runtime = harness({tabs: [ownTab], initial: {sites: {piggo: {enabled: false}, "52pt.site": {enabled: true, refreshOnly: false}}}});
  const saved = await runtime.send({type: "site-settings", siteId: "52pt.site", config: {refreshOnly: false}});
  assert.equal(saved.config.refreshOnly, true);
  await runtime.send({type: "run", siteId: "52pt.site"});
  assert.ok(runtime.actions.some(action => action[0] === "inspect" && action[2].fresh));
  assert.equal(runtime.actions.some(action => action[0] === "signin"), false);
  runtime.state["lastResult:52pt.site"] = {status: "manual_required"};
  await runtime.send({type: "open", siteId: "52pt.site"});
  assert.equal(runtime.actions.findLast(action => action[0] === "update")[2].url, "https://52pt.site/bakatest.php");
});

test("manual refresh creates an inactive task, closes it and is independent of daily budgets", async () => {
  const runtime = harness({initial: {autoEnabled: false, sites: {piggo: {enabled: true, refreshOnly: true}}, schedule: {day: require("../sites.js").day(), attempts: 999}}});
  for (let attempt = 0; attempt < 2; attempt += 1) assert.equal((await runtime.send({type: "run"})).status, "ready");
  assert.equal(runtime.actions.filter(action => action[0] === "create").length, 2);
  assert.equal(runtime.actions.filter(action => action[0] === "remove").length, 2);
  assert.ok(runtime.actions.filter(action => action[0] === "create").every(action => action[1].active === false));
  assert.equal(runtime.actions.some(action => action[0] === "signin" || action[0] === "window"), false);
  assert.equal(runtime.state.schedule.attempts, 999);
});

test("single-site sign-in creates and closes a background page when the site is not open", async () => {
  const runtime = harness({
    inspect: (tabId, message, actions) => actions.some(action => action[0] === "signin" && action[1] === tabId) ? "already_done" : "ready",
    initial: {autoEnabled: false, sites: {piggo: {enabled: false}, "audiences.me": {enabled: true}}}
  });
  const result = await runtime.send({type: "run", siteId: "audiences.me"});
  assert.equal(result.status, "already_done");
  assert.equal(runtime.actions.filter(action => action[0] === "create").length, 1);
  assert.equal(runtime.actions.find(action => action[0] === "create")[1].active, false);
  assert.equal(runtime.actions.find(action => action[0] === "inspect" && action[2].fresh)[2].reuseCurrentPage, true);
  assert.equal(runtime.actions.filter(action => action[0] === "signin").length, 1);
  assert.equal(runtime.actions.filter(action => action[0] === "remove").length, 1);
  assert.equal(runtime.state["verifiedDay:audiences.me"], require("../sites.js").day());
});

test("refresh failure preserves old account fields and still closes its task page", async () => {
  const runtime = harness({inspect: "blocked", initial: {sites: {piggo: {enabled: true, refreshOnly: true}}, lastResult: {status: "ready", profile: {level: "User", bonus: "1234", uploaded: "2 TB"}}}});
  const result = await runtime.send({type: "run"});
  assert.equal(result.status, "blocked");
  assert.equal(result.profile.level, "User");
  assert.equal(result.profile.bonus, "1234");
  assert.equal(runtime.actions.filter(action => action[0] === "remove").length, 1);
  assert.equal(runtime.actions.some(action => action[0] === "signin"), false);
});

test("a stalled content injection cannot hold a refresh task past its timeout", async () => {
  const runtime = harness({scriptWait: new Promise(() => {}), initial: {scheduleConfig: {startTime: "00:00", retryInterval: 30, retryCount: 0, timeout: 5}, sites: {piggo: {enabled: true, refreshOnly: true}}, lastResult: {profile: {bonus: "123"}}}});
  const started = Date.now();
  const result = await runtime.send({type: "run"});
  assert.equal(result.status, "error");
  assert.ok(Date.now() - started < 6500);
  assert.equal(result.profile.bonus, "123");
  assert.equal(runtime.actions.filter(action => action[0] === "remove").length, 1);
});

test("background inspect-all closes each task before starting another and never signs in", async () => {
  const runtime = harness({initial: automaticSettings});
  const result = await runtime.send({type: "inspect-all", background: true});
  assert.deepEqual(Object.keys(result.results).sort(), ["audiences.me", "piggo"]);
  assert.deepEqual(runtime.actions.filter(action => ["create", "remove"].includes(action[0])).map(action => action[0]), ["create", "remove", "create", "remove"]);
  assert.equal(runtime.actions.some(action => action[0] === "signin"), false);
  assert.equal(runtime.state.inspection.running, false);
});

test("enabling sites in refresh-only mode queues one page at a time even with automation off", async () => {
  const runtime = harness({initial: {autoEnabled: false, sites: {piggo: {enabled: false, refreshOnly: true}, "audiences.me": {enabled: false, refreshOnly: true}}}});
  await Promise.all([runtime.send({type: "site-settings", config: {enabled: true}}), runtime.send({type: "site-settings", siteId: "audiences.me", config: {enabled: true}})]);
  await runtime.drain();
  assert.equal(runtime.actions.filter(action => action[0] === "create").length, 2);
  assert.equal(runtime.actions.filter(action => action[0] === "remove").length, 2);
  const firstClose = runtime.actions.findIndex(action => action[0] === "remove");
  assert.ok(runtime.actions.slice(firstClose + 1).some(action => action[0] === "create"));
  assert.equal(runtime.actions.some(action => action[0] === "signin"), false);
  assert.equal(runtime.state.lastResult.status, "ready");
  assert.equal(runtime.state["lastResult:audiences.me"].status, "ready");
});

test("switching refresh-only on while inspection is outstanding cancels the sign-in", async () => {
  let release;
  const inspectWait = new Promise(resolve => { release = resolve; });
  const runtime = harness({tabs: [{...tab}], inspectWait});
  const run = runtime.send({type: "run"});
  await new Promise(resolve => setImmediate(resolve));
  assert.equal((await runtime.send({type: "site-settings", config: {refreshOnly: true}})).config.refreshOnly, true);
  release();
  assert.equal((await run).status, "ready");
  await runtime.drain();
  assert.equal(runtime.state.sites.piggo.refreshOnly, true);
  assert.equal(runtime.actions.some(action => action[0] === "signin"), false);
});

test("a queued enable-refresh cannot become a sign-in when refresh-only is switched off", async () => {
  let release;
  const inspectWait = new Promise(resolve => { release = resolve; });
  const runtime = harness({tabs: [{...tab}], initial: {sites: {piggo: {enabled: true, refreshOnly: true}, "audiences.me": {enabled: false, refreshOnly: true}}}, inspectWait});
  const inspecting = runtime.send({type: "inspect"});
  await new Promise(resolve => setImmediate(resolve));
  await runtime.send({type: "site-settings", siteId: "audiences.me", config: {enabled: true}});
  await runtime.send({type: "site-settings", siteId: "audiences.me", config: {refreshOnly: false}});
  release();
  await inspecting;
  await runtime.drain();
  assert.equal(runtime.actions.some(action => action[0] === "create" || action[0] === "signin"), false);
});

test("refresh-only setting survives backup and restore while old backups default off", async () => {
  const runtime = harness({initial: {sites: {piggo: {enabled: false}}}});
  await runtime.send({type: "site-settings", config: {refreshOnly: true}});
  const {backup} = await runtime.send({type: "backup"});
  assert.equal(backup.settings.sites.piggo.refreshOnly, true);
  assert.equal(backup.settings.sites["audiences.me"].refreshOnly, false);
  await runtime.send({type: "site-settings", config: {refreshOnly: false}});
  await runtime.send({type: "restore", backup});
  assert.equal(runtime.state.sites.piggo.refreshOnly, true);
  delete backup.settings.sites.piggo.refreshOnly;
  await runtime.send({type: "restore", backup});
  assert.equal(runtime.state.sites.piggo.refreshOnly, false);
});

test("one site refreshes while another signs in, and changing one switch preserves the other", async () => {
  const other = {id: 22, windowId: 5, url: "https://audiences.me/"};
  const runtime = harness({tabs: [{...tab}, other], initial: {sites: {piggo: {enabled: true, refreshOnly: true}, "audiences.me": {enabled: true}}}});
  await runtime.send({type: "run"});
  await runtime.send({type: "run", siteId: "audiences.me"});
  assert.deepEqual(runtime.actions.filter(action => action[0] === "signin").map(action => action[1]), [22]);
  await runtime.send({type: "site-settings", config: {enabled: false}});
  assert.equal(runtime.state.sites.piggo.refreshOnly, true);
  await runtime.send({type: "site-settings", config: {refreshOnly: false}});
  assert.equal(runtime.state.sites.piggo.enabled, false);
  assert.equal(runtime.state.sites["audiences.me"].enabled, true);
  assert.equal(runtime.state.sites["audiences.me"].refreshOnly, false);
});

test("automatic sites close their task tab before the next queued site opens", async () => {
  const runtime = harness({initial: automaticSettings, inspect: "already_done"});
  await Promise.all([runtime.alarm("netsurf-daily"), runtime.alarm("netsurf-daily:audiences.me")]);
  assert.deepEqual(runtime.actions.filter(action => ["create", "remove"].includes(action[0])).map(action => action[0]), ["create", "remove", "create", "remove"]);
  assert.equal(runtime.state.lastResult.status, "already_done");
  assert.equal(runtime.state["lastResult:audiences.me"].status, "already_done");
});

test("automatic tasks preserve pages that were already open", async () => {
  const existing = {...tab};
  const runtime = harness({tabs: [existing], initial: automaticSettings, inspect: "already_done"});
  await runtime.alarm("netsurf-daily");
  assert.equal(runtime.actions.filter(action => ["create", "remove"].includes(action[0])).length, 0);
});

test("inspection after a task page closes preserves its result and original check time", async () => {
  const runtime = harness({initial: automaticSettings, inspect: "already_done"});
  await runtime.alarm("netsurf-daily");
  const saved = JSON.parse(JSON.stringify(runtime.state.lastResult));
  assert.deepEqual(JSON.parse(JSON.stringify(await runtime.send({type: "inspect"}))), saved);
  assert.deepEqual(runtime.state.lastResult, saved);
  await runtime.installed({reason: "update"});
  assert.deepEqual(JSON.parse(JSON.stringify(await runtime.send({type: "inspect"}))), saved);
});

test("an existing verified day recovers today's completion overwritten by a no-tab check", async () => {
  const now = new Date();
  const day = `${now.getFullYear()}-${now.getMonth() + 1}-${now.getDate()}`;
  const time = now.toISOString();
  const runtime = harness({initial: {verifiedDay: day, lastResult: {status: "no_tab", time, profile: {bonus: "123"}}}});
  const restored = await runtime.send({type: "inspect"});
  assert.equal(restored.status, "already_done");
  assert.equal(restored.verified, true);
  assert.equal(restored.time, time);
  assert.equal(restored.profile.bonus, "123");
});

test("yesterday's saved result remains dated yesterday after inspection without a page", async () => {
  const time = new Date(Date.now() - 86400000).toISOString();
  const runtime = harness({initial: {lastResult: {status: "already_done", time, verified: true}, verifiedDay: "2026-01-01"}});
  const inspected = await runtime.send({type: "inspect"});
  assert.equal(inspected.time, time);
  assert.equal(runtime.state.verifiedDay, "2026-01-01");
});

test("recovering a verified day without a timestamp does not invent a check time", async () => {
  const now = new Date();
  const day = `${now.getFullYear()}-${now.getMonth() + 1}-${now.getDate()}`;
  const runtime = harness({initial: {verifiedDay: day, lastResult: {status: "no_tab"}}});
  const restored = await runtime.send({type: "inspect"});
  assert.equal(restored.status, "already_done");
  assert.equal(restored.confirmedDay, day);
  assert.equal(restored.time, undefined);
});

test("task tabs close on WAF, login and transient failure, including retry attempts", async () => {
  for (const inspect of ["blocked", "login_required", "error"]) {
    const runtime = harness({initial: automaticSettings, inspect});
    await runtime.alarm("netsurf-daily");
    assert.equal(runtime.actions.filter(action => action[0] === "remove").length, 1);
    assert.equal(runtime.state.lastResult.status, inspect);
    if (inspect === "error") {
      await runtime.alarm("netsurf-retry");
      assert.deepEqual(runtime.actions.filter(action => ["create", "remove"].includes(action[0])).map(action => action[0]), ["create", "remove", "create", "remove"]);
    }
  }
});

test("submission is confirmed before closing the page and moving to the next site", async () => {
  const runtime = harness({initial: automaticSettings, inspect: (tabId, message, actions) => actions.some(action => action[0] === "signin" && action[1] === tabId) ? "already_done" : "ready"});
  await Promise.all([runtime.alarm("netsurf-daily"), runtime.alarm("netsurf-daily:audiences.me")]);
  const lifecycle = runtime.actions.filter(action => ["create", "signin", "remove"].includes(action[0]));
  assert.deepEqual(lifecycle.map(action => action[0]), ["create", "signin", "remove", "create", "signin", "remove"]);
  assert.ok(runtime.state.verifiedDay);
  assert.ok(runtime.state["verifiedDay:audiences.me"]);
  assert.equal(runtime.alarms.has("netsurf-verify"), false);
});

test("an unknown attendance response rechecks the homepage before giving up", async () => {
  let checksAfterSubmit = 0;
  const runtime = harness({
    tabs: [tab],
    inspect: (tabId, message, actions) => {
      if (!actions.some(action => action[0] === "signin" && action[1] === tabId)) return "ready";
      checksAfterSubmit += 1;
      return checksAfterSubmit === 1 ? "unknown" : "already_done";
    }
  });
  const result = await runtime.send({type: "run"});
  assert.equal(result.status, "already_done");
  assert.ok(runtime.state.verifiedDay);
  assert.equal(runtime.actions.filter(action => action[0] === "signin").length, 1);
});

test("an unknown refresh cannot downgrade today's confirmed completion", async () => {
  const day = new Date().toLocaleDateString("en-CA");
  const runtime = harness({tabs: [tab], inspect: "unknown", initial: {verifiedDay: day, lastResult: {status: "unknown", verified: true, time: new Date().toISOString()}}});
  const result = await runtime.send({type: "inspect"});
  assert.equal(result.status, "already_done");
  assert.equal(runtime.state.verifiedDay, day);
  assert.match(result.message, /已保留确认状态/);
});

test("unconfirmed task submission times out, closes and never automatically resubmits", async () => {
  const runtime = harness({initial: automaticSettings});
  await runtime.alarm("netsurf-daily");
  assert.equal(runtime.actions.filter(action => action[0] === "signin").length, 1);
  assert.equal(runtime.actions.filter(action => action[0] === "remove").length, 1);
  assert.equal(runtime.state.lastResult.status, "pending");
  assert.equal(runtime.state.verifiedDay, undefined);
  assert.equal(runtime.alarms.has("netsurf-verify"), false);
  assert.equal(runtime.alarms.has("netsurf-retry"), false);
  await runtime.alarm("netsurf-daily");
  assert.equal(runtime.actions.filter(action => action[0] === "signin").length, 1);
});

test("a task page that never becomes ready is closed on load timeout", async () => {
  const runtime = harness({initial: automaticSettings, inspect: () => new Error("Page not loaded")});
  await runtime.alarm("netsurf-daily");
  assert.equal(runtime.state.lastResult.status, "error");
  assert.equal(runtime.actions.filter(action => action[0] === "remove").length, 1);
  assert.equal(runtime.actions.filter(action => action[0] === "signin").length, 0);
});

test("read-only refresh can start while a slow task page is still loading", async () => {
  const runtime = harness({tabs: [{id: 100, windowId: 5, active: false, url: "https://piggo.me/"}], inspect: () => ({status: "ready", path: "/index.php", pageReady: false})});
  await runtime.evaluate("waitForPage({id:100,url:'https://piggo.me/'},Date.now()+500,'piggo',false)");
  assert.equal(runtime.actions.filter(action => action[0] === "inspect").length, 2);
});

test("HDCity retries a failed background navigation inside the same timeout budget", async () => {
  const runtime = harness({tabs: [{id: 100, windowId: 5, active: false, url: "about:blank"}], inspect: (tabId, message, actions) => actions.filter(action => action[0] === "update").length > 1 ? {status: "already_done", path: "/index.php", pageReady: true} : new Error("Page not loaded")});
  const loaded = await runtime.evaluate("navigateTaskPage({id:100,url:'about:blank'},Date.now()+600,'hdcity.city',false)");
  assert.equal(loaded.url, "https://hdcity.city/index.php");
  assert.equal(runtime.actions.filter(action => action[0] === "update").length, 2);
});

test("a failed data refresh cannot downgrade an already completed page", async () => {
  const runtime = harness({tabs: [{...tab}], inspect: (tabId, message, actions) => actions.filter(action => action[0] === "inspect").length >= 3 ? "error" : "already_done"});
  const result = await runtime.evaluate("freshPage({id:12,url:'https://piggo.me/'},1)");
  assert.equal(result.status, "already_done");
  assert.match(result.message, /保留旧数据/);
});

test("worker recovery cleans only a session-owned task tab and cancels its stale verification", async () => {
  const runtime = harness({tabs: [{...tab}, {id: 77, url: "https://audiences.me/"}], initial: {...automaticSettings, schedule: {day: "2026-01-01", attempts: 1, verifyAt: Date.now()}}, sessionInitial: {taskTab: {siteId: "piggo", tabId: tab.id}}});
  await runtime.startup();
  assert.deepEqual(runtime.actions.filter(action => action[0] === "remove"), [["remove", tab.id]]);
  assert.equal(runtime.state.schedule.verifyAt, null);
  assert.equal(runtime.alarms.has("netsurf-verify"), false);
});

test("opening a task page manually transfers ownership and prevents later automatic closing", async () => {
  const runtime = harness({tabs: [{...tab}], sessionInitial: {taskTab: {siteId: "piggo", tabId: tab.id}}});
  await runtime.send({type: "open"});
  await runtime.startup();
  assert.equal(runtime.actions.filter(action => action[0] === "remove").length, 0);
});

test("concurrent toolbar clicks create only one dashboard in the source window", async () => {
  const runtime = harness({tabs: [tab]});
  await Promise.all([runtime.clickAction(tab), runtime.clickAction(tab), runtime.clickAction(tab)]);
  const created = runtime.actions.filter(action => action[0] === "create");
  assert.equal(created.length, 1);
  assert.equal(created[0][1].url, "chrome-extension://netsurf-test/dashboard.html");
  assert.equal(created[0][1].windowId, tab.windowId);
});

test("toolbar reuses a dashboard with an active secondary route after worker restart", async () => {
  const dashboard = {id: 90, windowId: 7, url: "chrome-extension://netsurf-test/dashboard.html#records"};
  const runtime = harness({tabs: [tab, dashboard]});
  await runtime.clickAction(tab);
  assert.deepEqual(JSON.parse(JSON.stringify(runtime.actions)), [["update", 90, {active: true}], ["window", 7, {focused: true}]]);
});

test("operation records are bounded and omit page identity and tab metadata", async () => {
  const runtime = harness({tabs: [tab], initial: {activity: Array.from({length: 50}, () => ({type: "inspect", message: "之前的检查"}))}});
  await runtime.send({type: "inspect"});
  assert.equal(runtime.state.activity.length, 50);
  assert.equal(runtime.state.activity[0].type, "inspect");
  assert.deepEqual(Object.keys(runtime.state.activity[0]).sort(), ["message", "siteId", "status", "time", "type"]);
  assert.equal(runtime.state.activity[0].status, "ready");
});

test("open focuses the existing tab without creating another tab or window", async () => {
  const runtime = harness({tabs: [tab]});
  await runtime.send({type: "open"});
  assert.deepEqual(runtime.actions.map(action => action[0]), ["update", "window"]);
});

test("open creates only one tab when no PigGo tab exists", async () => {
  const runtime = harness();
  await runtime.send({type: "open"});
  assert.equal(runtime.actions.length, 1);
  assert.equal(runtime.actions[0][0], "create");
  assert.equal(runtime.actions[0][1].url, "https://piggo.me/");
});

test("the trusted dashboard works as an extension tab", async () => {
  const runtime = harness({tabs: [tab]});
  const dashboard = {id: 99, url: "chrome-extension://netsurf-test/dashboard.html#sites"};
  assert.equal((await runtime.send({type: "inspect"}, dashboard)).status, "ready");
  await runtime.send({type: "open"}, dashboard);
  assert.equal(runtime.actions.filter(action => action[0] === "update").length, 1);
  assert.equal((await runtime.send({type: "run"}, dashboard)).status, "pending");
  assert.equal(runtime.actions.filter(action => action[0] === "signin").length, 1);
});

test("concurrent clicks submit only once", async () => {
  const runtime = harness({tabs: [tab]});
  await Promise.all([runtime.send({type: "run"}), runtime.send({type: "run"})]);
  assert.equal(runtime.actions.filter(action => action[0] === "signin").length, 1);
  assert.equal(runtime.state.lastResult.status, "pending");
});

test("the persisted lock prevents duplicate submission after worker restart", async () => {
  const runtime = harness({tabs: [tab], initial: {operation: {startedAt: Date.now(), tabId: tab.id}}});
  const result = await runtime.send({type: "run"});
  assert.equal(result.status, "pending");
  assert.equal(runtime.actions.filter(action => action[0] === "signin").length, 0);
});

test("navigation disconnect does not lose a confirmed result or trigger another click", async () => {
  const runtime = harness({tabs: [tab], navigate: true});
  const result = await runtime.send({type: "run"});
  assert.equal(result.status, "already_done");
  assert.equal(runtime.state.lastResult.status, "already_done");
  assert.ok(runtime.state.verifiedDay);
  assert.equal(runtime.actions.filter(action => action[0] === "signin").length, 1);
});

test("an unconfirmed navigation never reports success", async () => {
  const runtime = harness({tabs: [tab], signinError: true});
  const result = await runtime.send({type: "run"});
  assert.equal(result.status, "pending");
  assert.equal(runtime.state.verifiedDay, undefined);
});

test("a stale result from the same tab cannot confirm a new attempt", async () => {
  const runtime = harness({tabs: [tab], signinError: true, initial: {lastResult: {tabId: tab.id, status: "success", time: "2026-01-01T00:00:00.000Z"}}});
  const result = await runtime.send({type: "run"});
  assert.equal(result.status, "pending");
  assert.equal(runtime.state.lastResult.status, "pending");
});

test("a recent lock never hides an already confirmed page", async () => {
  const runtime = harness({tabs: [tab], inspect: "already_done", initial: {operation: {startedAt: Date.now(), tabId: tab.id}}});
  assert.equal((await runtime.send({type: "run"})).status, "already_done");
  assert.equal(runtime.actions.filter(action => action[0] === "signin").length, 0);
});

test("login and WAF observations stop before submission", async () => {
  for (const inspect of ["already_done", "blocked", "debugging", "login_required", "manual_required", "ambiguous", "unknown"]) {
    const runtime = harness({tabs: [tab], inspect});
    assert.equal((await runtime.send({type: "run"})).status, inspect);
    assert.equal(runtime.actions.filter(action => action[0] === "signin").length, 0);
  }
});

test("automatic sign-in requires explicit opt-in", async () => {
  const runtime = harness({tabs: [tab]});
  await runtime.send({type: "auto"}, tab);
  assert.equal(runtime.actions.length, 0);
  await runtime.send({type: "settings", enabled: true});
  await runtime.send({type: "auto"}, tab);
  assert.equal(runtime.actions.filter(action => action[0] === "signin").length, 1);
});

test("a completed local day stops automatic sign-in", async () => {
  const runtime = harness({tabs: [tab], inspect: "already_done", initial: {autoEnabled: true}});
  await runtime.send({type: "run"});
  const previous = runtime.actions.length;
  await runtime.send({type: "auto"}, tab);
  assert.equal(runtime.actions.length, previous);
});

test("manual inspection refreshes the homepage instead of trusting yesterday's result", async () => {
  const runtime = harness({tabs: [tab], initial: {lastResult: {status: "already_done", time: "2026-01-01T00:00:00.000Z"}}});
  const result = await runtime.send({type: "inspect"});
  assert.equal(result.status, "ready");
  assert.equal(result.verified, true);
  assert.equal(runtime.actions[0][0], "inspect");
  assert.ok(runtime.actions.some(action => action[0] === "inspect" && action[2].fresh === true));
  assert.equal(runtime.actions.filter(action => action[0] === "signin").length, 0);
});

test("old unverified completion caches cannot suppress automatic sign-in", async () => {
  const now = new Date();
  const legacyDay = `${now.getFullYear()}-${now.getMonth() + 1}-${now.getDate()}`;
  const runtime = harness({tabs: [tab], initial: {autoEnabled: true, completedDay: legacyDay}});
  await runtime.send({type: "auto"}, tab);
  assert.equal(runtime.actions.filter(action => action[0] === "signin").length, 1);
});

test("ordinary page observations cannot mark today's completion verified", async () => {
  const runtime = harness({tabs: [tab]});
  await runtime.send({type: "observed", result: {status: "already_done"}}, tab);
  assert.equal(runtime.state.lastResult.verified, false);
  assert.equal(runtime.state.verifiedDay, undefined);
});

test("an attendance challenge is not hidden by a successful homepage check", async () => {
  const runtime = harness({tabs: [tab], inspect: "blocked"});
  assert.equal((await runtime.send({type: "inspect"})).status, "blocked");
  assert.equal(runtime.actions.filter(action => action[2]?.fresh).length, 0);
  assert.equal(runtime.actions.filter(action => action[0] === "signin").length, 0);
});

test("website messages cannot change settings or control other tabs", async () => {
  const runtime = harness({tabs: [tab]});
  await runtime.send({type: "settings", enabled: true}, tab);
  await runtime.send({type: "open"}, tab);
  assert.equal(runtime.state.autoEnabled, undefined);
  assert.equal(runtime.actions.length, 0);
  await runtime.send({type: "observed", result: {status: "success"}}, {...tab, url: "https://evil.test/"});
  assert.equal(runtime.state.lastResult, undefined);
});

test("disabled sites cannot inspect or sign in and clear every scheduling alarm", async () => {
  const runtime = harness({tabs: [tab], initial: {autoEnabled: true}});
  await runtime.send({type: "schedule-settings", config: {startTime: "08:30", retryInterval: 90, retryCount: 2, timeout: 15}});
  const saved = await runtime.send({type: "site-settings", config: {enabled: false}});
  assert.equal(saved.saved, true);
  assert.equal(runtime.state.sites.piggo.timeout, 15);
  await runtime.send({type: "run"});
  await runtime.send({type: "inspect"});
  await runtime.send({type: "auto"}, tab);
  await runtime.alarm("netsurf-daily");
  assert.equal(runtime.actions.length, 0);
  assert.equal(runtime.alarms.size, 0);
});

test("automatic navigation honors the configured local start time", async () => {
  const runtime = harness({tabs: [tab], initial: {autoEnabled: true, sites: {piggo: {startTime: "23:59"}}}});
  if (new Date().getHours() === 23 && new Date().getMinutes() === 59) return;
  await runtime.send({type: "auto"}, tab);
  assert.equal(runtime.actions.length, 0);
});

test("transient pre-submit errors retry at the chosen interval and stop at the chosen count", async () => {
  const runtime = harness({tabs: [tab], inspect: "error", initial: {autoEnabled: true, sites: {piggo: {startTime: "00:00", retryInterval: 90, retryCount: 2, timeout: 12}}}});
  const before = Date.now();
  await runtime.alarm("netsurf-daily");
  assert.equal(runtime.state.schedule.attempts, 1);
  assert.ok(runtime.alarms.get("netsurf-retry").when >= before + 90000);
  await runtime.alarm("netsurf-retry");
  assert.equal(runtime.state.schedule.attempts, 2);
  await runtime.alarm("netsurf-retry");
  assert.equal(runtime.state.schedule.attempts, 3);
  assert.equal(runtime.alarms.has("netsurf-retry"), false);
  await runtime.alarm("netsurf-retry");
  assert.equal(runtime.state.schedule.attempts, 3);
  assert.equal(runtime.actions.filter(action => action[0] === "signin").length, 0);
  assert.ok(runtime.actions.find(action => action[2]?.fresh)[2].timeoutMs <= 12000);
});

test("WAF, login and unconfirmed submission never schedule another submission", async () => {
  for (const inspect of ["blocked", "debugging", "login_required", "manual_required", "unknown", "ready"]) {
    const runtime = harness({tabs: [tab], inspect, initial: {autoEnabled: true}});
    await runtime.alarm("netsurf-daily");
    assert.equal(runtime.alarms.has("netsurf-retry"), false);
    if (inspect === "ready") {
      assert.equal(runtime.alarms.has("netsurf-verify"), true);
      await runtime.alarm("netsurf-verify");
      assert.equal(runtime.actions.filter(action => action[0] === "signin").length, 1);
      assert.equal(runtime.state.lastResult.status, "pending");
      assert.equal(runtime.alarms.has("netsurf-verify"), false);
    }
  }
});

test("browser startup recovers a persisted retry without resetting the daily budget", async () => {
  const now = new Date();
  const day = `${now.getFullYear()}-${now.getMonth() + 1}-${now.getDate()}`;
  const runtime = harness({tabs: [tab], inspect: "error", initial: {autoEnabled: true, schedule: {day, attempts: 1, retryAt: Date.now() - 10000}}});
  await runtime.startup();
  assert.ok(runtime.alarms.has("netsurf-retry"));
  assert.equal(runtime.state.schedule.attempts, 1);
  assert.equal(new Date(runtime.alarms.get("netsurf-daily").when).getDate(), new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1).getDate());
});

const fixtureCookie = {name: "fixture", value: "fixture-only", domain: "piggo.me", path: "/", secure: true, httpOnly: true, hostOnly: true, session: true, sameSite: "lax"};

test("backup needs optional permission, includes cookies and settings, and excludes caches", async () => {
  const denied = harness({cookiePermission: false});
  assert.match((await denied.send({type: "backup"})).error, /Cookie/);
  const runtime = harness({cookies: [fixtureCookie, {...fixtureCookie, domain: "ordinary.test", partitionKey: {topLevelSite: "https://parent.test"}}], initial: {operation: {tabId: 12}, verifiedDay: "today", autoEnabled: true}});
  const result = await runtime.send({type: "backup"});
  assert.equal(result.backup.cookies.length, 2);
  assert.deepEqual(JSON.parse(JSON.stringify(runtime.cookieQueries)), [{partitionKey: {}}]);
  assert.equal(result.backup.settings.autoEnabled, true);
  assert.equal(result.backup.settings.operation, undefined);
  assert.equal(result.backup.settings.verifiedDay, undefined);
  const foreign = await runtime.send({type: "backup"}, tab);
  assert.equal(foreign.backup, undefined);
});

test("global schedule applies to every PT site while switches and results remain isolated", async () => {
  const other = {id: 13, windowId: 5, active: false, url: "https://audiences.me/"};
  const runtime = harness({tabs: [tab, other]});
  const config = {startTime: "00:00", retryInterval: 90, retryCount: 2, timeout: 15};
  assert.equal((await runtime.send({type: "schedule-settings", config})).saved, true);
  await runtime.send({type: "site-settings", siteId: "audiences.me", config: {enabled: true, timeout: 120}});
  assert.equal(runtime.state.sites["audiences.me"].timeout, 15);
  const inspected = await runtime.send({type: "inspect-all"});
  assert.deepEqual(Object.keys(inspected.results).sort(), ["audiences.me", "piggo"]);
  await runtime.send({type: "run", siteId: "audiences.me"});
  assert.equal(runtime.state["operation:audiences.me"].tabId, 13);
  assert.equal(runtime.state.operation, undefined);
  await runtime.send({type: "run", siteId: "piggo"});
  assert.equal(runtime.state.operation.tabId, 12);
  assert.deepEqual(runtime.actions.filter(action => action[0] === "signin").map(action => action[1]), [13, 12]);
  for (const action of runtime.actions.filter(action => action[2]?.fresh)) assert.ok(action[2].timeoutMs <= 15000);
});

test("the shared retry policy keeps independent per-site attempt budgets", async () => {
  const other = {id: 13, windowId: 5, active: false, url: "https://audiences.me/"};
  const runtime = harness({tabs: [tab, other], inspect: "error", initial: {autoEnabled: true, scheduleConfig: {startTime: "00:00", retryInterval: 60, retryCount: 1, timeout: 5}, sites: {piggo: {enabled: true}, "audiences.me": {enabled: true}}}});
  await runtime.alarm("netsurf-daily");
  await runtime.alarm("netsurf-daily:audiences.me");
  assert.equal(runtime.state.schedule.attempts, 1);
  assert.equal(runtime.state["schedule:audiences.me"].attempts, 1);
  await runtime.alarm("netsurf-retry:audiences.me");
  assert.equal(runtime.state.schedule.attempts, 1);
  assert.equal(runtime.state["schedule:audiences.me"].attempts, 2);
  assert.equal(runtime.alarms.has("netsurf-retry:audiences.me"), false);
  assert.equal(runtime.alarms.has("netsurf-retry"), true);
});

test("restore validates before writes, restores cookie attributes and clears stale completion", async () => {
  const runtime = harness({initial: {verifiedDay: "today", operation: {tabId: 1}, autoEnabled: true}});
  const document = {format: "netsurf-backup", version: 1, settings: {autoEnabled: false, sites: {piggo: {timeout: 60}}}, cookies: [fixtureCookie, {...fixtureCookie, session: false, expirationDate: 1}]};
  const invalid = await runtime.send({type: "restore", backup: {...document, cookies: [fixtureCookie, {...fixtureCookie, domain: "ordinary.test/path"}]}});
  assert.ok(invalid.error);
  assert.equal(runtime.actions.length, 0);
  assert.equal(runtime.state.autoEnabled, true);
  const result = await runtime.send({type: "restore", backup: document});
  assert.equal(result.restored, 1);
  assert.equal(result.expired, 1);
  assert.equal(runtime.state.verifiedDay, null);
  assert.equal(runtime.state.operation, null);
  assert.equal(runtime.state.sites.piggo.timeout, 60);
  const details = runtime.actions.find(action => action[0] === "cookie")[1];
  assert.equal(details.httpOnly, true);
  assert.equal(details.sameSite, "lax");
  assert.equal(details.domain, undefined);
});

test("partial cookie restoration does not claim completion and leaves automatic work disabled", async () => {
  const runtime = harness({cookieFailure: true, initial: {autoEnabled: true}});
  const document = {format: "netsurf-backup", version: 1, settings: {autoEnabled: true, sites: {piggo: {timeout: 60}}}, cookies: [fixtureCookie]};
  const result = await runtime.send({type: "restore", backup: document});
  assert.match(result.error, /还原未完成.*1 条失败/);
  assert.equal(runtime.state.autoEnabled, false);
  assert.equal(runtime.state.sites.piggo.timeout, undefined);
  assert.equal(runtime.alarms.size, 0);
});

test("a long operation keeps its worker active and releases the timer on completion", async () => {
  let finish;
  const inspectWait = new Promise(resolve => { finish = resolve; });
  const runtime = harness({tabs: [tab], inspectWait});
  const pending = runtime.send({type: "inspect"});
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(runtime.intervals.size, 1);
  for (const interval of runtime.intervals) await interval();
  assert.equal(runtime.keepAlivePings(), 1);
  finish();
  await pending;
  assert.equal(runtime.intervals.size, 0);
});

test("saving switches does not wait behind an outstanding page inspection", async () => {
  let finish;
  const inspectWait = new Promise(resolve => { finish = resolve; });
  const runtime = harness({tabs: [tab], inspectWait});
  const pending = runtime.send({type: "inspect"});
  await new Promise(resolve => setImmediate(resolve));
  let saved = false;
  const setting = runtime.send({type: "settings", enabled: true}).then(result => { saved = result.enabled === true; });
  await new Promise(resolve => setTimeout(resolve, 50));
  const savedBeforeInspection = saved;
  finish();
  await Promise.all([pending, setting]);
  assert.equal(savedBeforeInspection, true);
});

test("switching automatic work off during its page check prevents the pending submission", async () => {
  let finish;
  const inspectWait = new Promise(resolve => { finish = resolve; });
  const runtime = harness({tabs: [tab], inspectWait, initial: {autoEnabled: true}});
  const pending = runtime.send({type: "auto"}, tab);
  await new Promise(resolve => setImmediate(resolve));
  const stopped = await runtime.send({type: "settings", enabled: false});
  assert.equal(stopped.enabled, false);
  finish();
  await pending;
  assert.equal(runtime.actions.filter(action => action[0] === "signin").length, 0);
  assert.equal(runtime.alarms.size, 0);
});

test("every catalog switch can be enabled and remains independent from the global switch", async () => {
  const runtime = harness();
  const catalog = require("../catalog.js");
  for (const site of catalog) {
    const result = await runtime.send({type: "site-settings", siteId: site.id, config: {enabled: true}});
    assert.equal(result.saved, true, site.name);
    assert.equal(runtime.state.sites[site.id].enabled, true, site.name);
  }
  assert.equal(Object.values(runtime.state.sites).filter(config => config.enabled).length, 64);
  assert.notEqual(runtime.state.autoEnabled, true);
});

test("an extension update reloads existing dashboards without reloading websites", async () => {
  const dashboard = {id: 90, windowId: 5, url: "chrome-extension://netsurf-test/dashboard.html#automation"};
  const runtime = harness({tabs: [tab, dashboard]});
  await runtime.installed({reason: "update"});
  assert.deepEqual(JSON.parse(JSON.stringify(runtime.actions)), [["reload", 90, {bypassCache: true}]]);
});

test("a schedule rebuild error reports the saved switch and an explicit warning", async () => {
  const runtime = harness({schedulingError: true});
  const result = await runtime.send({type: "settings", enabled: true});
  assert.equal(result.enabled, true);
  assert.equal(runtime.state.autoEnabled, true);
  assert.match(result.warning, /签到计划更新失败.*fixture/);
  assert.equal(result.error, undefined);
});
