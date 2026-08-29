const state = {
  sources: [],
  credentials: [],
  ptCandidates: [],
  ptSites: [],
  ptHistory: { today: null, days: [], items: [], latest_execution: null },
  ptStats: [],
  periodicCandidates: [],
  periodicSites: [],
  periodicExecutions: [],
  webCredentials: [],
  debugLogs: [],
  debugAutomations: [],
  lanOnly: true,
  ptSelection: new Set(),
  periodicSelection: new Set(),
  selected: "",
  activeView: "pt-signin",
  activePtTab: "signin",
  activeSigninTab: "tasks",
  activePeriodicTab: "tasks",
  browserControl: {
    active: false,
    starting: false,
    url: "",
    title: "",
    error: null,
    busy: false,
    remote_url: "/browser-control/remote/vnc.html?autoconnect=1&resize=scale&reconnect=1&path=websockify",
    viewport: { width: 1365, height: 768 },
    supported_resolutions: [],
  },
};

const ACTIVE_EXECUTION_STATUSES = new Set(["pending", "running", "retry_wait"]);
let executionRefreshInFlight = false;
let browserStatusTimer = null;
let browserResolutionChanging = false;

const elements = {
  body: document.body,
  pageTitle: document.querySelector("#page-title"),
  pageDescription: document.querySelector("#page-description"),
  navItems: document.querySelectorAll("[data-view]"),
  settingsTabList: document.querySelector("#settings-tabs"),
  ptTabList: document.querySelector("#pt-tabs"),
  settingsTabs: document.querySelectorAll("[data-settings-tab]"),
  ptTabs: document.querySelectorAll("[data-pt-tab]"),
  signinTabs: document.querySelectorAll("[data-signin-tab]"),
  periodicTabs: document.querySelectorAll("[data-periodic-tab]"),
  ptPanel: document.querySelector("#pt-signin-panel"),
  ptTasksPanel: document.querySelector("#pt-tasks-panel"),
  ptHistoryPanel: document.querySelector("#pt-history-panel"),
  ptStatsPanel: document.querySelector("#pt-stats-panel"),
  periodicPanel: document.querySelector("#periodic-signin-panel"),
  periodicTasksPanel: document.querySelector("#periodic-tasks-panel"),
  periodicHistoryPanel: document.querySelector("#periodic-history-panel"),
  browserControlPanel: document.querySelector("#browser-control-panel"),
  browserControlSurface: document.querySelector("#browser-control-surface"),
  browserControlState: document.querySelector("#browser-control-state"),
  browserControlPageTitle: document.querySelector("#browser-control-page-title"),
  browserControlError: document.querySelector("#browser-control-error"),
  browserResolution: document.querySelector("#browser-resolution"),
  browserFullscreen: document.querySelector("#browser-fullscreen"),
  browserRemoteShell: document.querySelector("#browser-remote-shell"),
  browserRemoteFrame: document.querySelector("#browser-remote-frame"),
  browserRemotePlaceholder: document.querySelector("#browser-remote-placeholder"),
  browserRemoteCover: document.querySelector("#browser-remote-cover"),
  ptStatsRows: document.querySelector("#pt-stats-rows"),
  cookieCloudPanel: document.querySelector("#cookiecloud-settings-panel"),
  webCredentialsPanel: document.querySelector("#web-credentials-settings-panel"),
  siteSettingsPanel: document.querySelector("#site-settings-panel"),
  logsPanel: document.querySelector("#logs-settings-panel"),
  upgradePanel: document.querySelector("#upgrade-settings-panel"),
  form: document.querySelector("#source-form"),
  selector: document.querySelector("#source-selector"),
  uuid: document.querySelector("#uuid"),
  password: document.querySelector("#password"),
  copyUuidButton: document.querySelector("#copy-uuid-button"),
  copyPasswordButton: document.querySelector("#copy-password-button"),
  passwordHint: document.querySelector("#password-hint"),
  autoImport: document.querySelector("#auto-import"),
  importButton: document.querySelector("#import-button"),
  saveButton: document.querySelector("#save-button"),
  refreshButton: document.querySelector("#refresh-button"),
  copyButton: document.querySelector("#copy-button"),
  endpoint: document.querySelector("#endpoint-url"),
  toast: document.querySelector("#toast"),
  rows: document.querySelector("#credential-rows"),
  logoutButton: document.querySelector("#logout-button"),
  ptForm: document.querySelector("#pt-site-form"),
  ptName: document.querySelector("#pt-name"),
  ptCredential: document.querySelector("#pt-credential"),
  ptUrl: document.querySelector("#pt-url"),
  ptInterval: document.querySelector("#pt-interval"),
  ptTimeout: document.querySelector("#pt-timeout"),
  ptRandomDelay: document.querySelector("#pt-random-delay"),
  ptRetryInterval: document.querySelector("#pt-retry-interval"),
  ptMaxRetries: document.querySelector("#pt-max-retries"),
  ptClickSelector: document.querySelector("#pt-click-selector"),
  ptSuccessPatterns: document.querySelector("#pt-success-patterns"),
  ptAlreadyPatterns: document.querySelector("#pt-already-patterns"),
  ptSaveButton: document.querySelector("#pt-save-button"),
  ptCandidateRows: document.querySelector("#pt-candidate-rows"),
  ptSelectAllButton: document.querySelector("#pt-select-all-button"),
  ptCollectButton: document.querySelector("#pt-collect-button"),
  ptCollectInterval: document.querySelector("#pt-collect-interval"),
  ptCollectTimeout: document.querySelector("#pt-collect-timeout"),
  ptCollectRandomDelay: document.querySelector("#pt-collect-random-delay"),
  ptCollectRetryInterval: document.querySelector("#pt-collect-retry-interval"),
  ptCollectMaxRetries: document.querySelector("#pt-collect-max-retries"),
  ptUnknownCount: document.querySelector("#pt-unknown-count"),
  ptSiteRows: document.querySelector("#pt-site-rows"),
  ptHistoryRows: document.querySelector("#pt-history-rows"),
  ptHistoryHead: document.querySelector("#pt-history-head"),
  ptScheduleDialog: document.querySelector("#pt-schedule-dialog"),
  ptScheduleForm: document.querySelector("#pt-schedule-form"),
  ptScheduleSite: document.querySelector("#pt-schedule-site"),
  ptScheduleInterval: document.querySelector("#pt-schedule-interval"),
  ptScheduleRandomDelay: document.querySelector("#pt-schedule-random-delay"),
  ptScheduleTimeout: document.querySelector("#pt-schedule-timeout"),
  ptScheduleRetryInterval: document.querySelector("#pt-schedule-retry-interval"),
  ptScheduleMaxRetries: document.querySelector("#pt-schedule-max-retries"),
  ptScheduleCancel: document.querySelector("#pt-schedule-cancel"),
  ptScheduleDismiss: document.querySelector("#pt-schedule-dismiss"),
  upgradeStartButton: document.querySelector("#upgrade-start-button"),
  upgradeRevision: document.querySelector("#upgrade-revision"),
  upgradeRemoteRevision: document.querySelector("#upgrade-remote-revision"),
  upgradeDependencies: document.querySelector("#upgrade-dependencies"),
  upgradeBrowser: document.querySelector("#upgrade-browser"),
  upgradeState: document.querySelector("#upgrade-state"),
  tokenSyncBaseUrl: document.querySelector("#token-sync-base-url"),
  tokenSyncState: document.querySelector("#token-sync-state"),
  webCredentialRows: document.querySelector("#web-credential-rows"),
  tokenScriptButton: document.querySelector("#token-script-button"),
  tokenScriptCopyButton: document.querySelector("#token-script-copy-button"),
  periodicForm: document.querySelector("#periodic-site-form"),
  periodicTemplate: document.querySelector("#periodic-template"),
  periodicName: document.querySelector("#periodic-name"),
  periodicCredential: document.querySelector("#periodic-credential"),
  periodicUrl: document.querySelector("#periodic-url"),
  periodicInterval: document.querySelector("#periodic-interval"),
  periodicTimeout: document.querySelector("#periodic-timeout"),
  periodicRandomDelay: document.querySelector("#periodic-random-delay"),
  periodicRetryInterval: document.querySelector("#periodic-retry-interval"),
  periodicMaxRetries: document.querySelector("#periodic-max-retries"),
  periodicHandler: document.querySelector("#periodic-handler"),
  periodicMethod: document.querySelector("#periodic-method"),
  periodicWaitSelector: document.querySelector("#periodic-wait-selector"),
  periodicClickSelector: document.querySelector("#periodic-click-selector"),
  periodicClickRole: document.querySelector("#periodic-click-role"),
  periodicClickName: document.querySelector("#periodic-click-name"),
  periodicClickExact: document.querySelector("#periodic-click-exact"),
  periodicWaitAfter: document.querySelector("#periodic-wait-after"),
  periodicSuccessPatterns: document.querySelector("#periodic-success-patterns"),
  periodicAlreadyPatterns: document.querySelector("#periodic-already-patterns"),
  periodicAuthPatterns: document.querySelector("#periodic-auth-patterns"),
  periodicSaveButton: document.querySelector("#periodic-save-button"),
  periodicSiteRows: document.querySelector("#periodic-site-rows"),
  periodicCandidateRows: document.querySelector("#periodic-candidate-rows"),
  periodicSelectAllButton: document.querySelector("#periodic-select-all-button"),
  periodicCollectButton: document.querySelector("#periodic-collect-button"),
  periodicCollectInterval: document.querySelector("#periodic-collect-interval"),
  periodicCollectTimeout: document.querySelector("#periodic-collect-timeout"),
  periodicCollectRandomDelay: document.querySelector("#periodic-collect-random-delay"),
  periodicCollectRetryInterval: document.querySelector("#periodic-collect-retry-interval"),
  periodicCollectMaxRetries: document.querySelector("#periodic-collect-max-retries"),
  periodicHistoryRows: document.querySelector("#periodic-history-rows"),
  periodicScheduleDialog: document.querySelector("#periodic-schedule-dialog"),
  periodicScheduleForm: document.querySelector("#periodic-schedule-form"),
  periodicScheduleSite: document.querySelector("#periodic-schedule-site"),
  periodicScheduleInterval: document.querySelector("#periodic-schedule-interval"),
  periodicScheduleRandomDelay: document.querySelector("#periodic-schedule-random-delay"),
  periodicScheduleTimeout: document.querySelector("#periodic-schedule-timeout"),
  periodicScheduleRetryInterval: document.querySelector("#periodic-schedule-retry-interval"),
  periodicScheduleMaxRetries: document.querySelector("#periodic-schedule-max-retries"),
  periodicScheduleCancel: document.querySelector("#periodic-schedule-cancel"),
  periodicScheduleDismiss: document.querySelector("#periodic-schedule-dismiss"),
  siteBackupButton: document.querySelector("#site-backup-button"),
  siteRestoreButton: document.querySelector("#site-restore-button"),
  siteRestoreFile: document.querySelector("#site-restore-file"),
  lanOnlyAccess: document.querySelector("#lan-only-access"),
  debugLogAutomation: document.querySelector("#debug-log-automation"),
  debugLogStatus: document.querySelector("#debug-log-status"),
  debugLogOutcome: document.querySelector("#debug-log-outcome"),
  debugLogRefresh: document.querySelector("#debug-log-refresh"),
  debugLogCount: document.querySelector("#debug-log-count"),
  debugLogRows: document.querySelector("#debug-log-rows"),
  debugLogDialog: document.querySelector("#debug-log-dialog"),
  debugLogDialogTitle: document.querySelector("#debug-log-dialog-title"),
  debugLogDialogSubtitle: document.querySelector("#debug-log-dialog-subtitle"),
  debugLogDialogClose: document.querySelector("#debug-log-dialog-close"),
  debugLogDialogDismiss: document.querySelector("#debug-log-dialog-dismiss"),
  debugLogDetailStatus: document.querySelector("#debug-log-detail-status"),
  debugLogDetailOutcome: document.querySelector("#debug-log-detail-outcome"),
  debugLogDetailAttempts: document.querySelector("#debug-log-detail-attempts"),
  debugLogDetailDuration: document.querySelector("#debug-log-detail-duration"),
  debugLogArtifactSection: document.querySelector("#debug-log-artifact-section"),
  debugLogArtifact: document.querySelector("#debug-log-artifact"),
  debugLogArtifactState: document.querySelector("#debug-log-artifact-state"),
  debugLogOutput: document.querySelector("#debug-log-output"),
};

