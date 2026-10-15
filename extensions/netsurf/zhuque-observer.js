(() => {
  if (!/^https:\/\/(?:www\.)?zhuque\.in$/.test(location.origin) || globalThis.NetSurfZhuqueObserver) return;
  globalThis.NetSurfZhuqueObserver = true;
  const attribute = "data-netsurf-zhuque-profile";
  function matches(value, method) {
    try {
      const target = new URL(value, location.href);
      return String(method || "GET").toUpperCase() === "GET" && target.origin === location.origin && target.pathname === "/api/user/getInfo" && !target.search;
    } catch { return false; }
  }
  function publish(payload, status) {
    if (status !== 200 || !payload?.data?.id) { document.documentElement?.removeAttribute(attribute); return; }
    const data = payload.data;
    const safe = {class: {name: String(data.class?.name ?? data.class?.level ?? "").slice(0, 64)}, upload: Number(data.upload), download: Number(data.download), bonus: String(data.bonus ?? data.seedBonus ?? "").slice(0, 64)};
    document.documentElement?.setAttribute(attribute, JSON.stringify({time: Date.now(), data: safe}));
  }
  const originalFetch = globalThis.fetch;
  globalThis.fetch = function (input, options) {
    const pending = originalFetch.apply(this, arguments);
    if (matches(input?.url || input, options?.method || input?.method)) pending.then(response => response.clone().json().then(payload => publish(payload, response.status))).catch(() => {});
    return pending;
  };
  const prototype = XMLHttpRequest.prototype;
  const originalOpen = prototype.open;
  const originalSend = prototype.send;
  const targetKey = Symbol("NetSurfProfileTarget");
  const startedKey = Symbol("NetSurfProfileStarted");
  prototype.open = function (method, url) { this[targetKey] = matches(url, method); return originalOpen.apply(this, arguments); };
  prototype.send = function () {
    if (!this[startedKey]) {
      this[startedKey] = true;
      this.addEventListener("load", function () {
        if (!this[targetKey]) return;
        try { publish(this.responseType === "json" ? this.response : JSON.parse(this.responseText), this.status); } catch {}
      });
    }
    return originalSend.apply(this, arguments);
  };
})();
