const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

function harness(reply = async () => ({status: "ready", message: "可以尝试签到"}), initial = {}) {
  const elements = new Map();
  function element(tag = "div") {
    return {tagName: tag.toUpperCase(), set id(value) { elements.set(value, this); }, textContent: "", value: "", disabled: false, checked: false, hidden: false, dataset: {}, children: [], attributes: {}, handlers: {}, click() {}, addEventListener(type, callback) { this.handlers[type] = callback; }, setAttribute(name, value) { this.attributes[name] = value; }, removeAttribute(name) { delete this.attributes[name]; }, append(...children) { this.children.push(...children); }, replaceChildren() { this.children = []; }};
  }
  const getElement = id => { if (!elements.has(id)) elements.set(id, element(["open", "inspect", "run", "save-site", "backup", "restore"].includes(id) ? "button" : "div")); return elements.get(id); };
  const timers = new Map();
  const requests = [];
  let nextTimer = 0;
  let closed = false;
  let changed;
  const context = vm.createContext({
    Date,
    URL,
    document: {getElementById: getElement, createElement: element, querySelectorAll: selector => [...elements.values()].filter(item => selector === "button" ? item.tagName === "BUTTON" : selector === "input[type=checkbox]" ? item.type === "checkbox" || item === elements.get("auto") : false)},
    window: {location: {hash: "#overview"}, addEventListener() {}, close: () => { closed = true; }},
    setTimeout: callback => { nextTimer += 1; timers.set(nextTimer, callback); return nextTimer; },
    clearTimeout: id => timers.delete(id),
    chrome: {
      runtime: {getManifest: () => ({version: "0.2.0"}), sendMessage: message => { requests.push(message); return reply(message); }},
      permissions: {request: async () => true},
      storage: {
        local: {get: async () => initial},
        onChanged: {addListener: callback => { changed = callback; }}
      }
    }
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, "..", "catalog.js"), "utf8"), context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, "..", "site-rules.js"), "utf8"), context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, "..", "sites.js"), "utf8"), context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, "..", "dashboard.js"), "utf8"), context);
  return {
    elements, requests,
    click: id => elements.get(id).handlers.click(),
    timeout: () => [...timers.values()].forEach(callback => callback()),
    closed: () => closed,
    changed: result => changed({lastResult: {newValue: result}}, "local")
  };
}

test("clicking shows progress immediately and cannot be overwritten by initial storage", async () => {
  const runtime = harness(() => new Promise(() => {}));
  const completed = runtime.click("inspect");
  assert.match(runtime.elements.get("status").textContent, /正在刷新并检查/);
  assert.equal(runtime.elements.get("run").disabled, true);
  await Promise.resolve();
  runtime.changed({message: "旧结果"});
  assert.match(runtime.elements.get("status").textContent, /正在刷新并检查/);
  runtime.timeout();
  await completed;
});

test("refresh-only defaults off, persists through settings and renames the row action", async () => {
  const runtime = harness(async message => message.type === "site-settings" ? {saved: true, config: {enabled: true, refreshOnly: message.config.refreshOnly}} : {status: "ready", message: "可以尝试签到"});
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(runtime.elements.has("refresh-only"), false);
  for (const row of runtime.elements.get("site-list").children) assert.equal(runtime.elements.get("refresh-only-" + row.dataset.siteId).checked, ["52pt.site", "open.cd", "u2.dmhy.org"].includes(row.dataset.siteId));
  assert.equal(runtime.elements.get("refresh-only-52pt.site").disabled, true);
  runtime.elements.get("refresh-only-piggo").checked = true;
  await runtime.elements.get("refresh-only-piggo").handlers.change();
  assert.equal(runtime.elements.get("refresh-only-piggo").checked, true);
  assert.equal(runtime.elements.get("refresh-only-audiences.me").checked, false);
  assert.equal(runtime.elements.get("refresh-only-52pt.site").disabled, true);
  assert.equal(runtime.elements.get("run").textContent, "刷新");
  assert.match(runtime.elements.get("site-toggle-status").textContent, /PigGo 仅刷新已开启/);
  assert.deepEqual(JSON.parse(JSON.stringify(runtime.requests.at(-1))), {type: "site-settings", siteId: "piggo", config: {refreshOnly: true}});
});

test("one-click sign-in dispatches the serialized batch and cached next-class text stays unknown", async () => {
  const runtime = harness(async () => ({results: {}, skipped: 1}));
  await new Promise(resolve => setImmediate(resolve));
  await runtime.click("run-all");
  assert.equal(runtime.requests.at(-1).type, "run-all");
  runtime.changed({status: "profile_only", profile: {level: "Next class: Veteran UserAccount age (days): 822.10 / 224 (Met) D", uploaded: "4.087 TiB"}});
  assert.equal(runtime.elements.get("profile-level").textContent, "—");
  assert.equal(runtime.elements.get("profile-uploaded").textContent, "4.087 TiB");
});