elements.endpoint.textContent = `${location.origin}/cookiecloud`;
elements.tokenSyncBaseUrl.value = location.origin;

function escapeHtml(value) {
  const node = document.createElement("span");
  node.textContent = String(value ?? "");
  return node.innerHTML;
}

function formatDate(value) {
  if (!value) return "暂无";
  const normalized = typeof value === "string" && !/[zZ]|[+-]\d\d:\d\d$/.test(value) ? `${value}Z` : value;
  const date = new Date(normalized);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat("zh-CN", {
    year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
  }).format(date);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  if (!response.ok) {
    let detail = `请求失败 (${response.status})`;
    try {
      const payload = await response.json();
      if (typeof payload.detail === "string") detail = payload.detail;
      else if (Array.isArray(payload.detail)) {
        detail = payload.detail.map((item) => item.msg || JSON.stringify(item)).join("；");
      }
    } catch (_) {}
    const error = new Error(detail);
    error.status = response.status;
    throw error;
  }
  return response.status === 204 ? null : response.json();
}

function sourceByUuid(uuid) {
  return state.sources.find((item) => item.uuid === uuid);
}

function credentialById(id) {
  return state.credentials.find((item) => item.id === id);
}

function showToast(message, error = false) {
  elements.toast.textContent = message;
  elements.toast.classList.toggle("error", error);
  elements.toast.hidden = false;
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => { elements.toast.hidden = true; }, 3200);
}

function goToLogin() {
  const next = `${location.pathname}${location.search}${location.hash}`;
  location.replace(`/login?next=${encodeURIComponent(next)}`);
}

async function setActiveView(value, { syncHash = true } = {}) {
  const validViews = ["pt-signin", "periodic-signin", "browser-control", "cookiecloud", "web-credentials", "site-settings", "logs", "upgrade"];
  const activeView = validViews.includes(value) ? value : "pt-signin";
  state.activeView = activeView;
  const ptView = activeView === "pt-signin";
  const periodicView = activeView === "periodic-signin";
  const browserView = activeView === "browser-control";
  const systemView = !ptView && !periodicView && !browserView;
  elements.ptPanel.hidden = !ptView || state.activePtTab !== "signin";
  elements.ptStatsPanel.hidden = !ptView || state.activePtTab !== "stats";
  elements.periodicPanel.hidden = !periodicView;
  elements.browserControlPanel.hidden = !browserView;
  elements.cookieCloudPanel.hidden = activeView !== "cookiecloud";
  elements.webCredentialsPanel.hidden = activeView !== "web-credentials";
  elements.siteSettingsPanel.hidden = activeView !== "site-settings";
  elements.logsPanel.hidden = activeView !== "logs";
  elements.upgradePanel.hidden = activeView !== "upgrade";
  elements.settingsTabList.hidden = !systemView;
  elements.ptTabList.hidden = !ptView;

  for (const item of elements.navItems) {
    const active = item.dataset.view === activeView
      || (item.dataset.view === "cookiecloud" && systemView);
    item.classList.toggle("active", active);
    if (active) item.setAttribute("aria-current", "page");
    else item.removeAttribute("aria-current");
  }
  for (const button of elements.settingsTabs) {
    const active = button.dataset.settingsTab === activeView;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
    button.tabIndex = active ? 0 : -1;
  }

  if (browserView) {
    elements.pageTitle.textContent = "浏览器控制";
    elements.pageDescription.textContent = "Chrome 远程桌面";
  } else if (periodicView) {
    elements.pageTitle.textContent = "周期签到";
    elements.pageDescription.textContent = "普通站点周期任务";
  } else if (systemView) {
    elements.pageTitle.textContent = "系统设置";
    elements.pageDescription.textContent = "CookieCloud、Web 凭据、运行日志与系统升级";
  } else {
    elements.pageTitle.textContent = "PT 站点";
    elements.pageDescription.textContent = "站点管理与自动化";
  }
  const refreshLabels = {
    "pt-signin": "刷新签到任务",
    "periodic-signin": "刷新周期签到任务",
    "browser-control": "刷新浏览器状态",
    cookiecloud: "刷新 CookieCloud 状态",
    "web-credentials": "刷新 Web 凭据同步状态",
    "site-settings": "刷新站点设置",
    logs: "刷新运行日志",
    upgrade: "刷新升级状态",
  };
  elements.refreshButton.title = refreshLabels[activeView];
  elements.refreshButton.setAttribute("aria-label", refreshLabels[activeView]);
  if (syncHash && location.hash !== `#${activeView}`) {
    history.replaceState(null, "", `${location.pathname}${location.search}#${activeView}`);
  }
  setBrowserControlPolling(browserView && !document.hidden);
  if (browserView) await loadBrowserControlStatus({ quiet: true });
  if (activeView === "logs") await loadDebugLogs({ quiet: true });
  if (activeView === "upgrade") await loadUpgradeStatus();
}

function setActivePtTab(value) {
  state.activePtTab = value === "stats" ? "stats" : "signin";
  const systemView = state.activeView !== "pt-signin";
  elements.ptPanel.hidden = systemView || state.activePtTab !== "signin";
  elements.ptStatsPanel.hidden = systemView || state.activePtTab !== "stats";
  for (const button of elements.ptTabs) {
    const active = button.dataset.ptTab === state.activePtTab;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
    button.tabIndex = active ? 0 : -1;
  }
}

function setActiveSigninTab(value) {
  state.activeSigninTab = value === "history" ? "history" : "tasks";
  elements.ptTasksPanel.hidden = state.activeSigninTab !== "tasks";
  elements.ptHistoryPanel.hidden = state.activeSigninTab !== "history";
  for (const button of elements.signinTabs) {
    const active = button.dataset.signinTab === state.activeSigninTab;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
    button.tabIndex = active ? 0 : -1;
  }
}

function setActivePeriodicTab(value) {
  state.activePeriodicTab = value === "history" ? "history" : "tasks";
  elements.periodicTasksPanel.hidden = state.activePeriodicTab !== "tasks";
  elements.periodicHistoryPanel.hidden = state.activePeriodicTab !== "history";
  for (const button of elements.periodicTabs) {
    const active = button.dataset.periodicTab === state.activePeriodicTab;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
    button.tabIndex = active ? 0 : -1;
  }
}

function setBusy(busy) {
  elements.body.classList.toggle("loading", busy);
  elements.saveButton.disabled = busy;
  elements.ptSaveButton.disabled = busy;
  elements.periodicSaveButton.disabled = busy;
  elements.ptSelectAllButton.disabled = busy || selectablePtCandidates().length === 0;
  elements.ptCollectButton.disabled = busy || state.ptSelection.size === 0;
  elements.periodicSelectAllButton.disabled = busy || selectablePeriodicCandidates().length === 0;
  elements.periodicCollectButton.disabled = busy || state.periodicSelection.size === 0;
  elements.refreshButton.disabled = busy;
  elements.tokenScriptButton.disabled = busy;
  elements.tokenScriptCopyButton.disabled = busy;
  elements.siteBackupButton.disabled = busy;
  elements.siteRestoreButton.disabled = busy;
  for (const button of elements.periodicSiteRows.querySelectorAll("button, input")) button.disabled = busy;
  for (const button of elements.webCredentialRows.querySelectorAll("button")) button.disabled = busy;
}

function renderBrowserControl() {
  const browser = state.browserControl;
  const active = Boolean(browser.active);
  const starting = Boolean(browser.starting);
  const busy = Boolean(browser.busy);
  const changing = browserResolutionChanging;
  elements.browserControlState.textContent = changing ? "切换中" : (busy ? "任务占用" : (active ? "运行中" : (starting ? "恢复中" : "不可用")));
  elements.browserControlState.className = `status-badge ${active && !busy && !changing ? "succeeded" : (starting || busy || changing ? "running" : "failed")}`;
  elements.browserControlPageTitle.textContent = browser.title || browser.url || "正在连接常驻浏览器";
  elements.browserControlError.textContent = browser.error || "";
  elements.browserControlError.hidden = !browser.error;
  const viewport = browser.viewport || { width: 1365, height: 768 };
  const resolutionValue = `${viewport.width}x${viewport.height}`;
  elements.browserResolution.value = resolutionValue;
  elements.browserResolution.disabled = busy || changing;
  elements.browserRemoteShell.style.aspectRatio = `${viewport.width} / ${viewport.height}`;
  elements.browserRemotePlaceholder.hidden = active && !changing;
  elements.browserRemoteCover.hidden = !active || !busy;
  if (active && !changing && state.activeView === "browser-control" && !document.hidden) {
    const remoteUrl = browser.remote_url || "/browser-control/remote/vnc.html?autoconnect=1&resize=scale&reconnect=1&path=websockify";
    if (!elements.browserRemoteFrame.getAttribute("src")) {
      elements.browserRemoteFrame.src = remoteUrl;
    }
  }
}

function setBrowserControlState(payload) {
  state.browserControl = {
    ...state.browserControl,
    ...payload,
    viewport: payload.viewport || state.browserControl.viewport,
  };
  renderBrowserControl();
}

async function loadBrowserControlStatus({ quiet = false } = {}) {
  try {
    setBrowserControlState(await api("/api/v1/browser-control", { cache: "no-store" }));
  } catch (error) {
    if (error.status === 401) goToLogin();
    else if (!quiet) showToast(error.message, true);
  }
}

async function changeBrowserResolution() {
  const previous = state.browserControl.viewport;
  const [width, height] = elements.browserResolution.value.split("x").map(Number);
  if (width === previous.width && height === previous.height) return;
  browserResolutionChanging = true;
  elements.browserRemoteFrame.removeAttribute("src");
  renderBrowserControl();
  try {
    const status = await api("/api/v1/browser-control/resolution", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ width, height }),
    });
    setBrowserControlState(status);
    showToast(`远程桌面已切换为 ${width} x ${height}`);
  } catch (error) {
    elements.browserResolution.value = `${previous.width}x${previous.height}`;
    showToast(error.message || "无法切换分辨率", true);
  } finally {
    browserResolutionChanging = false;
    renderBrowserControl();
    await loadBrowserControlStatus({ quiet: true });
  }
}

function setBrowserControlPolling(enabled) {
  window.clearInterval(browserStatusTimer);
  browserStatusTimer = null;
  if (!enabled) {
    elements.browserRemoteFrame.removeAttribute("src");
    return;
  }
  loadBrowserControlStatus({ quiet: true });
  browserStatusTimer = window.setInterval(() => loadBrowserControlStatus({ quiet: true }), 2_000);
}

function browserControlIsFullscreen() {
  return (document.fullscreenElement || document.webkitFullscreenElement) === elements.browserControlSurface;
}

