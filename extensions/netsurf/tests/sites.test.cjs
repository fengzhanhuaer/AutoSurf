const assert = require("node:assert/strict");
const test = require("node:test");
const sites = require("../sites.js");
const backup = require("../backup.js");

globalThis.NetSurfSites = sites;

test("next-class requirements never become the current rank, including cached data", () => {
  const progress = "Next class: Veteran UserAccount age (days): 822.10 / 224 (Met) D";
  assert.equal(sites.level(progress), null);
  assert.equal(sites.level("Elite User" + progress), "Elite User");
  assert.equal(sites.level("自定义等级 Next class: Veteran User"), "自定义等级");
  assert.equal(sites.profile({level: progress, uploaded: "4.087 TiB"}).level, null);
  assert.equal(sites.profile({level: progress, uploaded: "4.087 TiB"}).uploaded, "4.087 TiB");
});

test("rank normalization keeps only the grade and removes verification and rules text", () => {
  assert.equal(sites.level("(小学)Power User 🔗 校验等级加群参考《规则&教程》第二部分第4条，等级参考第五部分。"), "Power User");
  assert.equal(sites.level("（博士）Nexus Master 规则说明"), "Nexus Master");
  assert.equal(sites.level("自定义等级 查看规则"), "自定义等级");
  assert.equal(sites.level("VIP"), "VIP");
  assert.equal(sites.level(null), null);
  assert.equal(sites.profile({level: "Power User校验等级加群参考", uploaded: "10.92TB"}).level, "Power User");
  assert.equal(sites.profile({level: "Power User校验等级加群参考", uploaded: "10.92TB"}).uploaded, "10.92TB");
});

const cookie = {domain: ".piggo.me", name: "login", value: "fixture-only", path: "/", secure: true, httpOnly: true, hostOnly: false, session: false, sameSite: "lax", expirationDate: Date.now() / 1000 + 3600};

test("site settings validate limits and exclude unrelated execution state", () => {
  for (const config of [null, [], 123, {enabled: "false"}, {startTime: "24:00"}, {startTime: "8:00"}, {retryInterval: 29}, {retryInterval: 86401}, {retryCount: -1}, {retryCount: 11}, {timeout: 4}, {timeout: 121}, {timeout: 5.5}]) assert.throws(() => sites.config(config));
  const settings = sites.settings({autoEnabled: true, operation: {secret: "unused"}});
  assert.equal(Object.keys(settings.sites).length, 64);
  assert.deepEqual(settings.sites.piggo, sites.defaults);
  assert.equal(Object.values(settings.sites).filter(site => site.enabled).length, 1);
  assert.equal(settings.operation, undefined);
  assert.equal(sites.config({retryCount: 0, timeout: 5}).retryCount, 0);
});

test("local daily start catches up once and then moves to the next day", () => {
  const configured = sites.config({startTime: "08:00"});
  const before = new Date(2026, 9, 14, 7, 0);
  const after = new Date(2026, 9, 14, 9, 0);
  assert.equal(new Date(sites.nextStart(configured, {}, before)).getHours(), 8);
  assert.equal(sites.nextStart(configured, {}, after), after.getTime() + 1000);
  for (const state of [{verifiedDay: sites.day(after)}, {schedule: {day: sites.day(after)}}]) {
    const next = new Date(sites.nextStart(configured, state, after));
    assert.equal(next.getDate(), 15);
    assert.equal(next.getHours(), 8);
  }
});

test("backup round-trip keeps HttpOnly, SameSite, host scope, session and partition attributes", () => {
  const session = {...cookie, hostOnly: true, domain: "piggo.me", session: true, partitionKey: {topLevelSite: "https://example.test", hasCrossSiteAncestor: true}};
  const document = backup.create({autoEnabled: true, verifiedDay: "today", operation: {tabId: 3}, sites: {piggo: {timeout: 60}}}, [cookie, session]);
  const validated = backup.validate(JSON.parse(JSON.stringify(document)));
  assert.deepEqual(Object.keys(document.settings).sort(), ["autoEnabled", "scheduleConfig", "sites"]);
  assert.deepEqual(Object.keys(document.settings.sites.piggo), ["enabled", "refreshOnly"]);
  assert.equal(validated.settings.sites.piggo.timeout, 60);
  assert.equal(validated.cookies[0].details.httpOnly, true);
  assert.equal(validated.cookies[0].details.domain, ".piggo.me");
  assert.equal(validated.cookies[1].details.domain, undefined);
  assert.equal(validated.cookies[1].details.expirationDate, undefined);
  assert.deepEqual(validated.cookies[1].details.partitionKey, session.partitionKey);
});

