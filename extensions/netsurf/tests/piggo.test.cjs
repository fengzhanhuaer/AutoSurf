const assert = require("node:assert/strict");
const test = require("node:test");
const piggo = require("../piggo.js");
const manifest = require("../manifest.json");

function element(label, {tag = "A", href = "/attendance.php", action = "/attendance.php", hidden = false, disabled = false} = {}) {
  return {
    tagName: tag, innerText: label, hidden, disabled,
    getAttribute: name => name === "href" ? href : "",
    getBoundingClientRect: () => ({width: 50, height: 20}),
    ownerDocument: {defaultView: {getComputedStyle: () => ({display: "block", visibility: "visible"})}},
    form: tag === "A" ? null : {getAttribute: () => action}
  };
}

function documentFixture(text, controls = [], {password = false, captcha = false} = {}) {
  return {
    body: {innerText: text},
    querySelectorAll: selector => selector.includes("password") ? (password ? [element("password")] : [])
      : selector.includes("captcha") ? (captcha ? [element("captcha")] : []) : controls
  };
}

test("a Cloudflare origin gateway error is not a human verification request", () => {
  const adapter = piggo.create("https://pt.btschool.club", "/index.php");
  const page = documentFixture("Bad gateway Error code 502 You Browser Working Cloudflare Working pt.btschool.club Host Error Cloudflare Ray ID: fixture");
  page.title = "btschool.club | 502: Bad gateway";
  assert.equal(adapter.inspect(page, "https://pt.btschool.club/index.php").status, "error");
  assert.match(adapter.inspect(page, "https://pt.btschool.club/index.php").message, /HTTP 502/);
  page.title = "Just a moment...";
  assert.equal(adapter.inspect(page, "https://pt.btschool.club/index.php").status, "blocked");
});

test("NetSurf keeps automatic host access scoped and asks for all-cookie access optionally", () => {
  assert.equal(manifest.name, "NetSurf");
  assert.equal(manifest.manifest_version, 3);
  assert.equal(manifest.action.default_popup, undefined);
  assert.deepEqual(manifest.permissions, ["storage", "alarms", "scripting", "offscreen"]);
  assert.deepEqual(manifest.optional_permissions, ["cookies"]);
  assert.deepEqual(manifest.optional_host_permissions, ["http://*/*", "https://*/*"]);
  assert.deepEqual(manifest.host_permissions, ["https://piggo.me/*"]);
  assert.deepEqual(manifest.content_scripts[0].matches, manifest.host_permissions);
});

test("rejects spoofed domains and insecure URLs", () => {
  for (const url of ["https://piggo.me.evil.test/", "https://evil.test/?host=piggo.me", "http://piggo.me/", "https://piggo.me:444/", "invalid"]) assert.equal(piggo.isPiggo(url), false);
});

test("generic adapters use the site's attendance path and retain origin checks", () => {
  const other = piggo.create("https://audiences.me", "/attendance.php", false, "Audiences");
  assert.equal(other.safeAttendanceLink("/attendance.php", "https://audiences.me/"), true);
  assert.equal(other.safeAttendanceLink("https://piggo.me/attendance.php", "https://audiences.me/"), false);
  assert.equal(other.classify({url: "https://audiences.me/attendance.php", text: "签到成功"}), "success");
  assert.equal(other.result("login_required", "https://audiences.me/").message, "请先在当前浏览器登录 Audiences");
  assert.equal(piggo.create("https://example.test", "/", true).action(documentFixture("签到", [element("签到")]), "https://example.test/"), null);
});

test("BTSchool permits only its exact daily bonus action", () => {
  const adapter = piggo.create("https://pt.btschool.club", "/attendance.php");
  const current = "https://pt.btschool.club/index.php";
  const target = `${current}?action=addbonus`;
  assert.equal(adapter.safeAttendanceLink(target, current), true);
  assert.equal(adapter.inspect(documentFixture("每日签到", [element("每日签到", {href: target})]), current).status, "ready");
  assert.equal(adapter.classify({url: target, text: "签到成功"}), "success");
  assert.equal(adapter.classify({url: current, text: "签到成功"}), "unknown");
  for (const href of ["/index.php?action=delete", "/index.php?action=addbonus&other=1", "/index.php?action=addbonus#sign", "https://evil.test/index.php?action=addbonus"]) {
    assert.equal(adapter.safeAttendanceLink(href, current), false);
    assert.equal(adapter.classify({url: new URL(href, current).href, text: "签到成功"}), "unknown");
  }
});

test("GGPT recognizes its G-value reward entry without broadening safe targets", () => {
  const adapter = piggo.create("https://www.gamegamept.com", "/attendance.php");
  const current = "https://www.gamegamept.com/index.php";
  const entry = element("[签到得G值]");
  assert.equal(adapter.action(documentFixture("", [entry]), current), entry);
  assert.equal(adapter.inspect(documentFixture("", [entry]), current).status, "ready");
  for (const href of ["https://evil.test/attendance.php", "/logout.php", "/attendance.php?submit=1", "/attendance.php#sign"]) {
    assert.equal(adapter.action(documentFixture("", [element("[签到得G值]", {href})]), current), null);
  }
  assert.equal(adapter.classify({url: current, text: "签到成功"}), "unknown");
  assert.equal(adapter.classify({url: "https://www.gamegamept.com/attendance.php", text: "今日已签到"}), "already_done");
  assert.equal(piggo.create("https://example.test").action(documentFixture("", [entry]), "https://example.test/index.php"), null);
});

test("OurBits and PTHome recognize reward text only in the current account row", () => {
  for (const host of ['ourbits.club','pthome.net']) {
  const adapter = piggo.create(`https://${host}`, "/attendance.php");
  const snapshot = documentFixture("");
  let rowText = "欢迎回来 tester 魔力值 [使用]: 100 (签到已得50)";
  snapshot.querySelectorAll = selector => selector === "tr" ? [{textContent: rowText}] : [];
  assert.equal(adapter.inspect(snapshot, `https://${host}/index.php`).status, "already_done");
  for (const text of ["公告：欢迎回来，昨天(签到已得50)", "欢迎回来 tester 签到得魔力", "历史记录 (签到已得50)"]) {
    rowText = text;
    assert.equal(adapter.inspect(snapshot, `https://${host}/index.php`).status, "unknown");
  }
  assert.equal(piggo.create("https://example.test").inspect(snapshot, "https://example.test/index.php").status, "unknown");
  }
});

