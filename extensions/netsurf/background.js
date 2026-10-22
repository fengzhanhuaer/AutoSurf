importScripts("catalog.js", "site-rules.js", "sites.js", "hdsky.js", "opencd.js", "ptsbao.js", "freefarm.js", "pt52.js", "piggo.js", "captcha-background.js", "periodic.js", "periodic-background.js", "backup.js");

const piggo = globalThis.NetSurfPiggo;
const sites = globalThis.NetSurfSites;
const backup = globalThis.NetSurfBackup;
const periodic = globalThis.NetSurfPeriodicBackground.create(chrome);
const captchaOcr = globalThis.NetSurfCaptchaBackground.create(chrome, sites, readState);
const contentRevision = "2026-10-21-attendance-record-v66";
let actionQueue = Promise.resolve();
let settingsQueue = Promise.resolve();
let scheduleQueue = Promise.resolve();
let dashboardQueue = Promise.resolve();
const resultQueues = new Map();

async function withWorkerAlive(action) {
  const timer = setInterval(() => chrome.runtime.getPlatformInfo().catch(() => {}), 20000);
  try { return await action(); } finally { clearInterval(timer); }
}

function adapter(siteId = "piggo", url) {
  const site = sites.get(siteId);
  return piggo.create(sites.resolve(url)?.id === siteId ? new URL(url).origin : site.origin, site.signinPath, site.mode === "profile", site.name);
}

async function readState(siteId = "piggo") {
  const fields = ["verifiedDay", "refreshedDay", "operation", "lastResult", "schedule"];
  const state = await chrome.storage.local.get(["autoEnabled", "sites", "scheduleConfig", ...fields.map(field => sites.key(field, siteId))]);
  return {...sites.settings(state), ...Object.fromEntries(fields.map(field => [field, state[sites.key(field, siteId)]]))};
}

async function openDashboard(sourceTab) {
  const url = chrome.runtime.getURL("dashboard.html");
  const contexts = await chrome.runtime.getContexts({contextTypes: ["TAB"]});
  const tabs = contexts.filter(context => context.documentUrl?.split("#")[0] === url).map(context => ({id: context.tabId, windowId: context.windowId}));
  tabs.sort((left, right) => Number(right.windowId === sourceTab?.windowId) - Number(left.windowId === sourceTab?.windowId));
  if (tabs.length) {
    await chrome.tabs.update(tabs[0].id, {active: true});
    await chrome.windows.update(tabs[0].windowId, {focused: true});
  } else {
    const created = await chrome.tabs.create({url, active: true, ...(sourceTab?.windowId !== undefined ? {windowId: sourceTab.windowId} : {})});
    for (let attempt = 0; attempt < 40; attempt += 1) {
      const opened = await chrome.runtime.getContexts({contextTypes: ["TAB"]});
      if (opened.some(context => context.tabId === created.id)) break;
      await new Promise(resolve => setTimeout(resolve, 50));
    }
  }
}

chrome.action.onClicked.addListener(tab => {
  dashboardQueue = dashboardQueue.catch(() => {}).then(() => openDashboard(tab));
  dashboardQueue.catch(() => {});
  return dashboardQueue;
});

function pageMessage(tabId, message, timeoutMs = 3000) {
  let timeout;
  return Promise.race([
    chrome.tabs.sendMessage(tabId, {...message, type: `netsurf-${message.type}`}),
    new Promise((resolve, reject) => { timeout = setTimeout(() => reject(new Error("Page response timed out")), timeoutMs); })
  ]).finally(() => clearTimeout(timeout));
}

function today() { return sites.day(); }

function confirmedPersistentForm(state, siteId) {
  const rule = NetSurfRules.get(sites.get(siteId).origin);
  return rule?.statusPageKeepsForm && !state.sites[siteId].refreshOnly && state.verifiedDay === today() && state.operation?.day === today() && (state.operation.phase === "submitted" || rule.turnstileAttendance && state.operation.phase === "preparing") && state.operation.awaitingConfirmation === false;
}

function unresolvedSubmission(state) {
  const operationDay = state.operation?.day || (state.operation?.startedAt ? sites.day(new Date(state.operation.startedAt)) : state.lastResult?.time ? sites.day(new Date(state.lastResult.time)) : today());
  const legacyOperation = state.operation && !Object.hasOwn(state.operation, "awaitingConfirmation") && state.verifiedDay !== today();
  return operationDay === today() && (legacyOperation || state.operation?.awaitingConfirmation === true || state.lastResult?.status === "pending" || state.lastResult?.confirmationFailed === true);
}

async function confirmationFailure(tab, siteId, reason = "核验超时，未取得签到成功证据", snapshot) {
  const state = await readState(siteId);
  if (state.lastResult?.verified && ["success", "already_done"].includes(state.lastResult.status) && state.verifiedDay === today()) return state.lastResult;
  await chrome.storage.local.set({[sites.key("operation", siteId)]: {...state.operation, day: today(), awaitingConfirmation: true}});
  const url = tab?.url || sites.get(siteId).origin;
  return save({...adapter(siteId, url).result("error", url), confirmationFailed: true, message: `签到核验失败：${reason}；已停止提交及自动核验，可手动刷新检查结果，避免重复签到`, diagnostic: {...snapshot?.diagnostic, phase: "签到核验", path: new URL(url).pathname, elapsedMs: state.operation?.startedAt ? Math.max(0, Date.now() - state.operation.startedAt) : 0}}, tab?.id, false, siteId);
}

async function save(result, tabId, verified = false, siteId = "piggo") {
  const next = (resultQueues.get(siteId) || Promise.resolve()).catch(() => {}).then(() => persistResult(result, tabId, verified, siteId));
  resultQueues.set(siteId, next);
  return next;
}

