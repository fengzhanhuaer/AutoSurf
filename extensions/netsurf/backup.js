(function (root) {
  function cookie(value, now = Date.now() / 1000) {
    if (!value || typeof value.domain !== "string" || typeof value.name !== "string" || typeof value.value !== "string" || typeof value.path !== "string" || !value.path.startsWith("/") || /[\x00-\x1f\x7f]/.test(value.name + value.path)) throw new Error("Cookie 格式无效");
    if (typeof value.secure !== "boolean" || typeof value.httpOnly !== "boolean" || typeof value.hostOnly !== "boolean" || typeof value.session !== "boolean" || !["unspecified", "no_restriction", "lax", "strict"].includes(value.sameSite)) throw new Error("Cookie 属性无效");
    if (!value.session && (!Number.isFinite(value.expirationDate) || value.expirationDate <= 0)) throw new Error("Cookie 有效期无效");
    const host = value.domain.replace(/^\./, "");
    let url;
    try {
      url = new URL(`${value.secure ? "https" : "http"}://${host}/`);
      if (!host || /[\s\\/?#@]/.test(host) || url.hostname !== host.toLowerCase() || url.port || url.username || url.password) throw new Error();
    } catch { throw new Error("Cookie 域名无效"); }
    if (value.partitionKey) {
      try {
        const partition = new URL(value.partitionKey.topLevelSite);
        if (!["http:", "https:"].includes(partition.protocol) || partition.username || partition.password || (value.partitionKey.hasCrossSiteAncestor !== undefined && typeof value.partitionKey.hasCrossSiteAncestor !== "boolean")) throw new Error();
      } catch { throw new Error("分区 Cookie 属性无效"); }
    }
    const details = {url: url.origin + value.path, name: value.name, value: value.value, path: value.path, secure: value.secure, httpOnly: value.httpOnly, sameSite: value.sameSite};
    if (!value.hostOnly) details.domain = value.domain;
    if (!value.session) details.expirationDate = value.expirationDate;
    if (value.partitionKey) details.partitionKey = {topLevelSite: value.partitionKey.topLevelSite, ...(value.partitionKey.hasCrossSiteAncestor !== undefined ? {hasCrossSiteAncestor: value.partitionKey.hasCrossSiteAncestor} : {})};
    return {details, expired: !value.session && value.expirationDate <= now};
  }

  function validate(document) {
    if (!document || document.format !== "netsurf-backup" || document.version !== 1 || typeof document.settings?.autoEnabled !== "boolean" || !document.settings.sites || Object.keys(document.settings.sites).some(key => !root.NetSurfSites.get(key)) || !Array.isArray(document.cookies) || document.cookies.length > 10000) throw new Error("不是受支持的 NetSurf 备份文件");
    const settings = root.NetSurfSites.settings(document.settings);
    if (document.settings.periodicTasks !== undefined) settings.periodicTasks = root.NetSurfPeriodic.settings(document.settings.periodicTasks);
    const cookies = document.cookies.map(value => cookie(value));
    return {settings, cookies};
  }

  function create(state, cookies) {
    const normalized = root.NetSurfSites.settings(state);
    const settings = {...normalized, sites: Object.fromEntries(Object.entries(normalized.sites).map(([siteId, configured]) => [siteId, {enabled: configured.enabled, refreshOnly: configured.refreshOnly}]))};
    if (state.periodicTasks !== undefined) settings.periodicTasks = root.NetSurfPeriodic.settings(state.periodicTasks);
    const document = {format: "netsurf-backup", version: 1, cookieScope: "all-sites", createdAt: new Date().toISOString(), settings, cookies};
    validate(document);
    return document;
  }

  const api = {cookie, validate, create};
  root.NetSurfBackup = api;
  if (typeof module !== "undefined") module.exports = api;
})(globalThis);
