(function () {
  const tasks = globalThis.NetSurfPeriodic;
  const element = id => document.getElementById(id);
  const labels = {success: "已完成", already_done: "已完成", ready: "待签到", error: "执行失败", blocked: "需验证", login_required: "需登录", unknown: "未识别", disabled: "已停用"};
  const saving = new Set();
  let busy = false;
  let loadRevision = 0;
  function node(tag, text, id) { const result = document.createElement(tag); if (text !== undefined) result.textContent = text; if (id) result.id = id; return result; }
  function time(value) { return value ? new Date(value).toLocaleString("zh-CN") : "—"; }
  async function send(type, extra = {}) {
    let timer;
    try {
      const response = await Promise.race([
        chrome.runtime.sendMessage({type: "periodic-" + type, ...extra}),
        new Promise((resolve, reject) => { timer = setTimeout(() => reject(new Error("任务通信超时，请重新加载 NetSurf 后核对开关")), ["inspect", "run"].includes(type) ? tasks.defaults.timeout * 1000 + 10000 : 10000); })
      ]);
      if (!response || type === "settings" && response.saved !== true) throw new Error(response?.error || "扩展后台未更新，请在扩展管理页重新加载 NetSurf");
      if (response.error) throw new Error(response.error);
      return response;
    } finally { clearTimeout(timer); }
  }
  function render(state) {
    element("periodic-summary").textContent = `${tasks.catalog.length} 个任务 · 已启用 ${Object.values(state.tasks).filter(item => item.enabled).length}`;
    element("periodic-run-all").disabled = busy || !tasks.catalog.some(site => state.tasks[site.id].enabled);
    for (const site of tasks.catalog) {
      const enabled = state.tasks[site.id].enabled;
      const toggle = element(`periodic-${site.id}-enabled`);
      if (!saving.has(site.id)) toggle.checked = enabled;
      toggle.disabled = saving.has(site.id);
      const record = state.states[site.id] || {};
      const completed = record.completedDay === tasks.day();
      const staleCompletion = ["success", "already_done"].includes(record.lastResult?.status) && !completed;
      const idle = enabled ? "待签到" : "未启用";
      const badge = element(`periodic-status-${site.id}`);
      badge.textContent = completed ? "已完成" : !enabled || staleCompletion ? idle : labels[record.lastResult?.status] || idle;
      badge.title = record.lastResult?.message || "尚无执行记录";
      badge.dataset.tone = completed ? "success" : enabled && record.lastResult ? "warning" : "neutral";
      element(`periodic-next-${site.id}`).textContent = enabled ? time(record.nextAt) : "—";
      element(`periodic-result-${site.id}`).textContent = record.lastResult ? `${time(record.lastResult.time)} · ${record.lastResult.message}` : "—";
      for (const action of ["open", "run"]) element(`periodic-${action}-${site.id}`).disabled = busy || (action !== "open" && !enabled);
    }
  }
  async function load() {
    if (!["#periodic", "#periodic-settings"].includes(window.location.hash)) return;
    const revision = ++loadRevision;
    try {
      const stored = await chrome.storage.local.get(["periodicTasks", "periodicState"]);
      if (revision === loadRevision) render({tasks: tasks.settings(stored.periodicTasks), states: stored.periodicState || {}});
    }
    catch (error) { element(window.location.hash === "#periodic-settings" ? "periodic-settings-feedback" : "periodic-feedback").textContent = error.message; }
  }
  async function save(site, toggle) {
    const enabled = toggle.checked;
    saving.add(site.id);
    toggle.disabled = true;
    const feedback = element("periodic-settings-feedback");
    feedback.textContent = "正在保存…";
    let message;
    try {
      if (enabled) {
        feedback.textContent = "等待 Chrome 授予站点访问权限…";
        if (!await chrome.permissions.request({origins: tasks.origins(site)})) throw new Error("未授权站点访问，任务未启用");
      }
      feedback.textContent = "正在保存…";
      await send("settings", {taskId: site.id, config: {enabled}});
      message = `${site.name} 每日签到已${enabled ? "开启" : "关闭"}`;
    } catch (error) { toggle.checked = !enabled; message = error.message; }
    finally { saving.delete(site.id); toggle.disabled = false; feedback.textContent = message; void load(); }
  }
  async function perform(site, action) {
    if (busy) return;
    busy = true;
    element("periodic-feedback").textContent = action === "open" ? "正在打开原站…" : "正在后台执行，请稍候…";
    for (const button of element("view-periodic").querySelectorAll("button")) button.disabled = true;
    try {
      if (site) {
        const result = await send(action, {taskId: site.id});
        element("periodic-feedback").textContent = action === "open" ? "已打开 " + site.name : result.message;
      } else {
        const stored = await chrome.storage.local.get(["periodicTasks", "periodicState"]);
        const configured = tasks.settings(stored.periodicTasks);
        const enabled = tasks.catalog.filter(item => configured[item.id].enabled);
        const pending = enabled.filter(item => stored.periodicState?.[item.id]?.completedDay !== tasks.day());
        let completed = 0;
        let failed = 0;
        for (const task of pending) {
          element("periodic-feedback").textContent = `正在执行 ${task.name}（${completed + failed + 1}/${pending.length}）…`;
          const result = await send("run", {taskId: task.id});
          if (["success", "already_done"].includes(result.status)) completed++;
          else failed++;
        }
        element("periodic-feedback").textContent = enabled.length ? `执行结束：完成 ${completed}，未完成 ${failed}，今日已完成跳过 ${enabled.length - pending.length}` : "没有已启用的任务，请先在设置中开启";
      }
    } catch (error) { element("periodic-feedback").textContent = (site ? "" : "一键执行已停止，剩余任务未执行：") + error.message; }
    finally { busy = false; await load(); }
  }
  for (const site of tasks.catalog) {
    const row = node("tr");
    const name = node("td"); name.append(node("strong", site.name), node("small", new URL(site.url).hostname));
    const status = node("td"); const badge = node("span", "未启用", `periodic-status-${site.id}`); badge.className = "status-badge"; status.append(badge);
    const result = node("td", "—", `periodic-result-${site.id}`); result.className = "periodic-result";
    const actions = node("td"); const buttons = node("div"); buttons.className = "row-actions";
    for (const [action, label] of [["open", "打开"], ["run", "执行"]]) {
      const button = node("button", label, `periodic-${action}-${site.id}`); button.type = "button"; button.className = "button " + (action === "run" ? "primary" : "secondary");
      button.disabled = action !== "open";
      button.addEventListener("click", () => perform(site, action)); buttons.append(button);
    }
    actions.append(buttons); row.append(name, status, result, node("td", "—", `periodic-next-${site.id}`), actions);
    element("periodic-task-list").append(row);
    const setting = node("label"); setting.className = "periodic-setting";
    const title = node("span"); title.append(node("strong", site.name), node("small", new URL(site.url).hostname));
    const toggle = node("input"); toggle.type = "checkbox"; toggle.className = "switch"; toggle.id = `periodic-${site.id}-enabled`; toggle.disabled = true;
    toggle.setAttribute("role", "switch"); toggle.setAttribute("aria-label", site.name + " 每日签到");
    toggle.addEventListener("change", () => save(site, toggle));
    setting.append(title, toggle); element("periodic-settings-list").append(setting);
  }
  element("periodic-run-all").addEventListener("click", () => perform(null, "run"));
  window.addEventListener("hashchange", load);
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area === "local" && ["periodicTasks", "periodicState", "periodicHistory"].some(key => changes[key])) load();
  });
  load();
})();