async function persistResult(result, tabId, verified, siteId) {
  const previous = await readState(siteId);
  if (result.status === "ready" && confirmedPersistentForm(previous, siteId)) {
    result = {...result, status: "already_done", confirmedDay: previous.verifiedDay, message: "今日已有已确认签到记录，不重复提交"};
    verified = true;
  }
  const refreshFailed = previous.verifiedDay === today() && !previous.sites[siteId].refreshOnly && ["error", "no_tab"].includes(result.status);
  if (refreshFailed) {
    result = {...result, status: "already_done", confirmedDay: previous.verifiedDay, confirmationFailed: false, refreshError: result.message || "页面通信失败", message: `今日已签到；本次账号刷新失败：${result.message || "页面通信失败"}；已保留确认状态`};
    verified = true;
  }
  if (unresolvedSubmission(previous) && previous.lastResult?.confirmationFailed && !result.confirmationFailed && (!verified || result.status === "pending")) return previous.lastResult;
  if (result.status === "pending" && previous.lastResult?.verified && ["success", "already_done"].includes(previous.lastResult.status) && previous.lastResult.tabId === tabId && previous.operation?.tabId === tabId && new Date(previous.lastResult.time).getTime() >= previous.operation.startedAt) return previous.lastResult;
  if (verified && result.status === "unknown" && previous.verifiedDay === today()) {
    result = {...result, status: "already_done", message: "今日已签到；本次页面未识别签到入口，已保留确认状态"};
  }
  const profile = sites.profile(previous.lastResult?.profile);
  const profileSucceeded = !refreshFailed && verified && ["ready", "success", "already_done", "profile_only", "refreshed", "unknown", "pending"].includes(result.status) && Object.values(sites.profile(result.profile)).some(Boolean);
  if (profileSucceeded) for (const [field, value] of Object.entries(sites.profile(result.profile))) if (value) profile[field] = value;
  const saved = {...result, siteId, profile, tabId, verified, profileTime: profileSucceeded ? result.time : previous.lastResult?.profileTime || previous.lastResult?.time};
  const state = {[sites.key("lastResult", siteId)]: saved};
  if (profileSucceeded) state[sites.key("refreshedDay", siteId)] = today();
  if (verified && ["success", "already_done"].includes(result.status)) {
    state[sites.key("verifiedDay", siteId)] = today();
    if (previous.operation) state[sites.key("operation", siteId)] = {...previous.operation, awaitingConfirmation: false};
  }
  if (verified && result.status === "ready") state[sites.key("verifiedDay", siteId)] = null;
  await chrome.storage.local.set(state);
  return saved;
}

async function recordActivity(type, result) {
  if (!result) return result;
  const {activity} = await chrome.storage.local.get("activity");
  const entry = {type, siteId: result.siteId || "piggo", status: result.status, message: result.message, time: result.time || new Date().toISOString()};
  await chrome.storage.local.set({activity: [entry, ...(Array.isArray(activity) ? activity : [])].slice(0, 50)});
  return result;
}

async function selectTab(siteId = "piggo") {
  const patterns = sites.origins(sites.get(siteId));
  const tabs = await chrome.tabs.query({url: patterns});
  tabs.sort((left, right) => Number(right.active) - Number(left.active) || (right.lastAccessed || 0) - (left.lastAccessed || 0));
  return tabs[0];
}

function ensureContent(tab, siteId, timeoutMs = 3000) {
  let timeout;
  return Promise.race([
    injectContent(tab, siteId),
    new Promise((resolve, reject) => { timeout = setTimeout(() => reject(new Error("内容脚本注入超时")), timeoutMs); })
  ]).finally(() => clearTimeout(timeout));
}

async function injectContent(tab, siteId) {
  try {
    const current = await pageMessage(tab.id, {type: "inspect"}, 250);
    if (current?.contentVersion === chrome.runtime.getManifest().version && current?.contentRevision === contentRevision && current.path) return;
  } catch {}
  await chrome.scripting.executeScript({target: {tabId: tab.id}, injectImmediately: true, func: () => { globalThis.NetSurfReadOnlyInjection = true; }});
  await chrome.scripting.executeScript({target: {tabId: tab.id}, injectImmediately: true, files: ["catalog.js", "site-rules.js", "sites.js", "profile-api.js", "hdsky.js", "opencd.js", "ptsbao.js", "freefarm.js", "pt52.js", "piggo.js", "content.js"]});
}

async function freshPage(tab, timeoutSeconds = 30, reuseCurrentPage = false, skipDetails = false) {
  const siteId = sites.resolve(tab.url)?.id || "piggo";
  const dataOnly = (await readState(siteId)).sites[siteId].refreshOnly;
  const deadline = Date.now() + timeoutSeconds * 1000;
  await ensureContent(tab, siteId, Math.max(1, Math.min(3000, deadline - Date.now())));
  let current = await pageMessage(tab.id, {type: "inspect"}, Math.max(1, Math.min(3000, deadline - Date.now())));
  while (current.challengePending && NetSurfRules.get(sites.get(siteId).origin)?.waitForSecurityChallenge) {
    if (Date.now() >= deadline) return {...current, challengePending: false, message: "站点自动安全验证超时，请打开站点完成后刷新"};
    await new Promise(resolve => setTimeout(resolve, Math.min(250, deadline - Date.now())));
    if (Date.now() >= deadline) return {...current, challengePending: false, message: "站点自动安全验证超时，请打开站点完成后刷新"};
    try { current = await pageMessage(tab.id, {type: "inspect"}, Math.max(1, Math.min(1000, deadline - Date.now()))); } catch {}
  }
  if (["blocked", "debugging", "login_required"].includes(current.status) || current.status === "manual_required" && !dataOnly && !adapter(siteId, tab.url).statusPath) return current;
  const remaining = Math.max(1, deadline - Date.now());
  const reusable = reuseCurrentPage && ["ready", "success", "already_done", "profile_only", "manual_required"].includes(current.status);
  const refreshed = await pageMessage(tab.id, {type: "inspect", fresh: true, dataOnly, reuseCurrentPage: reusable, skipDetails, timeoutMs: Math.max(1, remaining - 250)}, remaining + 1000);
  if (refreshed.status === "error" && ["success", "already_done"].includes(current.status)) return {...current, message: `${current.message}；账号数据刷新失败，已保留旧数据`};
  if (!dataOnly && ["success", "already_done"].includes(current.status) && ["ready", "unknown"].includes(refreshed.status)) return {...refreshed, status: current.status, message: current.message};
  if (refreshed.status === "ready" && confirmedPersistentForm(await readState(siteId), siteId)) return {...refreshed, status: "already_done", confirmedDay: today(), message: "今日已有已确认签到记录，不重复提交"};
  return refreshed;
}