test("Dolby migrated hosts recognize the account welcome reward and keep whale coins separate", () => {
  for (const host of ['www.uhddolby.com','uhddolby.com']) {
    const adapter = piggo.create(`https://${host}`, '/attendance.php');
    let text = '欢迎回来 fixture 鲸币 [使用]: 11,383,551.8 (签到已得300) 做种积分: 3,758,387.4 上传量: 34.199 TB 下载量: 50.160 TB';
    const snapshot = {body:{textContent:''},querySelectorAll: selector => selector === 'tr' ? [{textContent:text}] : []};
    assert.equal(adapter.inspect(snapshot, `https://${host}/index.php`).status, 'already_done');
    const profile = adapter.profile(snapshot);
    assert.equal(profile.bonus, '11,383,551.8');
    assert.equal(profile.seedingPoints, '3,758,387.4');
    text = '公告 历史签到已得300 鲸币 [使用]: 999999';
    assert.equal(adapter.inspect(snapshot, `https://${host}/index.php`).status, 'unknown');
    assert.equal(adapter.profile(snapshot).bonus, null);
  }
});

test("only PigGo's known transient SafeLine page can wait for automatic verification", () => {
  const text = "安全检测能力由 雷池 WAF 驱动";
  let source = "https://challenge.rivers.chaitin.cn/challenge/v2/challenge.js";
  const snapshot = documentFixture(text);
  snapshot.querySelectorAll = selector => selector === 'script[src]' ? [{getAttribute: () => source}] : [];
  const adapter = piggo.create();
  assert.equal(adapter.inspect(snapshot, "https://piggo.me/attendance.php").challengePending, true);
  for (const suffix of [" 无法连接人机验证服务", " 访问已被拦截", " 请求频率过高", " 客户端异常"]) {
    snapshot.body.innerText = text + suffix;
    assert.equal(adapter.inspect(snapshot, "https://piggo.me/attendance.php").challengePending, undefined);
  }
  snapshot.body.innerText = text;
  for (const invalid of ["https://evil.test/challenge/v2/challenge.js", "https://challenge.rivers.chaitin.cn/challenge/v2/challenge.js?evil=1"]) {
    source = invalid;
    assert.equal(adapter.inspect(snapshot, "https://piggo.me/attendance.php").challengePending, undefined);
  }
  source = "https://challenge.rivers.chaitin.cn/challenge/v2/challenge.js";
  assert.equal(piggo.create("https://ourbits.club").inspect(snapshot, "https://ourbits.club/attendance.php").challengePending, undefined);
});

test("HDArea recognizes completed text only in its current welcome row", () => {
  const adapter = piggo.create("https://hdarea.club");
  const snapshot = documentFixture("");
  let rowText = "欢迎回来 fixture 魔力值 [使用]: 100 [已签到] (20)";
  snapshot.querySelectorAll = selector => selector === "tr" ? [{textContent: rowText}] : [];
  assert.equal(adapter.inspect(snapshot, "https://hdarea.club/index.php").status, "already_done");
  for (const text of ["公告 欢迎回来 fixture [已签到]", "历史记录 [已签到]", "欢迎回来 fixture [签到]"]) {
    rowText = text;
    assert.equal(adapter.inspect(snapshot, "https://hdarea.club/index.php").status, "unknown");
  }
  rowText = "欢迎回来 fixture [已签到]";
  assert.equal(piggo.create("https://example.test").inspect(snapshot, "https://example.test/index.php").status, "unknown");
});

test("PigGo recognizes its non-link reward and makeup-card text", () => {
  const snapshot = documentFixture("");
  let rowText = "欢迎回来 tester 魔力值 [使用]: 100 [签到已得10, 补签卡: 25]";
  snapshot.querySelectorAll = selector => selector === "tr" ? [{textContent: rowText}] : [];
  assert.equal(piggo.inspect(snapshot, "https://piggo.me/index.php").status, "already_done");
  rowText = "公告 欢迎回来 tester [签到已得10, 补签卡: 25]";
  assert.equal(piggo.inspect(snapshot, "https://piggo.me/index.php").status, "unknown");
});

test("52PT has scoped legacy entries and requires manual slider completion", () => {
  const adapter = piggo.create("https://52pt.site", "/bakatest.php", false, "52PT");
  const entry = element("签到赚魔力", {href: "/52bakatestdate0823.php"});
  const snapshot = documentFixture("", [entry]);
  const baseQuery = snapshot.querySelectorAll;
  snapshot.querySelectorAll = selector => selector === "#slider-container, #slider-btn" ? [] : baseQuery(selector);
  assert.equal(adapter.inspect(snapshot, "https://52pt.site/index.php").status, "ready");
  assert.equal(adapter.statusPath, "/bakatest.php");
  for (const href of ["https://evil.test/bakatest.php", "/bakatest.php?submit=1", "/bakatest.php#sign", "/logout.php"]) assert.equal(adapter.safeAttendanceLink(href, "https://52pt.site/"), false);
  snapshot.querySelectorAll = selector => selector === "#slider-container, #slider-btn" ? [element("slider", {tag: "DIV"})] : baseQuery(selector);
  assert.equal(adapter.inspect(snapshot, "https://52pt.site/bakatest.php").status, "manual_required");
  assert.match(adapter.result("manual_required", "https://52pt.site/bakatest.php").message, /完成滑块/);
  assert.equal(adapter.classify({url: "https://52pt.site/bakatest.php", text: "今日已签到"}), "already_done");
  assert.equal(piggo.create("https://52pt.site.evil.test").statusPath, undefined);
  assert.equal(piggo.safeAttendanceLink("/52bakatestdate0823.php", "https://piggo.me/"), false);
});

test("JPopsuki reads Up/Down and only its own scoped user.php profile", () => {
  const adapter = piggo.create("https://jpopsuki.eu", "/", true);
  const text = "Up: 70.02 GB Down: 323.69 MB Ratio: 221.51 Bonus: 311055";
  const block = {cloneNode: () => ({textContent: text, querySelectorAll: () => []})};
  let href = "/user.php?id=42";
  const link = {getAttribute: () => href};
  const snapshot = {querySelectorAll: selector => selector === "ul.stats > li" ? [{textContent: "Class: Member"}, {textContent: "Class Stats"}]
    : selector === "#userinfo a[href]" ? [link] : selector.includes("#userinfo") && !selector.includes("a[href]") ? [block] : []};
  assert.equal(adapter.accountLink(snapshot), "https://jpopsuki.eu/user.php?id=42");
  assert.deepEqual(adapter.profile(snapshot, true), {level: "Member", bonus: "311055", seedingPoints: null, uploaded: "70.02 GB", downloaded: "323.69 MB", ratio: "221.51"});
  for (const target of ["https://evil.test/user.php?id=42", "/user.php?action=edit&id=42", "/user.php?id=42&other=1", "/userdetails.php?id=42"]) {
    href = target;
    assert.equal(adapter.accountLink(snapshot), null);
  }
  href = "/user.php?id=42";
  assert.equal(piggo.create("https://example.test").accountLink(snapshot), null);
});

