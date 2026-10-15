(() => {
  const version = chrome.runtime.getManifest().version;
  const contentRevision = "2026-10-15-audiences-profile-v7";
  const suppressAuto = globalThis.NetSurfReadOnlyInjection === true;
  delete globalThis.NetSurfReadOnlyInjection;
  if (globalThis.NetSurfContentStarted === contentRevision) return;
  globalThis.NetSurfContentStop?.();
  globalThis.NetSurfContentStarted = contentRevision;
  const site = globalThis.NetSurfSites?.resolve(location.href);
  if (!site && !globalThis.NetSurfPiggo.isPiggo(location.href)) return;
  const piggo = site ? globalThis.NetSurfPiggo.create(new URL(location.href).origin, site.signinPath, site.mode === "profile", site.name) : globalThis.NetSurfPiggo;
  let submitted = false;
  let latestKey = "";
  let updateTimer;

  function diagnose(snapshot, response, status) {
    const entries = Array.from(snapshot.querySelectorAll('a[href], button, input[type="submit"], input[type="button"]')).map(element => {
      const label = (element.textContent || element.value || element.getAttribute("title") || "").trim().slice(0, 80);
      let path = "";
      let targetOrigin = "";
      let hasQuery = false;
      let hasFragment = false;
      try {
        const target = new URL(element.getAttribute("href") || element.form?.getAttribute("action") || "", response.url);
        path = target.pathname;
        targetOrigin = target.origin;
        hasQuery = Boolean(target.search);
        hasFragment = Boolean(target.hash);
      } catch {}
      return {label, path, targetOrigin, hasQuery, hasFragment, disabled: element.disabled === true, tag: element.tagName, id: element.id || "", className: typeof element.className === "string" ? element.className.slice(0, 100) : "", clickHandler: element.hasAttribute("onclick")};
    }).filter(entry => /签到|簽到|打卡|check.?in|attendance/i.test(entry.label + entry.path)).slice(0, 12);
    const profileHints = piggo.profileHints?.(snapshot) || [];
    return {path: new URL(response.url).pathname, httpStatus: response.status, accountFound: Boolean(piggo.accountLink(snapshot)), entries, status, ...(profileHints.length ? {profileHints} : {})};
  }

  async function refreshOnly() {
    const state = await chrome.storage.local.get("sites");
    return globalThis.NetSurfSites?.refreshOnlyRequired(site?.id || "piggo") || state.sites?.[site?.id || "piggo"]?.refreshOnly === true;
  }

  function wait(delay, signal) {
    return new Promise((resolve, reject) => {
      const finish = callback => { signal.removeEventListener("abort", abort); callback(); };
      const timer = setTimeout(() => finish(resolve), delay);
      const abort = () => { clearTimeout(timer); finish(() => reject(new DOMException("Aborted", "AbortError"))); };
      if (signal.aborted) abort();
      else signal.addEventListener("abort", abort, {once: true});
    });
  }

  async function readPage(url, signal) {
    const transient = new Set([408, 500, 502, 503, 504]);
    for (let attempt = 0; attempt < 2; attempt += 1) {
      try {
        const response = await fetch(url, {credentials: "same-origin", cache: "no-store", signal});
        if (!transient.has(response.status) || attempt === 1) return response;
      } catch (error) {
        if (signal.aborted || attempt === 1) throw error;
      }
      await wait(500, signal);
    }
  }

  async function freshSnapshot(timeoutMs = 7000, dataOnly = false, reuseCurrentPage = false) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), timeoutMs);
    try {
      if (piggo.profileApi) {
        const snapshot = await globalThis.NetSurfProfileApi.read(piggo.origin, piggo.profileApi, controller.signal);
        const status = dataOnly && snapshot.profile && ["profile_only", "ready", "already_done", "unknown"].includes(snapshot.status) ? "refreshed" : snapshot.status;
        return {...piggo.result(status, location.href), ...snapshot, status};
      }
      const navigationStatus = Number(globalThis.performance?.getEntriesByType?.("navigation")?.[0]?.responseStatus);
      const reuseLoadedPage = reuseCurrentPage && piggo.isPiggo(location.href) && navigationStatus >= 200 && navigationStatus < 400;
      const response = reuseLoadedPage
        ? {url: location.href, status: 200, ok: true}
        : await readPage(`${piggo.origin}${site?.homePath || "/index.php"}`, controller.signal);
      if (!piggo.isPiggo(response.url)) return piggo.result("error", location.href);
      const snapshot = reuseLoadedPage
        ? document.cloneNode(true)
        : new DOMParser().parseFromString(await response.text(), "text/html");
      snapshot.querySelectorAll("script, style").forEach(element => element.remove());
      const {status} = piggo.inspect(snapshot, response.url);
      const diagnostic = diagnose(snapshot, response, status);
      if (!["unknown", "ready", "already_done", "success", "profile_only"].includes(status) && !(dataOnly && status === "manual_required")) return {...piggo.result(status, response.url), diagnostic};
      if (response.status === 468 || response.status === 403) return {...piggo.result("blocked", response.url), diagnostic};
      if (response.status === 401) return {...piggo.result("login_required", response.url), diagnostic};
      if (!response.ok) return {...piggo.result("error", response.url), diagnostic, message: `首页返回 HTTP ${response.status}`};
      async function optionalPage(url, label) {
        const optionalController = new AbortController();
        const abort = () => optionalController.abort();
        controller.signal.addEventListener("abort", abort, {once: true});
        if (controller.signal.aborted) abort();
        const detail = {label, path: new URL(url).pathname};
        diagnostic.auxiliary ||= [];
        diagnostic.auxiliary.push(detail);
        try {
          const pageResponse = await readPage(url, optionalController.signal);
          detail.httpStatus = pageResponse.status;
          const pageHtml = await pageResponse.text();
          return {response: pageResponse, html: pageHtml};
        } catch (error) {
          detail.error = error.name === "AbortError" ? "读取超时，保留已有字段" : "请求失败，保留已有字段";
          return null;
        } finally {
          controller.signal.removeEventListener("abort", abort);
        }
      }
      const profile = piggo.profile(snapshot);
      let classUrl = piggo.classLink(snapshot);
      const accountUrl = piggo.accountLink(snapshot);
      if (accountUrl && Object.values(profile).some(value => !value)) {
        try {
          const accountPage = await optionalPage(accountUrl, "账号资料");
          if (accountPage?.response) Object.assign(diagnostic.auxiliary.at(-1), {sameUrl: accountPage.response.url === accountUrl, finalPath: new URL(accountPage.response.url).pathname});
          if (accountPage?.response.ok && accountPage.response.url === accountUrl) {
            const accountDocument = new DOMParser().parseFromString(accountPage.html, "text/html");
            const accountStatus = piggo.inspect(accountDocument, accountUrl).status;
            diagnostic.auxiliary.at(-1).status = accountStatus;
            if (!["blocked", "debugging", "login_required", "manual_required"].includes(accountStatus)) {
              const accountProfile = piggo.profile(accountDocument, true);
              for (const [field, value] of Object.entries(accountProfile)) if (value && (!piggo.detailFillOnly || !profile[field])) profile[field] = value;
              diagnostic.auxiliary.at(-1).profileHints = piggo.profileHints?.(accountDocument) || [];
              classUrl = piggo.classLink(accountDocument, true) || classUrl;
            }
          }
        } catch {}
      }
      if (!profile.level && classUrl) {
        try {
          const target = new URL(classUrl);
          target.hash = "";
          const classPage = await optionalPage(target.href, "等级详情");
          if (classPage?.response.ok && classPage.response.url === target.href) {
            const classDocument = new DOMParser().parseFromString(classPage.html, "text/html");
            const classStatus = piggo.inspect(classDocument, target.href).status;
            if (!["blocked", "debugging", "login_required", "manual_required"].includes(classStatus)) profile.level = piggo.classLevel(classDocument, classUrl);
          }
        } catch {}
      }
      if (dataOnly) {
        const refreshed = Object.values(profile).some(Boolean);
        return {...piggo.result(refreshed ? "refreshed" : "unknown", response.url), profile, diagnostic, ...(!refreshed ? {message: "页面可访问，但未读取到当前账号数据"} : {})};
      }
      if (piggo.statusPath) {
        const statusUrl = `${piggo.origin}${piggo.statusPath}`;
        const statusResponse = await readPage(statusUrl, controller.signal);
        if (!piggo.isPiggo(statusResponse.url)) return {...piggo.result("error", location.href), profile};
        const statusDocument = new DOMParser().parseFromString(await statusResponse.text(), "text/html");
        statusDocument.querySelectorAll("script, style").forEach(element => element.remove());
        let attendanceStatus = piggo.inspect(statusDocument, statusResponse.url).status;
        if (statusResponse.status === 468 || statusResponse.status === 403) attendanceStatus = "blocked";
        else if (statusResponse.status === 401) attendanceStatus = "login_required";
        else if (!statusResponse.ok || statusResponse.url !== statusUrl && !["blocked", "debugging", "login_required"].includes(attendanceStatus)) attendanceStatus = "error";
        return {...piggo.result(attendanceStatus, statusResponse.url), profile, diagnostic: diagnose(statusDocument, statusResponse, attendanceStatus)};
      }
      return {...piggo.result(status, response.url), profile, diagnostic};
    } catch (error) {
      return {...piggo.result("error", location.href), message: error.name === "AbortError" ? "账号数据请求超时" : "账号数据请求失败，请检查站点网络或访问权限"};
    } finally {
      clearTimeout(timeout);
    }
  }

  async function publish() {
    const {status} = piggo.inspect(document, location.href);
    const key = `${location.pathname}:${status}`;
    if (key === latestKey) return;
    latestKey = key;
    await chrome.runtime.sendMessage({type: "observed", result: piggo.result(status, location.href)});
  }

  async function signin(timeoutMs) {
    if (submitted) return piggo.result("pending", location.href);
    submitted = true;
    const fresh = await freshSnapshot(timeoutMs);
    if (fresh.status !== "ready") {
      submitted = false;
      return fresh;
    }
    if (await refreshOnly()) {
      submitted = false;
      return fresh;
    }
    if (["rousi", "sunny"].includes(piggo.profileApi)) {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), timeoutMs || 7000);
      await chrome.runtime.sendMessage({type: "observed", result: piggo.result("pending", location.href)});
      try {
        const result = await globalThis.NetSurfProfileApi.signIn(piggo.origin, piggo.profileApi, controller.signal, globalThis, async () => !await refreshOnly());
        return {...piggo.result(result.status, location.href), ...result};
      } finally { clearTimeout(timeout); }
    }
    let control = piggo.action(document, location.href);
    if (!control) {
      const links = Array.from(document.querySelectorAll('a[href]'))
        .filter(piggo.visible)
        .filter(element => piggo.safeAttendanceLink(element.getAttribute("href"), location.href));
      control = links.length === 1 ? links[0] : links.length > 1 ? "ambiguous" : null;
    }
    if (!control || control === "ambiguous") {
      submitted = false;
      return piggo.result(control === "ambiguous" ? "ambiguous" : "unknown", location.href);
    }
    const pending = piggo.result("pending", location.href);
    await chrome.runtime.sendMessage({type: "observed", result: pending});
    if (await refreshOnly()) {
      submitted = false;
      await chrome.runtime.sendMessage({type: "observed", result: fresh});
      return fresh;
    }
    control.click();
    return pending;
  }

  function messageListener(message, sender, respond) {
    if (sender.id !== chrome.runtime.id) return;
    if (message.type === "netsurf-inspect") {
      if (message.fresh) {
        refreshOnly().then(readOnly => freshSnapshot(message.timeoutMs, message.dataOnly === true || readOnly, message.reuseCurrentPage === true)).then(result => respond({...result, contentVersion: version, contentRevision})).catch(() => respond(piggo.result("error", location.href)));
        return true;
      }
      respond({...piggo.result(piggo.inspect(document, location.href).status, location.href), contentVersion: version, contentRevision, pageReady: document.readyState !== "loading"});
    } else if (message.type === "netsurf-signin") {
      signin(message.timeoutMs).then(respond).catch(() => respond(piggo.result("error", location.href)));
      return true;
    }
  }
  chrome.runtime.onMessage.addListener(messageListener);

  publish().catch(() => {});
  const observer = new MutationObserver(() => {
    clearTimeout(updateTimer);
    updateTimer = setTimeout(() => publish().catch(() => {}), 300);
  });
  observer.observe(document.documentElement, {childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ["style", "class", "hidden", "disabled"]});
  globalThis.NetSurfContentStop = () => {
    chrome.runtime.onMessage.removeListener(messageListener);
    observer.disconnect();
    clearTimeout(updateTimer);
  };
  if (!suppressAuto) {
    (async () => {
      const {taskTab} = await chrome.storage.session?.get("taskTab") || {};
      if (taskTab?.purpose !== "refresh" || taskTab.siteId !== site?.id) await chrome.runtime.sendMessage({type: "auto"});
    })().catch(() => {});
  }
})();