async function run(tab, automatic = false, attemptDeadline = null, siteId = sites.resolve(tab.url)?.id || "piggo", reuseCurrentPage = false) {
  const state = await readState(siteId);
  const configured = state.sites[siteId];
  const page = adapter(siteId, tab.url);
  if (!configured.enabled) return {siteId, status: "disabled", message: `${sites.get(siteId).name} 已停用`};
  if (automatic && (!state.autoEnabled || (!configured.refreshOnly && state.verifiedDay === today()))) return null;
  const deadline = attemptDeadline || Date.now() + configured.timeout * 1000;
  if (Date.now() >= deadline) return save(page.result("error", tab.url), tab.id, false, siteId);
  const snapshot = await freshPage(tab, (deadline - Date.now()) / 1000, reuseCurrentPage, true);
  if (snapshot.status !== "ready") return save(snapshot, tab.id, true, siteId);
  const current = await readState(siteId);
  if (!current.sites[siteId].enabled) return {siteId, status: "disabled", message: `${sites.get(siteId).name} 已停用`};
  if (automatic && !current.autoEnabled) return null;
  if (configured.refreshOnly || current.sites[siteId].refreshOnly) return save(snapshot, tab.id, true, siteId);
  if (unresolvedSubmission(current)) return confirmationFailure(tab, siteId, "先前提交未取得成功证据，本次只读核验仍未发现完成标记", snapshot);
  if (Date.now() >= deadline) return save(page.result("error", tab.url), tab.id, false, siteId);
  if (state.operation && Date.now() - state.operation.startedAt < (state.operation.timeout || configured.timeout) * 1000) return {...page.result("pending", tab.url), siteId};
  const operationId = Date.now();
  await chrome.storage.local.set({[sites.key("operation", siteId)]: {tabId: tab.id, startedAt: operationId, day: today(), timeout: configured.timeout, deadline, automatic, phase: "preparing", awaitingConfirmation: true}});
  await save({...page.result("pending", tab.url), profile: snapshot.profile}, tab.id, true, siteId);
  try {
    const remaining = Math.max(1, deadline - Date.now());
    const result = await pageMessage(tab.id, {type: "signin", operationId, timeoutMs: Math.max(1, remaining - 100)}, remaining);
    if (result.status !== "pending") {
      if (result.status !== "error") await chrome.storage.local.set({[sites.key("operation", siteId)]: {...(await readState(siteId)).operation, awaitingConfirmation: false}});
      if (result.status === "error") return confirmationFailure(tab, siteId, result.message || "提交响应异常，未取得成功证据", result);
      return save(result, tab.id, true, siteId);
    }
  } catch {}
  const {lastResult} = await readState(siteId);
  if (lastResult?.tabId === tab.id && ["success", "already_done", "blocked", "debugging", "login_required", "manual_required"].includes(lastResult.status)) return lastResult;
  return save(page.result("pending", tab.url), tab.id, true, siteId);
}

async function inspectSite(siteId, background = false) {
  const state = await readState(siteId);
  const site = sites.get(siteId);
  if (!state.sites[siteId].enabled) return {siteId, status: "disabled", message: `${site.name} 已停用`};
  if (state.lastResult?.status === "pending" || unresolvedSubmission(state)) return refreshSite(siteId);
  if (background) return refreshSite(siteId);
  const tab = await selectTab(siteId);
  if (!tab) {
    if (state.lastResult?.status === "no_tab" && state.verifiedDay === today()) {
      const restored = {...state.lastResult, status: "already_done", confirmedDay: state.verifiedDay, message: "今日已有已确认签到记录，站点页面未打开"};
      if (new Date(restored.time).toDateString() !== new Date().toDateString()) delete restored.time;
      return save(restored, state.lastResult.tabId, true, siteId);
    }
    if (state.lastResult) return state.lastResult;
    return save({status: "no_tab", message: `先打开 ${site.name} 并登录`}, undefined, false, siteId);
  }
  try { return save(await freshPage(tab, state.sites[siteId].timeout), tab.id, true, siteId); }
  catch { return save(adapter(siteId, tab.url).result("error", tab.url), tab.id, false, siteId); }
}