test("HhanClub reads only its own sidebar and exposes a scoped reveal control", () => {
  const adapter = piggo.create("https://hhanclub.net");
  const block = {cloneNode: () => ({querySelectorAll: () => [], textContent: "分享率： [分享率]: 20.376 憨豆： 1,065,011 上传： 1.187 TB 下载： 59.64 GB"})};
  const ownLink = {getAttribute: () => "/userdetails.php?id=42"};
  const snapshot = {querySelectorAll: selector => selector.includes("#user-info-panel") ? selector.endsWith("a[href]") ? [ownLink] : [block] : []};
  assert.equal(adapter.accountLink(snapshot), "https://hhanclub.net/userdetails.php?id=42");
  assert.equal(adapter.revealAttendanceSelector, "#user-avatar");
  assert.deepEqual(adapter.profile(snapshot), {level: null, bonus: "1,065,011", seedingPoints: null, uploaded: "1.187 TB", downloaded: "59.64 GB", ratio: "20.376"});
  const details = {...snapshot, querySelectorAll: selector => selector === 'img[title], img[alt]' ? [{getAttribute: name => name === "title" ? "Power User(憨声憨气)" : ""}] : snapshot.querySelectorAll(selector)};
  assert.equal(adapter.profile(details, true).level, "Power User");
  assert.equal(piggo.create("https://example.test").profile(snapshot).bonus, null);
  assert.equal(piggo.create("https://example.test").revealAttendanceSelector, undefined);
});

test("HXPT reads statistics and its own account link from the redesigned profile bar", () => {
  const adapter = piggo.create("https://www.hxpt.org");
  const text = "fixture 火花 [火花商店] [我的火花]: 12,345.6 分享率: 2.000 上传量: 2.00 TB 下载量: 1.00 TB";
  const block = {cloneNode: () => ({textContent: text, querySelectorAll: () => []})};
  const ownLink = element("fixture", {href: "/userdetails.php?id=42"});
  const snapshot = {querySelectorAll: selector => selector.includes(".cute-top-profile") ? selector.endsWith("a[href]") ? [ownLink] : [block] : []};
  assert.equal(adapter.accountLink(snapshot), "https://www.hxpt.org/userdetails.php?id=42");
  assert.deepEqual(adapter.profile(snapshot), {level: null, bonus: "12,345.6", seedingPoints: null, uploaded: "2.00 TB", downloaded: "1.00 TB", ratio: "2.000"});
  assert.equal(piggo.create("https://example.test").profile(snapshot).bonus, null);
});

test("HDSky allows local image OCR but preserves explicit refresh-only and unknown CAPTCHA protection", () => {
  const sites = require("../sites.js");
  const adapter = piggo.create("https://hdsky.me");
  assert.equal(sites.refreshOnlyRequired("hdsky.me"), false);
  assert.equal(sites.settings({sites: {"hdsky.me": {enabled: true, refreshOnly: false}}}).sites["hdsky.me"].refreshOnly, false);
  assert.equal(sites.settings({sites: {"hdsky.me": {enabled: true, refreshOnly: true}}}).sites["hdsky.me"].refreshOnly, true);
  const inspection = adapter.inspect(documentFixture("签到(Show Up)", [], {captcha: true}), "https://hdsky.me/index.php");
  assert.equal(inspection.status, "manual_required");
  assert.equal(inspection.control, null);
  assert.match(adapter.result("manual_required", "https://hdsky.me/").message, /图片验证码/);
});

test("CHDBits requires refresh-only even when stored settings request sign-in", () => {
  const sites = require("../sites.js");
  assert.equal(sites.refreshOnlyRequired("ptchdbits.co"), true);
  assert.equal(sites.settings({sites: {"ptchdbits.co": {enabled: true, refreshOnly: false}}}).sites["ptchdbits.co"].refreshOnly, true);
  assert.equal(sites.refreshOnlyRequired("piggo"), false);
});

test("XingYunGePT recognizes its scoped sign-in and star currency", () => {
  const adapter = piggo.create("https://pt.xingyungept.org");
  const entry = element("[签到得星焱]");
  const snapshot = documentFixture("", [entry]);
  assert.equal(adapter.inspect(snapshot, "https://pt.xingyungept.org/index.php").status, "ready");
  assert.equal(piggo.create("https://audiences.me").inspect(snapshot, "https://audiences.me/index.php").status, "unknown");
  const block = {cloneNode: () => ({querySelectorAll: () => [], textContent: "星焱 [使用]: 123,456.7 做种积分: 987.6"})};
  const document = {querySelectorAll: selector => selector.includes("#info_block") ? [block] : []};
  assert.equal(adapter.profile(document).bonus, "123,456.7");
  assert.equal(adapter.profile(document).seedingPoints, "987.6");
  const rows = [[{textContent: "星焱"}, {textContent: "456.7"}]].map(cells => ({querySelectorAll: () => cells}));
  assert.equal(adapter.profile({querySelectorAll: selector => selector === "tr" ? rows : []}, true).bonus, "456.7");
});

test("CrabPT recognizes its scoped crab currency entry", () => {
  const adapter = piggo.create("https://crabpt.vip");
  const snapshot = documentFixture("", [element("[签到得蟹币]")]);
  assert.equal(adapter.inspect(snapshot, "https://crabpt.vip/index.php").status, "ready");
  assert.equal(piggo.create("https://audiences.me").inspect(snapshot, "https://audiences.me/index.php").status, "unknown");
});

test("HDDolby recognizes its scoped whale currency entry", () => {
  const adapter = piggo.create("https://hddolby.com");
  const snapshot = documentFixture("", [element("签到得鲸币")]);
  assert.equal(adapter.inspect(snapshot, "https://hddolby.com/index.php").status, "ready");
  for (const host of ["uhddolby.com", "www.uhddolby.com"]) {
    const origin = `https://${host}`;
    assert.equal(piggo.create(origin).inspect(snapshot, `${origin}/index.php`).status, "ready");
  }
  assert.equal(piggo.create("https://audiences.me").inspect(snapshot, "https://audiences.me/index.php").status, "unknown");
});

test("HDCity recognizes its exact English entry with a Material icon prefix", () => {
  const adapter = piggo.create("https://hdcity.city", "/sign");
  const snapshot = documentFixture("", [element("assignment_turned_inCheck in", {href: "/sign"})]);
  assert.equal(adapter.inspect(snapshot, "https://hdcity.city/index.php").status, "ready");
  snapshot.querySelectorAll = selector => selector === 'a[href]' ? [element("assignment_turned_inChecked in", {href: "/sign"})] : [];
  assert.equal(adapter.inspect(snapshot, "https://hdcity.city/index.php").status, "already_done");
  assert.equal(adapter.safeAttendanceLink("/sign?purchase=1", "https://hdcity.city/"), false);
  assert.equal(piggo.create("https://audiences.me").inspect(snapshot, "https://audiences.me/index.php").status, "unknown");
});

