const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const test = require("node:test");
const tasks = require("../periodic.js");

function harness({initial = {}, permission = true, inspect = "ready", outcome = "success", beforePermit = null, beforeInspect = null} = {}) {
  const state = structuredClone(initial);
  const session = {};
  const alarms = new Map();
  const actions = [];
  const tabs = [{id: 12, active: true, windowId: 1, url: "https://www.nodeseek.com/post-123"}];
  let timestamp = new Date(2026, 9, 20, 9).getTime();
  let nextId = 100;
  let runtime;
  const chrome = {
    storage: {local: {get: async keys => Object.fromEntries([keys].flat().map(key => [key, state[key]])), set: async values => Object.assign(state, structuredClone(values))}, session: {get: async key => ({[key]: session[key]}), set: async values => Object.assign(session, structuredClone(values)), remove: async key => delete session[key]}},
    permissions: {contains: async () => permission},
    alarms: {clear: async name => alarms.delete(name), create: async (name, details) => alarms.set(name, details)},
    windows: {update: async () => {}},
    tabs: {
      query: async options => tabs.filter(tab => !options.url || options.url.some(pattern => tab.url.startsWith(pattern.slice(0, -1)))),
      create: async options => { const tab = {...options, id: nextId++, windowId: 1}; tabs.push(tab); actions.push(["create", tab.id]); return tab; },
      update: async (tabId, options) => Object.assign(tabs.find(tab => tab.id === tabId), options),
      remove: async tabId => { actions.push(["remove", tabId]); tabs.splice(tabs.findIndex(tab => tab.id === tabId), 1); }
    },
    scripting: {executeScript: async details => {
      const [taskId, action, token] = details.args;
      actions.push([action, taskId]);
      if (action === "inspect") {
        if (beforeInspect) await beforeInspect({advance: milliseconds => { timestamp += milliseconds; }});
        return [{result: {status: typeof inspect === "function" ? inspect() : inspect, message: "检查结果"}}];
      }
      if (beforePermit) await beforePermit({state, tabs, runtime});
      const tab = tabs.find(item => item.id === details.target.tabId);
      const allowed = await runtime.permit({taskId, token}, {tab, url: tab.url});
      if (allowed.accepted) actions.push(["submit", taskId]);
      return [{result: {status: allowed.accepted ? outcome : "error", message: allowed.accepted ? "任务结果" : "许可拒绝"}}];
    }}
  };
  const context = vm.createContext({NetSurfPeriodic: tasks, URL, Date, Math, setTimeout, clearTimeout});
  vm.runInContext(fs.readFileSync(path.join(__dirname, "../periodic-background.js"), "utf8"), context);
  runtime = context.NetSurfPeriodicBackground.create(chrome, () => timestamp, () => 0);
  return {runtime, state, session, tabs, actions, alarms, advance: milliseconds => { timestamp += milliseconds; }, now: () => timestamp};
}

test("periodic defaults are off and reject malformed or unknown settings", () => {
  assert.deepEqual(tasks.catalog.map(site => site.id), ["nodeseek", "invitesfun"]);
  assert.ok(Object.values(tasks.settings()).every(item => !item.enabled));
  for (const value of [null, [], {enabled: "true"}, {startTime: "25:00"}, {intervalHours: 0}, {timeout: 181}, {maxRetries: -1}, {randomDelayMinutes: Infinity}]) assert.throws(() => tasks.config(value));
  assert.throws(() => tasks.settings({other: {enabled: true}}));
  assert.equal(tasks.firstRun(tasks.config(), new Date(2026, 9, 20, 7).getTime(), 0), new Date(2026, 9, 20, 8).getTime());
});

