(function (root) {
  function create(chrome, sites, readState) {
    let queue = Promise.resolve();

    async function permitted(message, sender, phase) {
      let target;
      try { target = new URL(sender.url); } catch { return null; }
      if (sender.id !== chrome.runtime.id || !sender.tab || sender.frameId !== 0 || target.protocol !== "https:" || !["hdsky.me", "www.hdsky.me", "open.cd", "www.open.cd", "ptsbao.club", "www.ptsbao.club"].includes(target.hostname) || target.port || target.search || target.hash) return null;
      const site = sites.resolve(sender.url);
      if (!["hdsky.me", "open.cd", "ptsbao.club"].includes(site?.id) || !(site.id === "ptsbao.club" ? target.pathname === "/attendance.php" : ["/", "/index.php"].includes(target.pathname)) || !await chrome.permissions.contains({origins: sites.origins(site)})) return null;
      const state = await readState(site.id);
      const operation = state.operation;
      const expectedPhase = site.id === "ptsbao.club" && phase === "preparing" ? "continuing" : phase;
      if (!state.sites[site.id]?.enabled || state.sites[site.id].refreshOnly || operation?.automatic && !state.autoEnabled || state.verifiedDay === sites.day() || operation?.tabId !== sender.tab.id || operation.day !== sites.day() || operation.startedAt !== message.operationId || operation.awaitingConfirmation !== true || !(Date.now() < operation.deadline) || operation.phase !== expectedPhase) return null;
      const tab = await chrome.tabs.get(sender.tab.id);
      if (tab.url !== sender.url) return null;
      return {operation, siteId: site.id};
    }

    async function infer(image, deadline) {
      const url = chrome.runtime.getURL("ocr.html");
      const contexts = await chrome.runtime.getContexts({contextTypes: ["OFFSCREEN_DOCUMENT"], documentUrls: [url]});
      if (!contexts.length) await chrome.offscreen.createDocument({url: "ocr.html", reasons: ["BLOBS"], justification: "在本地解码 PNG Blob、画布预处理并执行捆绑 OCR 模型"});
      let timeout;
      try {
        return await Promise.race([
          chrome.runtime.sendMessage({type: "netsurf-ocr-infer", image}),
          new Promise((resolve, reject) => { timeout = setTimeout(() => reject(new Error("ocr_timeout")), Math.max(1, Math.min(40000, deadline - Date.now()))); })
        ]);
      } finally {
        clearTimeout(timeout);
        await chrome.offscreen.closeDocument().catch(() => {});
      }
    }

    async function action(message, sender) {
      if (message.type === "captcha-open") {
        const permittedEntry = await permitted(message, sender, "preparing");
        if (permittedEntry?.siteId !== "open.cd" || permittedEntry.operation.captchaOpened) return {accepted: false};
        await chrome.storage.local.set({[sites.key("operation", permittedEntry.siteId)]: {...permittedEntry.operation, captchaOpened: true}});
        return {accepted: true};
      }
      if (message.type === "captcha-recognize") {
        if (typeof message.image !== "string" || message.image.length > 1400000 || !/^data:image\/png;base64,[A-Za-z0-9+/=]+$/.test(message.image)) return {accepted: false};
        const allowed = await permitted(message, sender, "preparing");
        if (!allowed) return {accepted: false};
        const {operation, siteId} = allowed;
        const key = sites.key("operation", siteId);
        await chrome.storage.local.set({[key]: {...operation, phase: "recognizing"}});
        let result;
        try { result = await infer(message.image, operation.deadline); } catch { return {accepted: false, message: "本地图片识别失败或超时，未提交签到"}; }
        const current = await permitted(message, sender, "recognizing");
        if (!current || !/^[A-Z0-9]{6}$/.test(result?.answer || "")) return {accepted: false, message: "验证码识别结果不可靠或操作已取消，未提交签到"};
        const ticket = crypto.randomUUID();
        await chrome.storage.local.set({[key]: {...current.operation, phase: "recognized", captchaTicket: ticket}});
        return {accepted: true, answer: result.answer, ticket};
      }
      if (message.type === "captcha-submit") {
        const allowed = await permitted(message, sender, "recognized");
        if (!allowed || !message.ticket || allowed.operation.captchaTicket !== message.ticket) return {accepted: false};
        await chrome.storage.local.set({[sites.key("operation", allowed.siteId)]: {...allowed.operation, phase: "submitted", captchaTicket: null}});
        return {accepted: true};
      }
      return {accepted: false};
    }

    function handle(message, sender) {
      const result = queue.catch(() => {}).then(() => action(message, sender));
      queue = result;
      return result;
    }
    return {handle};
  }
  root.NetSurfCaptchaBackground = {create};
  if (typeof module !== "undefined") module.exports = {create};
})(globalThis);