test("HDCity reads account data from its current Material homepage", () => {
  const adapter = piggo.create("https://hdcity.city", "/sign");
  const block = {cloneNode: () => ({querySelectorAll: () => [], textContent: "用户等级: Power User 魔力值: 123.4 上传量: 2.00 TiB 下载量: 1.00 TiB 分享率: 2.000"})};
  const account = element("fixture", {href: "/userdetails"});
  const document = {querySelectorAll: selector => selector.startsWith('#info_block,') ? [block] : selector === '.button-group > a[href="userdetails"], .button-group > a[href="/userdetails"]' ? [account] : []};
  assert.deepEqual(adapter.profile(document), {level: "Power User", bonus: "123.4", seedingPoints: null, uploaded: "2.00 TiB", downloaded: "1.00 TiB", ratio: "2.000"});
  assert.equal(adapter.accountLink(document), "https://hdcity.city/userdetails");
  assert.equal(adapter.reuseRecentPage, true);
  assert.equal(adapter.navigationRetries, 1);
});

test("MonikaDesign reads scoped transfer metrics and Nanyang reads magic beans", () => {
  const metrics = {'.top-nav__stats-up': '1.25 TiB', '.top-nav__stats-down': '500.00 GiB', '.top-nav__stats-ratio': '2.560'};
  const snapshot = {querySelectorAll: () => [], querySelector: selector => ({textContent: metrics[selector], getAttribute: () => ''})};
  const profile = piggo.create('https://monikadesign.uk', '/', true).profile(snapshot);
  assert.equal(profile.uploaded, '1.25 TiB');
  assert.equal(profile.downloaded, '500.00 GiB');
  assert.equal(profile.ratio, '2.560');
  const header = {querySelectorAll: selector => selector === 'tr' ? [{textContent: '用户组：小小学士 魔力豆 (12,345.6)'}] : []};
  assert.equal(piggo.create('https://nanyangpt.com', '/', true).profile(header).bonus, '12,345.6');
  const compact = {querySelectorAll: () => [], querySelector: () => ({textContent: '魔力豆 (766,494.8)', getAttribute: () => ''})};
  assert.equal(piggo.create('https://nanyangpt.com', '/', true).profile(compact).bonus, '766,494.8');
  assert.equal(piggo.create('https://example.test', '/', true).profile(header).bonus, null);
});

test("AGSV recognizes its ice-crystal attendance and balance", () => {
  const adapter = piggo.create("https://www.agsvpt.com", "/attendance.php");
  const snapshot = documentFixture("", [element("[签到得冰晶]")]);
  assert.equal(adapter.inspect(snapshot, "https://www.agsvpt.com/index.php").status, "ready");
  assert.equal(adapter.inspect(documentFixture("", [element("[签到得冰晶]"), element("[签到得冰晶]")]), "https://www.agsvpt.com/index.php").status, "ready");
  const submit = element("立即签到", {tag: "INPUT"});
  assert.equal(adapter.action(documentFixture("", [element("[签到得冰晶]"), submit]), "https://www.agsvpt.com/attendance.php"), submit);
  const block = {cloneNode: () => ({querySelectorAll: () => [], textContent: "冰晶 [使用]: 12,345.6"})};
  assert.equal(adapter.profile({querySelectorAll: selector => selector.includes("#info_block") ? [block] : []}).bonus, "12,345.6");
  assert.equal(piggo.create("https://example.test").inspect(snapshot, "https://example.test/index.php").status, "unknown");
});

test("site currency labels are restricted to their own sites", () => {
  for (const [origin, label] of [["https://hhanclub.net", "[签到得憨豆]"], ["https://hxpt.org", "签到得火花"], ["https://pttime.org", "签到领魔力"], ["https://qingwapt.org", "[签到得蝌蚪]"], ["https://xingtan.one", "[签到得杏仁]"]]) {
    const snapshot = documentFixture("", [element(label)]);
    assert.equal(piggo.create(origin).inspect(snapshot, origin + "/index.php").status, "ready");
    assert.equal(piggo.create("https://audiences.me").inspect(snapshot, "https://audiences.me/index.php").status, "unknown");
  }
});

test("ZhiMengPT recognizes its electricity sign-in and maps electricity to magic", () => {
  const adapter = piggo.create("https://zmpt.cc");
  const entry = element("[签到得电力]", {href: "/attendance.php"});
  const snapshot = documentFixture("", [entry]);
  assert.equal(adapter.inspect(snapshot, "https://zmpt.cc/index.php").status, "ready");
  assert.equal(piggo.create("https://audiences.me").inspect(snapshot, "https://audiences.me/index.php").status, "unknown");
  const block = {cloneNode: () => ({querySelectorAll: () => [], textContent: "用户等级: Elite User 电力值 789.5 做种积分: 1,646,531.5 上传量: 16.332 TB 下载量: 294.79 GB 分享率: 56.731"})};
  const document = {querySelectorAll: selector => selector.includes("#info_block") ? [block] : []};
  assert.deepEqual(adapter.profile(document), {level: "Elite User", bonus: "789.5", seedingPoints: "1,646,531.5", uploaded: "16.332 TB", downloaded: "294.79 GB", ratio: "56.731"});
  const rows = [[{textContent: "电力值"}, {textContent: "1,234.5 [明细]"}]].map(cells => ({querySelectorAll: () => cells}));
  assert.equal(adapter.profile({querySelectorAll: selector => selector === "tr" ? rows : []}, true).bonus, "1,234.5");
});

test("PTSBao reuses its loaded homepage and requires scoped completion evidence", () => {
  const adapter = piggo.create("https://ptsbao.club");
  const home = "https://ptsbao.club/index.php";
  assert.equal(adapter.reuseRecentPage, true);
  assert.equal(piggo.create("https://www.ptsbao.club").reuseRecentPage, true);
  assert.equal(adapter.inspect(documentFixture("", [element("[签到得魔力]")]), home).status, "ready");
  assert.equal(adapter.inspect(documentFixture("", [element("[签到已得25]")]), home).status, "already_done");
  assert.equal(adapter.inspect(documentFixture("聊天：我签到成功了"), home).status, "unknown");
  assert.equal(adapter.safeAttendanceLink("https://evil.test/attendance.php", home), false);
});