async function handle(message, sender) {
  if (["captcha-open", "captcha-recognize", "captcha-submit"].includes(message.type)) return captchaOcr.handle(message, sender);
  if (message.type === "periodic-permit") return periodic.permit(message, sender);
  if (message.type?.startsWith("periodic-")) {
    if (sender.url?.split("#")[0] !== chrome.runtime.getURL("dashboard.html")) return {error: "消息来源不是 NetSurf 操作界面"};
    if (message.type === "periodic-list") return periodic.read();
    if (message.type === "periodic-settings") return periodic.save(message.taskId, message.config);
    if (message.type === "periodic-open") return periodic.open(message.taskId);
    if (message.type === "periodic-inspect" || message.type === "periodic-run") return periodic.run(message.taskId, message.type === "periodic-run" ? "run" : "inspect");
    return {error: "未知定时任务操作"};
  }
  if (message.type === "submission-stage" || message.type === "navigate-attendance") {
    const site = sites.resolve(sender.url);
    const navigation = message.type === "navigate-attendance";
    if (!site || !sender.tab || !(navigation ? NetSurfRules.get(site.origin)?.nativeAttendanceNavigation : NetSurfRules.get(site.origin)?.continueAttendanceForm || NetSurfRules.get(site.origin)?.modalAttendance)) return {accepted: false};
    const next = (resultQueues.get(site.id) || Promise.resolve()).catch(() => {}).then(async () => {
      if (!await chrome.permissions.contains({origins: sites.origins(site)})) return {accepted: false};
      const state = await readState(site.id);
      const operation = state.operation;
      const senderUrl = new URL(sender.url);
      const onAttendance = NetSurfRules.get(site.origin)?.modalAttendance
        ? ["/", "/index.php"].includes(senderUrl.pathname) && !senderUrl.search && !senderUrl.hash
        : senderUrl.pathname === site.signinPath;
      if (!state.sites[site.id].enabled || state.sites[site.id].refreshOnly || operation?.automatic && !state.autoEnabled || operation?.tabId !== sender.tab.id || operation.day !== today() || operation.startedAt !== message.operationId || operation.awaitingConfirmation !== true || !(Date.now() < operation.deadline)) return {accepted: false};
      if (navigation) {
        if (operation.phase !== "preparing" || onAttendance || message.url !== new URL(site.signinPath, new URL(sender.url).origin).href) return {accepted: false};
        await chrome.storage.local.set({[sites.key("operation", site.id)]: {...operation, phase: NetSurfRules.get(site.origin)?.continueAttendanceForm ? "entry" : "submitted"}});
        await chrome.tabs.update(sender.tab.id, {url: message.url});
        return {accepted: true};
      }
      if (NetSurfRules.get(site.origin)?.modalAttendance && (message.stage !== "submitted" || operation.phase !== "preparing")) return {accepted: false};
      if (!(message.stage === "entry" && !onAttendance && operation.phase === "preparing" || message.stage === "submitted" && onAttendance && ["preparing", "continuing"].includes(operation.phase))) return {accepted: false};
      await chrome.storage.local.set({[sites.key("operation", site.id)]: {...operation, phase: message.stage}});
      return {accepted: true};
    });
    resultQueues.set(site.id, next);
    return next;
  }
  if (message.type === "observed" || message.type === "auto") {
    const site = sites.resolve(sender.url);
    if (!sender.tab || !site) return null;
    if (message.type === "auto") {
      if (!(await chrome.tabs.query({url: sites.origins(site)})).some(tab => tab.id === sender.tab.id)) return null;
      await scheduledRun(sender.tab, false, site.id);
      return null;
    }
    const page = adapter(site.id, sender.url);
    const status = message.result?.status;
    if (!Object.hasOwn(page.labels, status)) return null;
    const current = await readState(site.id);
    if (status === "blocked" && message.result?.challengePending === true && NetSurfRules.get(site.origin)?.waitForSecurityChallenge) return current.lastResult;
    if (current.lastResult?.confirmationFailed && !["success", "already_done", "blocked", "debugging", "login_required", "manual_required"].includes(status)) return current.lastResult;
    const {operation} = current;
    const verified = operation?.tabId === sender.tab.id && operation.day === today() && Date.now() - operation.startedAt < (operation.timeout || 60) * 1000;
    if (!verified && current.lastResult?.verified && ["ready", "unknown", "already_done", "success"].includes(status)) return current.lastResult;
    const observed = page.result(status, sender.url);
    if (status === "blocked" && message.result?.message === "无法连接人机验证服务，请稍后在站点重试验证") observed.message = message.result.message;
    return save(observed, sender.tab.id, verified, site.id);
  }
  if (sender.url?.split("#")[0] !== chrome.runtime.getURL("dashboard.html")) return {status: "error", message: "消息来源不是 NetSurf 操作界面"};
  const siteId = message.siteId || "piggo";
  const site = sites.get(siteId);
  if (!site) return {error: "未知 PT 站点"};
  if (message.type === "open") {
    const tab = await selectTab(siteId);
    const state = await readState(siteId);
    const statusPath = adapter(siteId, tab?.url).statusPath;
    const targetUrl = statusPath && state.lastResult?.status === "manual_required" ? `${tab ? new URL(tab.url).origin : site.origin}${statusPath}` : null;
    if (tab) {
      const {taskTab} = await chrome.storage.session.get("taskTab");
      if (taskTab?.tabId === tab.id) await chrome.storage.session.remove("taskTab");
      await chrome.tabs.update(tab.id, {active: true, ...(targetUrl ? {url: targetUrl} : {})});
      await chrome.windows.update(tab.windowId, {focused: true});
    } else await chrome.tabs.create({url: targetUrl || `${site.origin}/`});
    return {opened: true};
  }
  if (message.type === "inspect-all" || message.type === "run-all") {
    const state = await readState();
    const enabled = sites.catalog.filter(item => state.sites[item.id].enabled);
    const results = [];
    let skipped = 0;
    if (message.background || message.type === "run-all") {
      for (const item of enabled) {
        const current = await readState(item.id);
        const signin = message.type === "run-all";
        const cached = current.lastResult;
        const signedIn = current.verifiedDay === today() || cached?.verified && ["success", "already_done"].includes(cached.status) && sites.day(new Date(cached.time)) === today();
        const refreshed = current.refreshedDay === today() || cached?.verified && ["ready", "success", "already_done", "profile_only", "refreshed", "unknown"].includes(cached.status) && Object.values(sites.profile(cached.profile)).some(Boolean) && sites.day(new Date(cached.profileTime || cached.time)) === today();
        if (!current.sites[item.id].enabled || (signin ? signedIn || item.mode === "profile" || current.sites[item.id].refreshOnly || cached?.status === "profile_only" : refreshed)) {
          skipped += 1;
          continue;
        }
        await chrome.storage.local.set({inspection: {current: item.name, siteId: item.id, completed: results.length + skipped, total: enabled.length, running: true}});
        results.push([item.id, signin ? await batchSignIn(item.id) : await inspectSite(item.id, true)]);
      }
      await chrome.storage.local.set({inspection: {completed: results.length + skipped, total: enabled.length, running: false}});
    } else {
      const pending = [];
      const ordinary = [];
      for (const item of enabled) {
        const current = await readState(item.id);
        (current.lastResult?.status === "pending" || unresolvedSubmission(current) ? pending : ordinary).push(item);
      }
      results.push(...await Promise.all(ordinary.map(async item => [item.id, await inspectSite(item.id)])));
      for (const item of pending) results.push([item.id, await inspectSite(item.id)]);
    }
    return {results: Object.fromEntries(results), skipped};
  }
  if (message.type === "inspect") return recordActivity("inspect", await inspectSite(siteId, message.background === true));
  if (message.type === "run") {
    const state = await readState(siteId);
    if (!state.sites[siteId].enabled) return {siteId, status: "disabled", message: `${site.name} 已停用`};
    if (state.sites[siteId].refreshOnly || site.mode === "profile") return recordActivity("refresh", await refreshSite(siteId));
    return batchSignIn(siteId);
  }
  if (message.type === "settings") {
    await chrome.storage.local.set({autoEnabled: message.enabled === true});
    return finishSettingsSave({enabled: message.enabled === true});
  }
  if (message.type === "site-settings") {
    const state = await readState();
    const previous = state.sites[siteId];
    const configured = sites.config({...previous, ...state.scheduleConfig, ...Object.fromEntries(["enabled", "refreshOnly"].filter(field => Object.hasOwn(message.config || {}, field)).map(field => [field, message.config[field]]))});
    if (sites.refreshOnlyRequired(siteId)) configured.refreshOnly = true;
    if (configured.enabled && !await chrome.permissions.contains({origins: sites.origins(site)})) return {error: "请先允许访问该站点"};
    await chrome.storage.local.set({sites: {...state.sites, [siteId]: configured}, [sites.key("schedule", siteId)]: null});
    if (configured.refreshOnly && configured.enabled && (!previous.enabled || !previous.refreshOnly)) {
      actionQueue = actionQueue.catch(() => {}).then(() => withWorkerAlive(() => scheduledRun(null, false, siteId, true)));
      actionQueue.catch(() => {});
    }
    return finishSettingsSave({saved: true, siteId, config: configured});
  }
  if (message.type === "schedule-settings") {
    const configured = sites.settings({scheduleConfig: message.config}).scheduleConfig;
    const reset = Object.fromEntries(sites.catalog.map(item => [sites.key("schedule", item.id), null]));
    await chrome.storage.local.set({scheduleConfig: configured, ...reset});
    return finishSettingsSave({saved: true, scheduleConfig: configured});
  }
  if (message.type === "backup" || message.type === "restore") {
    if (!await chrome.permissions.contains({permissions: ["cookies"], origins: ["http://*/*", "https://*/*"]})) return {error: "需要允许访问所有网站 Cookie 才能备份或还原"};
    if (message.type === "backup") {
      const state = await chrome.storage.local.get(["autoEnabled", "sites", "scheduleConfig", "periodicTasks"]);
      return {backup: backup.create(state, await chrome.cookies.getAll({partitionKey: {}}))};
    }
    let validated;
    try { validated = backup.validate(message.backup); } catch (error) { return {error: error.message}; }
    const reset = Object.fromEntries(sites.catalog.flatMap(item => ["operation", "verifiedDay", "refreshedDay", "lastResult", "schedule"].map(field => [sites.key(field, item.id), null])));
    await chrome.storage.local.set({autoEnabled: false, ...reset});
    const previousPeriodic = await periodic.read();
    await chrome.storage.local.set({periodicTasks: Object.fromEntries(Object.entries(previousPeriodic.tasks).map(([taskId, configured]) => [taskId, {...configured, enabled: false}]))});
    await periodic.resume();
    await clearSchedules();
    let restored = 0;
    let expired = 0;
    let failed = 0;
    for (const cookie of validated.cookies) {
      if (cookie.expired) { expired += 1; continue; }
      try { if (await chrome.cookies.set(cookie.details)) restored += 1; else failed += 1; }
      catch { failed += 1; }
    }
    if (failed) return {error: `还原未完成：${restored} 条 Cookie 已恢复，${expired} 条已过期，${failed} 条失败。自动签到已关闭，设置未覆盖。`};
    await chrome.storage.local.set(validated.settings);
    await periodic.resume();
    await reschedule();
    return {restored, expired, settings: validated.settings};
  }
  return null;
}

