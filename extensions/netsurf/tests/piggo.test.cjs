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

test("NetSurf keeps automatic host access scoped and asks for all-cookie access optionally", () => {
  assert.equal(manifest.name, "NetSurf");
  assert.equal(manifest.manifest_version, 3);
  assert.equal(manifest.action.default_popup, undefined);
  assert.deepEqual(manifest.permissions, ["storage", "alarms", "scripting"]);
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
  const account = element("fixture", {href: "/userdetails.php?id=42"});
  const document = {querySelectorAll: selector => selector.endsWith(", body") ? [block] : selector === "body a[href]" ? [account] : []};
  assert.deepEqual(adapter.profile(document), {level: "Power User", bonus: "123.4", seedingPoints: null, uploaded: "2.00 TiB", downloaded: "1.00 TiB", ratio: "2.000"});
  assert.equal(adapter.accountLink(document), "https://hdcity.city/userdetails.php?id=42");
  assert.equal(adapter.reuseRecentPage, true);
  assert.equal(adapter.navigationRetries, 1);
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

test("UBits recognizes its U coin sign-in and current account row", () => {
  const adapter = piggo.create("https://ubits.club");
  const entry = element("[签到得U币]", {href: "/attendance.php"});
  const snapshot = documentFixture("", [entry]);
  assert.equal(adapter.inspect(snapshot, "https://ubits.club/index.php").status, "ready");
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