function renderBrowserFullscreenState() {
  const active = browserControlIsFullscreen();
  const label = active ? "退出全屏" : "全屏";
  elements.browserFullscreen.title = label;
  elements.browserFullscreen.setAttribute("aria-label", label);
  elements.browserFullscreen.setAttribute("aria-pressed", String(active));
}

async function toggleBrowserFullscreen() {
  try {
    if (browserControlIsFullscreen()) {
      const exitFullscreen = document.exitFullscreen || document.webkitExitFullscreen;
      if (!exitFullscreen) throw new Error("当前浏览器不支持退出全屏");
      await exitFullscreen.call(document);
    } else {
      const requestFullscreen = elements.browserControlSurface.requestFullscreen
        || elements.browserControlSurface.webkitRequestFullscreen;
      if (!requestFullscreen) throw new Error("当前浏览器不支持全屏");
      await requestFullscreen.call(elements.browserControlSurface);
    }
  } catch (error) {
    showToast(error.message || "无法切换全屏", true);
  }
}

elements.browserFullscreen.addEventListener("click", toggleBrowserFullscreen);
elements.browserResolution.addEventListener("change", changeBrowserResolution);
document.addEventListener("fullscreenchange", renderBrowserFullscreenState);
document.addEventListener("webkitfullscreenchange", renderBrowserFullscreenState);

function statusLabel(status) {
  return ({
    pending: "等待执行",
    running: "执行中",
    retry_wait: "等待重试",
    succeeded: "成功",
    failed: "失败",
  })[status] || status || "暂无";
}

function statusBadge(status) {
  const badge = document.createElement("span");
  badge.className = `status-badge ${status || ""}`;
  badge.textContent = statusLabel(status);
  return badge;
}

function resultText(execution) {
  return execution?.result?.message || execution?.error || (execution ? statusLabel(execution.status) : "暂无");
}

function lineValues(value) {
  return value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean).slice(0, 20);
}

function renderPtCredentialOptions() {
  const selected = elements.ptCredential.value;
  const candidateIds = new Set(state.ptCandidates
    .filter((item) => item.recognized && !item.configured)
    .map((item) => item.credential.id));
  const credentials = state.credentials
    .filter((item) => item.provider === "cookiecloud" && candidateIds.has(item.id))
    .sort((left, right) => left.domain.localeCompare(right.domain));
  elements.ptCredential.replaceChildren(new Option("请选择凭据", ""));
  for (const item of credentials) {
    const option = new Option(`${item.domain} · v${item.version}`, item.id);
    elements.ptCredential.append(option);
  }
  if (credentials.some((item) => item.id === selected)) elements.ptCredential.value = selected;
}

function applyPtCredentialSuggestion() {
  const credential = credentialById(elements.ptCredential.value);
  if (!credential) return;
  if (!elements.ptName.value.trim()) elements.ptName.value = credential.domain;
  if (!elements.ptUrl.value.trim() || elements.ptUrl.dataset.suggested === "true") {
    elements.ptUrl.value = `https://${credential.domain}/attendance.php`;
    elements.ptUrl.dataset.suggested = "true";
  }
}

function renderPtSummary() {
  document.querySelector("#pt-discovered-count").textContent = state.ptCandidates.filter((item) => item.recognized).length;
  document.querySelector("#pt-enabled-count").textContent = state.ptSites.filter((item) => item.enabled).length;
  const latest = state.ptHistory.latest_execution;
  document.querySelector("#pt-recent-state").textContent = latest
    ? `${statusLabel(latest.status)} · ${latest.automation_name}`
    : "暂无记录";
}

function candidateReasonLabel(candidate) {
  if (["profile_refresh_only", "web_storage_profile_refresh_only"].includes(candidate.strategy)) {
    return "仅刷新个人信息";
  }
  return ({
    site_catalog: "站点目录",
    cookie_signature: "PT Cookie 特征",
  })[candidate.reason] || "未识别";
}

function selectablePtCandidates() {
  return state.ptCandidates.filter((item) => item.recognized && item.supported && !item.configured);
}

function updatePtCollectControls() {
  const selectable = selectablePtCandidates();
  const selectedCount = state.ptSelection.size;
  elements.ptSelectAllButton.disabled = selectable.length === 0;
  elements.ptSelectAllButton.textContent = selectable.length > 0 && selectedCount === selectable.length
    ? "取消全选" : "全选可添加站点";
  elements.ptCollectButton.disabled = selectedCount === 0;
  elements.ptCollectButton.textContent = selectedCount ? `添加所选站点 (${selectedCount})` : "添加所选站点";
}

function renderPtCandidates() {
  const recognized = state.ptCandidates.filter((item) => item.recognized && !item.configured);
  const validIds = new Set(selectablePtCandidates().map((item) => item.credential.id));
  state.ptSelection = new Set([...state.ptSelection].filter((id) => validIds.has(id)));
  elements.ptUnknownCount.textContent = recognized.length;
  elements.ptCandidateRows.replaceChildren();
  if (!recognized.length) {
    elements.ptCandidateRows.innerHTML = '<tr><td class="empty" colspan="5">暂无识别到的 PT 站点</td></tr>';
    updatePtCollectControls();
    return;
  }
  for (const candidate of recognized) {
    const row = document.createElement("tr");
    const selectCell = document.createElement("td");
    selectCell.className = "select-column";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.className = "candidate-checkbox";
    checkbox.disabled = candidate.configured || !candidate.supported;
    checkbox.checked = state.ptSelection.has(candidate.credential.id);
    checkbox.setAttribute("aria-label", `选择 ${candidate.name}`);
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) state.ptSelection.add(candidate.credential.id);
      else state.ptSelection.delete(candidate.credential.id);
      updatePtCollectControls();
    });
    selectCell.append(checkbox);
    row.append(selectCell);

    for (const value of [candidate.name, candidate.credential.domain, candidateReasonLabel(candidate)]) {
      const cell = document.createElement("td");
      cell.textContent = value;
      row.append(cell);
    }
    const statusCell = document.createElement("td");
    const badge = document.createElement("span");
    badge.className = `candidate-state ${candidate.configured ? "configured" : candidate.supported ? "available" : "unsupported"}`;
    badge.textContent = candidate.configured
      ? "已添加"
      : ["profile_refresh_only", "web_storage_profile_refresh_only"].includes(candidate.strategy)
        ? "可添加（仅刷新）"
        : candidate.supported ? "可添加" : "待专用适配";
    statusCell.append(badge);
    row.append(statusCell);
    elements.ptCandidateRows.append(row);
  }
  updatePtCollectControls();
}

function renderPtSites() {
  elements.ptSiteRows.replaceChildren();
  if (!state.ptSites.length) {
    elements.ptSiteRows.innerHTML = '<tr><td class="empty" colspan="7">暂无签到任务</td></tr>';
    return;
  }
  for (const site of state.ptSites) {
    const row = document.createElement("tr");
    for (const value of [site.name, site.credential?.domain || "凭据已删除"]) {
      const cell = document.createElement("td");
      cell.textContent = value;
      row.append(cell);
    }
    const featureCell = document.createElement("td");
    const featureToggles = document.createElement("div");
    featureToggles.className = "site-action-toggles";
    for (const [key, label, title] of [
      ["sign_in_enabled", "签到", "执行站点签到"],
      ["profile_refresh_enabled", "刷新", "刷新个人信息页"],
    ]) {
      const toggleLabel = document.createElement("label");
      toggleLabel.className = "row-toggle";
      toggleLabel.title = title;
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.checked = Boolean(site.config[key]);
      const supportKey = key === "sign_in_enabled" ? "sign_in_supported" : "profile_refresh_supported";
      checkbox.disabled = site.config[supportKey] === false;
      if (checkbox.disabled) toggleLabel.title = `${site.name} 不支持${label}`;
      checkbox.setAttribute("aria-label", `${site.name} ${title}`);
      checkbox.addEventListener("change", () => setPtSiteAction(site, key, checkbox.checked));
      toggleLabel.append(checkbox, document.createTextNode(label));
      featureToggles.append(toggleLabel);
    }
    featureCell.append(featureToggles);
    row.append(featureCell);
    for (const value of [`${site.interval_hours} 小时`, formatDate(site.next_run_at)]) {
      const cell = document.createElement("td");
      cell.textContent = value;
      row.append(cell);
    }
    const statusCell = document.createElement("td");
    statusCell.append(statusBadge(site.last_execution?.status));
    statusCell.title = resultText(site.last_execution);
    row.append(statusCell);

    const actionsCell = document.createElement("td");
    const actions = document.createElement("div");
    actions.className = "table-actions";
    const settings = document.createElement("button");
    settings.type = "button";
    settings.className = "table-button";
    settings.textContent = "设置";
    settings.addEventListener("click", () => openPtSchedule(site));
    const run = document.createElement("button");
    run.type = "button";
    run.className = "table-button";
    run.textContent = "立即执行";
    run.addEventListener("click", () => runPtSite(site.id));
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "table-button danger";
    remove.textContent = "删除";
    remove.addEventListener("click", () => deletePtSite(site));
    actions.append(settings, run, remove);
    actionsCell.append(actions);
    row.append(actionsCell);
    elements.ptSiteRows.append(row);
  }
}

function renderPeriodicCredentialOptions() {
  const selected = elements.periodicCredential.value;
  elements.periodicCredential.innerHTML = '<option value="">无需凭据</option>';
  for (const credential of state.credentials.filter((item) => item.provider === "cookiecloud")) {
    const option = document.createElement("option");
    option.value = credential.id;
    option.textContent = `${credential.domain} · v${credential.version}`;
    elements.periodicCredential.append(option);
  }
  if (selected && [...elements.periodicCredential.options].some((option) => option.value === selected)) {
    elements.periodicCredential.value = selected;
  } else if (elements.periodicTemplate.value === "nodeseek") {
    const recommended = state.credentials.find((item) => (
      item.provider === "cookiecloud" && item.domain === "www.nodeseek.com"
    )) || state.credentials.find((item) => (
      item.provider === "cookiecloud" && item.domain === "nodeseek.com"
    ));
    elements.periodicCredential.value = recommended?.id || "";
  }
}

function selectablePeriodicCandidates() {
  return state.periodicCandidates.filter((item) => item.supported && !item.configured);
}

function updatePeriodicCollectControls() {
  const selectable = selectablePeriodicCandidates();
  const selectedCount = state.periodicSelection.size;
  elements.periodicSelectAllButton.disabled = selectable.length === 0;
  elements.periodicSelectAllButton.textContent = selectable.length > 0 && selectedCount === selectable.length
    ? "取消全选" : "全选可添加站点";
  elements.periodicCollectButton.disabled = selectedCount === 0;
  elements.periodicCollectButton.textContent = selectedCount
    ? `添加所选站点 (${selectedCount})` : "添加所选站点";
}

