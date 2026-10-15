(function (root) {
  const catalog = root.NetSurfCatalog || (typeof module !== "undefined" ? require("./catalog.js") : []);
  const rules = root.NetSurfRules || (typeof module !== "undefined" ? require("./site-rules.js") : null);
  const defaults = {enabled: true, refreshOnly: false, startTime: "08:00", retryInterval: 300, retryCount: 3, timeout: 30};
  const profileFields = ["level", "bonus", "seedingPoints", "uploaded", "downloaded", "ratio"];

  function config(value = {}) {
    if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("站点设置格式无效");
    const merged = {...defaults, ...value};
    if (typeof merged.refreshOnly !== "boolean") throw new Error("仅刷新设置格式无效");
    if (typeof merged.enabled !== "boolean" || typeof merged.startTime !== "string" || !/^([01]\d|2[0-3]):[0-5]\d$/.test(merged.startTime)) throw new Error("启用状态或开始时间无效");
    for (const [field, minimum, maximum] of [["retryInterval", 30, 86400], ["retryCount", 0, 10], ["timeout", 5, 120]]) {
      if (!Number.isInteger(merged[field]) || merged[field] < minimum || merged[field] > maximum) throw new Error("重试或超时设置超出允许范围");
    }
    return Object.fromEntries(Object.keys(defaults).map(field => [field, merged[field]]));
  }

  function settings(state = {}) {
    const shared = config(state.scheduleConfig || state.sites?.piggo || {});
    const scheduleConfig = Object.fromEntries(Object.entries(shared).filter(([field]) => !["enabled", "refreshOnly"].includes(field)));
    return {autoEnabled: state.autoEnabled === true, scheduleConfig, sites: Object.fromEntries(catalog.map(site => {
      const configured = config({...scheduleConfig, enabled: state.sites?.[site.id]?.enabled ?? site.id === "piggo", refreshOnly: state.sites?.[site.id]?.refreshOnly ?? false});
      return [site.id, {...configured, refreshOnly: refreshOnlyRequired(site.id) || configured.refreshOnly}];
    }))};
  }

  function refreshOnlyRequired(siteId) { return rules?.get(get(siteId)?.origin)?.refreshOnly === true; }

  function get(id = "piggo") { return catalog.find(site => site.id === id); }

  function resolve(url) {
    try {
      const target = new URL(url);
      return target.protocol === "https:" && !target.port ? catalog.find(site => site.hosts.includes(target.hostname)) : null;
    } catch { return null; }
  }

  function origins(site) { return site.id === "piggo" ? [site.origin + "/*"] : site.hosts.map(host => `https://${host}/*`); }

  function key(field, siteId = "piggo") { return siteId === "piggo" ? field : `${field}:${siteId}`; }

  function day(date = new Date()) {
    return `${date.getFullYear()}-${date.getMonth() + 1}-${date.getDate()}`;
  }

  function start(configured, date = new Date()) {
    const result = new Date(date);
    const [hours, minutes] = configured.startTime.split(":").map(Number);
    result.setHours(hours, minutes, 0, 0);
    return result;
  }

  function nextStart(configured, state, date = new Date()) {
    const result = start(configured, date);
    if (result <= date) {
      if (state.verifiedDay !== day(date) && state.schedule?.day !== day(date)) return date.getTime() + 1000;
      result.setDate(result.getDate() + 1);
    }
    return result.getTime();
  }

  function level(value) {
    if (typeof value !== "string") return null;
    const text = value.replace(/\s+/g, " ").trim().replace(/^(?:\([^)]*\)|（[^）]*）)\s*/, "").split(/\s*(?:Next\s+(?:class|level)\s*[:：]|Account\s+age\s*\(days\)\s*[:：]|下一(?:等级|等級)|下[个個]等[级級])/i)[0].trim();
    const rank = text.match(/^(?:(?:\([^)]{1,20}\)|（[^）]{1,20}）)\s*)?(?:Nexus\s*Master|Staff\s*Leader|Ultimate\s*User|Extreme\s*User|Crazy\s*User|Insane\s*User|Veteran\s*User|Elite\s*User|Power\s*User|Administrator|Moderator|Uploader|Sysop|Peasant|VIP|User)(?=$|[^a-z])/i);
    const name = rank?.[0] || text.split(/\s*(?:等级详情|等級詳情|提升等级|提升等級|校验|校驗|验证|驗證|规则|規則|教程|说明|說明|查看|升级|升級|加群|参考|參考|\p{Extended_Pictographic}|\b(?:verify|help|rules|guide|learn more)\b)/iu)[0];
    return name.replace(/[\s,，:：|·]+$/, "").slice(0, 64) || null;
  }

  function number(value) {
    return typeof value === "string" ? value.trim().match(/^[+-]?\d+(?:,\d{3})*(?:\.\d+)?(?=$|[^\d,.])/)?.[0] || null : null;
  }

  function profile(value) {
    return Object.fromEntries(profileFields.map(field => [field, field === "level" ? level(value?.[field]) : ["bonus", "seedingPoints"].includes(field) ? number(value?.[field]) : typeof value?.[field] === "string" ? value[field].trim().slice(0, 64) : null]));
  }

  const api = {catalog, get, resolve, origins, key, defaults, profileFields, config, settings, refreshOnlyRequired, day, start, nextStart, level, number, profile};
  root.NetSurfSites = api;
  if (typeof module !== "undefined") module.exports = api;
})(globalThis);