test("UBits recognizes its U coin sign-in and current account row", () => {
  const adapter = piggo.create("https://ubits.club");
  const entry = element("[签到得U币]", {href: "/attendance.php"});
  const snapshot = documentFixture("", [entry]);
  assert.equal(adapter.inspect(snapshot, "https://ubits.club/index.php").status, "ready");
  assert.equal(adapter.reuseRecentPage, true);
  assert.equal(adapter.inspect(documentFixture("", [element("[签到已得25, 补签卡: 2]", {href: "/attendance.php"})]), "https://ubits.club/index.php").status, "already_done");
  assert.equal(piggo.create("https://audiences.me").inspect(snapshot, "https://audiences.me/index.php").status, "unknown");
  const block = {cloneNode: () => ({querySelectorAll: () => [], textContent: "U币 [使用]: 1,058,119.5 上传量: 10.742 TB 下载量: 231.34 GB 分享率: 47.547"})};
  const account = {getAttribute: () => "/userdetails.php?id=42"};
  const row = {textContent: "欢迎回来 fixture", querySelectorAll: selector => selector === 'a[href]' ? [account] : []};
  const document = {querySelectorAll: selector => selector.includes("#info_block") ? [block] : selector === "tr" ? [row] : []};
  assert.equal(adapter.accountLink(document), "https://ubits.club/userdetails.php?id=42");
  assert.deepEqual(adapter.profile(document), {level: null, bonus: "1,058,119.5", seedingPoints: null, uploaded: "10.742 TB", downloaded: "231.34 GB", ratio: "47.547"});
});

test("TTG recognizes its scoped inline sign-in and header statistics", () => {
  const adapter = piggo.create("https://totheglory.im");
  const entry = element("签到", {href: "javascript:void(0);"});
  entry.matches = selector => selector === "#signed";
  const snapshot = documentFixture("", [entry]);
  assert.equal(adapter.inspect(snapshot, "https://totheglory.im/index.php").status, "ready");
  assert.equal(piggo.create("https://audiences.me").inspect(snapshot, "https://audiences.me/index.php").status, "unknown");
  const query = snapshot.querySelectorAll;
  snapshot.querySelectorAll = selector => selector === "tr" ? [{textContent: "欢迎回来，fixture [已签到]"}] : selector === 'a[href]' ? [] : query(selector);
  assert.equal(adapter.inspect(snapshot, "https://totheglory.im/index.php").status, "already_done");
  const account = {getAttribute: () => "/userdetails.php?id=42"};
  const row = {textContent: "欢迎回来，fixture 分享率: 3.500 上传量: 7.00 TiB 下载量: 2.00 TiB 积分: 123,456.7", querySelectorAll: selector => selector === 'a[href]' ? [account] : []};
  const document = {querySelectorAll: selector => selector === "tr" ? [row] : []};
  assert.equal(adapter.accountLink(document), "https://totheglory.im/userdetails.php?id=42");
  assert.deepEqual(adapter.profile(document), {level: null, bonus: "123,456.7", seedingPoints: null, uploaded: "7.00 TiB", downloaded: "2.00 TiB", ratio: "3.500"});
});

test("SSD maps jasmine and seeding points during profile refresh", () => {
  const adapter = piggo.create("https://springsunday.net", "/", true, "SSD");
  const block = {cloneNode: () => ({querySelectorAll: () => [], textContent: "茉莉: 987,654.3 做种积分: 1.79 上传量: 9.538 TB 下载量: 170.82 GB 分享率: 57.176"})};
  const document = {querySelectorAll: selector => selector.includes("#info_block") ? [block] : []};
  assert.deepEqual(adapter.profile(document), {level: null, bonus: "987,654.3", seedingPoints: "1.79", uploaded: "9.538 TB", downloaded: "170.82 GB", ratio: "57.176"});
  assert.equal(adapter.inspect(document, "https://springsunday.net/index.php").status, "profile_only");
  assert.equal(adapter.reuseRecentPage, true);
  assert.equal(adapter.navigationRetries, 2);
  const rows = [[{textContent: "茉莉"}, {textContent: "1,234.5"}]].map(cells => ({querySelectorAll: () => cells}));
  assert.equal(adapter.profile({querySelectorAll: selector => selector === "tr" ? rows : []}, true).bonus, "1,234.5");
});

test("SewerPT recognizes its gold sign-in and maps gold to magic", () => {
  const adapter = piggo.create("https://sewerpt.com");
  const entry = element("[签到得金币]", {href: "/attendance.php"});
  const snapshot = documentFixture("欢迎回来 fixture 金币 [使用]: 108,689.1 分享率: 无限 上传量: 40.20 GB 下载量: 0.00 KB 做种积分: 108,689.1", [entry]);
  assert.equal(adapter.inspect(snapshot, "https://sewerpt.com/index.php").status, "ready");
  assert.equal(adapter.action(snapshot, "https://sewerpt.com/index.php"), entry);
  assert.equal(adapter.reuseRecentPage, true);
  assert.equal(adapter.navigationRetries, 2);
  assert.equal(piggo.create("https://audiences.me").inspect(snapshot, "https://audiences.me/index.php").status, "unknown");
  const block = {cloneNode: () => ({querySelectorAll: () => [], textContent: snapshot.body.innerText})};
  const profile = {querySelectorAll: selector => selector.includes("#info_block") ? [block] : []};
  assert.deepEqual(adapter.profile(profile), {level: null, bonus: "108,689.1", seedingPoints: "108,689.1", uploaded: "40.20 GB", downloaded: "0.00 KB", ratio: "∞"});
  const rows = [[{textContent: "金币"}, {textContent: "123,456.7"}]].map(cells => ({querySelectorAll: () => cells}));
  assert.equal(adapter.profile({querySelectorAll: selector => selector === "tr" ? rows : []}, true).bonus, "123,456.7");
});

test("PTLGS recognizes its work-points sign-in and maps work points to magic", () => {
  const adapter = piggo.create("https://ptlgs.org");
  const entry = element("[签到得工分]", {href: "/attendance.php"});
  const snapshot = documentFixture("欢迎回来 fixture 工分 [使用]: 98,765.4 分享率: 无限 上传量: 12.34 TB 下载量: 56.78 GB 做种积分: 123.45", [entry]);
  assert.equal(adapter.inspect(snapshot, "https://ptlgs.org/index.php").status, "ready");
  assert.equal(adapter.action(snapshot, "https://ptlgs.org/index.php"), entry);
  assert.equal(adapter.reuseRecentPage, true);
  assert.equal(adapter.navigationRetries, 2);
  assert.equal(piggo.create("https://audiences.me").inspect(snapshot, "https://audiences.me/index.php").status, "unknown");
  const block = {cloneNode: () => ({querySelectorAll: () => [], textContent: snapshot.body.innerText})};
  const profile = {querySelectorAll: selector => selector.includes("#info_block") ? [block] : []};
  assert.deepEqual(adapter.profile(profile), {level: null, bonus: "98,765.4", seedingPoints: "123.45", uploaded: "12.34 TB", downloaded: "56.78 GB", ratio: "∞"});
  const rows = [[{textContent: "工分"}, {textContent: "5,432.1"}]].map(cells => ({querySelectorAll: () => cells}));
  assert.equal(adapter.profile({querySelectorAll: selector => selector === "tr" ? rows : []}, true).bonus, "5,432.1");
});