function renderPeriodicCandidates() {
  const candidates = state.periodicCandidates.filter((item) => !item.configured);
  const validIds = new Set(selectablePeriodicCandidates().map((item) => item.credential.id));
  state.periodicSelection = new Set(
    [...state.periodicSelection].filter((id) => validIds.has(id)),
  );
  elements.periodicCandidateRows.replaceChildren();
  if (!candidates.length) {
    elements.periodicCandidateRows.innerHTML = '<tr><td class="empty" colspan="5">暂无可添加的普通站点</td></tr>';
    updatePeriodicCollectControls();
    return;
  }
  for (const candidate of candidates) {
    const row = document.createElement("tr");
    const selectCell = document.createElement("td");
    selectCell.className = "select-column";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.className = "candidate-checkbox";
    checkbox.disabled = !candidate.supported;
    checkbox.checked = state.periodicSelection.has(candidate.credential.id);
    checkbox.setAttribute("aria-label", `选择 ${candidate.name}`);
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) state.periodicSelection.add(candidate.credential.id);
      else state.periodicSelection.delete(candidate.credential.id);
      updatePeriodicCollectControls();
    });
    selectCell.append(checkbox);
    row.append(selectCell);
    for (const value of [candidate.name, candidate.credential.domain, "内置周期模板"]) {
      const cell = document.createElement("td");
      cell.textContent = value;
      row.append(cell);
    }
    const statusCell = document.createElement("td");
    const badge = document.createElement("span");
    badge.className = `candidate-state ${candidate.supported ? "available" : "unsupported"}`;
    badge.textContent = candidate.supported ? "可添加" : "待专用适配";
    statusCell.append(badge);
    row.append(statusCell);
    elements.periodicCandidateRows.append(row);
  }
  updatePeriodicCollectControls();
}

function applyPeriodicTemplate() {
  const template = elements.periodicTemplate.value;
  const browser = template === "custom_browser";
  elements.periodicHandler.value = browser ? "browser_signin" : "http_signin";
  elements.periodicMethod.value = "GET";
  if (template !== "nodeseek") {
    elements.periodicName.value = "";
    elements.periodicUrl.value = "";
    elements.periodicWaitSelector.value = "";
    elements.periodicClickSelector.value = "";
    elements.periodicClickRole.value = "";
    elements.periodicClickName.value = "";
    elements.periodicClickExact.checked = false;
    elements.periodicWaitAfter.value = "1500";
    elements.periodicSuccessPatterns.value = "";
    elements.periodicAlreadyPatterns.value = "";
    elements.periodicAuthPatterns.value = "";
    elements.periodicCredential.value = "";
    return;
  }
  elements.periodicName.value = "NodeSeek";
  elements.periodicHandler.value = "http_signin";
  elements.periodicMethod.value = "POST";
  elements.periodicUrl.value = "https://www.nodeseek.com/api/attendance?random=false";
  elements.periodicWaitSelector.value = "";
  elements.periodicClickSelector.value = "";
  elements.periodicClickRole.value = "";
  elements.periodicClickName.value = "";
  elements.periodicClickExact.checked = false;
  elements.periodicWaitAfter.value = "0";
  elements.periodicSuccessPatterns.value = '"success"\\s*:\\s*true\n签到成功';
  elements.periodicAlreadyPatterns.value = "今日已签到\n已经签到\n重复签到";
  elements.periodicAuthPatterns.value = "请先登录\n未登录\n登录后";
  renderPeriodicCredentialOptions();
}

function openPeriodicSchedule(site) {
  elements.periodicScheduleDialog.dataset.siteId = site.id;
  elements.periodicScheduleSite.textContent = site.name;
  elements.periodicScheduleInterval.value = site.interval_hours;
  elements.periodicScheduleRandomDelay.value = site.config.random_delay_minutes;
  elements.periodicScheduleTimeout.value = site.config.timeout_seconds;
  elements.periodicScheduleRetryInterval.value = site.config.retry_interval_hours;
  elements.periodicScheduleMaxRetries.value = site.config.max_retries;
  elements.periodicScheduleDialog.showModal();
}

async function setPeriodicEnabled(site, enabled) {
  try {
    await api(`/api/v1/periodic-signin/sites/${encodeURIComponent(site.id)}/enabled`, {
      method: "PATCH", body: JSON.stringify({ enabled }),
    });
    await refresh({ quiet: true });
    showToast(`周期任务已${enabled ? "启用" : "停用"}`);
  } catch (error) {
    showToast(error.message, true);
    await refresh({ quiet: true });
  }
}

async function runPeriodicSite(site) {
  setBusy(true);
  try {
    await api(`/api/v1/periodic-signin/sites/${encodeURIComponent(site.id)}/run`, {
      method: "POST", body: "{}",
    });
    await refresh({ quiet: true });
    showToast(`${site.name} 已进入执行队列`);
  } catch (error) {
    showToast(error.message, true);
  } finally {
    setBusy(false);
  }
}

async function deletePeriodicSite(site) {
  if (!window.confirm(`删除周期任务“${site.name}”及其执行记录？`)) return;
  setBusy(true);
  try {
    await api(`/api/v1/periodic-signin/sites/${encodeURIComponent(site.id)}`, { method: "DELETE" });
    await refresh({ quiet: true });
    showToast("周期任务已删除");
  } catch (error) {
    showToast(error.message, true);
  } finally {
    setBusy(false);
  }
}

function renderPeriodicSites() {
  document.querySelector("#periodic-site-count").textContent = state.periodicSites.length;
  document.querySelector("#periodic-enabled-count").textContent = state.periodicSites.filter((item) => item.enabled).length;
  const executions = state.periodicSites.map((item) => item.last_execution).filter(Boolean).sort((a, b) => (
    new Date(b.scheduled_at) - new Date(a.scheduled_at)
  ));
  document.querySelector("#periodic-recent-state").textContent = executions[0]
    ? `${statusLabel(executions[0].status)} · ${formatDate(executions[0].scheduled_at)}` : "暂无记录";
  elements.periodicSiteRows.replaceChildren();
  if (!state.periodicSites.length) {
    elements.periodicSiteRows.innerHTML = '<tr><td class="empty" colspan="7">暂无普通站点任务</td></tr>';
    return;
  }
  for (const site of state.periodicSites) {
    const row = document.createElement("tr");
    const nameCell = document.createElement("td");
    const link = document.createElement("a");
    link.className = "site-link-text";
    link.href = site.site_url || site.url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = site.name;
    nameCell.append(link);
    row.append(nameCell);
    for (const value of [site.credential?.domain || "无需凭据", `${site.interval_hours} 小时`, formatDate(site.next_run_at)]) {
      const cell = document.createElement("td");
      cell.textContent = value;
      row.append(cell);
    }
    const statusCell = document.createElement("td");
    statusCell.append(statusBadge(site.last_execution?.status));
    statusCell.title = resultText(site.last_execution);
    row.append(statusCell);
    const enabledCell = document.createElement("td");
    const enabled = document.createElement("input");
    enabled.type = "checkbox";
    enabled.checked = site.enabled;
    enabled.setAttribute("aria-label", `${site.name} 周期任务`);
    enabled.addEventListener("change", () => setPeriodicEnabled(site, enabled.checked));
    enabledCell.append(enabled);
    row.append(enabledCell);
    const actionsCell = document.createElement("td");
    const actions = document.createElement("div");
    actions.className = "table-actions";
    for (const [label, className, action] of [
      ["设置", "table-button", () => openPeriodicSchedule(site)],
      ["立即执行", "table-button", () => runPeriodicSite(site)],
      ["删除", "table-button danger", () => deletePeriodicSite(site)],
    ]) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = className;
      button.textContent = label;
      button.addEventListener("click", action);
      actions.append(button);
    }
    actionsCell.append(actions);
    row.append(actionsCell);
    elements.periodicSiteRows.append(row);
  }
}

function renderPeriodicHistory() {
  elements.periodicHistoryRows.replaceChildren();
  if (!state.periodicExecutions.length) {
    elements.periodicHistoryRows.innerHTML = '<tr><td class="empty" colspan="6">暂无执行记录</td></tr>';
    return;
  }
  for (const execution of state.periodicExecutions) {
    const row = document.createElement("tr");
    const taskCell = document.createElement("td");
    const task = document.createElement("div");
    task.className = "history-site";
    const name = document.createElement(execution.url ? "a" : "strong");
    name.textContent = execution.automation_name || "周期任务";
    if (execution.url) {
      name.className = "site-link-text";
      name.href = execution.url;
      name.target = "_blank";
      name.rel = "noopener noreferrer";
    }
    const domain = document.createElement("small");
    domain.textContent = execution.domain || "无需凭据";
    task.append(name, domain);
    taskCell.append(task);
    row.append(taskCell);
    for (const value of [formatDate(execution.scheduled_at), formatDate(execution.started_at)]) {
      const cell = document.createElement("td");
      cell.textContent = value;
      row.append(cell);
    }
    const statusCell = document.createElement("td");
    statusCell.append(statusBadge(execution.status));
    row.append(statusCell);
    const attemptsCell = document.createElement("td");
    attemptsCell.textContent = String(execution.attempts ?? 0);
    row.append(attemptsCell);
    const resultCell = document.createElement("td");
    resultCell.className = "result-cell";
    resultCell.textContent = resultText(execution);
    resultCell.title = resultText(execution);
    row.append(resultCell);
    elements.periodicHistoryRows.append(row);
  }
}

function renderPeriodic() {
  renderPeriodicCredentialOptions();
  renderPeriodicCandidates();
  renderPeriodicSites();
  renderPeriodicHistory();
}

function historyState(execution) {
  if (!execution) return { key: "empty", icon: "−", label: "未记录" };
  if (execution.site_reported) return { key: "success", icon: "✓", label: "站点已签到" };
  const refresh = execution.action_type === "profile_refresh";
  const outcome = execution.result?.outcome;
  if (outcome === "success") return refresh
    ? { key: "refresh", icon: "↻", label: "刷新成功" }
    : { key: "success", icon: "✓", label: "签到成功" };
  if (outcome === "already_done") return refresh
    ? { key: "refresh", icon: "↻", label: "刷新完成" }
    : { key: "success", icon: "✓", label: "今日已签到" };
  if (outcome === "blocked") return { key: "warning", icon: "!", label: "访问被拦截" };
  if (outcome === "auth_expired") return { key: "failed", icon: "×", label: "登录已失效" };
  if (execution.status === "running") return { key: "running", icon: "↻", label: refresh ? "刷新中" : "执行中" };
  if (execution.status === "pending") return { key: "pending", icon: "…", label: refresh ? "等待刷新" : "等待执行" };
  if (execution.status === "retry_wait") return { key: "warning", icon: "↻", label: "等待重试" };
  if (execution.status === "succeeded") return refresh
    ? { key: "refresh", icon: "↻", label: "刷新成功" }
    : { key: "success", icon: "✓", label: "成功" };
  return { key: "failed", icon: "×", label: statusLabel(execution.status) };
}

function historyExecution(site, date) {
  const execution = site.executions?.[date];
  if (execution) return execution;
  const reported = site.site_history?.[date];
  if (!reported) return null;
  const reward = reported.reward ? ` · 奖励 ${reported.reward}` : "";
  return {
    status: "succeeded",
    site_reported: true,
    result: { outcome: "success", message: `站点历史签到${reward}` },
  };
}

function historyTitle(date, execution) {
  const state = historyState(execution);
  return `${date} · ${execution ? resultText(execution) : state.label}`;
}

