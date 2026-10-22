const sites = globalThis.NetSurfSites;
const element = id => document.getElementById(id);
let busy = false;
let settingsBusy = false;
let settingsLocked = false;
let requested = false;
let state = sites.settings();
let latestResult = null;
let results = {};
let configDirty = false;
let activeSiteId = null;
let activeOperation = null;

const routes = {
  overview: {group: "pt", label: "概览", description: "已启用站点的签到状态与账号数据。"},
  sites: {group: "pt", label: "站点管理", description: "设置共用签到计划，管理全部 PT 站点。"},
  periodic: {group: "periodic", label: "概览", description: "NodeSeek 与 InvitesFun 每日签到状态。"},
  "periodic-settings": {group: "periodic", label: "设置", description: "管理每日签到任务的启用状态。"},
  automation: {group: "settings", label: "常规", description: "管理自动签到和所有网站 Cookie 的备份。"},
  about: {group: "settings", label: "关于", description: "浏览器中的 PT 站点签到助手。"}
};

function navigate() {
  const key = window.location.hash.slice(1);
  const route = Object.hasOwn(routes, key) ? key : "overview";
  const current = routes[route];
  element("page-title").textContent = route === "automation" ? "设置" : current.label;
  element("page-description").textContent = current.description;
  element("secondary-nav").replaceChildren();
  for (const [name, item] of Object.entries(routes)) {
    if (item.group !== current.group) continue;
    const link = document.createElement("a");
    link.href = "#" + name;
    link.className = "secondary-link";
    link.textContent = item.label;
    if (name === route) link.setAttribute("aria-current", "page");
    element("secondary-nav").append(link);
  }
  for (const link of document.querySelectorAll(".nav-link")) {
    if (link.dataset.group === current.group) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
  for (const name of Object.keys(routes)) element("view-" + name).hidden = name !== route;
  element("feedback-region").hidden = current.group !== "pt";
  element("inspect").hidden = route !== "overview";
  element("run-all").hidden = route !== "overview";
}

function node(tag, text, id) {
  const item = document.createElement(tag);
  if (text !== undefined) item.textContent = text;
  if (id) item.id = id;
  return item;
}

function enabledSites() { return sites.catalog.filter(site => state.sites[site.id].enabled); }

function checkedToday(result) {
  return result?.verified === true && (result.confirmedDay ? result.confirmedDay === sites.day() : new Date(result.time).toDateString() === new Date().toDateString());
}

function completed(result) { return checkedToday(result) && ["success", "already_done"].includes(result.status); }

function refreshOnly(site) { return state.sites[site.id].refreshOnly || site.mode === "profile"; }

function refreshed(result) {
  return ["refreshed", "ready", "profile_only", "success", "already_done"].includes(result?.status) && Object.values(sites.profile(result?.profile)).some(Boolean);
}

function dailyCount(selected, matches) {
  return (selected.length === 0 || selected.some(site => checkedToday(results[site.id])) ? String(selected.filter(site => checkedToday(results[site.id]) && matches(results[site.id])).length) : "—") + " / " + selected.length;
}

function renderOverview() {
  const enabled = enabledSites();
  element("overview-body").replaceChildren();
  element("overview-empty").hidden = enabled.length > 0;
  element("enabled-count").textContent = String(enabled.length);
  const signInSites = enabled.filter(site => !refreshOnly(site));
  const refreshSites = enabled.filter(refreshOnly);
  element("completed-count").textContent = dailyCount(signInSites, completed);
  element("refresh-count").textContent = dailyCount(refreshSites, refreshed);
  element("refresh-summary").hidden = refreshSites.length === 0;
  const labels = {ready: "待签到", success: "已完成", already_done: "已完成", profile_only: "无需签到", blocked: "需验证", debugging: "需验证", login_required: "需登录", manual_required: "需处理", pending: "核验中", no_tab: "未打开", disabled: "已停用", error: "检查失败", unknown: "未识别", ambiguous: "需处理"};
  for (const site of enabled) {
    const result = results[site.id];
    const refreshResult = result?.status === "refreshed" || refreshOnly(site) && refreshed(result);
    const working = busy && activeSiteId === site.id;
    const suffix = site.id === "piggo" ? "" : "-" + site.id;
    const row = node("tr", undefined, site.id === "piggo" ? "piggo-row" : "row-" + site.id);
    row.dataset.siteId = site.id;
    const name = node("td");
    name.append(node("strong", site.name), node("small", new URL(site.origin).hostname));
    row.append(name);
    const badge = node("span", working ? activeOperation === "run" || activeOperation === "run-all" ? "签到中" : "刷新中" : refreshResult ? checkedToday(result) && refreshed(result) ? "已刷新" : "待刷新" : completed(result) ? "已完成" : ["success", "already_done"].includes(result?.status) ? "待核验" : result?.confirmationFailed ? "签到失败" : labels[result?.status] || "待检查", "site-status" + suffix);
    badge.setAttribute("title", working ? "正在后台访问站点，弱网环境可能需要更长时间" : result?.message || "尚未检查");
    badge.className = "status-badge";
    badge.dataset.tone = (refreshResult ? refreshed(result) && checkedToday(result) : completed(result)) ? "success" : ["error", "blocked", "debugging", "login_required", "manual_required"].includes(result?.status) ? "warning" : "neutral";
    const status = node("td");
    status.append(badge);
    row.append(status);
    const profile = sites.profile(result?.profile);
    for (const field of sites.profileFields) row.append(node("td", profile[field] || "—", "profile-" + field + suffix));
    const timestamp = new Date(result?.profileTime || result?.time);
    row.append(node("td", Number.isNaN(timestamp.getTime()) ? "—" : timestamp.toLocaleString("zh-CN", {month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit"}), "checked" + suffix));
    const actions = node("td");
    const group = node("div");
    group.className = "site-actions";
    for (const [type, text] of [["open", "打开"], ...(!refreshOnly(site) ? [["refresh", "刷新"]] : []), ["run", refreshOnly(site) ? "刷新" : "签到"]]) {
      const button = node("button", text, type + suffix);
      button.className = "button " + (type === "run" ? "primary" : "secondary");
      button.disabled = busy || settingsBusy;
      button.addEventListener("click", () => type === "refresh" ? request("inspect", {siteId: site.id, background: true}) : request(type, {siteId: site.id}));
      group.append(button);
    }
    actions.append(group);
    row.append(actions);
    element("overview-body").append(row);
  }
  renderInspection();
}

function renderInspection() {
  element("inspection-body").replaceChildren();
  for (const site of enabledSites()) {
    const result = results[site.id];
    const row = node("tr");
    const details = result?.diagnostic;
    const reason = [result?.message || "尚未检查", details ? `HTTP ${details.httpStatus} ${details.path}；${details.accountFound ? "已定位本人资料" : "未定位本人资料"}` : "", details?.entries?.length ? "入口：" + details.entries.map(entry => entry.label + " " + entry.path).join("；") : "", ...(details?.auxiliary || []).map(item => `${item.label} ${item.path}：${item.error || "HTTP " + item.httpStatus}`)].filter(Boolean).join("；");
    row.append(node("td", site.name), node("td", element("site-status" + (site.id === "piggo" ? "" : "-" + site.id)).textContent), node("td", reason));
    const action = node("td");
    const inspect = node("button", "重新检查", "inspect-" + site.id);
    inspect.className = "secondary";
    inspect.disabled = busy || settingsBusy;
    inspect.addEventListener("click", () => request("inspect", {siteId: site.id, background: true}));
    action.append(inspect);
    row.append(action);
    element("inspection-body").append(row);
  }
}

function renderSites() {
  element("site-list").replaceChildren();
  const query = element("site-search").value.trim().toLowerCase();
  const selected = sites.catalog.filter(site => (site.name + " " + site.origin).toLowerCase().includes(query));
  element("catalog-count").textContent = "共 " + sites.catalog.length + " 个站点 · 已启用 " + enabledSites().length;
  element("site-list-empty").hidden = selected.length > 0;
  for (const site of selected) {
    const row = node("tr");
    row.dataset.siteId = site.id;
    row.append(node("td", site.name), node("td", new URL(site.origin).hostname));
    for (const [field, id, label] of [["enabled", site.id === "piggo" ? "site-enabled" : "enabled-" + site.id, "启用 "], ["refreshOnly", "refresh-only-" + site.id, "仅刷新 "]]) {
      const cell = node("td");
      const toggle = node("input", undefined, id);
      toggle.type = "checkbox";
      toggle.className = "switch";
      toggle.checked = state.sites[site.id][field] === true;
      const fixed = field === "refreshOnly" && sites.refreshOnlyRequired(site.id);
      toggle.dataset.fixed = fixed ? "true" : "false";
      toggle.disabled = fixed || settingsBusy || settingsLocked;
      toggle.setAttribute("role", "switch");
      toggle.setAttribute("aria-label", label + site.name);
      toggle.addEventListener("change", () => request("site-settings", {siteId: site.id, config: {[field]: toggle.checked}}));
      cell.append(toggle);
      if (fixed) cell.append(node("small", "内置仅刷新"));
      row.append(cell);
    }
    const actions = node("td");
    const open = node("button", "打开站点");
    open.className = "button secondary";
    open.disabled = busy || settingsBusy;
    open.addEventListener("click", () => request("open", {siteId: site.id}));
    actions.append(open);
    row.append(actions);
    element("site-list").append(row);
  }
}

function showConfig() {
  element("auto").checked = state.autoEnabled;
  element("auto-mode").textContent = state.autoEnabled ? "已开启" : "未开启";
  if (!configDirty) {
    for (const [id, field] of [["start-time", "startTime"], ["retry-interval", "retryInterval"], ["retry-count", "retryCount"], ["timeout", "timeout"]]) element(id).value = state.scheduleConfig[field];
  }
  renderSites();
  renderOverview();
}

function displayFeedback(result) {
  element("status").textContent = result?.message || "打开站点并登录后刷新数据";
  const timestamp = new Date(result?.time);
  element("time").textContent = Number.isNaN(timestamp.getTime()) ? "尚无新的检查结果" : "检查时间：" + timestamp.toLocaleString("zh-CN");
}

function display(result, siteId = "piggo") {
  if (result?.status) {
    const currentSite = result.siteId || siteId;
    results[currentSite] = {...result, profile: {...sites.profile(results[currentSite]?.profile), ...Object.fromEntries(Object.entries(sites.profile(result.profile)).filter(([, value]) => value))}};
  }
  latestResult = result;
  displayFeedback(result);
  renderOverview();
}

async function send(type, extra = {}, milliseconds = 20000) {
  let timeout;
  try {
    const result = await Promise.race([
      chrome.runtime.sendMessage({type, ...extra}),
      new Promise((resolve, reject) => { timeout = setTimeout(() => reject(new Error("插件通信失败或超时，请重新加载 NetSurf 并刷新相关站点")), milliseconds); })
    ]);
    if (!result) throw new Error("插件通信失败或超时");
    if (result.error) throw new Error(result.error);
    return result;
  } finally { clearTimeout(timeout); }
}

function setBusy(value) {
  busy = value;
  updateControls();
}

function setSettingsBusy(value) {
  settingsBusy = value;
  updateControls();
}

function updateControls() {
  for (const button of document.querySelectorAll("button")) if (!button.closest?.("#view-periodic, #view-periodic-settings")) button.disabled = busy || settingsBusy;
  for (const toggle of document.querySelectorAll("input[type=checkbox]")) if (!toggle.closest?.("#view-periodic, #view-periodic-settings")) toggle.disabled = toggle.dataset.fixed === "true" || settingsBusy || settingsLocked;
  element("auto").disabled = settingsBusy || settingsLocked;
  element("save-site").disabled = settingsBusy || settingsLocked;
}

async function request(type, extra = {}, showProgress = true) {
  const setting = ["settings", "site-settings", "schedule-settings"].includes(type);
  if (setting ? settingsBusy || settingsLocked : busy || settingsBusy) return;
  requested = true;
  if (setting) setSettingsBusy(true);
  else setBusy(true);
  const siteId = extra.siteId || "piggo";
  const site = sites.get(siteId);
  if (showProgress && !setting && type !== "open") {
    activeSiteId = ["inspect-all", "run-all"].includes(type) ? null : siteId;
    activeOperation = type === "run" && (state.sites[siteId].refreshOnly || site.mode === "profile") ? "inspect" : type;
    renderOverview();
  }
  const feedback = element(type === "site-settings" ? "site-toggle-status" : type === "schedule-settings" ? "site-settings-status" : "settings-status");
  if (setting) feedback.textContent = "正在保存设置…";
  else element("status").textContent = type === "open" ? "正在打开 / 切换 " + site.name + "…" : type === "run-all" || type === "run" && !state.sites[siteId].refreshOnly && site.mode !== "profile" ? "正在刷新今日状态并尝试签到…" : "正在刷新并检查今日状态…";
  try {
    if (type === "site-settings" && extra.config.enabled) {
      if (!await chrome.permissions.request({origins: sites.origins(site)})) throw new Error("未授权站点访问，启用已取消");
    }
    const result = await send(type, extra, Math.max(20000, state.scheduleConfig.timeout * 1000 * (type === "run-all" || type === "inspect-all" && extra.background ? enabledSites().length : 1) + 10000));
    if (type === "settings") {
      if (typeof result.enabled !== "boolean") throw new Error("后台设置响应不兼容，请在扩展管理页重新加载 NetSurf");
      state.autoEnabled = result.enabled;
      feedback.textContent = (result.enabled ? "已保存：自动签到已开启" : "已保存：自动签到已关闭") + (result.warning ? "；" + result.warning : "");
    } else if (type === "site-settings") {
      if (!result.saved) throw new Error("站点设置保存失败");
      state.sites[siteId] = sites.config({...state.sites[siteId], ...result.config});
      feedback.textContent = site.name + (Object.hasOwn(extra.config, "refreshOnly") ? (result.config.refreshOnly ? " 仅刷新已开启" : " 仅刷新已关闭") : (result.config.enabled ? " 已启用" : " 已停用")) + (result.warning ? "；" + result.warning : "");
    } else if (type === "schedule-settings") {
      if (!result.saved) throw new Error("签到设置保存失败");
      state = sites.settings({...state, scheduleConfig: result.scheduleConfig});
      configDirty = false;
      feedback.textContent = "签到设置已保存，所有站点共用" + (result.warning ? "；" + result.warning : "");
    } else if (type === "open" && result.opened) displayFeedback({message: "已切换到 " + site.name});
    else if (result.results) {
      results = {...results, ...result.results};
      latestResult = {message: (type === "run-all" ? "已检查签到 " : "已检查刷新 ") + Object.keys(result.results).length + " 个启用站点" + (result.skipped ? "，已跳过 " + result.skipped + " 个站点" : "")};
      displayFeedback(latestResult);
    } else display(result, siteId);
  } catch (error) {
    if (setting) feedback.textContent = type === "settings" ? "设置保存失败：" + error.message : error.message;
    else displayFeedback({message: error.message + "；若刚尝试签到，请先确认网页结果。"});
  } finally {
    if (setting) setSettingsBusy(false);
    else {
      activeSiteId = null;
      activeOperation = null;
      setBusy(false);
    }
    showConfig();
  }
}

function refresh(background = false, showProgress = true) {
  const enabled = enabledSites();
  return !background && enabled.length === 1 ? request("inspect", {siteId: enabled[0].id, background}, showProgress) : request("inspect-all", {background}, showProgress);
}

element("run-all").addEventListener("click", () => request("run-all"));

async function allowCookies() {
  const granted = await chrome.permissions.request({permissions: ["cookies"], origins: ["http://*/*", "https://*/*"]});
  if (!granted) throw new Error("未授权 Cookie 访问，操作已取消");
}

async function exportBackup() {
  if (busy || settingsBusy) return;
  setBusy(true);
  element("backup-status").textContent = "正在备份…";
  try {
    await allowCookies();
    const result = await send("backup");
    if (!result.backup) throw new Error("备份失败，请重试");
    const url = URL.createObjectURL(new Blob([JSON.stringify(result.backup, null, 2)], {type: "application/json"}));
    const link = document.createElement("a");
    link.href = url;
    link.download = `netsurf-backup-${new Date().toISOString().replace(/[:.]/g, "-")}.json`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
    element("backup-status").textContent = `备份已下载，包含设置和所有网站的 ${result.backup.cookies.length} 条 Cookie`;
  } catch (error) { element("backup-status").textContent = error.message; }
  finally { setBusy(false); }
}

async function chooseRestore() {
  if (busy || settingsBusy) return;
  try {
    await allowCookies();
    element("restore-file").value = "";
    element("restore-file").click();
  } catch (error) { element("backup-status").textContent = error.message; }
}

async function importBackup() {
  const file = element("restore-file").files?.[0];
  if (!file || busy || settingsBusy) return;
  requested = true;
  settingsLocked = true;
  setBusy(true);
  element("backup-status").textContent = "正在还原…";
  try {
    if (file.size > 10 * 1024 * 1024) throw new Error("备份文件不能超过 10 MB");
    let backup;
    try { backup = JSON.parse(await file.text()); } catch { throw new Error("文件不是有效的 JSON 备份"); }
    const result = await send("restore", {backup}, 120000);
    if (!result.settings) throw new Error("还原失败，请重试");
    state = sites.settings(result.settings);
    configDirty = false;
    latestResult = null;
    results = {};
    showConfig();
    element("backup-status").textContent = `还原完成：${result.restored} 条 Cookie 已恢复，${result.expired} 条已过期。请刷新相关网站后检查。`;
  } catch (error) { element("backup-status").textContent = error.message; }
  finally { settingsLocked = false; setBusy(false); showConfig(); }
}

element("version").textContent = "v" + chrome.runtime.getManifest().version;
element("about-version").textContent = chrome.runtime.getManifest().version;
element("about-sites").textContent = sites.catalog.length + " 个 PT 站点";
element("date").textContent = new Intl.DateTimeFormat("zh-CN", {month: "long", day: "numeric", weekday: "long"}).format(new Date());
window.addEventListener("hashchange", navigate);
navigate();
showConfig();
element("inspect").addEventListener("click", () => refresh(true));
element("site-search").addEventListener("input", renderSites);
element("auto").addEventListener("change", () => request("settings", {enabled: element("auto").checked}));
element("site-form").addEventListener("input", () => { configDirty = true; });
element("site-form").addEventListener("submit", event => {
  event.preventDefault();
  try {
    const configured = sites.config({startTime: element("start-time").value, retryInterval: Number(element("retry-interval").value), retryCount: Number(element("retry-count").value), timeout: Number(element("timeout").value)});
    return request("schedule-settings", {config: configured});
  } catch (error) { element("site-settings-status").textContent = error.message; }
});
element("backup").addEventListener("click", exportBackup);
element("restore").addEventListener("click", chooseRestore);
element("restore-file").addEventListener("change", importBackup);
chrome.storage.local.get(["autoEnabled", "sites", "scheduleConfig", ...sites.catalog.map(site => sites.key("lastResult", site.id))]).then(initial => {
  if (requested) return;
  state = sites.settings(initial);
  for (const site of sites.catalog) {
    const saved = initial[sites.key("lastResult", site.id)];
    if (saved && !Object.hasOwn(results, site.id)) results[site.id] = saved;
  }
  showConfig();
  if (enabledSites().length) refresh(false, false);
}).catch(() => { if (!busy) displayFeedback({message: "无法读取插件设置，请重新加载 NetSurf"}); });
chrome.storage.onChanged.addListener((changes, area) => {
  if (area !== "local") return;
  if (changes.inspection?.newValue?.running) {
    const progress = changes.inspection.newValue;
    activeSiteId = progress.siteId || null;
    activeOperation = activeOperation === "run-all" ? "run-all" : "inspect-all";
    element("status").textContent = `正在逐站刷新 ${progress.completed + 1}/${progress.total}：${progress.current}`;
  } else if (changes.inspection && busy && ["inspect-all", "run-all"].includes(activeOperation)) {
    activeSiteId = null;
  }
  if (changes.autoEnabled) state.autoEnabled = changes.autoEnabled.newValue === true;
  if (changes.sites || changes.scheduleConfig) state = sites.settings({...state, ...(changes.sites ? {sites: changes.sites.newValue} : {}), ...(changes.scheduleConfig ? {scheduleConfig: changes.scheduleConfig.newValue} : {})});
  for (const site of sites.catalog) {
    const changed = changes[sites.key("lastResult", site.id)];
    if (changed) {
      results[site.id] = changed.newValue || null;
      if (changed.newValue) latestResult = changed.newValue;
    }
  }
  if (!busy) {
    showConfig();
    if (latestResult) displayFeedback(latestResult);
  } else renderOverview();
});
