const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");
const piggo = require("../piggo.js");

function harness(initial = "ready", builtInRefresh = false, {accountWait = false, headerProfile = null, pageUrl = "https://piggo.me/"} = {}) {
  let status = initial;
  let freshStatus = initial;
  let clicked = 0;
  let refreshOnly = false;
  let refreshOnPending = false;
  let listener;
  const messages = [];
  const requests = [];
  const snapshot = {querySelectorAll: () => []};
  const context = vm.createContext({
    URL,
    document: {documentElement: {}},
    location: {href: pageUrl, pathname: new URL(pageUrl).pathname},
    clearTimeout, setTimeout,
    AbortController,
    DOMParser: class { parseFromString() { return snapshot; } },
    fetch: async (url, options) => {
      requests.push({url, options});
      if (accountWait && url.includes("/userdetails.php")) return new Promise((resolve, reject) => options.signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), {once: true}));
      return {url, status: 200, ok: true, text: async () => ""};
    },
    MutationObserver: class { observe() {} },
    NetSurfSites: {resolve: () => null, refreshOnlyRequired: () => builtInRefresh},
    NetSurfPiggo: {
      ...piggo,
      ...(headerProfile ? {profile: () => headerProfile, accountLink: () => "https://piggo.me/userdetails.php?id=42"} : {}),
      inspect: document => ({status: document === snapshot ? freshStatus : status}),
      action: () => ({click: () => { clicked += 1; }})
    },
    chrome: {storage: {local: {get: async () => ({sites: {piggo: {refreshOnly}, "audiences.me": {refreshOnly: true}}})}}, runtime: {
      id: "netsurf-test",
      getManifest: () => ({version: "0.4.8"}),
      sendMessage: async message => { messages.push(message); if (refreshOnPending && message.result?.status === "pending") refreshOnly = true; },
      onMessage: {addListener: callback => { listener = callback; }}
    }}
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, "..", "content.js"), "utf8"), context);
  return {
    messages, requests,
    clicks: () => clicked,
    setStatus: value => { status = value; freshStatus = value; },
    setFreshStatus: value => { freshStatus = value; },
    setRefreshOnly: value => { refreshOnly = value; },
    refreshBeforeClick: () => { refreshOnPending = true; },
    send: (type, senderId = "netsurf-test", extra = {}) => new Promise(resolve => listener({type: `netsurf-${type}`, ...extra}, {id: senderId}, resolve)),
    foreign: type => listener({type}, {id: "foreign"}, () => { throw new Error("responded to foreign caller"); })
  };
}

test("content script reports the page, then announces automatic mode without clicking", async () => {
  const runtime = harness();
  await Promise.resolve();
  assert.equal(runtime.clicks(), 0);
  assert.deepEqual(runtime.messages.map(message => message.type), ["observed", "auto"]);
});

test("a stalled optional profile request returns the known homepage status and fields within budget", async () => {
  const runtime = harness("already_done", false, {accountWait: true, headerProfile: {level: "User", bonus: "42", uploaded: "1 GiB", downloaded: null}});
  const result = await runtime.send("inspect", "netsurf-test", {fresh: true, timeoutMs: 300});
  assert.equal(result.status, "already_done");
  assert.equal(result.profile.level, "User");
  assert.equal(result.profile.bonus, "42");
  assert.equal(result.diagnostic.auxiliary[0].path, "/userdetails.php");
  assert.match(result.diagnostic.auxiliary[0].error, /读取超时/);
  assert.equal(runtime.clicks(), 0);
});

test("an about-blank page cannot register a tracker listener or announce automation", async () => {
  const runtime = harness("unknown", false, {pageUrl: "about:blank"});
  await Promise.resolve();
  assert.equal(runtime.messages.length, 0);
  assert.equal(runtime.requests.length, 0);
});

test("built-in refresh mode still reads account fields when the homepage has a manual challenge", async () => {
  const runtime = harness("manual_required", true, {headerProfile: {level: "User", bonus: "42"}});
  const result = await runtime.send("inspect", "netsurf-test", {fresh: true});
  assert.equal(result.status, "refreshed");
  assert.equal(result.profile.level, "User");
  assert.equal(runtime.clicks(), 0);
});

test("refresh-only prevents clicks even when switched on just before submission", async () => {
  for (const late of [false, true]) {
    const runtime = harness();
    if (late) runtime.refreshBeforeClick();
    else runtime.setRefreshOnly(true);
    assert.equal((await runtime.send("signin")).status, "ready");
    assert.equal(runtime.clicks(), 0);
  }
});

test("a built-in refresh-only rule blocks submission even with stored mode off", async () => {
  const runtime = harness("ready", true);
  assert.equal((await runtime.send("signin")).status, "ready");
  assert.equal(runtime.clicks(), 0);
});

test("concurrent sign-in messages only click once in the same document", async () => {
  const runtime = harness();
  const results = await Promise.all([runtime.send("signin"), runtime.send("signin")]);
  assert.equal(runtime.clicks(), 1);
  assert.ok(results.every(result => result.status === "pending"));
});

test("content rechecks current safety status before clicking", async () => {
  const runtime = harness();
  runtime.setStatus("debugging");
  assert.equal((await runtime.send("signin")).status, "debugging");
  assert.equal(runtime.clicks(), 0);
});

test("manual inspection never submits and cannot be invoked by another extension", async () => {
  const runtime = harness();
  assert.equal((await runtime.send("inspect")).status, "ready");
  runtime.foreign("signin");
  assert.equal(runtime.clicks(), 0);
});

test("sign-in reads the server even when the live document still shows yesterday's completion", async () => {
  const runtime = harness("already_done");
  runtime.setFreshStatus("ready");
  assert.equal((await runtime.send("signin")).status, "pending");
  assert.equal(runtime.clicks(), 1);
  assert.equal(runtime.requests[0].url, "https://piggo.me/index.php");
  assert.equal(runtime.requests[0].options.cache, "no-store");
  assert.equal(runtime.requests[0].options.credentials, "same-origin");
});

test("a fresh server login or WAF response prevents clicking a stale ready page", async () => {
  for (const fresh of ["debugging", "login_required", "blocked", "already_done"]) {
    const runtime = harness("ready");
    runtime.setFreshStatus(fresh);
    assert.equal((await runtime.send("signin")).status, fresh);
    assert.equal(runtime.clicks(), 0);
  }
});