function renderPtHistory() {
  const days = state.ptHistory.days || [];
  elements.ptHistoryHead.replaceChildren();
  for (const label of ["站点", "今日", ...days.map((item) => item.label)]) {
    const heading = document.createElement("th");
    heading.textContent = label;
    elements.ptHistoryHead.append(heading);
  }

  elements.ptHistoryRows.replaceChildren();
  if (!state.ptHistory.items.length) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.className = "empty";
    cell.colSpan = days.length + 2;
    cell.textContent = "暂无签到任务";
    row.append(cell);
    elements.ptHistoryRows.append(row);
    return;
  }

  for (const site of state.ptHistory.items) {
    const row = document.createElement("tr");
    const siteCell = document.createElement("td");
    const siteDetails = document.createElement("div");
    siteDetails.className = "history-site";
    const siteHeading = document.createElement("div");
    siteHeading.className = "history-site-heading";
    const siteName = document.createElement("strong");
    siteName.textContent = site.name;
    siteHeading.append(siteName);
    if (site.url) {
      const siteLink = document.createElement("a");
      siteLink.className = "site-link";
      siteLink.href = site.url;
      siteLink.target = "_blank";
      siteLink.rel = "noopener noreferrer";
      siteLink.title = `打开 ${site.name}`;
      siteLink.setAttribute("aria-label", `打开 ${site.name}`);
      siteLink.textContent = "↗";
      siteHeading.append(siteLink);
    }
    const retryButton = document.createElement("button");
    retryButton.type = "button";
    retryButton.className = "site-link";
    retryButton.title = `立即重试 ${site.name}`;
    retryButton.setAttribute("aria-label", `立即重试 ${site.name}`);
    retryButton.textContent = "↻";
    retryButton.addEventListener("click", () => runPtSite(site.automation_id));
    siteHeading.append(retryButton);
    const count = document.createElement("small");
    const reportedCount = Object.keys(site.site_history || {}).length;
    count.textContent = reportedCount
      ? `${site.record_count} 条执行 · ${reportedCount} 天站点历史`
      : `${site.record_count} 条执行`;
    siteDetails.append(siteHeading, count);
    siteCell.append(siteDetails);
    row.append(siteCell);

    const todayExecution = historyExecution(site, state.ptHistory.today);
    const todayState = historyState(todayExecution);
    const todayCell = document.createElement("td");
    const todayBadge = document.createElement("span");
    todayBadge.className = `history-today ${todayState.key}`;
    todayBadge.textContent = todayState.label;
    todayBadge.title = historyTitle(state.ptHistory.today, todayExecution);
    todayCell.append(todayBadge);
    row.append(todayCell);

    for (const day of days) {
      const execution = historyExecution(site, day.date);
      const itemState = historyState(execution);
      const cell = document.createElement("td");
      const dot = document.createElement("span");
      dot.className = `history-dot ${itemState.key}`;
      dot.textContent = itemState.icon;
      dot.title = historyTitle(day.date, execution);
      dot.setAttribute("aria-label", historyTitle(day.date, execution));
      cell.append(dot);
      row.append(cell);
    }
    elements.ptHistoryRows.append(row);
  }
}

function renderPtStats() {
  elements.ptStatsRows.replaceChildren();
  if (!state.ptStats.length) {
    elements.ptStatsRows.innerHTML = '<tr><td class="empty" colspan="10">暂无站点信息统计</td></tr>';
    return;
  }
  for (const item of state.ptStats) {
    const row = document.createElement("tr");
    const stats = item.stats || {};
    const refresh = ptStatsRefreshState(item, stats);
    const title = [];
    if (item.refresh_message) title.push(item.refresh_message);
    if (item.refresh_updated_at) title.push(`最近刷新：${formatDate(item.refresh_updated_at)}`);
    if (item.updated_at) title.push(`数据时间：${formatDate(item.updated_at)}`);
    row.title = title.join("；") || "等待首次刷新";
    const values = [
      item.name,
      refresh.label,
      stats.username || "-",
      stats.user_level || "-",
      stats.uploaded || "-",
      stats.downloaded || "-",
      stats.ratio || "-",
      stats.bonus || "-",
      stats.seeding_count || "-",
      stats.seeding_size || "-",
    ];
    values.forEach((value, index) => {
      const cell = document.createElement("td");
      if (index === 1) {
        const badge = document.createElement("span");
        badge.className = `status-badge ${refresh.key}`;
        badge.textContent = value;
        cell.append(badge);
      } else {
        cell.textContent = value;
      }
      if (index === 0) cell.title = item.domain || item.name;
      if (index === 4) cell.className = "stat-uploaded";
      if (index === 5) cell.className = "stat-downloaded";
      row.append(cell);
    });
    elements.ptStatsRows.append(row);
  }
}

function ptStatsRefreshState(item, stats) {
  if (item.refresh_outcome === "success" || item.refresh_outcome === "already_done") {
    return Object.keys(stats).length
      ? { key: "succeeded", label: "已刷新" }
      : { key: "retry_wait", label: "未解析数据" };
  }
  if (item.refresh_outcome === "auth_expired") return { key: "failed", label: "登录失效" };
  if (item.refresh_outcome === "blocked") return { key: "retry_wait", label: "验证受阻" };
  if (item.refresh_outcome === "failed") return { key: "failed", label: "刷新失败" };
  if (!item.profile_refresh_enabled) return { key: "", label: "已停用" };
  return { key: "running", label: "等待刷新" };
}

function openPtSchedule(site) {
  elements.ptScheduleDialog.dataset.siteId = site.id;
  elements.ptScheduleSite.textContent = site.name;
  elements.ptScheduleInterval.value = site.interval_hours;
  elements.ptScheduleRandomDelay.value = site.config.random_delay_minutes ?? 30;
  elements.ptScheduleTimeout.value = site.config.timeout_seconds ?? 60;
  elements.ptScheduleRetryInterval.value = site.config.retry_interval_hours ?? 2;
  elements.ptScheduleMaxRetries.value = site.config.max_retries ?? 5;
  elements.ptScheduleDialog.showModal();
}

function renderPt() {
  renderPtCredentialOptions();
  renderPtSummary();
  renderPtCandidates();
  renderPtSites();
  renderPtHistory();
  renderPtStats();
}

async function setPtSiteAction(site, key, checked) {
  const payload = {
    sign_in_enabled: Boolean(site.config.sign_in_enabled),
    profile_refresh_enabled: Boolean(site.config.profile_refresh_enabled),
  };
  payload[key] = checked;
  try {
    await api(`/api/v1/pt-signin/sites/${encodeURIComponent(site.id)}/actions`, {
      method: "PATCH", body: JSON.stringify(payload),
    });
    await refresh({ quiet: true });
    const action = key === "sign_in_enabled" ? "签到" : "个人信息刷新";
    showToast(`${action}已${checked ? "启用" : "停用"}`);
  } catch (error) {
    showToast(error.message, true);
    await refresh({ quiet: true });
  }
}

async function runPtSite(id) {
  setBusy(true);
  try {
    await api(`/api/v1/pt-signin/sites/${encodeURIComponent(id)}/run`, { method: "POST", body: "{}" });
    await refresh({ quiet: true });
    showToast("签到任务已进入执行队列");
  } catch (error) {
    showToast(error.message, true);
  } finally {
    setBusy(false);
  }
}

async function deletePtSite(site) {
  if (!window.confirm(`删除签到任务“${site.name}”及其执行记录？`)) return;
  setBusy(true);
  try {
    await api(`/api/v1/pt-signin/sites/${encodeURIComponent(site.id)}`, { method: "DELETE" });
    await refresh({ quiet: true });
    showToast("签到任务已删除");
  } catch (error) {
    showToast(error.message, true);
  } finally {
    setBusy(false);
  }
}

function renderWebCredentials(statuses) {
  state.webCredentials = statuses;
  const configuredCount = statuses.filter((item) => item.credential_configured).length;
  const scriptConfigured = statuses.length > 0 && statuses.every((item) => item.script_configured);
  elements.tokenSyncState.textContent = configuredCount === statuses.length && statuses.length
    ? "同步正常" : scriptConfigured ? `已同步 ${configuredCount}/${statuses.length}` : "未配置";
  elements.tokenSyncState.className = `status-badge${configuredCount === statuses.length && statuses.length ? " succeeded" : ""}`;
  elements.tokenScriptButton.textContent = scriptConfigured ? "重新下载脚本" : "下载脚本";
  elements.webCredentialRows.innerHTML = statuses.length ? statuses.map((status) => `
    <tr>
      <td>${escapeHtml(status.site)}</td>
      <td>${escapeHtml(status.domain)}</td>
      <td>${status.script_configured ? "已生成" : "未生成"}</td>
      <td>${status.credential_configured ? `已加密保存 (${status.configured_keys.length} 项)` : "未同步"}</td>
      <td>${escapeHtml(formatDate(status.last_sync_at))}</td>
      <td><button class="table-button danger" type="button" data-web-credential-clear="${escapeHtml(status.source_key)}"
        ${status.credential_configured ? "" : "disabled"}>清除凭据</button></td>
    </tr>`).join("") : '<tr><td class="empty" colspan="6">暂无 Web 凭据来源</td></tr>';
}

async function loadWebCredentialStatus() {
  const status = await api("/api/v1/web-credentials", { cache: "no-store" });
  renderWebCredentials(status.items);
  return status.items;
}

const DEBUG_STATUS_LABELS = {
  pending: "等待执行",
  running: "执行中",
  retry_wait: "等待重试",
  succeeded: "已完成",
  failed: "失败",
  cancelled: "已取消",
  timed_out: "已超时",
};

const DEBUG_OUTCOME_LABELS = {
  success: "成功",
  already_done: "无需执行",
  auth_expired: "登录失效",
  blocked: "访问被拦截",
  failed: "执行失败",
};

function debugStatusLabel(value) {
  return DEBUG_STATUS_LABELS[value] || value || "未知";
}

function debugOutcomeLabel(value) {
  return DEBUG_OUTCOME_LABELS[value] || value || "尚无结果";
}

function debugOutcomeClass(value) {
  if (["success", "already_done"].includes(value)) return "succeeded";
  if (["blocked", "auth_expired", "failed"].includes(value)) return "failed";
  return "";
}

function formatDuration(value) {
  if (!Number.isFinite(value)) return "-";
  if (value < 1000) return `${value} 毫秒`;
  if (value < 60000) return `${(value / 1000).toFixed(value < 10000 ? 1 : 0)} 秒`;
  const minutes = Math.floor(value / 60000);
  const seconds = Math.round((value % 60000) / 1000);
  return seconds ? `${minutes} 分 ${seconds} 秒` : `${minutes} 分钟`;
}

function renderDebugLogAutomationOptions(automations) {
  const selected = elements.debugLogAutomation.value;
  elements.debugLogAutomation.innerHTML = '<option value="">全部任务</option>' + automations.map((item) => (
    `<option value="${escapeHtml(item.id)}">${escapeHtml(item.name)}</option>`
  )).join("");
  if (automations.some((item) => item.id === selected)) elements.debugLogAutomation.value = selected;
}

function renderDebugLogs(payload) {
  state.debugLogs = payload.items || [];
  state.debugAutomations = payload.automations || [];
  renderDebugLogAutomationOptions(state.debugAutomations);
  elements.debugLogCount.textContent = `${state.debugLogs.length} 条`;
  elements.debugLogRows.innerHTML = state.debugLogs.length ? state.debugLogs.map((item) => {
    const message = item.message || item.error || "暂无详情";
    const outcomeClass = debugOutcomeClass(item.outcome);
    return `<tr>
      <td>${escapeHtml(formatDate(item.started_at || item.scheduled_at))}</td>
      <td><span class="debug-log-task"><strong>${escapeHtml(item.automation_name)}</strong><small>${escapeHtml(item.handler_type)}</small></span></td>
      <td><span class="status-badge ${escapeHtml(item.status)}">${escapeHtml(debugStatusLabel(item.status))}</span></td>
      <td>${escapeHtml(item.attempts)}</td>
      <td><span class="status-badge ${outcomeClass}">${escapeHtml(debugOutcomeLabel(item.outcome))}</span></td>
      <td class="debug-log-message" title="${escapeHtml(message)}">${escapeHtml(message)}</td>
      <td><button class="table-button" type="button" data-debug-log-id="${escapeHtml(item.id)}">查看详情</button></td>
    </tr>`;
  }).join("") : '<tr><td class="empty" colspan="7">没有符合筛选条件的运行日志</td></tr>';
}