test("52PT's current restricted entry stops before the retired status endpoint", () => {
  const adapter = piggo.create("https://52pt.site", "/bakatest.php");
  const entry = element("做种会员签到处", {href: "bakatestfinal.php"});
  const snapshot = documentFixture("欢迎回来 fixture", [entry]);
  snapshot.querySelectorAll = selector => selector === '#game[href="bakatestfinal.php"]' || selector.startsWith('a[href]') ? [entry] : [];
  assert.equal(adapter.inspect(snapshot, "https://52pt.site/index.php").status, "manual_required");
  assert.match(adapter.inspect(snapshot, "https://52pt.site/index.php").message, /限制脚本/);
  assert.equal(adapter.inspect(snapshot, "https://evil.test/index.php").status, "unknown");
  entry.innerText = "签到记录";
  assert.equal(adapter.inspect(snapshot, "https://52pt.site/index.php").status, "unknown");
});

test("maintenance-only pages report the site outage without matching announcements", () => {
  for (const origin of ["https://hdvideo.top", "https://ptsbao.club"]) {
    const adapter = piggo.create(origin);
    const snapshot = documentFixture("站点关闭维护中，请稍后再访问...谢谢", []);
    const inspection = adapter.inspect(snapshot, origin + "/index.php");
    assert.equal(inspection.status, "error");
    assert.match(inspection.message, /维护/);
    assert.equal(inspection.control, null);
    assert.equal(adapter.inspect(snapshot, "https://evil.test/").status, "unknown");
    const entry = element("签到", {href: "/attendance.php"});
    const announcement = documentFixture("欢迎回来 fixture 公告：站点关闭维护中，请稍后再访问...谢谢", [entry]);
    assert.equal(adapter.inspect(announcement, origin + "/index.php").status, "ready");
  }
});

test("PterClub recognizes its inline cat-food sign-in and cleans the current rank", () => {
  for (const origin of ["https://pterclub.net", "https://pterclub.com"]) {
    const adapter = piggo.create(origin);
    const entry = element("签到得猫粮", {href: "/index.php"});
    entry.matches = selector => selector === "#do-attendance";
    const snapshot = documentFixture("欢迎回来 fixture 猫粮 [使用 | 站免池]: 88,765.4 分享率: 2.500 上传量: 10.00 TB 下载量: 4.00 TB 做种积分: 321.5", [entry]);
    assert.equal(adapter.inspect(snapshot, `${origin}/index.php`).status, "ready");
    assert.equal(adapter.action(snapshot, `${origin}/index.php`), entry);
    entry.innerText = "已签到";
    assert.equal(adapter.inspect(snapshot, `${origin}/index.php`).status, "already_done");
    entry.innerText = "签到得猫粮";
    snapshot.querySelectorAll = selector => selector === "tr" ? [{textContent: "欢迎回来 fixture 猫粮: 88,765.4 (签到已得10)"}] : selector === 'a[href]' ? [] : [];
    assert.equal(adapter.inspect(snapshot, `${origin}/index.php`).status, "already_done");
    const block = {cloneNode: () => ({querySelectorAll: () => [], textContent: snapshot.body.innerText})};
    const rows = [[{textContent: "等级"}, {textContent: "加菲猫 POWER USER", querySelectorAll: () => []}], [{textContent: "猫粮"}, {textContent: "88,765.4", querySelectorAll: () => []}]].map(cells => ({querySelectorAll: () => cells}));
    const profile = {querySelectorAll: selector => selector.includes("#info_block") ? [block] : selector === "tr" ? rows : []};
    assert.deepEqual(adapter.profile(profile, true), {level: "POWER USER", bonus: "88,765.4", seedingPoints: "321.5", uploaded: "10.00 TB", downloaded: "4.00 TB", ratio: "2.500"});
    assert.equal(adapter.reuseRecentPage, true);
    assert.equal(adapter.navigationRetries, 2);
  }
});

test("PTTime accepts only its known sign query for the current account", () => {
  const adapter = piggo.create("https://www.pttime.org");
  const entry = element("签到领魔力", {href: "/attendance.php?type=sign&uid=42"});
  const snapshot = documentFixture("", [entry]);
  const query = snapshot.querySelectorAll;
  snapshot.querySelectorAll = selector => selector.includes("#info_block a[href]") ? [element("fixture", {href: "/userdetails.php?id=42"})] : query(selector);
  assert.equal(adapter.inspect(snapshot, "https://www.pttime.org/index.php").status, "ready");
  for (const href of ["/attendance.php?type=sign&uid=43", "/attendance.php?type=buy&uid=42", "/attendance.php?type=sign&uid=42&submit=1", "/attendance.php?type=sign&uid=42&uid=43", "https://evil.test/attendance.php?type=sign&uid=42"]) {
    entry.getAttribute = () => href;
    assert.equal(adapter.inspect(snapshot, "https://www.pttime.org/index.php").status, "unknown");
  }
});

test("HDArea inline entries require the own user bar and cannot click other navigation", () => {
  const adapter = piggo.create("https://hdarea.club");
  const entry = element("[签到]", {href: "javascript:void(0)"});
  entry.hasAttribute = name => name === "onclick";
  entry.closest = () => ({id: "info_block"});
  const snapshot = documentFixture("", [entry]);
  assert.equal(adapter.inspect(snapshot, "https://hdarea.club/index.php").status, "ready");
  assert.equal(piggo.create("https://audiences.me").inspect(snapshot, "https://audiences.me/index.php").status, "unknown");
  entry.innerText = "[已签到]";
  assert.equal(adapter.inspect(snapshot, "https://hdarea.club/index.php").status, "already_done");
  entry.closest = () => null;
  assert.equal(adapter.inspect(snapshot, "https://hdarea.club/index.php").status, "unknown");
});

test("52PT trusts its own account link and reads the nested transfer table and grade image", () => {
  const adapter = piggo.create("https://52pt.site", "/bakatest.php");
  const link = {getAttribute: () => "/userdetails.php?id=42#private"};
  assert.equal(adapter.accountLink({querySelectorAll: selector => selector === "#info_block a.User_Name[href]" ? [link] : []}), "https://52pt.site/userdetails.php?id=42");
  const grade = {textContent: "", querySelectorAll: () => [{getAttribute: () => "(幼儿班)User"}]};
  const transfer = {textContent: "分享率: 192,560.378 上传量: 188.05 GB 下载量: 1.00 MB", querySelectorAll: () => ["分享率: 192,560.378", "上传量: 188.05 GB", "下载量: 1.00 MB"].map(textContent => ({textContent}))};
  const rows = [[{textContent: "等级"}, grade], [{textContent: "传输"}, transfer], [{textContent: "魔力值"}, {textContent: "1228942.83"}]].map(cells => ({querySelectorAll: () => cells}));
  const profile = adapter.profile({querySelectorAll: selector => selector === "tr" ? rows : []}, true);
  assert.deepEqual(profile, {level: "User", bonus: "1228942.83", seedingPoints: null, uploaded: "188.05 GB", downloaded: "1.00 MB", ratio: "192,560.378"});
});

