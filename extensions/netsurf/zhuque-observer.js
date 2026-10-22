(() => {
  const mteam = location.origin === "https://kp.m-team.cc";
  if (!mteam && !/^https:\/\/(?:www\.)?zhuque\.in$/.test(location.origin) || globalThis.NetSurfZhuqueObserver) return;
  globalThis.NetSurfZhuqueObserver = true;
  const attribute = mteam ? "data-netsurf-mteam-profile" : "data-netsurf-zhuque-profile";
  function matches(value, method) {
    try {
      const target = new URL(value, location.href);
      if (mteam) return String(method || "GET").toUpperCase() === "POST" && ["https://api.m-team.cc", "https://api.m-team.io", "https://api2.m-team.cc"].includes(target.origin) && target.pathname === "/api/member/profile" && !target.search;
      return String(method || "GET").toUpperCase() === "GET" && target.origin === location.origin && target.pathname === "/api/user/getInfo" && !target.search;
    } catch { return false; }
  }
  function publish(payload, status) {
    if (status !== 200 || !payload?.data?.id) { document.documentElement?.removeAttribute(attribute); return; }
    const data = payload.data;
    if (mteam) {
      if (Number(payload.code) !== 0) { document.documentElement?.removeAttribute(attribute); return; }
      const count = data.memberCount || {};
      const safe = {id: true, memberStatus: {name: String(data.memberStatus?.name || "").slice(0, 64)}, memberCount: {uploaded: Number(count.uploaded), downloaded: Number(count.downloaded), bonus: String(count.bonus ?? "").slice(0, 64), ...(count.ratio !== undefined ? {ratio: String(count.ratio).slice(0, 64)} : {})}};
      document.documentElement?.setAttribute(attribute, JSON.stringify({time: Date.now(), data: safe}));
      return;
    }
    const safe = {class: {name: String(data.class?.name ?? data.class?.level ?? "").slice(0, 64)}, upload: Number(data.upload), download: Number(data.download), bonus: String(data.bonus ?? "").slice(0, 64), seedBonus: String(data.seedBonus ?? "").slice(0, 64)};
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