async function loadDebugLogs({ quiet = false } = {}) {
  const params = new URLSearchParams({ limit: "100" });
  if (elements.debugLogAutomation.value) params.set("automation_id", elements.debugLogAutomation.value);
  if (elements.debugLogStatus.value) params.set("status", elements.debugLogStatus.value);
  if (elements.debugLogOutcome.value) params.set("outcome", elements.debugLogOutcome.value);
  elements.debugLogRefresh.disabled = true;
  try {
    const payload = await api(`/api/v1/debug/executions?${params}`, { cache: "no-store" });
    renderDebugLogs(payload);
    if (!quiet) showToast("运行日志已刷新");
    return payload;
  } catch (error) {
    if (error.status === 401) goToLogin();
    else {
      elements.debugLogRows.innerHTML = `<tr><td class="empty" colspan="7">${escapeHtml(error.message)}</td></tr>`;
      showToast(error.message, true);
    }
    return null;
  } finally {
    elements.debugLogRefresh.disabled = false;
  }
}

function openDebugLog(item) {
  elements.debugLogDialogTitle.textContent = item.automation_name || "执行详情";
  elements.debugLogDialogSubtitle.textContent = `${formatDate(item.started_at || item.scheduled_at)} · ${item.handler_type}`;
  elements.debugLogDetailStatus.textContent = debugStatusLabel(item.status);
  elements.debugLogDetailOutcome.textContent = debugOutcomeLabel(item.outcome);
  elements.debugLogDetailAttempts.textContent = String(item.attempts ?? "-");
  elements.debugLogDetailDuration.textContent = formatDuration(item.duration_ms);
  elements.debugLogOutput.textContent = JSON.stringify({
    message: item.message,
    error: item.error,
    result: item.result,
    started_at: item.started_at,
    finished_at: item.finished_at,
  }, null, 2);
  elements.debugLogArtifactState.hidden = true;
  elements.debugLogArtifact.hidden = false;
  elements.debugLogArtifactSection.hidden = !item.artifact_url;
  elements.debugLogArtifact.removeAttribute("src");
  if (item.artifact_url) elements.debugLogArtifact.src = `${item.artifact_url}?t=${Date.now()}`;
  elements.debugLogDialog.showModal();
}

function closeDebugLog() {
  elements.debugLogArtifact.removeAttribute("src");
  elements.debugLogDialog.close();
}

function renderUpgradeStatus(status) {
  const localRevision = status.local_revision || status.revision;
  elements.upgradeRevision.textContent = localRevision ? `${status.branch}@${localRevision.slice(0, 12)}` : "未知";
  elements.upgradeRemoteRevision.textContent = status.version_check_error
    ? "检查失败" : status.remote_revision ? `${status.branch}@${status.remote_revision.slice(0, 12)}` : "未知";
  const dependencies = status.python_dependencies || {};
  const dependencyIssues = Array.isArray(dependencies.issues) ? dependencies.issues : [];
  elements.upgradeDependencies.textContent = !dependencies.checked
    ? "检查失败" : dependencies.satisfied ? `已满足 (${dependencies.total || 0} 项)`
      : `需修复 (${dependencies.issue_count || dependencyIssues.length} 项)`;
  elements.upgradeDependencies.title = dependencies.error || dependencyIssues.map((item) => item.status === "missing"
    ? `${item.name}: 未安装，要求 ${item.required}`
    : `${item.name}: 已安装 ${item.installed}，要求 ${item.required}`).join("\n");
  const browser = status.browser || {};
  const browserMode = browser.session_mode === "persistent_headful" ? "持久有头" : "持久无头";
  const browserName = browser.browser_name || "Google Chrome";
  const browserVersion = browser.browser_version || browser.chromium_version
    || browser.chromium_revision || "已安装";
  elements.upgradeBrowser.textContent = browser.installed
    ? `${browserName} ${browserVersion} · ${browserMode}` : "未安装";
  const lastState = status.last_upgrade?.state;
  elements.upgradeState.textContent = status.running ? "升级中"
    : status.version_check_error ? status.version_check_error
      : status.update_available ? "发现新版本"
        : dependencies.checked && !dependencies.satisfied ? "Python 依赖需要修复"
          : !browser.installed ? "浏览器运行时缺失"
            : !dependencies.checked ? dependencies.error || "Python 依赖检查失败"
              : lastState === "failed" ? "上次升级失败，当前已是最新版本" : "已是最新版本";
  elements.upgradeStartButton.disabled = !status.can_upgrade || status.running;
  elements.upgradeStartButton.textContent = status.running ? "升级中..."
    : status.update_available ? "升级到新版本"
      : dependencies.checked && !dependencies.satisfied ? "修复 Python 依赖"
        : !browser.installed ? "安装浏览器运行时" : "已是最新版本";
}

async function loadUpgradeStatus() {
  try {
    const status = await api("/api/v1/system/upgrade");
    renderUpgradeStatus(status);
    return status;
  } catch (error) {
    if (error.status === 401) goToLogin();
    elements.upgradeState.textContent = "状态读取失败";
    elements.upgradeStartButton.disabled = true;
    return null;
  }
}

async function waitForUpgrade() {
  const deadline = Date.now() + 15 * 60 * 1000;
  while (Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, 2000));
    try {
      const status = await api("/api/v1/system/upgrade", { cache: "no-store" });
      renderUpgradeStatus(status);
      if (!status.running && status.last_upgrade?.state === "complete") {
        showToast("程序与浏览器运行时升级完成");
        return;
      }
      if (!status.running && status.last_upgrade?.state === "failed") {
        showToast("升级失败，请查看服务日志", true);
        return;
      }
    } catch (_) {
      elements.upgradeState.textContent = "服务重启中";
    }
  }
  elements.upgradeState.textContent = "升级超时";
  showToast("升级状态等待超时，请查看服务日志", true);
}

function renderSelector() {
  const selected = state.selected;
  elements.selector.innerHTML = '<option value="">新建配置</option>';
  for (const source of state.sources) {
    const option = document.createElement("option");
    option.value = source.uuid;
    option.textContent = source.uuid;
    elements.selector.append(option);
  }
  elements.selector.value = selected;
}

function renderSelected() {
  const source = sourceByUuid(state.selected);
  const uuid = source?.uuid || "";
  elements.uuid.value = uuid;
  elements.uuid.disabled = Boolean(source);
  elements.password.value = "";
  elements.password.placeholder = source?.password_configured ? "已保存（不自动回显）" : "";
  elements.password.required = !source?.password_configured;
  elements.passwordHint.textContent = source?.password_configured ? "已加密保存；留空将保留当前密码" : "新配置必须填写密码";
  updateCredentialCopyControls();
  elements.autoImport.checked = source ? source.auto_import : true;
  elements.importButton.disabled = !source?.configured || !source?.password_configured || !source?.blob_updated_at;
  document.querySelector("#status-uuid").textContent = uuid || "未选择";
  document.querySelector("#last-upload").textContent = formatDate(source?.blob_updated_at);
  document.querySelector("#last-import").textContent = formatDate(source?.last_import_at);
  document.querySelector("#auto-import-state").textContent = source ? (source.auto_import ? "已启用" : "已停用") : "未配置";
  const errorBox = document.querySelector("#error-box");
  errorBox.hidden = !source?.last_error;
  errorBox.textContent = source?.last_error || "";
}

function updateCredentialCopyControls() {
  elements.copyUuidButton.disabled = !elements.uuid.value.trim();
  const savedPasswordAvailable = Boolean(sourceByUuid(state.selected)?.password_configured);
  elements.copyPasswordButton.disabled = !elements.password.value && !savedPasswordAvailable;
  const label = elements.password.value ? "复制当前输入的 CookieCloud 密码" : "复制已保存的 CookieCloud 密码";
  elements.copyPasswordButton.title = label;
  elements.copyPasswordButton.setAttribute("aria-label", label);
}

async function writeClipboardText(value) {
  const text = String(value ?? "");
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return;
    } catch (_) {}
  }

  const previousFocus = document.activeElement;
  const textArea = document.createElement("textarea");
  textArea.value = text;
  textArea.readOnly = true;
  textArea.setAttribute("aria-hidden", "true");
  Object.assign(textArea.style, {
    position: "fixed", top: "0", left: "0", width: "1px", height: "1px",
    padding: "0", border: "0", opacity: "0", pointerEvents: "none",
  });
  document.body.append(textArea);
  try {
    textArea.focus();
    textArea.select();
    textArea.setSelectionRange(0, text.length);
    if (!document.execCommand("copy")) throw new Error("copy command was rejected");
  } finally {
    textArea.remove();
    if (previousFocus instanceof HTMLElement) previousFocus.focus({ preventScroll: true });
  }
}

async function copyCredentialValue(value, successMessage) {
  try {
    await writeClipboardText(value);
    showToast(successMessage);
  } catch (_) {
    showToast("浏览器未允许复制，请手动选择内容", true);
  }
}

function renderSummary() {
  const configured = state.sources.filter((item) => item.configured).length;
  const imported = state.credentials.filter((item) => item.provider === "cookiecloud").length;
  const selected = sourceByUuid(state.selected);
  document.querySelector("#source-count").textContent = configured;
  document.querySelector("#credential-count").textContent = imported;
  document.querySelector("#sync-state").textContent = selected?.last_error ? "同步异常"
    : selected?.last_import_at ? "最近导入成功"
      : selected?.blob_updated_at ? "等待首次导入"
        : configured ? "等待浏览器上传" : "等待配置";
}

function renderCredentials() {
  const prefix = state.selected ? `cookiecloud:${state.selected}:` : "cookiecloud:";
  const credentials = state.credentials.filter((item) => item.provider === "cookiecloud" && item.name.startsWith(prefix));
  elements.rows.replaceChildren();
  if (!credentials.length) {
    elements.rows.innerHTML = '<tr><td class="empty" colspan="4">暂无已导入凭据</td></tr>';
    return;
  }
  for (const item of credentials) {
    const row = document.createElement("tr");
    for (const value of [item.domain, "CookieCloud", `v${item.version}`, formatDate(item.updated_at)]) {
      const cell = document.createElement("td");
      cell.textContent = value;
      row.append(cell);
    }
    elements.rows.append(row);
  }
}

function renderCookieCloud() {
  renderSelector();
  renderSelected();
  renderSummary();
  renderCredentials();
}

async function refresh({ quiet = false } = {}) {
  setBusy(true);
  try {
    const timezoneOffset = -new Date().getTimezoneOffset();
    const [sources, credentials, ptCandidates, ptSites, ptHistory, ptStats, webCredentials, accessSettings,
      periodicCandidates, periodicSites, periodicExecutions] = await Promise.all([
      api("/api/v1/cookiecloud/sources"),
      api("/api/v1/credentials"),
      api("/api/v1/pt-signin/candidates?include_unknown=true"),
      api("/api/v1/pt-signin/sites"),
      api(`/api/v1/pt-signin/history?days=7&timezone_offset=${timezoneOffset}`),
      api("/api/v1/pt-signin/stats"),
      api("/api/v1/web-credentials", { cache: "no-store" }),
      api("/api/v1/system/access", { cache: "no-store" }),
      api("/api/v1/periodic-signin/candidates"),
      api("/api/v1/periodic-signin/sites"),
      api("/api/v1/periodic-signin/executions?limit=100"),
    ]);
    state.sources = sources.items;
    state.credentials = credentials.items;
    state.ptCandidates = ptCandidates.items;
    state.ptSites = ptSites.items;
    state.ptHistory = ptHistory;
    state.ptStats = ptStats.items;
    state.webCredentials = webCredentials.items;
    state.lanOnly = accessSettings.lan_only;
    elements.lanOnlyAccess.checked = state.lanOnly;
    state.periodicCandidates = periodicCandidates.items;
    state.periodicSites = periodicSites.items;
    state.periodicExecutions = periodicExecutions.items;
    if (state.selected && !sourceByUuid(state.selected)) state.selected = "";
    if (!state.selected && state.sources.length === 1) state.selected = state.sources[0].uuid;
    renderCookieCloud();
    renderPt();
    renderPeriodic();
    renderWebCredentials(webCredentials.items);
    if (!quiet) showToast("状态已刷新");
  } catch (error) {
    if (error.status === 401) goToLogin();
    else showToast(error.message, true);
  } finally {
    setBusy(false);
  }
}