test("Audiences reads popcorn points, rank and nested transfer fields", () => {
  const adapter = piggo.create("https://audiences.me");
  const grade = {textContent: "", querySelectorAll: () => [{getAttribute: () => "(年轻气盛)Power User"}]};
  const transfer = {textContent: "分享率: 64.820 上传量: 132.270 TB 下载量: 2.041 TB", querySelectorAll: () => ["分享率: 64.820", "上传量: 132.270 TB", "下载量: 2.041 TB"].map(textContent => ({textContent}))};
  const rows = [[{textContent: "等级"}, grade], [{textContent: "传输"}, transfer], [{textContent: "爆米花"}, {textContent: "229786.3"}]].map(cells => ({querySelectorAll: () => cells}));
  const profile = adapter.profile({querySelectorAll: selector => selector === "tr" ? rows : []}, true);
  assert.deepEqual(profile, {level: "Power User", bonus: "229786.3", seedingPoints: null, uploaded: "132.270 TB", downloaded: "2.041 TB", ratio: "64.820"});
});

test("Audiences reads current stat cards and the rank from its profile text", () => {
  const adapter = piggo.create("https://audiences.me");
  const stat = (label, value) => ({
    textContent: `${value}${label}`,
    querySelector: selector => selector.includes('label') ? {textContent: label} : selector.includes('value') ? {textContent: value} : null
  });
  const stats = [stat("上传量", "132.270 TB"), stat("下载量", "2.041 TB"), stat("分享率", "64.820"), stat("爆米花", "229786.3")];
  const document = {
    body: {textContent: "mapleren (年轻气盛)Power User 加入日期"},
    querySelectorAll: selector => selector === '[class*="stat"], [class*="metric"]' ? stats : []
  };
  assert.deepEqual(adapter.profile(document, true), {level: "Power User", bonus: "229786.3", seedingPoints: null, uploaded: "132.270 TB", downloaded: "2.041 TB", ratio: "64.820"});
});

test("Audiences discovers the account page from its site user bar", () => {
  const adapter = piggo.create("https://audiences.me");
  const link = {getAttribute: () => "/userdetails.php?id=42"};
  const document = {
    querySelectorAll: selector => selector === ".site-userbar a[href]" ? [link] : [],
  };
  assert.equal(adapter.accountLink(document), "https://audiences.me/userdetails.php?id=42");
});

for (const [name, snapshot, expected] of [
  ["anti-debug notice overrides an apparent success", {text: "当前环境正在被调试 签到成功"}, "debugging"],
  ["WAF overrides a historical already-done notice", {text: "雷池 WAF 今日已签到"}, "blocked"],
  ["human verification stops submission", {text: "验证您是真人"}, "blocked"],
  ["login redirect overrides historical success", {url: "https://piggo.me/login.php", text: "签到成功"}, "login_required"],
  ["visible password form requires login", {password: true}, "login_required"],
  ["broken streak requires user decision", {text: "已断签 3 天 请选择补签 今日已签到"}, "manual_required"],
  ["today already done", {text: "今天已经签过到了"}, "already_done"],
  ["successful response", {text: "签到成功"}, "success"],
  ["captcha stops submission", {captcha: true}, "manual_required"],
  ["unknown page never claims success", {text: "欢迎回来 PigGo"}, "unknown"]
]) {
  test(name, () => assert.equal(piggo.classify({url: "https://piggo.me/attendance.php", ...snapshot}), expected));
}

test("only a clean same-origin attendance link can be clicked", () => {
  for (const href of ["https://evil.test/attendance.php", "/attendance.php?action=buy", "/attendance.php#buy", "javascript:signin()", "/bonus.php"]) assert.equal(piggo.safeAttendanceLink(href, "https://piggo.me/"), false);
  assert.equal(piggo.safeAttendanceLink("attendance.php", "https://piggo.me/"), true);
});

test("inspection finds a single safe entry and ignores hidden or unrelated controls", () => {
  const entry = element("[签到]");
  const document = documentFixture("欢迎", [element("删除账号"), element("签到", {href: "/logout.php"}), element("签到", {hidden: true}), entry]);
  assert.deepEqual(piggo.inspect(document, "https://piggo.me/"), {status: "ready", control: entry});
});

test("HXPT permits only its scoped hidden official entry during explicit sign-in", () => {
  const adapter = piggo.create("https://www.hxpt.org");
  const current = "https://www.hxpt.org/";
  function entry(label = "签到得火花", options = {}, scoped = true) {
    return {...element(label, options), textContent: label, getBoundingClientRect: () => ({width: 0, height: 0}), matches: selector => scoped && selector === ".cute-top-profile__dropdown a.cute-top-profile__attendance-link"};
  }
  const official = entry();
  assert.equal(adapter.action(documentFixture("", [official]), current), null);
  assert.equal(adapter.action(documentFixture("", [official]), current, true), official);
  for (const rejected of [entry("签到"), entry("签到得火花", {}, false), entry("签到得火花", {hidden: true}), entry("签到得火花", {disabled: true}), entry("签到得火花", {href: "https://evil.test/attendance.php"}), entry("签到得火花", {href: "/logout.php"}), entry("签到得火花", {href: "/attendance.php?submit=1"}), entry("签到得火花", {href: "/attendance.php#sign"}), entry("签到得火花", {tag: "BUTTON"})]) {
    assert.equal(adapter.action(documentFixture("", [rejected]), current, true), null);
  }
  assert.equal(adapter.action(documentFixture("", [official, entry()]), current, true), "ambiguous");
  assert.equal(adapter.action(documentFixture("", [official]), "https://evil.test/", true), null);
  assert.equal(piggo.action(documentFixture("", [official]), "https://piggo.me/", true), null);
  assert.equal(adapter.inspect(documentFixture("", [official], {captcha: true}), current).status, "manual_required");
});

test("Haitang prefers only its current-day same-origin attendance form over calendar links", () => {
  const adapter = piggo.create("https://www.htpt.cc");
  const current = "https://www.htpt.cc/attendance.php";
  const submit = element("立即签到（第 1 天，可获得 10 魔力值）", {tag: "INPUT"});
  const calendar = {...element("签到", {tag: "BUTTON"}), form: null};
  assert.equal(adapter.continueAttendanceForm, true);
  assert.equal(adapter.action(documentFixture("", [element("签到"), submit, calendar, element("补签")]), current), submit);
  for (const rejected of [element("立即签到（第 1 天，可获得 10 魔力值）", {tag: "INPUT", action: "https://evil.test/attendance.php"}), element("立即签到（第 1 天，可获得 10 魔力值）", {tag: "INPUT", action: "/attendance.php?action=retroactive"}), calendar]) {
    assert.equal(adapter.action(documentFixture("", [rejected]), current), null);
  }
  assert.equal(adapter.action(documentFixture("", [submit]), "https://www.htpt.cc/index.php"), null);
  assert.equal(adapter.inspect(documentFixture("", [submit], {captcha: true}), current).status, "manual_required");
});

