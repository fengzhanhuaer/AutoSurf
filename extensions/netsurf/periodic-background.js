(function (root) {
  function create(chrome, clock = () => Date.now(), random = () => Math.random()) {
    const tasks = root.NetSurfPeriodic;
    const prefix = "netsurf-periodic:";
    let stateQueue = Promise.resolve();
    let runQueue = Promise.resolve();
    const catalog = tasks.catalog;
    async function script(tabId, args, deadline) {
      let timer;
      try {
        return await Promise.race([
          chrome.scripting.executeScript({target: {tabId}, injectImmediately: true, func: tasks.pageAction, args}),
          new Promise((resolve, reject) => { timer = setTimeout(() => reject(new Error("页面响应超时")), Math.max(1, deadline - clock())); })
        ]);
      } finally { clearTimeout(timer); }
    }
    async function read() {
      const stored = await chrome.storage.local.get(["periodicTasks", "periodicState", "periodicHistory"]);
      return {tasks: tasks.settings(stored.periodicTasks), states: stored.periodicState || {}, history: stored.periodicHistory || []};
    }
    function update(taskId, patch) {
      const pending = stateQueue.catch(() => {}).then(async () => {
        const {states} = await read();
        const current = states[taskId] || {};
        const next = {...current, ...patch};
        await chrome.storage.local.set({periodicState: {...states, [taskId]: next}});
        return next;
      });
      stateQueue = pending;
      return pending;
    }
    async function schedule() {
      const state = await read();
      for (const site of catalog) {
        const name = prefix + site.id;
        await chrome.alarms.clear(name);
        if (state.tasks[site.id].enabled && Number.isFinite(state.states[site.id]?.nextAt)) await chrome.alarms.create(name, {when: Math.max(clock() + 1000, state.states[site.id].nextAt)});
      }
    }
    async function finish(taskId, result, mode) {
      const time = new Date(clock()).toISOString();
      const state = await read();
      const current = state.states[taskId] || {};
      const completed = ["success", "already_done"].includes(result.status);
      const lastResult = {...result, time};
      const next = {lastResult};
      if (completed) { next.completedDay = tasks.day(clock()); next.operation = null; }
      if (mode === "run") {
        const configured = state.tasks[taskId];
        const attempts = (current.attempts || 0) + 1;
        const retry = result.status === "error" && !current.operation?.submitted && attempts <= configured.maxRetries;
        next.attempts = retry ? attempts : 0;
        if (retry) next.nextAt = clock() + configured.retryIntervalHours * 3600000;
        else next.nextAt = tasks.nextRun(configured, clock());
      }
      await update(taskId, next);
      const {periodicHistory = []} = await chrome.storage.local.get("periodicHistory");
      await chrome.storage.local.set({periodicHistory: [{taskId, mode, ...lastResult}, ...periodicHistory].slice(0, 50)});
      return lastResult;
    }
    async function cleanup() {
      const {periodicTaskTab} = await chrome.storage.session.get("periodicTaskTab");
      if (!periodicTaskTab) return;
      const site = catalog.find(item => item.id === periodicTaskTab.taskId);
      const tabs = site ? await chrome.tabs.query({}) : [];
      const tab = tabs.find(item => item.id === periodicTaskTab.tabId);
      if (tab && !tab.active) await chrome.tabs.remove(tab.id);
      await chrome.storage.session.remove("periodicTaskTab");
    }
    async function permit(message, sender) {
      const site = catalog.find(item => item.id === message.taskId);
      if (!site || !sender.tab || !sender.url) return {accepted: false};
      const url = new URL(sender.url);
      if (url.protocol !== "https:" || url.port || !site.hosts.includes(url.hostname) || url.pathname !== new URL(site.url).pathname) return {accepted: false};
      if (!await chrome.permissions.contains({origins: tasks.origins(site)})) return {accepted: false};
      const pending = stateQueue.catch(() => {}).then(async () => {
        const state = await read();
        const current = state.states[site.id];
        const operation = current?.operation;
        if (!state.tasks[site.id].enabled || !operation || operation.token !== message.token || operation.tabId !== sender.tab.id || operation.submitted || operation.deadline <= clock() || operation.day !== tasks.day(clock())) return {accepted: false};
        await chrome.storage.local.set({periodicState: {...state.states, [site.id]: {...current, operation: {...operation, submitted: true}}}});
        return {accepted: true};
      });
      stateQueue = pending;
      return pending;
    }
    async function execute(taskId, mode = "inspect") {
      const site = catalog.find(item => item.id === taskId);
      if (!site) throw new Error("未知定时任务");
      let state = await read();
      const configured = state.tasks[taskId];
      if (!configured.enabled) return {status: "disabled", message: "请先启用该定时任务"};
      if (mode === "run" && state.states[taskId]?.completedDay === tasks.day(clock())) return finish(taskId, {status: "already_done", message: "今日已有已核验签到记录，已跳过重复提交"}, mode);
      if (!await chrome.permissions.contains({origins: tasks.origins(site)})) return finish(taskId, {status: "error", message: "未授予站点访问权限，请重新启用该任务"}, mode);
      await cleanup();
      const deadline = clock() + configured.timeout * 1000;
      let tab;
      try {
        tab = await chrome.tabs.create({url: "about:blank", active: false});
        await chrome.storage.session.set({periodicTaskTab: {tabId: tab.id, taskId}});
        await chrome.tabs.update(tab.id, {url: site.url});
        let snapshot = {status: "unknown", message: "站点页面尚未就绪"};
        let phase = "页面导航";
        while (clock() < deadline) {
          try {
            const replies = await script(tab.id, [taskId, "inspect", null, Math.max(1, deadline - clock())], deadline);
            phase = "页面识别";
            snapshot = replies?.[0]?.result || snapshot;
            if (snapshot.status !== "unknown" && snapshot.status !== "error") break;
          } catch { phase = "脚本注入"; }
          await new Promise(resolve => setTimeout(resolve, 300));
        }
        if (mode === "inspect" || snapshot.status !== "ready") return await finish(taskId, snapshot.status === "unknown" || snapshot.status === "error" ? {status: "error", message: `签到状态核验超时（阶段：${phase}，路径：${new URL(site.url).pathname}）：${snapshot.message}`} : snapshot, mode);
        state = await read();
        if (!state.tasks[taskId].enabled) return {status: "disabled", message: "任务已停用，未提交"};
        if (state.states[taskId]?.operation?.submitted && state.states[taskId].operation.day === tasks.day(clock())) return await finish(taskId, {status: "error", message: "先前提交未取得成功证据，本次仅只读核验，未再次提交"}, mode);
        const token = `${clock()}-${random()}`;
        await update(taskId, {operation: {token, tabId: tab.id, deadline, day: tasks.day(clock()), submitted: false}});
        const remaining = Math.max(1, deadline - clock());
        const result = await script(tab.id, [taskId, "run", token, remaining], deadline);
        return await finish(taskId, result?.[0]?.result || {status: "error", message: "未收到明确签到结果，已停止提交"}, mode);
      } catch { return await finish(taskId, {status: "error", message: "页面加载或签到通信失败；若已提交，后续仅只读核验"}, mode); }
      finally { await cleanup(); }
    }
    function run(taskId, mode) {
      const pending = runQueue.catch(() => {}).then(() => execute(taskId, mode)).finally(schedule);
      runQueue = pending;
      return pending;
    }
    async function save(taskId, value) {
      const site = catalog.find(item => item.id === taskId);
      if (!site) throw new Error("未知定时任务");
      const state = await read();
      const configured = tasks.config({...state.tasks[taskId], ...value});
      if (configured.enabled && !await chrome.permissions.contains({origins: tasks.origins(site)})) throw new Error("未授予站点访问权限");
      await chrome.storage.local.set({periodicTasks: {...state.tasks, [taskId]: configured}});
      const nextAt = state.states[taskId]?.completedDay === tasks.day(clock()) ? tasks.nextRun(configured, clock()) : tasks.firstRun(configured, clock());
      await update(taskId, {nextAt: configured.enabled ? nextAt : null, attempts: 0});
      await schedule();
      return {saved: true, ...(await read())};
    }
    async function resume() {
      await cleanup();
      const state = await read();
      const {periodicTasks} = await chrome.storage.local.get("periodicTasks");
      for (const site of catalog) {
        const configured = state.tasks[site.id];
        const legacy = periodicTasks?.[site.id];
        const changed = legacy && Object.keys(tasks.defaults).some(field => legacy[field] !== undefined && legacy[field] !== configured[field]);
        if (configured.enabled && (changed || !Number.isFinite(state.states[site.id]?.nextAt))) {
          const nextAt = state.states[site.id]?.completedDay === tasks.day(clock()) ? tasks.nextRun(configured, clock()) : tasks.firstRun(configured, clock());
          await update(site.id, {nextAt, attempts: 0});
        }
      }
      if (periodicTasks) await chrome.storage.local.set({periodicTasks: state.tasks});
      await schedule();
    }
    async function alarm(name) {
      if (!name.startsWith(prefix)) return;
      const taskId = name.slice(prefix.length);
      const state = await read();
      if (!state.tasks[taskId]?.enabled) return;
      if (state.states[taskId]?.nextAt > clock()) return schedule();
      return run(taskId, "run");
    }
    async function open(taskId) {
      const site = catalog.find(item => item.id === taskId);
      if (!site) throw new Error("未知定时任务");
      const tabs = await chrome.tabs.query({url: tasks.origins(site)});
      if (tabs.length) { await chrome.tabs.update(tabs[0].id, {active: true}); await chrome.windows.update(tabs[0].windowId, {focused: true}); }
      else await chrome.tabs.create({url: site.url, active: true});
      return {opened: true};
    }
    return {read, save, permit, run, resume, alarm, open};
  }
  root.NetSurfPeriodicBackground = {create};
})(globalThis);
