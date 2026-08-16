const state = {
  sources: [],
  credentials: [],
  ptCandidates: [],
  ptSites: [],
  ptHistory: { today: null, days: [], items: [], latest_execution: null },
  ptStats: [],
  webCredential: null,
  ptSelection: new Set(),
  selected: "",
  activeView: "pt-signin",
  activePtTab: "signin",
  activeSigninTab: "tasks",
};

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
  ptPanel: document.querySelector("#pt-signin-panel"),
  ptTasksPanel: document.querySelector("#pt-tasks-panel"),
  ptHistoryPanel: document.querySelector("#pt-history-panel"),
  ptStatsPanel: document.querySelector("#pt-stats-panel"),
  ptStatsRows: document.querySelector("#pt-stats-rows"),
  cookieCloudPanel: document.querySelector("#cookiecloud-settings-panel"),
  webCredentialsPanel: document.querySelector("#web-credentials-settings-panel"),
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
  tokenScriptState: document.querySelector("#token-script-state"),
  tokenValueState: document.querySelector("#token-value-state"),
  tokenLastSync: document.querySelector("#token-last-sync"),
  tokenScriptButton: document.querySelector("#token-script-button"),
  tokenClearButton: document.querySelector("#token-clear-button"),
};

elements.endpoint.textContent = `${location.origin}/cookiecloud`;
elements.tokenSyncBaseUrl.value = location.origin;

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
  const activeView = ["cookiecloud", "web-credentials", "upgrade"].includes(value) ? value : "pt-signin";
  state.activeView = activeView;
  const systemView = activeView !== "pt-signin";
  elements.ptPanel.hidden = systemView || state.activePtTab !== "signin";
  elements.ptStatsPanel.hidden = systemView || state.activePtTab !== "stats";
  elements.cookieCloudPanel.hidden = activeView !== "cookiecloud";
  elements.webCredentialsPanel.hidden = activeView !== "web-credentials";
  elements.upgradePanel.hidden = activeView !== "upgrade";
  elements.settingsTabList.hidden = !systemView;
  elements.ptTabList.hidden = systemView;

  for (const item of elements.navItems) {
    const active = item.dataset.view === "pt-signin" ? !systemView : systemView;
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

  if (systemView) {
    elements.pageTitle.textContent = "系统设置";
    elements.pageDescription.textContent = "CookieCloud、Web 凭据、程序与浏览器运行时";
  } else {
    elements.pageTitle.textContent = "PT 站点";
    elements.pageDescription.textContent = "站点管理与自动化";
  }
  const refreshLabels = {
    "pt-signin": "刷新签到任务",
    cookiecloud: "刷新 CookieCloud 状态",
    "web-credentials": "刷新 Web 凭据同步状态",
    upgrade: "刷新升级状态",
  };
  elements.refreshButton.title = refreshLabels[activeView];
  elements.refreshButton.setAttribute("aria-label", refreshLabels[activeView]);
  if (syncHash && location.hash !== `#${activeView}`) {
    history.replaceState(null, "", `${location.pathname}${location.search}#${activeView}`);
  }
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

function setBusy(busy) {
  elements.body.classList.toggle("loading", busy);
  elements.saveButton.disabled = busy;
  elements.ptSaveButton.disabled = busy;
  elements.ptSelectAllButton.disabled = busy || selectablePtCandidates().length === 0;
  elements.ptCollectButton.disabled = busy || state.ptSelection.size === 0;
  elements.refreshButton.disabled = busy;
  elements.tokenScriptButton.disabled = busy;
  elements.tokenClearButton.disabled = busy || !state.webCredential?.token_configured;
}

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
  if (candidate.strategy === "profile_refresh_only") return "仅刷新个人信息";
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
      : candidate.strategy === "profile_refresh_only"
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
    elements.ptStatsRows.innerHTML = '<tr><td class="empty" colspan="9">暂无站点信息统计</td></tr>';
    return;
  }
  for (const item of state.ptStats) {
    const row = document.createElement("tr");
    row.title = item.updated_at ? `更新时间：${formatDate(item.updated_at)}` : "等待首次刷新";
    const stats = item.stats || {};
    const values = [
      item.name,
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
      cell.textContent = value;
      if (index === 0) cell.title = item.domain || item.name;
      if (index === 3) cell.className = "stat-uploaded";
      if (index === 4) cell.className = "stat-downloaded";
      row.append(cell);
    });
    elements.ptStatsRows.append(row);
  }
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