test("unreachable human verification remains blocked with a precise reason", () => {
  const result = piggo.inspect(documentFixture("无法连接人机验证服务", [element("签到")]), "https://piggo.me/attendance.php");
  assert.equal(result.status, "blocked");
  assert.equal(result.control, null);
  assert.equal(result.message, "无法连接人机验证服务，请稍后在站点重试验证");
});

test("ambiguous entries require manual interaction", () => {
  const document = documentFixture("", [element("签到"), element("每日签到")]);
  assert.deepEqual(piggo.inspect(document, "https://piggo.me/"), {status: "ambiguous", control: null});
});

test("form submissions must originate on attendance and target attendance", () => {
  const entry = element("立即签到", {tag: "BUTTON"});
  assert.equal(piggo.action(documentFixture("", [entry]), "https://piggo.me/"), null);
  assert.equal(piggo.action(documentFixture("", [entry]), "https://piggo.me/attendance.php"), entry);
  for (const action of ["/bonus.php", "https://evil.test/attendance.php"]) {
    assert.equal(piggo.action(documentFixture("", [element("签到", {tag: "BUTTON", action})]), "https://piggo.me/attendance.php"), null);
  }
});

test("already done or blocked pages never expose an action", () => {
  for (const text of ["今日已签到", "签到成功", "当前环境正在被调试"]) assert.equal(piggo.inspect(documentFixture(text, [element("签到")]), "https://piggo.me/attendance.php").control, null);
});

test("home page chat or history cannot claim today's completion", () => {
  const entry = element("签到");
  const document = documentFixture("聊天：今日已签到；签到成功；签到已得130", [entry]);
  assert.equal(piggo.inspect(document, "https://piggo.me/index.php").status, "ready");
  assert.equal(piggo.classify({url: "https://piggo.me/index.php", text: "签到已得130"}), "unknown");
});

test("the current account's exact attendance reward link is recognized", () => {
  const document = documentFixture("", [element("[签到已得130, 补签卡: 25]")]);
  assert.equal(piggo.inspect(document, "https://piggo.me/index.php").status, "already_done");
  const other = documentFixture("签到已得130", [element("[签到已得130, 补签卡: 25]", {href: "/forums.php"})]);
  assert.equal(piggo.inspect(other, "https://piggo.me/index.php").status, "unknown");
});

test("results contain fixed messages and paths without private URL parameters", () => {
  const result = piggo.result("success", "https://piggo.me/attendance.php?token=secret#private");
  assert.equal(result.path, "/attendance.php");
  assert.equal(JSON.stringify(result).includes("secret"), false);
  assert.deepEqual(Object.keys(result).sort(), ["message", "path", "status", "time"]);
});

test("profile extraction separates the account rank from its neighboring help text", () => {
  const cells = [{textContent: "用户等级"}, {textContent: "(小学)Power User 🔗 校验等级加群参考《规则&教程》第二部分第4条，等级参考第五部分。"}];
  const row = {querySelectorAll: () => cells};
  const document = {querySelectorAll: selector => selector === "tr" ? [row] : []};
  assert.equal(piggo.profile(document, true).level, "Power User");
});

test("profile details clean bonus links and keep seeding points independent", () => {
  const rows = [["魔力值", "18,142,137.0 [明细]"], ["做种积分", "123.45 [明细]"], ["用户等级", "等级详情/提升等级"]].map(values => ({querySelectorAll: () => values.map(textContent => ({textContent}))}));
  const profile = piggo.profile({querySelectorAll: selector => selector === "tr" ? rows : []}, true);
  assert.equal(profile.bonus, "18,142,137.0");
  assert.equal(profile.seedingPoints, "123.45");
  assert.equal(profile.level, null);
});

test("current rank lookup trusts only a unique same-origin classes fragment in the account region", () => {
  const adapter = piggo.create("https://tjupt.org");
  const link = href => ({getAttribute: () => href});
  const document = links => ({querySelectorAll: () => links});
  assert.equal(adapter.classLink(document([link("/classes.php#6")])), "https://tjupt.org/classes.php#6");
  for (const links of [[link("https://evil.test/classes.php#6")], [link("/classes.php?action=upgrade#6")], [link("/classes.php")], [link("/classes.php#6"), link("/classes.php#5")]]) assert.equal(adapter.classLink(document(links)), null);
  const gradeCell = {textContent: "威震一方 Veteran User 目前人数: 2805人"};
  const currentAnchor = {closest: () => ({querySelector: () => gradeCell})};
  const classes = {getElementById: fragment => fragment === "6" ? currentAnchor : null, querySelectorAll: () => []};
  assert.equal(adapter.classLevel(classes, "https://tjupt.org/classes.php#6"), "Veteran User");
  assert.equal(adapter.classLevel(classes, "https://tjupt.org/classes.php#5"), null);
  assert.equal(adapter.classLevel(classes, "https://evil.test/classes.php#6"), null);
});

test("KEEPFRDS reads the current user bar grade rather than the next-class requirements", () => {
  const adapter = piggo.create("https://pt.keepfrds.com");
  const block = {cloneNode: () => ({querySelectorAll: () => [], textContent: "欢迎回来 fixture(Insane User) 魔力值：856003.8 上传量：4.087 TiB"})};
  const cells = [{textContent: "等级"}, {textContent: "Next class: Veteran UserAccount age (days): 822.58 / 224 (Met)", querySelectorAll: () => []}];
  const row = {querySelectorAll: () => cells};
  const snapshot = {querySelectorAll: selector => selector === "tr" ? [row] : [block]};
  assert.equal(adapter.profile(snapshot).level, "Insane User");
  assert.equal(adapter.profile(snapshot, true).level, "Insane User");
  assert.equal(adapter.profile(snapshot, true).uploaded, "4.087 TiB");
  block.cloneNode = () => ({querySelectorAll: () => [], textContent: "欢迎回来 fixture"});
  assert.equal(adapter.profile(snapshot, true).level, null);
});

test("a header containing only seeding points does not populate magic", () => {
  const block = {cloneNode: () => ({querySelectorAll: () => [], textContent: "做种积分：123.45"})};
  const profile = piggo.profile({querySelectorAll: () => [block]});
  assert.equal(profile.seedingPoints, "123.45");
  assert.equal(profile.bonus, null);
});