function hasActiveExecutions() {
  return [
    ...state.ptSites.map((item) => item.last_execution),
    ...state.periodicSites.map((item) => item.last_execution),
  ].some((execution) => ACTIVE_EXECUTION_STATUSES.has(execution?.status));
}

async function refreshExecutionStates() {
  if (executionRefreshInFlight || document.hidden || !hasActiveExecutions()) return;
  executionRefreshInFlight = true;
  try {
    const timezoneOffset = -new Date().getTimezoneOffset();
    const [ptSites, ptHistory, ptStats, periodicSites, periodicExecutions] = await Promise.all([
      api("/api/v1/pt-signin/sites"),
      api(`/api/v1/pt-signin/history?days=7&timezone_offset=${timezoneOffset}`),
      api("/api/v1/pt-signin/stats"),
      api("/api/v1/periodic-signin/sites"),
      api("/api/v1/periodic-signin/executions?limit=100"),
    ]);
    state.ptSites = ptSites.items;
    state.ptHistory = ptHistory;
    state.ptStats = ptStats.items;
    state.periodicSites = periodicSites.items;
    state.periodicExecutions = periodicExecutions.items;
    renderPtSummary();
    renderPtSites();
    renderPtHistory();
    renderPtStats();
    renderPeriodicSites();
    renderPeriodicHistory();
  } catch (error) {
    if (error.status === 401) goToLogin();
  } finally {
    executionRefreshInFlight = false;
  }
}

elements.ptSelectAllButton.addEventListener("click", () => {
  const selectable = selectablePtCandidates();
  const allSelected = selectable.length > 0 && selectable.every((item) => state.ptSelection.has(item.credential.id));
  state.ptSelection = allSelected
    ? new Set()
    : new Set(selectable.map((item) => item.credential.id));
  renderPtCandidates();
});

elements.ptCollectButton.addEventListener("click", async () => {
  if (!state.ptSelection.size) return;
  setBusy(true);
  try {
    const result = await api("/api/v1/pt-signin/sites/collect", {
      method: "POST",
      body: JSON.stringify({
        credential_ids: [...state.ptSelection],
        interval_hours: Number(elements.ptCollectInterval.value),
        timeout_seconds: Number(elements.ptCollectTimeout.value),
        random_delay_minutes: Number(elements.ptCollectRandomDelay.value),
        retry_interval_hours: Number(elements.ptCollectRetryInterval.value),
        max_retries: Number(elements.ptCollectMaxRetries.value),
      }),
    });
    state.ptSelection.clear();
    await refresh({ quiet: true });
    showToast(`已添加 ${result.created.length} 个签到站点`);
  } catch (error) {
    showToast(error.message, true);
  } finally {
    setBusy(false);
  }
});

elements.periodicSelectAllButton.addEventListener("click", () => {
  const selectable = selectablePeriodicCandidates();
  const allSelected = selectable.length > 0 && selectable.every(
    (item) => state.periodicSelection.has(item.credential.id),
  );
  state.periodicSelection = allSelected
    ? new Set()
    : new Set(selectable.map((item) => item.credential.id));
  renderPeriodicCandidates();
});

elements.periodicCollectButton.addEventListener("click", async () => {
  if (!state.periodicSelection.size) return;
  setBusy(true);
  try {
    const result = await api("/api/v1/periodic-signin/sites/collect", {
      method: "POST",
      body: JSON.stringify({
        credential_ids: [...state.periodicSelection],
        interval_hours: Number(elements.periodicCollectInterval.value),
        timeout_seconds: Number(elements.periodicCollectTimeout.value),
        random_delay_minutes: Number(elements.periodicCollectRandomDelay.value),
        retry_interval_hours: Number(elements.periodicCollectRetryInterval.value),
        max_retries: Number(elements.periodicCollectMaxRetries.value),
      }),
    });
    state.periodicSelection.clear();
    await refresh({ quiet: true });
    showToast(`已添加 ${result.created.length} 个周期站点`);
  } catch (error) {
    showToast(error.message, true);
  } finally {
    setBusy(false);
  }
});

function closePtSchedule() {
  elements.ptScheduleDialog.close();
}

elements.ptScheduleCancel.addEventListener("click", closePtSchedule);
elements.ptScheduleDismiss.addEventListener("click", closePtSchedule);
elements.ptScheduleForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const siteId = elements.ptScheduleDialog.dataset.siteId;
  if (!siteId) return;
  setBusy(true);
  try {
    await api(`/api/v1/pt-signin/sites/${encodeURIComponent(siteId)}/schedule`, {
      method: "PATCH",
      body: JSON.stringify({
        interval_hours: Number(elements.ptScheduleInterval.value),
        timeout_seconds: Number(elements.ptScheduleTimeout.value),
        random_delay_minutes: Number(elements.ptScheduleRandomDelay.value),
        retry_interval_hours: Number(elements.ptScheduleRetryInterval.value),
        max_retries: Number(elements.ptScheduleMaxRetries.value),
      }),
    });
    closePtSchedule();
    await refresh({ quiet: true });
    showToast("签到调度已保存");
  } catch (error) {
    showToast(error.message, true);
  } finally {
    setBusy(false);
  }
});

elements.ptCredential.addEventListener("change", applyPtCredentialSuggestion);
elements.ptUrl.addEventListener("input", () => { elements.ptUrl.dataset.suggested = "false"; });
elements.ptForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  setBusy(true);
  try {
    await api("/api/v1/pt-signin/sites", {
      method: "POST",
      body: JSON.stringify({
        name: elements.ptName.value.trim(),
        credential_id: elements.ptCredential.value,
        url: elements.ptUrl.value.trim(),
        interval_hours: Number(elements.ptInterval.value),
        timeout_seconds: Number(elements.ptTimeout.value),
        random_delay_minutes: Number(elements.ptRandomDelay.value),
        retry_interval_hours: Number(elements.ptRetryInterval.value),
        max_retries: Number(elements.ptMaxRetries.value),
        click_selector: elements.ptClickSelector.value.trim() || null,
        success_patterns: lineValues(elements.ptSuccessPatterns.value),
        already_patterns: lineValues(elements.ptAlreadyPatterns.value),
      }),
    });
    elements.ptForm.reset();
    elements.ptUrl.dataset.suggested = "false";
    await refresh({ quiet: true });
    showToast("签到任务已创建");
  } catch (error) {
    showToast(error.message, true);
  } finally {
    setBusy(false);
  }
});

elements.periodicTemplate.addEventListener("change", applyPeriodicTemplate);
elements.periodicScheduleCancel.addEventListener("click", () => elements.periodicScheduleDialog.close());
elements.periodicScheduleDismiss.addEventListener("click", () => elements.periodicScheduleDialog.close());
elements.periodicScheduleForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const siteId = elements.periodicScheduleDialog.dataset.siteId;
  if (!siteId) return;
  setBusy(true);
  try {
    await api(`/api/v1/periodic-signin/sites/${encodeURIComponent(siteId)}/schedule`, {
      method: "PATCH",
      body: JSON.stringify({
        interval_hours: Number(elements.periodicScheduleInterval.value),
        timeout_seconds: Number(elements.periodicScheduleTimeout.value),
        random_delay_minutes: Number(elements.periodicScheduleRandomDelay.value),
        retry_interval_hours: Number(elements.periodicScheduleRetryInterval.value),
        max_retries: Number(elements.periodicScheduleMaxRetries.value),
      }),
    });
    elements.periodicScheduleDialog.close();
    await refresh({ quiet: true });
    showToast("周期调度已保存");
  } catch (error) {
    showToast(error.message, true);
  } finally {
    setBusy(false);
  }
});

elements.periodicForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  setBusy(true);
  try {
    const template = elements.periodicTemplate.value;
    await api("/api/v1/periodic-signin/sites", {
      method: "POST",
      body: JSON.stringify({
        name: elements.periodicName.value.trim(),
        handler_type: elements.periodicHandler.value,
        credential_id: elements.periodicCredential.value || null,
        template_key: template === "nodeseek" ? "nodeseek" : null,
        url: elements.periodicUrl.value.trim(),
        interval_hours: Number(elements.periodicInterval.value),
        timeout_seconds: Number(elements.periodicTimeout.value),
        random_delay_minutes: Number(elements.periodicRandomDelay.value),
        retry_interval_hours: Number(elements.periodicRetryInterval.value),
        max_retries: Number(elements.periodicMaxRetries.value),
        method: elements.periodicMethod.value,
        wait_for_selector: elements.periodicWaitSelector.value.trim() || null,
        click_selector: elements.periodicClickSelector.value.trim() || null,
        click_role: elements.periodicClickRole.value.trim() || null,
        click_name: elements.periodicClickName.value.trim() || null,
        click_exact: elements.periodicClickExact.checked,
        wait_after_click_ms: Number(elements.periodicWaitAfter.value),
        success_patterns: lineValues(elements.periodicSuccessPatterns.value),
        already_patterns: lineValues(elements.periodicAlreadyPatterns.value),
        auth_expired_patterns: lineValues(elements.periodicAuthPatterns.value),
      }),
    });
    elements.periodicForm.reset();
    applyPeriodicTemplate();
    await refresh({ quiet: true });
    showToast("周期签到任务已创建");
  } catch (error) {
    showToast(error.message, true);
  } finally {
    setBusy(false);
  }
});

elements.selector.addEventListener("change", () => {
  state.selected = elements.selector.value;
  renderSelected();
  renderSummary();
  renderCredentials();
});

elements.form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const uuid = elements.uuid.value.trim();
  const password = elements.password.value;
  if (!uuid) return;
  setBusy(true);
  try {
    const selected = sourceByUuid(state.selected);
    if (selected?.configured && !password) {
      await api(`/api/v1/cookiecloud/sources/${encodeURIComponent(uuid)}/settings`, {
        method: "PATCH", body: JSON.stringify({ auto_import: elements.autoImport.checked }),
      });
    } else {
      await api(`/api/v1/cookiecloud/sources/${encodeURIComponent(uuid)}`, {
        method: "PUT", body: JSON.stringify({ uuid, password, auto_import: elements.autoImport.checked }),
      });
    }
    state.selected = uuid;
    await refresh({ quiet: true });
    showToast("CookieCloud 配置已保存");
  } catch (error) {
    showToast(error.message, true);
  } finally {
    setBusy(false);
  }
});

elements.importButton.addEventListener("click", async () => {
  const uuid = state.selected;
  if (!uuid) return;
  setBusy(true);
  try {
    const result = await api(`/api/v1/cookiecloud/sources/${encodeURIComponent(uuid)}/import`, {
      method: "POST", body: JSON.stringify({ password: null }),
    });
    await refresh({ quiet: true });
    showToast(`导入完成：${result.credentials.length} 个域名`);
  } catch (error) {
    showToast(error.message, true);
  } finally {
    setBusy(false);
  }
});