async function finishSettingsSave(response) {
  try { await reschedule(); }
  catch (error) { response.warning = "签到计划更新失败：" + (error.message || "请重新加载 NetSurf"); }
  return response;
}

function alarmName(type, siteId) { return `netsurf-${type}${siteId === "piggo" ? "" : `:${siteId}`}`; }

async function clearSchedules() {
  for (const alarm of await chrome.alarms.getAll()) if (alarm.name.startsWith("netsurf-") && !alarm.name.startsWith("netsurf-periodic:")) await chrome.alarms.clear(alarm.name);
}

async function syncScripts(state) {
  await syncProfileObserver(state);
  const matches = [];
  for (const site of sites.catalog) {
    if (!state.sites[site.id].enabled || site.id === "piggo") continue;
    if (await chrome.permissions.contains({origins: sites.origins(site)})) matches.push(...sites.origins(site));
  }
  const registered = await chrome.scripting.getRegisteredContentScripts({ids: ["netsurf-pt"]});
  const files = ["catalog.js", "site-rules.js", "sites.js", "profile-api.js", "hdsky.js", "opencd.js", "ptsbao.js", "freefarm.js", "pt52.js", "piggo.js", "content.js"];
  if (registered.length && JSON.stringify([...registered[0].matches].sort()) === JSON.stringify([...new Set(matches)].sort()) && JSON.stringify(registered[0].js) === JSON.stringify(files)) return;
  if (registered.length) await chrome.scripting.unregisterContentScripts({ids: ["netsurf-pt"]});
  if (matches.length) await chrome.scripting.registerContentScripts([{id: "netsurf-pt", matches: [...new Set(matches)], js: files, runAt: "document_idle"}]);
}

async function syncProfileObserver(state) {
  const mteam = sites.get("kp.m-team.cc");
  const mteamEnabled = state.sites[mteam.id].enabled && await chrome.permissions.contains({origins: sites.origins(mteam)});
  const mteamScripts = await chrome.scripting.getRegisteredContentScripts({ids: ["netsurf-mteam-profile"]});
  if (mteamScripts.length) await chrome.scripting.unregisterContentScripts({ids: ["netsurf-mteam-profile"]});
  if (mteamEnabled) await chrome.scripting.registerContentScripts([{id: "netsurf-mteam-profile", matches: sites.origins(mteam), js: ["zhuque-observer.js"], runAt: "document_start", world: "MAIN"}]);
  const site = sites.get("zhuque.in");
  const enabled = state.sites[site.id].enabled && await chrome.permissions.contains({origins: sites.origins(site)});
  const registered = await chrome.scripting.getRegisteredContentScripts({ids: ["netsurf-zhuque-profile"]});
  if (enabled && registered.length && registered[0].world === "MAIN" && JSON.stringify(registered[0].js) === JSON.stringify(["zhuque-observer.js"])) return;
  if (registered.length) await chrome.scripting.unregisterContentScripts({ids: ["netsurf-zhuque-profile"]});
  if (enabled) await chrome.scripting.registerContentScripts([{id: "netsurf-zhuque-profile", matches: sites.origins(site), js: ["zhuque-observer.js"], runAt: "document_start", world: "MAIN"}]);
}