function renderWebCredential(status) {
  state.webCredential = status;
  elements.tokenSyncState.textContent = status.token_configured ? "同步正常"
    : status.script_configured ? "等待凭据" : "未配置";
  elements.tokenSyncState.className = `status-badge${status.token_configured ? " succeeded" : ""}`;
  elements.tokenScriptState.textContent = status.script_configured ? "已生成" : "未生成";
  elements.tokenValueState.textContent = status.token_configured ? "已加密保存" : "未同步";
  elements.tokenLastSync.textContent = formatDate(status.last_sync_at);
  elements.tokenScriptButton.textContent = status.script_configured ? "重新生成同步脚本" : "生成同步脚本";
  elements.tokenClearButton.disabled = !status.token_configured;
}

async function loadWebCredentialStatus() {
  const status = await api("/api/v1/web-credentials/rousi", { cache: "no-store" });
  renderWebCredential(status);
  return status;
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
  elements.upgradeBrowser.textContent = browser.installed
    ? `Chromium ${browser.chromium_version || browser.chromium_revision || "已安装"} · ${browserMode}` : "未安装";
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

async function copyCredentialValue(value, successMessage) {
  try {
    await navigator.clipboard.writeText(value);
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
    const [sources, credentials, ptCandidates, ptSites, ptHistory, ptStats, webCredential] = await Promise.all([
      api("/api/v1/cookiecloud/sources"),
      api("/api/v1/credentials"),
      api("/api/v1/pt-signin/candidates?include_unknown=true"),
      api("/api/v1/pt-signin/sites"),
      api(`/api/v1/pt-signin/history?days=7&timezone_offset=${timezoneOffset}`),
      api("/api/v1/pt-signin/stats"),
      api("/api/v1/web-credentials/rousi", { cache: "no-store" }),
    ]);
    state.sources = sources.items;
    state.credentials = credentials.items;
    state.ptCandidates = ptCandidates.items;
    state.ptSites = ptSites.items;
    state.ptHistory = ptHistory;
    state.ptStats = ptStats.items;
    state.webCredential = webCredential;
    if (state.selected && !sourceByUuid(state.selected)) state.selected = "";
    if (!state.selected && state.sources.length === 1) state.selected = state.sources[0].uuid;
    renderCookieCloud();
    renderPt();
    renderWebCredential(webCredential);
    if (!quiet) showToast("状态已刷新");
  } catch (error) {
    if (error.status === 401) goToLogin();
    else showToast(error.message, true);
  } finally {
    setBusy(false);
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
  else refresh();
});
elements.copyButton.addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(elements.endpoint.textContent);
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
elements.tokenScriptButton.addEventListener("click", async () => {
  const baseUrl = elements.tokenSyncBaseUrl.value.trim();
  if (!baseUrl) return;
  setBusy(true);
  try {
    const response = await fetch("/api/v1/web-credentials/rousi/userscript", {
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
    const blobUrl = URL.createObjectURL(await response.blob());
    const link = document.createElement("a");
    link.href = blobUrl;
    link.download = "autosurf-web-credential-sync.user.js";
    document.body.append(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(blobUrl);
    await loadWebCredentialStatus();
    showToast("同步脚本已生成；旧脚本的上传密钥同时失效");
  } catch (error) {
    if (error.status === 401) goToLogin();
    else showToast(error.message, true);
  } finally {
    setBusy(false);
  }
});
elements.tokenClearButton.addEventListener("click", async () => {
  if (!window.confirm("清除 AutoSurf 中已同步的 Rousi Web 凭据？")) return;
  setBusy(true);
  try {
    await api("/api/v1/web-credentials/rousi/token", { method: "DELETE" });
    await loadWebCredentialStatus();
    showToast("Rousi Web 凭据已清除");
  } catch (error) {
    showToast(error.message, true);
  } finally {
    setBusy(false);
  }
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
window.addEventListener("hashchange", () => setActiveView(location.hash.slice(1), { syncHash: false }));

setActiveSigninTab("tasks");
setActiveView(location.hash.slice(1));
refresh({ quiet: true });
