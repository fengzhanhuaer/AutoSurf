const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

function harness(origin = "https://zhuque.in") {
  const attributes = new Map();
  const requests = [];
  class FixtureRequest {
    constructor() { this.listeners = {}; this.responseType = "json"; }
    open() { return "opened"; }
    send() { return "sent"; }
    addEventListener(name, callback) { this.listeners[name] = callback; }
    load(payload, status = 200) { this.status = status; this.response = payload; this.listeners.load.call(this); }
  }
  const originalFetch = (...args) => {
    requests.push(args);
    return Promise.resolve(new Response(JSON.stringify({data: {id: 42, username: "private-name", authToken: "private-token", class: {name: "Power User"}, upload: 1024, download: 512, bonus: 42, seedBonus: 84}})));
  };
  const context = vm.createContext({URL, Date, location: {origin, href: origin + "/user/info"}, fetch: originalFetch, XMLHttpRequest: FixtureRequest, document: {documentElement: {setAttribute: (key, value) => attributes.set(key, value), removeAttribute: key => attributes.delete(key)}}});
  vm.runInContext(fs.readFileSync(path.join(__dirname, "../zhuque-observer.js"), "utf8"), context);
  return {context, originalFetch, requests, attributes, FixtureRequest};
}

test("the page fetch keeps its original request and shares only account statistics", async () => {
  const runtime = harness();
  const options = {headers: {authorization: "private-header"}};
  const response = await runtime.context.fetch("/api/user/getInfo", options);
  assert.equal(response.status, 200);
  for (let attempt = 0; attempt < 20 && !runtime.attributes.size; attempt += 1) await new Promise(resolve => setImmediate(resolve));
  assert.equal(runtime.requests[0][1], options);
  const serialized = runtime.attributes.get("data-netsurf-zhuque-profile");
  assert.ok(serialized);
  assert.equal(/private|username|authToken/.test(serialized), false);
  assert.equal(JSON.parse(serialized).data.class.name, "Power User");
  assert.equal(JSON.parse(serialized).data.seedBonus, "84");
});

test("XHR observations are scoped to the own GET endpoint and discard expired sessions", () => {
  const runtime = harness();
  const request = new runtime.FixtureRequest();
  assert.equal(request.open("GET", "/api/user/getInfo"), "opened");
  assert.equal(request.send(), "sent");
  request.load({data: {id: 42, class: {name: "User"}, upload: 1024, download: 512, bonus: 42}});
  assert.ok(runtime.attributes.size);
  request.load({data: null}, 401);
  assert.equal(runtime.attributes.size, 0);
  for (const [method, url] of [["POST", "/api/user/getInfo"], ["GET", "/api/user/getInfo?id=99"], ["GET", "https://evil.test/api/user/getInfo"]]) {
    request.open(method, url);
    request.send();
    request.load({data: {id: 99}});
    assert.equal(runtime.attributes.size, 0);
  }
  const other = harness("https://evil.test");
  assert.equal(other.context.fetch, other.originalFetch);
});

test("M-Team observes only the site's own profile response without exposing authentication", () => {
  const runtime = harness("https://kp.m-team.cc");
  const request = new runtime.FixtureRequest();
  request.open("POST", "https://api.m-team.cc/api/member/profile");
  request.send();
  request.load({code: 0, data: {id: 42, username: "private-name", auth: "private-token", memberStatus: {name: "VIP"}, memberCount: {uploaded: 1024, downloaded: 512, bonus: 42}}});
  const serialized = runtime.attributes.get("data-netsurf-mteam-profile");
  assert.equal(JSON.parse(serialized).data.memberStatus.name, "VIP");
  assert.equal(/private|username|auth/.test(serialized), false);
  request.load({code: 401, data: {id: 42}});
  assert.equal(runtime.attributes.size, 0);
  request.open("POST", "https://evil.test/api/member/profile");
  request.send();
  request.load({code: 0, data: {id: 42}});
  assert.equal(runtime.attributes.size, 0);
});