function reschedule() {
  scheduleQueue = scheduleQueue.catch(() => {}).then(rebuildSchedule);
  return scheduleQueue;
}

async function rebuildSchedule() {
  const initial = await readState();
  await syncScripts(initial);
  if (!initial.autoEnabled) return clearSchedules();
  for (const site of sites.catalog) {
    const configured = initial.sites[site.id];
    if (!configured.enabled) {
      for (const type of ["daily", "retry", "verify"]) await chrome.alarms.clear(alarmName(type, site.id));
      continue;
    }
    const state = await readState(site.id);
    await chrome.alarms.create(alarmName("daily", site.id), {when: sites.nextStart(configured, {...state, verifiedDay: configured.refreshOnly ? null : state.verifiedDay})});
    for (const [type, field] of [["retry", "retryAt"], ["verify", "verifyAt"]]) {
      const name = alarmName(type, site.id);
      if (!state.lastResult?.confirmationFailed && (type !== "retry" || !unresolvedSubmission(state)) && state.schedule?.day === today() && (configured.refreshOnly || state.verifiedDay !== today()) && Number.isFinite(state.schedule[field])) await chrome.alarms.create(name, {when: Math.max(Date.now() + 1000, state.schedule[field])});
      else await chrome.alarms.clear(name);
    }
  }
}

async function closeTaskTab() {
  const {taskTab} = await chrome.storage.session.get("taskTab");
  if (!taskTab) return;
  try { await chrome.tabs.remove(taskTab.tabId); }
  catch (error) {
    if ((await chrome.tabs.query({})).some(tab => tab.id === taskTab.tabId)) throw error;
  }
  await chrome.storage.session.remove("taskTab");
  const state = await readState(taskTab.siteId);
  if (state.schedule?.verifyAt) {
    await chrome.storage.local.set({[sites.key("schedule", taskTab.siteId)]: {...state.schedule, verifyAt: null}});
    await chrome.alarms.clear(alarmName("verify", taskTab.siteId));
  }
}

async function waitForPage(tab, deadline, siteId, requireReady = true) {
  while (Date.now() < deadline) {
    try {
      const matching = await chrome.tabs.query({url: sites.origins(sites.get(siteId))});
      if (!matching.some(current => current.id === tab.id)) {
        await new Promise(resolve => setTimeout(resolve, 100));
        continue;
      }
      await ensureContent(tab, siteId, Math.max(1, Math.min(1000, deadline - Date.now())));
      const current = await pageMessage(tab.id, {type: "inspect"}, Math.max(1, Math.min(1000, deadline - Date.now())));
      if (current.challengePending && NetSurfRules.get(sites.get(siteId).origin)?.waitForSecurityChallenge) {
        await new Promise(resolve => setTimeout(resolve, Math.min(250, Math.max(0, deadline - Date.now()))));
        continue;
      }
      if (NetSurfRules.get(sites.get(siteId).origin)?.refreshInNewPage && current.status === "unknown" && !current.hasProfile) {
        await new Promise(resolve => setTimeout(resolve, 100));
        continue;
      }
      if (current.path && (!requireReady || current.pageReady !== false || NetSurfRules.get(sites.get(siteId).origin)?.signinBeforeLoadComplete && current.status === "ready" && current.hasProfile)) return;
      await new Promise(resolve => setTimeout(resolve, 100));
    } catch { await new Promise(resolve => setTimeout(resolve, 100)); }
  }
  throw new Error("站点加载超时");
}

async function navigateTaskPage(tab, deadline, siteId, requireReady = true) {
  const site = sites.get(siteId);
  const url = `${site.origin}${site.homePath}`;
  const attempts = adapter(siteId, url).navigationRetries + 1;
  let failure;
  for (let attempt = 0; attempt < attempts && Date.now() < deadline; attempt += 1) {
    await chrome.tabs.update(tab.id, {url});
    tab = {...tab, url};
    const remaining = deadline - Date.now();
    const attemptDeadline = attempt + 1 < attempts ? deadline - Math.max(1, Math.floor(remaining / 4)) : deadline;
    try {
      await waitForPage(tab, attemptDeadline, siteId, requireReady);
      return tab;
    } catch (error) {
      failure = error;
    }
  }
  throw failure || new Error("站点加载超时");
}

async function refreshSite(siteId) {
  const state = await readState(siteId);
  if (!state.sites[siteId].enabled) return {siteId, status: "disabled", message: `${sites.get(siteId).name} 已停用`};
  const site = sites.get(siteId);
  await closeTaskTab();
  const deadline = Date.now() + state.sites[siteId].timeout * 1000;
  let tab = await selectTab(siteId);
  const attendancePage = tab && new URL(tab.url).pathname === new URL(site.signinPath, site.origin).pathname && new URL(site.signinPath, site.origin).pathname !== new URL(site.homePath, site.origin).pathname;
  const recoverAttendance = unresolvedSubmission(state) && attendancePage && !state.sites[siteId].refreshOnly;
  if (state.sites[siteId].refreshOnly && attendancePage || ["zhuque.in", "kp.m-team.cc"].includes(siteId) || NetSurfRules.get(site.origin)?.refreshInNewPage && !recoverAttendance) tab = undefined;
  let created = false;
  try {
    if (!await chrome.permissions.contains({origins: sites.origins(sites.get(siteId))})) throw new Error("未授予站点访问权限，请在站点管理重新启用");
    if (!tab) {
      tab = await chrome.tabs.create({url: "about:blank", active: false});
      created = true;
      await chrome.storage.session.set({taskTab: {tabId: tab.id, siteId, purpose: "refresh"}});
      tab = await navigateTaskPage(tab, deadline, siteId, false);
    }
    const current = await readState(siteId);
    if (!current.sites[siteId].enabled) return {siteId, status: "disabled", message: `${sites.get(siteId).name} 已停用`};
    if (Date.now() >= deadline) throw new Error("页面加载超时");
    const snapshot = await freshPage(tab, (deadline - Date.now()) / 1000, created);
    if (unresolvedSubmission(state) && ["ready", "unknown", "pending", "error"].includes(snapshot.status)) {
      if (snapshot.status !== "error") await save(snapshot, tab.id, true, siteId);
      return await confirmationFailure(tab, siteId, snapshot.status === "error" ? snapshot.message || "只读核验请求失败" : "只读核验未发现今日签到完成标记", snapshot);
    }
    return await save(snapshot, tab.id, true, siteId);
  } catch (error) {
    if (unresolvedSubmission(state)) return await confirmationFailure(tab, siteId, `只读核验失败：${error.message || "页面通信失败"}`);
    return await save({...adapter(siteId, tab?.url).result("error", tab?.url || sites.get(siteId).origin), message: `后台刷新失败：${error.message || "页面通信失败"}`}, tab?.id, false, siteId);
  } finally {
    if (created) await closeTaskTab();
  }
}