test("numeric account fields drop detail links without rounding or mixing seeding points", () => {
  for (const amount of ["18,142,137.0", "1,358,325.6", "755150.4"]) assert.equal(sites.profile({bonus: amount + " [明细]"}).bonus, amount);
  assert.deepEqual(sites.profile({bonus: "18,142,137.0[明细]", seedingPoints: "123.45 [明细]", level: "等级详情/提升等级"}), {level: null, bonus: "18,142,137.0", seedingPoints: "123.45", uploaded: null, downloaded: null, ratio: null});
  assert.equal(sites.number("[明细]"), null);
  assert.equal(sites.number("1,23"), null);
});

test("refresh-only defaults off, round-trips in backups and rejects malformed settings", () => {
  assert.ok(Object.entries(sites.settings().sites).every(([siteId, site]) => site.refreshOnly === ["52pt.site", "open.cd", "u2.dmhy.org"].includes(siteId)));
  assert.equal(sites.settings({sites: {"52pt.site": {refreshOnly: false}}}).sites["52pt.site"].refreshOnly, true);
  const document = backup.create({sites: {piggo: {refreshOnly: true}}}, []);
  assert.equal(backup.validate(document).settings.sites.piggo.refreshOnly, true);
  assert.equal(backup.validate(document).settings.sites["audiences.me"].refreshOnly, false);
  assert.equal(document.settings.refreshOnly, undefined);
  delete document.settings.sites.piggo.refreshOnly;
  assert.equal(backup.validate(document).settings.sites.piggo.refreshOnly, false);
  document.settings.sites.piggo.refreshOnly = "true";
  assert.throws(() => backup.validate(document), /仅刷新/);
});

test("restore accepts all websites and validates Cookie domain syntax before writes", () => {
  const document = backup.create({}, [cookie]);
  for (const changed of [{...document, version: 99}, {...document, format: "other"}, {...document, cookies: [{...cookie, domain: "https://ordinary.test"}]}, {...document, cookies: [{...cookie, domain: "user@ordinary.test"}]}, {...document, settings: {autoEnabled: true, sites: {piggo: {timeout: 1000}}}}]) assert.throws(() => backup.validate(changed));
  assert.equal(backup.validate({...document, cookies: [{...cookie, path: "//evil.test/"}]}).cookies[0].details.url, "https://piggo.me//evil.test/");
  for (const domain of [".ordinary.test", "sub.other.test", "localhost", "127.0.0.1", "[::1]"]) assert.equal(backup.cookie({...cookie, domain, secure: false}).details.url, "http://" + domain.replace(/^\./, "") + "/");
  assert.equal(backup.cookie({...cookie, expirationDate: 1}).expired, true);
  assert.throws(() => backup.cookie({...cookie, sameSite: "invalid"}));
});

test("one shared schedule overrides historical per-site timing and preserves each switch", () => {
  const scheduleConfig = {startTime: "10:15", retryInterval: 90, retryCount: 0, timeout: 15};
  const state = sites.settings({scheduleConfig, sites: {piggo: {enabled: false, refreshOnly: true, timeout: 100}, "audiences.me": {enabled: true, startTime: "04:00"}}});
  assert.deepEqual(state.scheduleConfig, scheduleConfig);
  for (const configured of Object.values(state.sites)) assert.deepEqual({...configured, enabled: undefined, refreshOnly: undefined}, {...scheduleConfig, enabled: undefined, refreshOnly: undefined});
  assert.equal(state.sites.piggo.refreshOnly, true);
  assert.equal(state.sites["audiences.me"].refreshOnly, false);
  assert.equal(state.sites.piggo.enabled, false);
  assert.equal(state.sites["audiences.me"].enabled, true);
  const restored = backup.validate(backup.create(state, []));
  assert.deepEqual(restored.settings, state);
});