test("task schedules persist independently without PT automation or unrelated state changes", async () => {
  const runtime = harness({initial: {autoEnabled: false, sites: {piggo: {enabled: true}}, verifiedDay: "kept"}});
  await runtime.runtime.save("nodeseek", {enabled: true, startTime: "10:30"});
  await runtime.runtime.save("invitesfun", {enabled: true, startTime: "11:00", intervalHours: 48});
  assert.equal(runtime.alarms.size, 2);
  assert.equal(runtime.alarms.get("netsurf-periodic:nodeseek").when, runtime.now() + 1000);
  assert.equal(runtime.state.periodicTasks.invitesfun.intervalHours, 24);
  assert.equal(runtime.state.periodicTasks.nodeseek.startTime, "08:00");
  assert.equal(runtime.state.autoEnabled, false);
  assert.equal(runtime.state.verifiedDay, "kept");
  await runtime.runtime.resume();
  assert.equal(runtime.alarms.size, 2);
  await runtime.runtime.save("nodeseek", {enabled: false});
  assert.equal(runtime.alarms.has("netsurf-periodic:nodeseek"), false);
  assert.equal(runtime.alarms.has("netsurf-periodic:invitesfun"), true);
});

test("permission denial does not persist an enabled task or open a page", async () => {
  const runtime = harness({permission: false});
  await assert.rejects(runtime.runtime.save("nodeseek", {enabled: true}), /权限/);
  assert.equal(runtime.state.periodicTasks, undefined);
  assert.equal(runtime.actions.length, 0);
});

test("inspection is read-only and owned temporary pages close without touching user pages", async () => {
  const runtime = harness();
  await runtime.runtime.save("nodeseek", {enabled: true});
  assert.equal((await runtime.runtime.run("nodeseek", "inspect")).status, "ready");
  assert.equal(runtime.actions.some(action => action[0] === "submit"), false);
  assert.equal(runtime.tabs.length, 1);
  assert.equal(runtime.tabs[0].url, "https://www.nodeseek.com/post-123");
  assert.equal(runtime.state.periodicHistory[0].mode, "inspect");
});

test("late loaded task controls are inspected until ready without an early submission", async () => {
  let observations = 0;
  const runtime = harness({inspect: () => ++observations === 1 ? "unknown" : "ready"});
  await runtime.runtime.save("nodeseek", {enabled: true});
  assert.equal((await runtime.runtime.run("nodeseek", "inspect")).status, "ready");
  assert.equal(observations, 2);
  assert.equal(runtime.actions.some(action => action[0] === "submit"), false);
  assert.equal(runtime.tabs.length, 1);
});

test("timeout diagnostics distinguish unreadable pages from missing controls without submitting", async () => {
  for (const injectionFailed of [false, true]) {
    const runtime = harness({inspect: "unknown", beforeInspect: async ({advance}) => {
      advance(60001);
      if (injectionFailed) throw new Error("private URL or token must not be recorded");
    }});
    await runtime.runtime.save("nodeseek", {enabled: true});
    const result = await runtime.runtime.run("nodeseek", "run");
    assert.equal(result.status, "error");
    assert.match(result.message, injectionFailed ? /阶段：脚本注入/ : /阶段：页面识别/);
    assert.match(result.message, /路径：\/board/);
    assert.doesNotMatch(result.message, /private|token/);
    assert.equal(runtime.actions.some(action => action[0] === "submit"), false);
    assert.equal(runtime.tabs.length, 1);
  }
});

test("concurrent actions sign in once and confirmed completion skips another submission", async () => {
  const runtime = harness();
  await runtime.runtime.save("nodeseek", {enabled: true});
  await Promise.all([runtime.runtime.run("nodeseek", "run"), runtime.runtime.run("nodeseek", "run")]);
  assert.equal(runtime.actions.filter(action => action[0] === "submit").length, 1);
  assert.equal(runtime.state.periodicState.nodeseek.completedDay, tasks.day(runtime.now()));
  assert.equal(runtime.state.periodicState.nodeseek.operation, null);
  assert.equal(runtime.tabs.length, 1);
});

