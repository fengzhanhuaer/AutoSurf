const state = {
  sources: [],
  credentials: [],
  ptCandidates: [],
  ptSites: [],
  ptExecutions: [],
  ptSelection: new Set(),
  selected: "",
  activeView: "pt-signin",
};

const elements = {
  body: document.body,
  pageTitle: document.querySelector("#page-title"),
  pageDescription: document.querySelector("#page-description"),
  navItems: document.querySelectorAll("[data-view]"),
  settingsTabList: document.querySelector("#settings-tabs"),
  settingsTabs: document.querySelectorAll("[data-settings-tab]"),
  ptPanel: document.querySelector("#pt-signin-panel"),
  cookieCloudPanel: document.querySelector("#cookiecloud-settings-panel"),
  upgradePanel: document.querySelector("#upgrade-settings-panel"),
  form: document.querySelector("#source-form"),
  selector: document.querySelector("#source-selector"),
  uuid: document.querySelector("#uuid"),
  password: document.querySelector("#password"),
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
  ptClickSelector: document.querySelector("#pt-click-selector"),
  ptSuccessPatterns: document.querySelector("#pt-success-patterns"),
  ptAlreadyPatterns: document.querySelector("#pt-already-patterns"),
  ptSaveButton: document.querySelector("#pt-save-button"),
  ptCandidateRows: document.querySelector("#pt-candidate-rows"),
  ptSelectAllButton: document.querySelector("#pt-select-all-button"),
  ptCollectButton: document.querySelector("#pt-collect-button"),
  ptCollectInterval: document.querySelector("#pt-collect-interval"),
  ptCollectTimeout: document.querySelector("#pt-collect-timeout"),
  ptUnknownCount: document.querySelector("#pt-unknown-count"),
  ptSiteRows: document.querySelector("#pt-site-rows"),
  ptHistoryRows: document.querySelector("#pt-history-rows"),
  upgradeStartButton: document.querySelector("#upgrade-start-button"),
  upgradeRevision: document.querySelector("#upgrade-revision"),
  upgradeRemoteRevision: document.querySelector("#upgrade-remote-revision"),
  upgradeDependencies: document.querySelector("#upgrade-dependencies"),
  upgradeBrowser: document.querySelector("#upgrade-browser"),
  upgradeState: document.querySelector("#upgrade-state"),
};

elements.endpoint.textContent = `${location.origin}/cookiecloud`;

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
  const activeView = ["cookiecloud", "upgrade"].includes(value) ? value : "pt-signin";
  state.activeView = activeView;
  const systemView = activeView !== "pt-signin";
  elements.ptPanel.hidden = systemView;
  elements.cookieCloudPanel.hidden = activeView !== "cookiecloud";
  elements.upgradePanel.hidden = activeView !== "upgrade";
  elements.settingsTabList.hidden = !systemView;

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
    elements.pageDescription.textContent = "CookieCloud、程序与浏览器运行时";
  } else {
    elements.pageTitle.textContent = "PT 站签到";
    elements.pageDescription.textContent = "PT 站点与执行记录";
  }
  const refreshLabels = {
    "pt-signin": "刷新签到任务",
    cookiecloud: "刷新 CookieCloud 状态",
    upgrade: "刷新升级状态",
  };
  elements.refreshButton.title = refreshLabels[activeView];
  elements.refreshButton.setAttribute("aria-label", refreshLabels[activeView]);
  if (syncHash && location.hash !== `#${activeView}`) {
    history.replaceState(null, "", `${location.pathname}${location.search}#${activeView}`);
  }
  if (activeView === "upgrade") await loadUpgradeStatus();
}

function setBusy(busy) {
  elements.body.classList.toggle("loading", busy);
  elements.saveButton.disabled = busy;
  elements.ptSaveButton.disabled = busy;
  elements.ptSelectAllButton.disabled = busy || selectablePtCandidates().length === 0;
  elements.ptCollectButton.disabled = busy || state.ptSelection.size === 0;
  elements.refreshButton.disabled = busy;
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
  const credentials = state.credentials
    .filter((item) => item.provider === "cookiecloud")
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
  const latest = state.ptExecutions[0];
  document.querySelector("#pt-recent-state").textContent = latest
    ? `${statusLabel(latest.status)} · ${latest.automation_name}`
    : "暂无记录";
}

