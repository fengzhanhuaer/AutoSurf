const state = { sources: [], credentials: [], selected: "" };

const elements = {
  body: document.body,
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
};

elements.endpoint.textContent = `${location.origin}/cookiecloud`;

function formatDate(value) {
  if (!value) return "暂无";
  const date = new Date(value.endsWith?.("Z") ? value : `${value}Z`);
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
    throw new Error(detail);
  }
  return response.json();
}

function sourceByUuid(uuid) {
  return state.sources.find((item) => item.uuid === uuid);
}

function showToast(message, error = false) {
  elements.toast.textContent = message;
  elements.toast.classList.toggle("error", error);
  elements.toast.hidden = false;
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => { elements.toast.hidden = true; }, 3200);
}

function setBusy(busy) {
  elements.body.classList.toggle("loading", busy);
  elements.saveButton.disabled = busy;
  elements.refreshButton.disabled = busy;
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
  elements.passwordHint.textContent = source?.password_configured
    ? "已设置；留空将保留当前密码"
    : "新配置必须填写密码";
  elements.autoImport.checked = source ? source.auto_import : true;
  elements.importButton.disabled = !source?.configured || !source?.password_configured || !source?.blob_updated_at;

  document.querySelector("#status-uuid").textContent = uuid || "未选择";
  document.querySelector("#last-upload").textContent = formatDate(source?.blob_updated_at);
  document.querySelector("#last-import").textContent = formatDate(source?.last_import_at);
  document.querySelector("#auto-import-state").textContent = source
    ? (source.auto_import ? "已启用" : "已停用")
    : "未配置";
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
  document.querySelector("#sync-state").textContent = selected?.last_error
    ? "同步异常"
    : selected?.last_import_at
      ? "最近导入成功"
      : selected?.blob_updated_at
        ? "等待首次导入"
        : configured ? "等待浏览器上传" : "等待配置";
}

function renderCredentials() {
  const prefix = state.selected ? `cookiecloud:${state.selected}:` : "cookiecloud:";
  const credentials = state.credentials.filter((item) => item.provider === "cookiecloud" && item.name.startsWith(prefix));
  elements.rows.innerHTML = "";
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

function render() {
  renderSelector();
  renderSelected();
  renderSummary();
  renderCredentials();
}

async function refresh({ quiet = false } = {}) {
  setBusy(true);
  try {
    const [sources, credentials] = await Promise.all([
      api("/api/v1/cookiecloud/sources"),
      api("/api/v1/credentials"),
    ]);
    state.sources = sources.items;
    state.credentials = credentials.items;
    if (state.selected && !sourceByUuid(state.selected)) state.selected = "";
    if (!state.selected && state.sources.length === 1) state.selected = state.sources[0].uuid;
    render();
    if (!quiet) showToast("状态已刷新");
  } catch (error) {
    showToast(error.message, true);
  } finally {
    setBusy(false);
  }
}

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
        method: "PATCH",
        body: JSON.stringify({ auto_import: elements.autoImport.checked }),
      });
    } else {
      await api(`/api/v1/cookiecloud/sources/${encodeURIComponent(uuid)}`, {
        method: "PUT",
        body: JSON.stringify({ uuid, password, auto_import: elements.autoImport.checked }),
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

elements.refreshButton.addEventListener("click", () => refresh());
elements.copyButton.addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(elements.endpoint.textContent);
    showToast("连接地址已复制");
  } catch (_) {
    showToast("浏览器未允许复制，请手动选择地址", true);
  }
});

refresh({ quiet: true });