test("uncertain submission is never retried automatically, including after restart", async () => {
  const runtime = harness({outcome: "error"});
  await runtime.runtime.save("nodeseek", {enabled: true});
  await runtime.runtime.run("nodeseek", "run");
  assert.equal(runtime.state.periodicState.nodeseek.operation.submitted, true);
  assert.equal(runtime.state.periodicState.nodeseek.nextAt, new Date(2026, 9, 21, 8).getTime());
  await runtime.runtime.resume();
  await runtime.runtime.run("nodeseek", "run");
  assert.equal(runtime.actions.filter(action => action[0] === "submit").length, 1);
  assert.match(runtime.state.periodicState.nodeseek.lastResult.message, /仅只读核验/);
  runtime.advance(24 * 3600000);
  await runtime.runtime.alarm("netsurf-periodic:nodeseek");
  assert.equal(runtime.actions.filter(action => action[0] === "submit").length, 2);
});

test("verification and login states stop before submission", async () => {
  for (const inspect of ["blocked", "login_required", "already_done"]) {
    const runtime = harness({inspect});
    await runtime.runtime.save("invitesfun", {enabled: true});
    assert.equal((await runtime.runtime.run("invitesfun", "run")).status, inspect);
    assert.equal(runtime.actions.some(action => action[0] === "submit"), false);
  }
});

test("manual completion always schedules the next local morning instead of click time", async () => {
  const runtime = harness();
  await runtime.runtime.save("nodeseek", {enabled: true, startTime: "23:59"});
  await runtime.runtime.run("nodeseek", "run");
  const nextAt = new Date(2026, 9, 21, 8).getTime();
  assert.equal(runtime.state.periodicState.nodeseek.nextAt, nextAt);
  runtime.advance(3600000);
  await runtime.runtime.run("nodeseek", "run");
  assert.equal(runtime.state.periodicState.nodeseek.nextAt, nextAt);
});

test("disabling a task while preparing rejects its submission permit", async () => {
  const runtime = harness({beforePermit: async ({runtime}) => runtime.save("nodeseek", {enabled: false})});
  await runtime.runtime.save("nodeseek", {enabled: true});
  await runtime.runtime.run("nodeseek", "run");
  assert.equal(runtime.actions.some(action => action[0] === "submit"), false);
  assert.equal(runtime.alarms.has("netsurf-periodic:nodeseek"), false);
});

test("permits are bound to site, tab, deadline and token and can only be consumed once", async () => {
  const runtime = harness();
  await runtime.runtime.save("nodeseek", {enabled: true});
  runtime.state.periodicState.nodeseek.operation = {token: "own", tabId: 55, deadline: runtime.now() + 5000, day: tasks.day(runtime.now()), submitted: false};
  const message = {taskId: "nodeseek", token: "own"};
  const sender = {tab: {id: 55}, url: "https://www.nodeseek.com/board"};
  for (const changed of [{url: "http://www.nodeseek.com/board"}, {url: "https://evil.test/board"}, {url: "https://www.nodeseek.com/post-123"}, {tab: {id: 56}}]) assert.equal((await runtime.runtime.permit(message, {...sender, ...changed})).accepted, false);
  assert.equal((await runtime.runtime.permit({...message, token: "wrong"}, sender)).accepted, false);
  const allowed = await Promise.all([runtime.runtime.permit(message, sender), runtime.runtime.permit(message, sender)]);
  assert.equal(allowed.filter(item => item.accepted).length, 1);
  runtime.state.periodicState.nodeseek.operation.submitted = false;
  runtime.advance(6000);
  assert.equal((await runtime.runtime.permit(message, sender)).accepted, false);
});