elements.refreshButton.addEventListener("click", () => {
  if (state.activeView === "upgrade") loadUpgradeStatus();
  else if (state.activeView === "logs") loadDebugLogs();
  else if (state.activeView === "browser-control") loadBrowserControlStatus();
  else refresh();
});
elements.copyButton.addEventListener("click", async () => {
  try {
    await writeClipboardText(elements.endpoint.textContent);
    showToast("连接地址已复制");
  } catch (_) {
    showToast("浏览器未允许复制，请手动选择地址", true);
  }
});
elements.uuid.addEventListener("input", updateCredentialCopyControls);
elements.password.addEventListener("input", updateCredentialCopyControls);
elements.copyUuidButton.addEventListener("click", () => (
  copyCredentialValue(elements.uuid.value.trim(), "UUID 已复制")
));
elements.copyPasswordButton.addEventListener("click", async () => {
  try {
    let password = elements.password.value;
    if (!password) {
      const uuid = state.selected;
      if (!uuid) return;
      const result = await api(
        `/api/v1/cookiecloud/sources/${encodeURIComponent(uuid)}/password/reveal`,
        { method: "POST", body: "{}", cache: "no-store" },
      );
      password = result.password;
    }
    await copyCredentialValue(password, "CookieCloud 密码已复制");
  } catch (error) {
    showToast(error.message, true);
  }
});
async function generateWebCredentialScript() {
  const baseUrl = elements.tokenSyncBaseUrl.value.trim();
  if (!baseUrl) throw new Error("请填写上送地址");
  const response = await fetch("/api/v1/web-credentials/userscript", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ base_url: baseUrl }),
  });
  if (!response.ok) {
    let message = `脚本生成失败 (${response.status})`;
    try { message = (await response.json()).detail || message; } catch (_) {}
    const error = new Error(message);
    error.status = response.status;
    throw error;
  }
  const script = await response.text();
  await loadWebCredentialStatus();
  return script;
}

elements.tokenScriptButton.addEventListener("click", async () => {
  setBusy(true);
  try {
    const script = await generateWebCredentialScript();
    const blobUrl = URL.createObjectURL(new Blob([script], { type: "text/javascript;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = blobUrl;
    link.download = "autosurf-web-credential-sync.user.js";
    document.body.append(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(blobUrl);
    showToast("同步脚本已下载；旧脚本的上传密钥同时失效");
  } catch (error) {
    if (error.status === 401) goToLogin();
    else showToast(error.message, true);
  } finally {
    setBusy(false);
  }
});
elements.tokenScriptCopyButton.addEventListener("click", async () => {
  setBusy(true);
  try {
    const script = await generateWebCredentialScript();
    await writeClipboardText(script);
    showToast("同步脚本已复制；旧脚本的上传密钥同时失效");
  } catch (error) {
    if (error.status === 401) goToLogin();
    else showToast(error.message || "浏览器未允许复制", true);
  } finally {
    setBusy(false);
  }
});

elements.siteBackupButton.addEventListener("click", async () => {
  setBusy(true);
  try {
    const response = await fetch("/api/v1/site-settings/backup", { cache: "no-store" });
    if (!response.ok) throw new Error(`备份失败 (${response.status})`);
    const disposition = response.headers.get("Content-Disposition") || "";
    const filename = disposition.match(/filename="([^"]+)"/)?.[1] || "autosurf-site-settings.zip";
    const blobUrl = URL.createObjectURL(await response.blob());
    const link = document.createElement("a");
    link.href = blobUrl;
    link.download = filename;
    document.body.append(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(blobUrl);
    showToast("站点设置备份已生成");
  } catch (error) {
    showToast(error.message, true);
  } finally {
    setBusy(false);
  }
});
elements.lanOnlyAccess.addEventListener("change", async () => {
  const requested = elements.lanOnlyAccess.checked;
  elements.lanOnlyAccess.disabled = true;
  try {
    const result = await api("/api/v1/system/access", {
      method: "PATCH", body: JSON.stringify({ lan_only: requested }),
    });
    state.lanOnly = result.lan_only;
    elements.lanOnlyAccess.checked = state.lanOnly;
    showToast(state.lanOnly ? "已限制为局域网访问" : "已允许非局域网访问");
  } catch (error) {
    elements.lanOnlyAccess.checked = state.lanOnly;
    if (error.status === 401) goToLogin();
    else showToast(error.message, true);
  } finally {
    elements.lanOnlyAccess.disabled = false;
  }
});
elements.siteRestoreButton.addEventListener("click", () => elements.siteRestoreFile.click());
elements.siteRestoreFile.addEventListener("change", async () => {
  const file = elements.siteRestoreFile.files?.[0];
  elements.siteRestoreFile.value = "";
  if (!file || !window.confirm("恢复会替换现有站点任务、凭据和 CookieCloud 配置，继续？")) return;
  setBusy(true);
  try {
    const response = await fetch("/api/v1/site-settings/restore", {
      method: "POST", headers: { "Content-Type": "application/zip" }, body: file,
    });
    if (!response.ok) {
      let message = `恢复失败 (${response.status})`;
      try { message = (await response.json()).detail || message; } catch (_) {}
      throw new Error(message);
    }
    const result = await response.json();
    state.selected = "";
    await refresh({ quiet: true });
    showToast(`已恢复 ${result.automation_count} 个任务和 ${result.credential_count} 个凭据`);
  } catch (error) {
    showToast(error.message, true);
  } finally {
    setBusy(false);
  }
});
elements.webCredentialRows.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-web-credential-clear]");
  if (!button) return;
  const sourceKey = button.dataset.webCredentialClear;
  const status = state.webCredentials.find((item) => item.source_key === sourceKey);
  if (!status || !window.confirm(`清除 AutoSurf 中已同步的 ${status.site} Web 凭据？`)) return;
  setBusy(true);
  try {
    await api(`/api/v1/web-credentials/${encodeURIComponent(sourceKey)}/values`, { method: "DELETE" });
    await loadWebCredentialStatus();
    showToast(`${status.site} Web 凭据已清除`);
  } catch (error) {
    showToast(error.message, true);
  } finally {
    setBusy(false);
  }
});
elements.debugLogRefresh.addEventListener("click", () => loadDebugLogs());
for (const filter of [elements.debugLogAutomation, elements.debugLogStatus, elements.debugLogOutcome]) {
  filter.addEventListener("change", () => loadDebugLogs({ quiet: true }));
}
elements.debugLogRows.addEventListener("click", (event) => {
  const button = event.target.closest("[data-debug-log-id]");
  if (!button) return;
  const item = state.debugLogs.find((entry) => entry.id === button.dataset.debugLogId);
  if (item) openDebugLog(item);
});
elements.debugLogDialogClose.addEventListener("click", closeDebugLog);
elements.debugLogDialogDismiss.addEventListener("click", closeDebugLog);
elements.debugLogDialog.addEventListener("close", () => elements.debugLogArtifact.removeAttribute("src"));
elements.debugLogArtifact.addEventListener("error", () => {
  elements.debugLogArtifact.hidden = true;
  elements.debugLogArtifactState.hidden = false;
});
elements.logoutButton.addEventListener("click", async () => {
  try { await fetch("/api/auth/logout", { method: "POST" }); } finally { location.replace("/login"); }
});
elements.upgradeStartButton.addEventListener("click", async () => {
  elements.upgradeStartButton.disabled = true;
  elements.upgradeStartButton.textContent = "正在启动...";
  try {
    const status = await api("/api/v1/system/upgrade", { method: "POST", body: "{}" });
    renderUpgradeStatus(status);
    waitForUpgrade();
  } catch (error) {
    showToast(error.message, true);
    await loadUpgradeStatus();
  }
});

const settingsTabs = [...elements.settingsTabs];
settingsTabs.forEach((button, index) => {
  button.addEventListener("click", () => setActiveView(button.dataset.settingsTab));
  button.addEventListener("keydown", (event) => {
    let nextIndex = null;
    if (event.key === "ArrowRight") nextIndex = (index + 1) % settingsTabs.length;
    if (event.key === "ArrowLeft") nextIndex = (index - 1 + settingsTabs.length) % settingsTabs.length;
    if (event.key === "Home") nextIndex = 0;
    if (event.key === "End") nextIndex = settingsTabs.length - 1;
    if (nextIndex === null) return;
    event.preventDefault();
    settingsTabs[nextIndex].focus();
    setActiveView(settingsTabs[nextIndex].dataset.settingsTab);
  });
});
const ptTabs = [...elements.ptTabs];
ptTabs.forEach((button, index) => {
  button.addEventListener("click", () => setActivePtTab(button.dataset.ptTab));
  button.addEventListener("keydown", (event) => {
    let nextIndex = null;
    if (event.key === "ArrowRight") nextIndex = (index + 1) % ptTabs.length;
    if (event.key === "ArrowLeft") nextIndex = (index - 1 + ptTabs.length) % ptTabs.length;
    if (event.key === "Home") nextIndex = 0;
    if (event.key === "End") nextIndex = ptTabs.length - 1;
    if (nextIndex === null) return;
    event.preventDefault();
    ptTabs[nextIndex].focus();
    setActivePtTab(ptTabs[nextIndex].dataset.ptTab);
  });
});
const signinTabs = [...elements.signinTabs];
signinTabs.forEach((button, index) => {
  button.addEventListener("click", () => setActiveSigninTab(button.dataset.signinTab));
  button.addEventListener("keydown", (event) => {
    let nextIndex = null;
    if (event.key === "ArrowRight") nextIndex = (index + 1) % signinTabs.length;
    if (event.key === "ArrowLeft") nextIndex = (index - 1 + signinTabs.length) % signinTabs.length;
    if (event.key === "Home") nextIndex = 0;
    if (event.key === "End") nextIndex = signinTabs.length - 1;
    if (nextIndex === null) return;
    event.preventDefault();
    signinTabs[nextIndex].focus();
    setActiveSigninTab(signinTabs[nextIndex].dataset.signinTab);
  });
});
const periodicTabs = [...elements.periodicTabs];
periodicTabs.forEach((button, index) => {
  button.addEventListener("click", () => setActivePeriodicTab(button.dataset.periodicTab));
  button.addEventListener("keydown", (event) => {
    let nextIndex = null;
    if (event.key === "ArrowRight") nextIndex = (index + 1) % periodicTabs.length;
    if (event.key === "ArrowLeft") nextIndex = (index - 1 + periodicTabs.length) % periodicTabs.length;
    if (event.key === "Home") nextIndex = 0;
    if (event.key === "End") nextIndex = periodicTabs.length - 1;
    if (nextIndex === null) return;
    event.preventDefault();
    periodicTabs[nextIndex].focus();
    setActivePeriodicTab(periodicTabs[nextIndex].dataset.periodicTab);
  });
});
window.addEventListener("hashchange", () => setActiveView(location.hash.slice(1), { syncHash: false }));
document.addEventListener("visibilitychange", () => {
  setBrowserControlPolling(state.activeView === "browser-control" && !document.hidden);
  if (!document.hidden) {
    refreshExecutionStates();
    if (state.activeView === "browser-control") loadBrowserControlStatus({ quiet: true });
  }
});
window.setInterval(refreshExecutionStates, 15_000);

setActiveSigninTab("tasks");
setActivePeriodicTab("tasks");
applyPeriodicTemplate();
setActiveView(location.hash.slice(1));
refresh({ quiet: true });
