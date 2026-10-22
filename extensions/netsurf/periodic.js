(function (root) {
  const catalog = [
    {id: "nodeseek", name: "NodeSeek", url: "https://www.nodeseek.com/board", hosts: ["www.nodeseek.com", "nodeseek.com"]},
    {id: "invitesfun", name: "InvitesFun", url: "https://www.invites.fun/", hosts: ["www.invites.fun", "invites.fun"]}
  ];
  const defaults = {enabled: false, startTime: "08:00", intervalHours: 24, timeout: 60, randomDelayMinutes: 0, retryIntervalHours: 2, maxRetries: 3};
  function config(value = {}) {
    if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("定时任务设置格式无效");
    const result = {...defaults, ...value};
    if (typeof result.enabled !== "boolean" || typeof result.startTime !== "string" || !/^([01]\d|2[0-3]):[0-5]\d$/.test(result.startTime)) throw new Error("启用状态或开始时间无效");
    for (const [field, minimum, maximum] of [["intervalHours", 1, 720], ["timeout", 5, 180], ["randomDelayMinutes", 0, 1440], ["retryIntervalHours", 1, 168], ["maxRetries", 0, 20]]) {
      if (!Number.isInteger(result[field]) || result[field] < minimum || result[field] > maximum) throw new Error("任务周期、重试或超时超出允许范围");
    }
    return {...defaults, enabled: result.enabled};
  }
  function settings(value = {}) {
    if (!value || typeof value !== "object" || Array.isArray(value) || Object.keys(value).some(key => !catalog.some(site => site.id === key))) throw new Error("未知定时任务");
    return Object.fromEntries(catalog.map(site => [site.id, config(value[site.id])]));
  }
  function origins(site) { return site.hosts.map(host => `https://${host}/*`); }
  function day(timestamp = Date.now()) { const date = new Date(timestamp); return `${date.getFullYear()}-${date.getMonth() + 1}-${date.getDate()}`; }
  function start(configured, timestamp = Date.now()) {
    const date = new Date(timestamp);
    const [hours, minutes] = configured.startTime.split(":").map(Number);
    date.setHours(hours, minutes, 0, 0);
    return date.getTime();
  }
  function nextRun(configured, timestamp = Date.now()) {
    const date = new Date(start(configured, timestamp));
    date.setDate(date.getDate() + 1);
    return date.getTime();
  }
  function firstRun(configured, timestamp = Date.now()) {
    return Math.max(timestamp + 1000, start(configured, timestamp));
  }
  async function pageAction(taskId, action, token, timeoutMs) {
    const hosts = taskId === "nodeseek" ? ["www.nodeseek.com", "nodeseek.com"] : taskId === "invitesfun" ? ["www.invites.fun", "invites.fun"] : [];
    const path = taskId === "nodeseek" ? "/board" : "/";
    if (location.protocol !== "https:" || location.port || !hosts.includes(location.hostname) || location.pathname !== path) return {status: "error", message: "站点地址已改变，未提交"};
    const visible = element => {
      if (!element || element.hidden) return false;
      const style = getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
    };
    const labels = {ready: "待签到", already_done: "今日已签到", success: "签到成功", blocked: "需要在原站完成安全验证", login_required: "请先在原站登录", unknown: "未识别到明确的签到状态"};
    function inspect() {
      const text = document.body?.innerText || "";
      let status = "unknown";
      const controls = selector => Array.from(document.querySelectorAll(selector)).filter(visible);
      if (/Just a moment|验证您是真人|无法连接人机验证服务|当前环境正在被调试|雷池\s*WAF/i.test(text) || controls('iframe[src*="captcha"], iframe[src*="challenges.cloudflare.com"], input[name="captcha"], input[name="imagestring"]').length) status = "blocked";
      else if (controls('input[type="password"]').length) status = "login_required";
      else if (taskId === "invitesfun") {
        if (controls(".item-forum-checkin .CheckInButton--green").length) status = "already_done";
        else if (controls(".checkInResultModal .successTitleText, .Alert--success").some(element => /签到成功|您已签到\s*\d+\s*天|获得\s*\d+.*奖励/.test(element.innerText))) status = "success";
        else if (controls(".item-forum-checkin .CheckInButton--yellow").filter(element => !element.disabled).length === 1) status = "ready";
        else if (controls(".LogInButton").length || /登录后签到|请先登录/.test(text)) status = "login_required";
      } else {
        const board = document.querySelector(".board .head-info");
        const attendance = board ? board.innerText : text;
        if (/今日签到获得鸡腿\s*\d+\s*个|今日已签到|今天已签到|已经签到|重复签到/.test(attendance)) status = "already_done";
        else if (/签到成功/.test(attendance)) status = "success";
        else if (/登录后签到|请先登录|未登录/.test(text)) status = "login_required";
        else if (board && /今日(?:还)?未签到/.test(attendance) && controls(".board .head-info button").some(element => !element.disabled && /^鸡腿\s*[x×]\s*\d+$/.test(element.innerText.trim()))) status = "ready";
        else if (!board && controls("button, a, [role=button]").some(element => !element.disabled && /^(?:每日)?签到$/.test(element.innerText.trim()))) status = "ready";
      }
      return {status, message: labels[status]};
    }
    const initial = inspect();
    if (action !== "run" || initial.status !== "ready") return initial;
    const permit = await chrome.runtime.sendMessage({type: "periodic-permit", taskId, token});
    if (!permit?.accepted) return {status: "error", message: "任务已停用、过期或已提交，未再次签到"};
    if (taskId === "nodeseek") {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), timeoutMs);
      try {
        const response = await fetch("/api/attendance?random=false", {method: "POST", credentials: "include", redirect: "error", headers: {"Content-Type": "application/json"}, body: JSON.stringify({random: false}), signal: controller.signal});
        if ([403, 429, 468].includes(response.status)) return {status: "blocked", message: labels.blocked};
        if (response.status === 401) return {status: "login_required", message: labels.login_required};
        if (!response.ok || !response.headers.get("content-type")?.includes("json")) return {status: "error", message: "签到响应异常，已停止提交；后续只读核验"};
        const payload = await response.json();
        const message = typeof payload.message === "string" ? payload.message : "";
        const status = /今日已签到|已经签到|重复签到|今日签到获得鸡腿\s*\d+\s*个/.test(message) ? "already_done" : payload.success === true ? "success" : /请先登录|未登录|登录后/.test(message) ? "login_required" : "error";
        return {status, message: labels[status] || "未取得明确签到成功响应，已停止提交"};
      } catch { return {status: "error", message: "签到请求中断，结果未确认；不会自动重新提交"}; }
      finally { clearTimeout(timer); }
    }
    const buttons = Array.from(document.querySelectorAll(".item-forum-checkin .CheckInButton--yellow")).filter(element => visible(element) && !element.disabled);
    if (buttons.length !== 1) return {status: "error", message: "签到按钮已改变，未点击"};
    buttons[0].click();
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      await new Promise(resolve => setTimeout(resolve, 250));
      const current = inspect();
      if (["success", "already_done", "blocked", "login_required"].includes(current.status)) return current;
    }
    return {status: "error", message: "签到核验超时，已停止提交；后续只读核验"};
  }
  const api = {catalog, defaults, config, settings, origins, day, start, nextRun, firstRun, pageAction};
  root.NetSurfPeriodic = api;
  if (typeof module !== "undefined") module.exports = api;
})(globalThis);