async function batchSignIn(siteId) {
  const state = await readState(siteId);
  if (unresolvedSubmission(state)) return recordActivity("run", await refreshSite(siteId));
  await closeTaskTab();
  let tab = await selectTab(siteId);
  if (NetSurfRules.get(sites.get(siteId).origin)?.refreshInNewPage) tab = undefined;
  let created = false;
  const deadline = Date.now() + state.sites[siteId].timeout * 1000;
  try {
    if (!await chrome.permissions.contains({origins: sites.origins(sites.get(siteId))})) throw new Error("未授予站点访问权限");
    if (!tab) {
      tab = await chrome.tabs.create({url: "about:blank", active: false});
      created = true;
      await chrome.storage.session.set({taskTab: {tabId: tab.id, siteId, purpose: "signin"}});
      tab = await navigateTaskPage(tab, deadline, siteId);
    }
    let result = await run(tab, false, deadline, siteId, created);
    if (result?.status === "pending") result = await confirmSubmission(tab, deadline, siteId, true);
    return await recordActivity("run", result);
  } catch (error) {
    if (unresolvedSubmission(await readState(siteId))) return await confirmationFailure(tab, siteId, `核验中断：${error.message || "页面通信失败"}`);
    return await save({...adapter(siteId, tab?.url).result("error", tab?.url || sites.get(siteId).origin), message: `签到检查失败：${error.message}`}, tab?.id, false, siteId);
  } finally {
    if (created) await closeTaskTab();
  }
}

async function confirmSubmission(tab, deadline, siteId, manual = false) {
  const confirmed = ["success", "already_done", "blocked", "debugging", "login_required", "manual_required"];
  let snapshot;
  let failureReason;
  let refreshTask;
  let refreshed;
  let challengeSnapshot;
  while (Date.now() < deadline) {
    const latest = await readState(siteId);
    if (latest.lastResult?.tabId === tab.id && latest.lastResult.verified && confirmed.includes(latest.lastResult.status)) return latest.lastResult;
    if ((!manual && !latest.autoEnabled) || !latest.sites[siteId].enabled) {
      failureReason = "任务已停止，未取得签到成功证据";
      break;
    }
    if (refreshed && !["ready", "pending", "error", "unknown"].includes(refreshed.status)) return save(refreshed, tab.id, true, siteId);
    if (!refreshTask) {
      refreshed = undefined;
      refreshTask = freshPage(tab, Math.max(1, deadline - Date.now()) / 1000, false, true).then(result => { snapshot = result; refreshed = result; }).catch(() => {}).finally(() => { refreshTask = null; });
    }
    try {
      const current = await pageMessage(tab.id, {type: "inspect"}, Math.max(1, Math.min(1000, deadline - Date.now())));
      challengeSnapshot = current.challengePending ? current : undefined;
      if (confirmed.includes(current.status) && !current.challengePending) return save(current, tab.id, true, siteId);
      if (NetSurfRules.get(sites.get(siteId).origin)?.continueAttendanceForm && latest.operation?.phase === "entry" && current.status === "ready" && current.path === sites.get(siteId).signinPath) {
        await chrome.storage.local.set({[sites.key("operation", siteId)]: {...latest.operation, phase: "continuing"}});
        const continued = await pageMessage(tab.id, {type: "signin", continuation: true, operationId: latest.operation.startedAt, timeoutMs: Math.max(1, deadline - Date.now())}, Math.max(1, deadline - Date.now()));
        if (confirmed.includes(continued.status)) return save(continued, tab.id, true, siteId);
        if (continued.status === "error") return confirmationFailure(tab, siteId, continued.message || "签到表单核验失败", continued);
      }
    } catch {}
    if (refreshed && !["ready", "pending", "error", "unknown"].includes(refreshed.status)) return save(refreshed, tab.id, true, siteId);
    if (Date.now() < deadline) await new Promise(resolve => setTimeout(resolve, Math.min(500, deadline - Date.now())));
  }
  const latest = await readState(siteId);
  if (latest.lastResult?.tabId === tab.id && latest.lastResult.verified && confirmed.includes(latest.lastResult.status)) return latest.lastResult;
  if (challengeSnapshot && NetSurfRules.get(sites.get(siteId).origin)?.waitForSecurityChallenge) return save({...challengeSnapshot, challengePending: false, message: "站点自动安全验证超时，请打开站点完成后刷新"}, tab.id, true, siteId);
  return confirmationFailure(tab, siteId, failureReason || (snapshot?.status === "error" ? snapshot.message || "核验请求失败" : undefined), snapshot);
}