test("cached fields strip rank prefixes and numeric detail links and show separate seeding points", () => {
  const runtime = harness();
  runtime.changed({status: "ready", profile: {level: "(小学)Power User", bonus: "18,142,137.0 [明细]", seedingPoints: "123.45 [明细]"}});
  assert.equal(runtime.elements.get("profile-level").textContent, "Power User");
  assert.equal(runtime.elements.get("profile-bonus").textContent, "18,142,137.0");
  assert.equal(runtime.elements.get("profile-seedingPoints").textContent, "123.45");
});

test("failed refresh keeps the last successful profile update time visible", () => {
  const runtime = harness();
  const profileTime = "2026-10-14T01:00:00.000Z";
  runtime.changed({status: "error", time: "2026-10-15T02:00:00.000Z", profileTime, profile: {level: "Insane User", uploaded: "4.087 TiB"}});
  assert.equal(runtime.elements.get("profile-level").textContent, "Insane User");
  assert.equal(runtime.elements.get("checked").textContent, new Date(profileTime).toLocaleString("zh-CN", {month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit"}));
});

test("refresh-only shows today's refresh without claiming a sign-in and keeps old fields on failure", async () => {
  const runtime = harness(() => new Promise(() => {}), {sites: {piggo: {enabled: true, refreshOnly: true}}});
  await new Promise(resolve => setImmediate(resolve));
  runtime.changed({status: "refreshed", verified: true, time: new Date().toISOString(), profile: {level: "User", bonus: "123"}});
  assert.equal(runtime.elements.get("site-status").textContent, "已刷新");
  assert.equal(runtime.elements.get("completed-count").textContent, "0 / 1");
  runtime.changed({status: "ready", verified: true, time: "2000-01-01T00:00:00.000Z", profile: {level: "User", bonus: "123"}});
  assert.equal(runtime.elements.get("site-status").textContent, "待刷新");
});

test("a recovered verified day displays completion without inventing a check time", async () => {
  const runtime = harness();
  const now = new Date();
  const confirmedDay = `${now.getFullYear()}-${now.getMonth() + 1}-${now.getDate()}`;
  runtime.changed({status: "already_done", verified: true, confirmedDay});
  assert.equal(runtime.elements.get("site-status").textContent, "已完成");
  assert.equal(runtime.elements.get("checked").textContent, "—");
  runtime.changed({status: "already_done", verified: true, confirmedDay: "2026-01-01"});
  assert.equal(runtime.elements.get("site-status").textContent, "待核验");
});

test("saved results display immediately during a slow initial inspection", async () => {
  const runtime = harness(() => new Promise(() => {}), {lastResult: {status: "already_done", verified: true, time: new Date().toISOString()}});
  await Promise.resolve();
  assert.equal(runtime.elements.get("site-status").textContent, "已完成");
  assert.equal(runtime.elements.get("inspect").disabled, true);
  runtime.changed({status: "blocked", verified: true, time: new Date().toISOString()});
  assert.equal(runtime.elements.get("site-status").textContent, "需验证");
  assert.match(runtime.elements.get("status").textContent, /正在刷新并检查/);
  runtime.timeout();
});

test("initial storage cannot overwrite a newer result received from a running task", async () => {
  const runtime = harness(() => new Promise(() => {}), {lastResult: {status: "ready"}});
  runtime.changed({status: "already_done", verified: true, time: new Date().toISOString()});
  await Promise.resolve();
  assert.equal(runtime.elements.get("site-status").textContent, "已完成");
  runtime.timeout();
});

test("unanswered messages time out with visible feedback and restore buttons", async () => {
  const runtime = harness(() => new Promise(() => {}));
  const completed = runtime.click("run");
  runtime.timeout();
  await completed;
  assert.match(runtime.elements.get("status").textContent, /通信失败或超时/);
  for (const id of ["open", "inspect", "run", "auto"]) assert.equal(runtime.elements.get(id).disabled, false);
});

test("empty responses leave the dashboard open with an error", async () => {
  const runtime = harness(async () => null);
  await runtime.click("open");
  assert.equal(runtime.closed(), false);
  assert.match(runtime.elements.get("status").textContent, /通信失败或超时/);
});

test("opening PigGo keeps the dashboard open", async () => {
  const runtime = harness(async () => ({opened: true}));
  await runtime.click("open");
  assert.equal(runtime.closed(), false);
});

test("button actions display the returned page status", async () => {
  for (const type of ["inspect", "run"]) {
    const runtime = harness(async () => ({status: "debugging", message: "雷池提示当前环境正在被调试"}));
    await runtime.click(type);
    assert.equal(runtime.requests[0].type, type === "inspect" ? "inspect-all" : type);
    assert.match(runtime.elements.get("status").textContent, /正在被调试/);
  }
});

test("rapid repeated clicks do not dispatch duplicate operations", async () => {
  const runtime = harness(() => new Promise(() => {}));
  const completed = runtime.click("run");
  await runtime.click("run");
  assert.equal(runtime.requests.length, 1);
  runtime.timeout();
  await completed;
});

test("opening the dashboard queries fresh status rather than displaying a cached completion", async () => {
  const runtime = harness(async () => ({status: "ready", message: "可以尝试签到"}), {lastResult: {message: "今日已签到"}});
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(runtime.requests[0].type, "inspect");
  assert.equal(runtime.elements.get("status").textContent, "可以尝试签到");
});

test("today's summary counts only verified current-day completion", async () => {
  for (const result of [
    {status: "already_done", message: "今日已签到", verified: false, time: new Date().toISOString()},
    {status: "already_done", message: "今日已签到", verified: true, time: "2000-01-01T00:00:00.000Z"}
  ]) {
    const runtime = harness(async () => result);
    await runtime.click("inspect");
    assert.equal(runtime.elements.get("completed-count").textContent, "— / 1");
    assert.equal(runtime.elements.get("site-status").textContent, "待核验");
  }
  const runtime = harness(async () => ({status: "already_done", message: "今日已签到", verified: true, time: new Date().toISOString()}));
  await runtime.click("inspect");
  assert.equal(runtime.elements.get("completed-count").textContent, "1 / 1");
});

test("failed settings restore the switch and show a dedicated message", async () => {
  const runtime = harness(async message => message.type === "settings" ? null : {status: "ready", message: "可以尝试签到"}, {autoEnabled: false});
  await new Promise(resolve => setImmediate(resolve));
  runtime.elements.get("auto").checked = true;
  await runtime.elements.get("auto").handlers.change();
  assert.equal(runtime.elements.get("auto").checked, false);
  assert.match(runtime.elements.get("settings-status").textContent, /设置保存失败.*通信失败/);
  assert.equal(runtime.elements.get("status").textContent, "可以尝试签到");
});

test("a delayed initial preference cannot overwrite a setting already saved", async () => {
  let resolveInitial;
  const initial = new Promise(resolve => { resolveInitial = resolve; });
  const runtime = harness(async () => ({enabled: true}), initial);
  runtime.elements.get("auto").checked = true;
  await runtime.elements.get("auto").handlers.change();
  resolveInitial({autoEnabled: false, activity: []});
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(runtime.elements.get("auto").checked, true);
  assert.equal(runtime.elements.get("auto-mode").textContent, "已开启");
});

test("disabled sites disappear from the overview without dispatching an inspection", async () => {
  const runtime = harness(async () => null, {sites: {piggo: {enabled: false}}});
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(runtime.requests.length, 0);
  assert.equal(runtime.elements.get("overview-body").children.length, 0);
  assert.equal(runtime.elements.get("overview-empty").hidden, false);
  assert.equal(runtime.elements.get("completed-count").textContent, "0 / 0");
});

test("overview renders account fields as text and leaves missing values unknown", async () => {
  const runtime = harness(async () => ({status: "ready", message: "可以尝试签到", profile: {level: "Power User", bonus: "1234.50", uploaded: "2 TiB", downloaded: "1 TiB"}}));
  await runtime.click("inspect");
  assert.equal(runtime.elements.get("profile-level").textContent, "Power User");
  assert.equal(runtime.elements.get("profile-bonus").textContent, "1234.50");
  assert.equal(runtime.elements.get("profile-ratio").textContent, "—");
});

test("overview row refresh requests only that site's background inspection without signing in", async () => {
  const runtime = harness(async () => ({status: "ready", time: new Date().toISOString()}));
  await new Promise(resolve => setImmediate(resolve));
  const actions = runtime.elements.get("overview-body").children[0].children.at(-1).children[0];
  assert.deepEqual(actions.children.map(button => button.textContent), ["打开", "刷新", "签到"]);
  await runtime.click("refresh");
  assert.deepEqual(JSON.parse(JSON.stringify(runtime.requests.at(-1))), {type: "inspect", siteId: "piggo", background: true});
  await runtime.click("refresh");
  assert.deepEqual(JSON.parse(JSON.stringify(runtime.requests.at(-1))), {type: "inspect", siteId: "piggo", background: true});
  assert.equal(runtime.requests.some(message => message.type === "run" || message.type === "run-all"), false);
});

test("refresh-only rows keep a single refresh action", async () => {
  const runtime = harness(async () => ({status: "ready"}), {sites: {piggo: {enabled: true, refreshOnly: true}}});
  await new Promise(resolve => setImmediate(resolve));
  const actions = runtime.elements.get("overview-body").children[0].children.at(-1).children[0];
  assert.deepEqual(actions.children.map(button => button.textContent), ["打开", "刷新"]);
});

test("a per-site diagnostic retry requests background inspection without signing in", async () => {
  const runtime = harness(async () => ({status: "ready", time: new Date().toISOString()}));
  await new Promise(resolve => setImmediate(resolve));
  await runtime.click("inspect-piggo");
  assert.deepEqual(JSON.parse(JSON.stringify(runtime.requests.at(-1))), {type: "inspect", siteId: "piggo", background: true});
});

test("PT navigation contains exactly overview and site management", () => {
  const runtime = harness();
  const links = runtime.elements.get("secondary-nav").children;
  assert.deepEqual(links.map(link => link.textContent), ["概览", "站点管理"]);
});

test("background observations cannot overwrite unsaved site settings", async () => {
  const runtime = harness();
  await new Promise(resolve => setImmediate(resolve));
  runtime.elements.get("start-time").value = "11:45";
  runtime.elements.get("site-form").handlers.input();
  runtime.changed({status: "ready", message: "新的检查", verified: true, time: new Date().toISOString()});
  assert.equal(runtime.elements.get("start-time").value, "11:45");
});

test("the full catalog is searchable and shares one schedule form", async () => {
  const runtime = harness(async message => message.type === "schedule-settings" ? {saved: true, scheduleConfig: message.config} : {status: "ready", message: "可以尝试签到"});
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(runtime.elements.get("site-list").children.length, 64);
  runtime.elements.get("site-search").value = "Audiences";
  runtime.elements.get("site-search").handlers.input();
  assert.equal(runtime.elements.get("site-list").children.length, 1);
  for (const [id, value] of [["start-time", "09:15"], ["retry-interval", "90"], ["retry-count", "2"], ["timeout", "15"]]) runtime.elements.get(id).value = value;
  await runtime.elements.get("site-form").handlers.submit({preventDefault() {}});
  const saved = runtime.requests.find(message => message.type === "schedule-settings");
  assert.equal(saved.siteId, undefined);
  assert.equal(saved.config.startTime, "09:15");
  assert.equal(runtime.elements.get("site-settings-status").textContent, "签到设置已保存，所有站点共用");
});

test("automatic and site switches remain usable while an inspection is waiting", async () => {
  const runtime = harness(async message => {
    if (message.type === "inspect") return new Promise(() => {});
    if (message.type === "settings") return {enabled: message.enabled};
    if (message.type === "site-settings") return {saved: true, config: {enabled: message.config.enabled}};
  });
  const pending = runtime.click("inspect");
  const interactive = runtime.elements.get("auto").disabled;
  runtime.elements.get("auto").checked = true;
  await runtime.elements.get("auto").handlers.change();
  runtime.elements.get("enabled-audiences.me").checked = true;
  await runtime.elements.get("enabled-audiences.me").handlers.change();
  const saved = runtime.elements.get("auto").checked;
  const siteEnabled = runtime.elements.get("enabled-audiences.me").checked;
  runtime.timeout();
  await pending;
  assert.equal(interactive, false);
  assert.equal(saved, true);
  assert.equal(siteEnabled, true);
  assert.equal(runtime.elements.get("auto").checked, true);
});

test("a saved switch remains on when the scheduler reports a separate failure", async () => {
  const runtime = harness(async () => ({enabled: true, warning: "签到计划更新失败：fixture"}));
  runtime.elements.get("auto").checked = true;
  await runtime.elements.get("auto").handlers.change();
  assert.equal(runtime.elements.get("auto").checked, true);
  assert.match(runtime.elements.get("settings-status").textContent, /已保存.*已开启.*签到计划更新失败/);
});

test("an incompatible worker response explains that the extension needs reloading", async () => {
  const runtime = harness(async () => ({status: "error", message: "legacy fixture"}));
  runtime.elements.get("auto").checked = true;
  await runtime.elements.get("auto").handlers.change();
  assert.match(runtime.elements.get("settings-status").textContent, /后台设置响应不兼容.*扩展管理页重新加载/);
});