test("due alarms run while early or disabled alarms do not submit", async () => {
  const runtime = harness();
  runtime.advance(-2 * 3600000);
  await runtime.runtime.save("nodeseek", {enabled: true, startTime: "10:00"});
  await runtime.runtime.alarm("netsurf-periodic:nodeseek");
  assert.equal(runtime.actions.length, 0);
  runtime.advance(3600000);
  runtime.alarms.delete("netsurf-periodic:nodeseek");
  await runtime.runtime.alarm("netsurf-periodic:nodeseek");
  assert.equal(runtime.actions.filter(action => action[0] === "submit").length, 1);
  assert.equal(runtime.alarms.get("netsurf-periodic:nodeseek").when, new Date(2026, 9, 21, 8).getTime());
  runtime.alarms.delete("netsurf-periodic:nodeseek");
  await runtime.runtime.run("nodeseek", "run");
  assert.equal(runtime.alarms.get("netsurf-periodic:nodeseek").when, new Date(2026, 9, 21, 8).getTime());
  await runtime.runtime.alarm("netsurf-periodic:invitesfun");
  assert.equal(runtime.actions.filter(action => action[0] === "submit").length, 1);
});

test("revoked permissions rearm bounded pre-submission retries even when no page opens", async () => {
  const runtime = harness({permission: false, initial: {periodicTasks: {nodeseek: {...tasks.defaults, enabled: true, maxRetries: 1}}, periodicState: {nodeseek: {nextAt: new Date(2026, 9, 20, 9).getTime()}}}});
  await runtime.runtime.alarm("netsurf-periodic:nodeseek");
  assert.equal(runtime.state.periodicState.nodeseek.attempts, 1);
  assert.equal(runtime.alarms.get("netsurf-periodic:nodeseek").when, new Date(2026, 9, 20, 11).getTime());
  for (let attempt = 0; attempt < tasks.defaults.maxRetries; attempt++) {
    runtime.advance(2 * 3600000);
    runtime.alarms.delete("netsurf-periodic:nodeseek");
    await runtime.runtime.alarm("netsurf-periodic:nodeseek");
  }
  assert.equal(runtime.state.periodicState.nodeseek.attempts, 0);
  assert.equal(runtime.alarms.get("netsurf-periodic:nodeseek").when, new Date(2026, 9, 21, 8).getTime());
  assert.equal(runtime.actions.length, 0);
});

test("restart cleans only its abandoned inactive tab and preserves an adopted tab", async () => {
  const runtime = harness();
  runtime.tabs.push({id: 100, active: false, url: "https://login.example.test/"});
  runtime.session.periodicTaskTab = {tabId: 100, taskId: "nodeseek"};
  await runtime.runtime.resume();
  assert.equal(runtime.tabs.some(tab => tab.id === 100), false);
  runtime.session.periodicTaskTab = {tabId: 12, taskId: "nodeseek"};
  await runtime.runtime.resume();
  assert.equal(runtime.tabs.some(tab => tab.id === 12), true);
});

test("legacy multi-day settings migrate to daily without erasing confirmation or submission protection", async () => {
  const runtime = harness({initial: {periodicTasks: {nodeseek: {...tasks.defaults, enabled: true, intervalHours: 48, startTime: "23:59", randomDelayMinutes: 30}}, periodicState: {nodeseek: {completedDay: tasks.day(new Date(2026, 9, 20, 9).getTime()), operation: {submitted: true, token: "keep"}, nextAt: new Date(2026, 9, 23, 23, 59).getTime()}}}});
  await runtime.runtime.resume();
  assert.equal(runtime.state.periodicTasks.nodeseek.intervalHours, 24);
  assert.equal(runtime.state.periodicTasks.nodeseek.startTime, "08:00");
  assert.equal(runtime.state.periodicState.nodeseek.operation.token, "keep");
  assert.equal(runtime.alarms.get("netsurf-periodic:nodeseek").when, new Date(2026, 9, 21, 8).getTime());
  assert.equal(runtime.actions.length, 0);
  await runtime.runtime.save("nodeseek", {enabled: false});
  await runtime.runtime.save("nodeseek", {enabled: true});
  assert.equal(runtime.alarms.get("netsurf-periodic:nodeseek").when, new Date(2026, 9, 21, 8).getTime());
  assert.equal(tasks.nextRun(tasks.config(), new Date(2026, 11, 31, 21).getTime()), new Date(2027, 0, 1, 8).getTime());
});