async function scheduledRun(tab, retry, siteId = "piggo", refreshRequested = false) {
  await closeTaskTab();
  const state = await readState(siteId);
  const configured = state.sites[siteId];
  if (refreshRequested && !configured.refreshOnly) return;
  if ((!state.autoEnabled && !refreshRequested) || !configured.enabled || (!configured.refreshOnly && state.verifiedDay === today()) || (!refreshRequested && new Date() < sites.start(configured))) return;
  const count = state.schedule?.day === today() ? state.schedule.attempts : 0;
  if ((!retry && count > 0) || count >= configured.retryCount + 1) return;
  if (!configured.refreshOnly && unresolvedSubmission(state)) return;
  await chrome.storage.local.set({[sites.key("schedule", siteId)]: {day: today(), attempts: count + 1}});
  let result;
  let created = false;
  const deadline = Date.now() + configured.timeout * 1000;
  try {
    if (!tab) tab = await selectTab(siteId);
    if (NetSurfRules.get(sites.get(siteId).origin)?.refreshInNewPage) tab = undefined;
    if (!tab) {
      const site = sites.get(siteId);
      tab = await chrome.tabs.create({url: "about:blank", active: false});
      created = true;
      try { await chrome.storage.session.set({taskTab: {tabId: tab.id, siteId, purpose: configured.refreshOnly ? "refresh" : "signin"}}); }
      catch (error) { await chrome.tabs.remove(tab.id); throw error; }
      tab = await navigateTaskPage(tab, deadline, siteId, !(configured.refreshOnly || refreshRequested));
    }
    if (configured.refreshOnly || refreshRequested) {
      const current = await readState(siteId);
      if (current.sites[siteId].enabled && (refreshRequested || current.autoEnabled) && Date.now() < deadline) result = await save(await freshPage(tab, (deadline - Date.now()) / 1000, created), tab.id, true, siteId);
    } else result = await run(tab, true, deadline, siteId, created);
    if (result?.status === "pending") result = await confirmSubmission(tab, deadline, siteId);
  } catch {
    result = unresolvedSubmission(await readState(siteId)) ? await confirmationFailure(tab, siteId, "核验中断，未取得成功证据") : await save(adapter(siteId, tab?.url).result("error", tab?.url || sites.get(siteId).origin), tab?.id, false, siteId);
  }
  finally { if (created) await closeTaskTab(); }
  await recordActivity("auto", result);
  const latest = await readState(siteId);
  if (!latest.autoEnabled || !latest.sites[siteId].enabled) return;
  const schedule = {day: today(), attempts: count + 1};
  if (result?.status === "error" && !unresolvedSubmission(latest) && count < configured.retryCount) schedule.retryAt = Date.now() + configured.retryInterval * 1000;
  await chrome.storage.local.set({[sites.key("schedule", siteId)]: schedule});
  await reschedule();
}

async function alarmAction(alarm) {
  if (alarm.name.startsWith("netsurf-periodic:")) return periodic.alarm(alarm.name);
  const matched = /^netsurf-(daily|retry|verify)(?::(.+))?$/.exec(alarm.name);
  if (!matched) return;
  const siteId = matched[2] || "piggo";
  if (!sites.get(siteId)) return;
  if (matched[1] !== "verify") {
    await scheduledRun(null, matched[1] === "retry", siteId);
    return reschedule();
  }
  const state = await readState(siteId);
  if (!unresolvedSubmission(state) || state.lastResult?.confirmationFailed) return reschedule();
  if (state.sites[siteId].enabled) await refreshSite(siteId);
  else await confirmationFailure(null, siteId, "站点已停用，核验已停止");
  if (state.schedule) await chrome.storage.local.set({[sites.key("schedule", siteId)]: {day: state.schedule.day, attempts: state.schedule.attempts}});
  await reschedule();
}

chrome.alarms.onAlarm.addListener(alarm => {
  actionQueue = actionQueue.catch(() => {}).then(() => withWorkerAlive(() => alarmAction(alarm)));
  actionQueue.catch(() => {});
});
function resumeSchedule() {
  actionQueue = actionQueue.catch(() => {}).then(() => withWorkerAlive(async () => {
    await closeTaskTab();
    await periodic.resume();
    for (const site of sites.catalog) {
      const state = await readState(site.id);
      if (state.verifiedDay === today() && !state.sites[site.id].refreshOnly && ["error", "no_tab"].includes(state.lastResult?.status)) {
        await save(state.lastResult, state.lastResult.tabId, false, site.id);
        continue;
      }
      if (state.lastResult?.status !== "pending" && !unresolvedSubmission(state)) continue;
      if (state.lastResult?.confirmationFailed) continue;
      if (state.sites[site.id].enabled) await refreshSite(site.id);
      else await confirmationFailure(null, site.id, "站点已停用，核验已停止");
    }
    await reschedule();
  }));
  actionQueue.catch(() => {});
  return actionQueue;
}

async function installed(details) {
  if (details.reason === "update") {
    const url = chrome.runtime.getURL("dashboard.html");
    const contexts = await chrome.runtime.getContexts({contextTypes: ["TAB"]});
    const dashboardIds = new Set(contexts.filter(context => context.documentUrl?.split("#")[0] === url).map(context => context.tabId));
    for (const tab of await chrome.tabs.query({})) if (tab.url?.split("#")[0] === url) dashboardIds.add(tab.id);
    await Promise.allSettled([...dashboardIds].map(tabId => chrome.tabs.reload(tabId, {bypassCache: true})));
  }
  return resumeSchedule();
}

chrome.runtime.onInstalled.addListener(details => installed(details).catch(() => {}));
chrome.runtime.onStartup.addListener(resumeSchedule);

function enqueueAction(message, sender, respond) {
  actionQueue = actionQueue.catch(() => {}).then(() => withWorkerAlive(() => {
    if (message.type !== "restore") return handle(message, sender);
    settingsQueue = settingsQueue.catch(() => {}).then(() => handle(message, sender));
    return settingsQueue;
  }));
  actionQueue.then(respond).catch(() => respond({error: "操作失败，请检查权限或刷新相关站点"}));
}

chrome.runtime.onMessage.addListener((message, sender, respond) => {
  if (sender.id !== chrome.runtime.id) return;
  if (message.type === "netsurf-ocr-infer") return;
  if (["settings", "site-settings", "schedule-settings", "periodic-settings"].includes(message.type)) {
    settingsQueue = settingsQueue.catch(() => {}).then(() => withWorkerAlive(() => handle(message, sender)));
    settingsQueue.then(respond).catch(() => respond({error: "设置保存失败，请检查扩展权限并重新加载 NetSurf"}));
  } else if (["inspect", "inspect-all", "run", "run-all", "auto", "backup", "restore", "periodic-inspect", "periodic-run"].includes(message.type)) {
    if (message.type === "auto") {
      chrome.storage.session.get("taskTab").then(({taskTab}) => {
        if (taskTab?.tabId === sender.tab?.id) respond(null);
        else enqueueAction(message, sender, respond);
      }).catch(() => respond(null));
    } else enqueueAction(message, sender, respond);
  } else handle(message, sender).then(respond).catch(() => respond({error: "操作失败，请重试"}));
  return true;
});