function candidateReasonLabel(reason) {
  return ({
    site_catalog: "站点目录",
    cookie_signature: "PT Cookie 特征",
  })[reason] || "未识别";
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
  const recognized = state.ptCandidates.filter((item) => item.recognized);
  const validIds = new Set(selectablePtCandidates().map((item) => item.credential.id));
  state.ptSelection = new Set([...state.ptSelection].filter((id) => validIds.has(id)));
  elements.ptUnknownCount.textContent = state.ptCandidates.filter((item) => !item.recognized).length;
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

    for (const value of [candidate.name, candidate.credential.domain, candidateReasonLabel(candidate.reason)]) {
      const cell = document.createElement("td");
      cell.textContent = value;
      row.append(cell);
    }
    const statusCell = document.createElement("td");
    const badge = document.createElement("span");
    badge.className = `candidate-state ${candidate.configured ? "configured" : candidate.supported ? "available" : "unsupported"}`;
    badge.textContent = candidate.configured ? "已添加" : candidate.supported ? "可添加" : "待专用适配";
    statusCell.append(badge);
    row.append(statusCell);
    elements.ptCandidateRows.append(row);
  }
  updatePtCollectControls();
}

function renderPtSites() {
  elements.ptSiteRows.replaceChildren();
  if (!state.ptSites.length) {
    elements.ptSiteRows.innerHTML = '<tr><td class="empty" colspan="6">暂无签到任务</td></tr>';
    return;
  }
  for (const site of state.ptSites) {
    const row = document.createElement("tr");
    const values = [site.name, site.credential?.domain || "凭据已删除", `${site.interval_hours} 小时`, formatDate(site.next_run_at)];
    for (const value of values) {
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
    const enabledLabel = document.createElement("label");
    enabledLabel.className = "row-toggle";
    const enabled = document.createElement("input");
    enabled.type = "checkbox";
    enabled.checked = site.enabled;
    enabled.setAttribute("aria-label", `${site.name} 启用`);
    enabled.addEventListener("change", () => setPtSiteEnabled(site.id, enabled.checked));
    enabledLabel.append(enabled, document.createTextNode("启用"));
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
    actions.append(enabledLabel, run, remove);
    actionsCell.append(actions);
    row.append(actionsCell);
    elements.ptSiteRows.append(row);
  }
}

function renderPtHistory() {
  elements.ptHistoryRows.replaceChildren();
  if (!state.ptExecutions.length) {
    elements.ptHistoryRows.innerHTML = '<tr><td class="empty" colspan="5">暂无执行记录</td></tr>';
    return;
  }
  for (const execution of state.ptExecutions) {
    const row = document.createElement("tr");
    for (const value of [execution.automation_name, execution.domain || "暂无", formatDate(execution.scheduled_at)]) {
      const cell = document.createElement("td");
      cell.textContent = value;
      row.append(cell);
    }
    const statusCell = document.createElement("td");
    statusCell.append(statusBadge(execution.status));
    row.append(statusCell);
    const resultCell = document.createElement("td");
    resultCell.className = "result-cell";
    resultCell.textContent = resultText(execution);
    resultCell.title = resultText(execution);
    row.append(resultCell);
    elements.ptHistoryRows.append(row);
  }
}

function renderPt() {
  renderPtCredentialOptions();
  renderPtSummary();
  renderPtCandidates();
  renderPtSites();
  renderPtHistory();
}

async function setPtSiteEnabled(id, enabled) {
  try {
    await api(`/api/v1/pt-signin/sites/${encodeURIComponent(id)}/enabled`, {
      method: "PATCH", body: JSON.stringify({ enabled }),
    });
    await refresh({ quiet: true });
    showToast(enabled ? "签到任务已启用" : "签到任务已停用");
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
  elements.upgradeBrowser.textContent = browser.installed
    ? `Chromium ${browser.chromium_version || browser.chromium_revision || "已安装"}` : "未安装";
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
  elements.password.required = !source?.password_configured;
  elements.passwordHint.textContent = source?.password_configured ? "已设置；留空将保留当前密码" : "新配置必须填写密码";
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
    const [sources, credentials, ptCandidates, ptSites, ptExecutions] = await Promise.all([
      api("/api/v1/cookiecloud/sources"),
      api("/api/v1/credentials"),
      api("/api/v1/pt-signin/candidates?include_unknown=true"),
      api("/api/v1/pt-signin/sites"),
      api("/api/v1/pt-signin/executions"),
    ]);
    state.sources = sources.items;
    state.credentials = credentials.items;
    state.ptCandidates = ptCandidates.items;
    state.ptSites = ptSites.items;
    state.ptExecutions = ptExecutions.items;
    if (state.selected && !sourceByUuid(state.selected)) state.selected = "";
    if (!state.selected && state.sources.length === 1) state.selected = state.sources[0].uuid;
    renderCookieCloud();
    renderPt();
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
window.addEventListener("hashchange", () => setActiveView(location.hash.slice(1), { syncHash: false }));

setActiveView(location.hash.slice(1));
refresh({ quiet: true });
