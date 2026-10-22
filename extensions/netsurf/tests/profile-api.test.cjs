const assert = require("node:assert/strict");
const test = require("node:test");
const {webcrypto} = require("node:crypto");
const api = require("../profile-api.js");

function environment(fetch, initial = {}) {
  const values = new Map(Object.entries(initial));
  return {fetch, crypto: webcrypto, TextEncoder, FormData, btoa, document: initial.document, localStorage: {getItem: key => values.get(key), setItem: (key, value) => values.set(key, value)}};
}

test("Zhuque reads the current account API rather than a blank SPA shell", async () => {
  const result = await api.read("https://zhuque.in", "zhuque", undefined, environment(async (url, options) => {
    assert.equal(url, "https://zhuque.in/api/user/getInfo");
    assert.equal(options.credentials, "include");
    assert.equal(options.method, undefined);
    assert.equal(options.headers["x-csrf-token"], "fixture-csrf");
    return new Response(JSON.stringify({data: {id: 42, class: {name: "Power User"}, upload: 1073741824, download: 536870912, bonus: 123.4, seedBonus: 567.8}}));
  }, {document: {querySelector: selector => selector === 'meta[name="x-csrf-token"]' ? {content: " fixture-csrf "} : null}}));
  assert.equal(result.status, "profile_only");
  assert.equal(result.profile.level, "Power User");
  assert.equal(result.profile.bonus, "123.4");
  assert.equal(result.profile.seedingPoints, "567.8");
  assert.equal(result.profile.uploaded, "1.00 GiB");
  assert.equal(result.profile.ratio, "2.000");
  assert.equal(result.diagnostic.accountFound, true);
});

test("M-Team uses only the signed own-profile endpoint and never exports its session", async () => {
  const session = "fixture-session";
  const runtime = environment(async (url, options) => {
    assert.equal(url, "https://api.m-team.cc/api/member/profile");
    assert.equal(options.method, "POST");
    assert.equal(options.headers.authorization, session);
    assert.equal(typeof options.body.get("_sgin"), "string");
    assert.ok(options.body.get("_timestamp"));
    return new Response(JSON.stringify({code: "0", data: {id: 42, memberStatus: {name: "VIP"}, memberCount: {uploaded: 1024, downloaded: 0, bonus: "1.5"}}}), {headers: {authorization: "fixture-refreshed-session"}});
  }, {auth: session});
  const result = await api.read("https://kp.m-team.cc", "mteam", undefined, runtime);
  assert.equal(result.status, "profile_only");
  assert.equal(result.profile.uploaded, "1.00 KiB");
  assert.equal(result.profile.ratio, "∞");
  assert.equal(runtime.localStorage.getItem("auth"), "fixture-refreshed-session");
  assert.equal(JSON.stringify(result).includes("session"), false);
});

test("API adapter rejects other origins and stops unauthenticated sessions", async () => {
  const runtime = environment(() => { throw new Error("Unexpected request"); });
  for (const origin of ["https://evil.test", "http://kp.m-team.cc", "https://kp.m-team.cc.evil.test"]) await assert.rejects(api.read(origin, "mteam", undefined, runtime));
  assert.equal((await api.read("https://kp.m-team.cc", "mteam", undefined, runtime)).status, "login_required");
});

test("API errors retain precise status and never manufacture account fields", async () => {
  for (const [code, expected] of [[401, "login_required"], [468, "blocked"], [500, "error"]]) {
    const result = await api.read("https://zhuque.in", "zhuque", undefined, environment(async () => new Response("", {status: code})));
    assert.equal(result.status, expected);
    assert.equal(result.diagnostic.httpStatus, code);
    assert.equal(result.profile, undefined);
  }
  const result = await api.read("https://zhuque.in", "zhuque", undefined, environment(async () => new Response(JSON.stringify({data: {upload: 1234}}))));
  assert.equal(result.status, "unknown");
  assert.equal(result.profile, undefined);
});

function modernFixture(kind, confirmed = true) {
  let signed = false;
  let posts = 0;
  const runtime = environment(async (url, options) => {
    const path = new URL(url).pathname;
    if (options.method === "POST") {
      posts += 1;
      if (kind === "rousi") {
        assert.equal(options.headers["X-CSRF-Token"], "fixture-csrf");
        assert.ok(options.headers["Idempotency-Key"]);
      }
      signed = confirmed;
      if (!confirmed) throw new Error("Unconfirmed request");
    }
    const payloads = kind === "rousi" ? {
      "/api/v1/session": {user: {id: 42}, csrf_token: "fixture-csrf"},
      "/api/v1/me/traffic": {totals: {credited_uploaded_bytes: 1024, charged_downloaded_bytes: 512}},
      "/api/v1/me/economy": {magic_balance: 42, progress: {level: 6}},
      "/api/v1/me/attendance": {claimed_today: signed}
    } : {
      "/api/auth/session": {data: {accessToken: "fixture-session"}},
      "/api/v1/user/details/info": {data: {id: 42, title: "Power User", uploaded: 1024, downloaded: 512, seed_bonus: 42}},
      "/api/v1/attendance/status": {data: {checked_in: signed}},
      "/api/v1/attendance/check-in": {data: {}}
    };
    assert.ok(Object.hasOwn(payloads, path), path);
    return new Response(JSON.stringify(payloads[path]));
  });
  return {runtime, posts: () => posts, origin: kind === "rousi" ? "https://rousi.pro" : "https://sunnypt.top"};
}

test("modern trackers read only account and attendance APIs and omit session tokens", async () => {
  for (const kind of ["rousi", "sunny"]) {
    const fixture = modernFixture(kind);
    const result = await api.read(fixture.origin, kind, undefined, fixture.runtime);
    assert.equal(result.status, "ready");
    assert.equal(result.profile.uploaded, "1.00 KiB");
    assert.equal(result.profile.ratio, "2.000");
    assert.equal(result.profile.bonus, "42");
    assert.equal(fixture.posts(), 0);
    assert.equal(/fixture-csrf|fixture-session/.test(JSON.stringify(result)), false);
  }
});

test("modern tracker sign-in submits exactly once and requires server confirmation", async () => {
  for (const kind of ["rousi", "sunny"]) {
    for (const confirmed of [true, false]) {
      const fixture = modernFixture(kind, confirmed);
      const result = await api.signIn(fixture.origin, kind, undefined, fixture.runtime);
      assert.equal(result.status, confirmed ? "success" : "pending");
      assert.equal(fixture.posts(), 1);
      assert.equal(/fixture-csrf|fixture-session/.test(JSON.stringify(result)), false);
    }
  }
});

test("switching to refresh-only at the API submission boundary cancels the POST", async () => {
  for (const kind of ["rousi", "sunny"]) {
    const fixture = modernFixture(kind);
    const result = await api.signIn(fixture.origin, kind, undefined, fixture.runtime, async () => false);
    assert.equal(result.status, "refreshed");
    assert.equal(fixture.posts(), 0);
  }
});
