const assert = require("node:assert/strict");
const test = require("node:test");
const core = require("../ocr-core.js");
const hdsky = require("../hdsky.js");
const opencd = require("../opencd.js");
const ptsbao = require("../ptsbao.js");
const sites = require("../sites.js");
const {create} = require("../captcha-background.js");

test("OCR accepts only two matching six-character candidates, not one valid result or conflicts", () => {
  assert.equal(core.consensus(["ABC123", "ABC123", "ZZZ999"]), "ABC123");
  for (const values of [["ABC123"], ["ABC123", "ZZZ999", "DEF456"], ["ABC123", "", "wrong"], ["1234567", "1234567"], ["abc123", "abc123"]]) assert.equal(core.consensus(values), null);
});

test("CTC decoding removes consecutive indices, not characters separated by blank", () => {
  assert.equal(core.decode({dims: [1, 8], data: [1, 1, 0, 1, 2, 2, 0, 2]}, ["", "A", "B"]), "AABB");
  assert.equal(core.decode({dims: [4, 1, 3], data: [0, 2, 1, 0, 2, 1, 3, 0, 0, 0, 0, 3]}, ["", "A", "B"]), "AB");
  assert.throws(() => core.decode({dims: [1, 1], data: [99]}, ["", "A"]));
});

test("preprocessing crops borders and rejects huge images before work", () => {
  const data = new Uint8ClampedArray(12 * 12 * 4).fill(255);
  for (const position of [3 * 12 + 4, 4 * 12 + 4]) { data[position * 4] = 0; data[position * 4 + 1] = 0; data[position * 4 + 2] = 0; }
  const prepared = core.candidates({width: 12, height: 12, data});
  assert.equal(prepared.length, 3);
  assert.equal(prepared[0].pixels.filter(value => value === 0).length, 2);
  assert.equal(prepared[1].width, 8);
  assert.throws(() => core.candidates({width: 10000, height: 12, data}));
});

test("HDSky image adapter only accepts exact HTTPS homepage paths", () => {
  for (const url of ["https://hdsky.me/", "https://www.hdsky.me/index.php"]) assert.equal(hdsky.supported(url), true);
  for (const url of ["https://hdsky.me.evil.test/", "http://hdsky.me/", "https://hdsky.me:444/", "https://hdsky.me/attendance.php", "https://hdsky.me/?action=delete", "https://hdsky.me/#other"]) assert.equal(hdsky.supported(url), false);
});

test("HDSky actual Showed Up completion is recognized without keeping its success dialog open", () => {
  const entry = {textContent: "已签到(Showed Up)"};
  const document = {querySelector: () => entry, querySelectorAll: () => []};
  assert.equal(hdsky.inspect(document, "https://hdsky.me/", () => true).status, "already_done");
  entry.textContent = "签到(Showed Up)";
  assert.equal(hdsky.inspect(document, "https://hdsky.me/", () => true), null);
  entry.textContent = "已签到(Showed Up) 论坛历史";
  assert.equal(hdsky.inspect(document, "https://hdsky.me/", () => true), null);
});

function runtime(overrides = {}, siteId = "hdsky.me") {
  const state = {autoEnabled: true, sites: {[siteId]: {enabled: true, refreshOnly: false}}, operation: {tabId: 7, startedAt: 123, day: sites.day(), deadline: Date.now() + 10000, phase: "preparing", awaitingConfirmation: true}, ...overrides};
  const sender = {id: "own", frameId: 0, tab: {id: 7}, url: `https://${siteId}/`};
  const actions = [];
  let reply = {answer: "ABC123"};
  const chrome = {
    runtime: {id: "own", getURL: path => `chrome-extension://own/${path}`, getContexts: async () => [], sendMessage: async () => { actions.push("infer"); return typeof reply === "function" ? reply() : reply; }},
    permissions: {contains: async () => true},
    tabs: {get: async () => ({url: sender.url})},
    offscreen: {createDocument: async () => { actions.push("open"); }, closeDocument: async () => { actions.push("close"); }},
    storage: {local: {set: async values => { assert.ok(Object.hasOwn(values, sites.key("operation", siteId))); state.operation = values[sites.key("operation", siteId)]; }}}
  };
  return {state, sender, actions, chrome, service: create(chrome, sites, async () => state), setReply: value => { reply = value; }};
}

const recognition = {type: "captcha-recognize", operationId: 123, image: "data:image/png;base64,AAAA"};

test("PTSBao OCR is scoped to the top-level attendance form continuation and one ticket", async () => {
  const current = runtime({}, "ptsbao.club");
  current.sender.url = "https://ptsbao.club/attendance.php";
  assert.equal((await current.service.handle(recognition, current.sender)).accepted, false);
  current.state.operation.phase = "entry";
  assert.equal((await current.service.handle(recognition, current.sender)).accepted, false);
  current.state.operation.phase = "continuing";
  const result = await current.service.handle(recognition, current.sender);
  assert.equal(result.accepted, true);
  assert.equal((await current.service.handle(recognition, current.sender)).accepted, false);
  const submit = {type: "captcha-submit", operationId: 123, ticket: result.ticket};
  assert.equal((await current.service.handle(submit, current.sender)).accepted, true);
  assert.equal((await current.service.handle(submit, current.sender)).accepted, false);
  assert.equal(current.state.operation.phase, "submitted");
  assert.equal(JSON.stringify(current.state).includes("ABC123"), false);
});

test("PTSBao OCR denies wrong paths, nested frames, cancelled or expired continuation", async () => {
  for (const change of [current => {current.sender.url = "https://ptsbao.club/index.php";}, current => {current.sender.url += "?action=other";}, current => {current.sender.url = "https://ptsbao.club.evil.test/attendance.php";}, current => {current.sender.frameId = 1;}, current => {current.state.sites["ptsbao.club"].refreshOnly = true;}, current => {current.state.sites["ptsbao.club"].enabled = false;}, current => {current.state.operation.deadline = 0;}, current => {current.state.operation.tabId = 8;}]) {
    const current = runtime({}, "ptsbao.club");
    current.sender.url = "https://ptsbao.club/attendance.php";
    current.state.operation.phase = "continuing";
    change(current);
    assert.equal((await current.service.handle(recognition, current.sender)).accepted, false);
    assert.deepEqual(current.actions, []);
  }
  for (const url of ["https://ptsbao.club/attendance.php", "https://www.ptsbao.club/index.php"]) assert.equal(ptsbao.supported(url), true);
  for (const url of ["http://ptsbao.club/attendance.php", "https://ptsbao.club/attendance.php?other=1", "https://ptsbao.club/logout.php", "https://ptsbao.club.evil.test/attendance.php"]) assert.equal(ptsbao.supported(url), false);
});

test("OCR and submission are serialized, each once, and answer is never persisted", async () => {
  const current = runtime();
  const results = await Promise.all([current.service.handle(recognition, current.sender), current.service.handle(recognition, current.sender)]);
  assert.equal(results[0].accepted, true);
  assert.equal(results[1].accepted, false);
  assert.deepEqual(current.actions, ["open", "infer", "close"]);
  assert.equal(JSON.stringify(current.state).includes("ABC123"), false);
  assert.equal((await current.service.handle({type: "captcha-submit", operationId: 123, ticket: "wrong"}, current.sender)).accepted, false);
  const request = {type: "captcha-submit", operationId: 123, ticket: results[0].ticket};
  assert.equal((await current.service.handle(request, current.sender)).accepted, true);
  assert.equal(current.state.operation.phase, "submitted");
  assert.equal((await current.service.handle(request, current.sender)).accepted, false);
});

test("OpenCD only accepts known HTTPS homepages and keeps explicit refresh-only", () => {
  for (const url of ["https://open.cd/", "https://www.open.cd/index.php"]) assert.equal(opencd.supported(url), true);
  for (const url of ["http://open.cd/", "https://open.cd.evil.test/", "https://open.cd:444/", "https://open.cd/plugin_sign-in.php", "https://open.cd/?cmd=signin", "https://open.cd/#other"]) assert.equal(opencd.supported(url), false);
  assert.equal(sites.refreshOnlyRequired("open.cd"), false);
  assert.equal(sites.settings({sites: {"open.cd": {refreshOnly: true}}}).sites["open.cd"].refreshOnly, true);
});

test("OpenCD opens its iframe once, uses its own operation key, and consumes one ticket", async () => {
  const current = runtime({}, "open.cd");
  const opening = {type: "captcha-open", operationId: 123};
  assert.equal((await current.service.handle(opening, current.sender)).accepted, true);
  assert.equal((await current.service.handle(opening, current.sender)).accepted, false);
  const recognized = await current.service.handle(recognition, current.sender);
  assert.equal(recognized.accepted, true);
  const submit = {type: "captcha-submit", operationId: 123, ticket: recognized.ticket};
  assert.equal((await current.service.handle(submit, current.sender)).accepted, true);
  assert.equal((await current.service.handle(submit, current.sender)).accepted, false);
  assert.equal(current.state.operation.phase, "submitted");
  assert.deepEqual(current.actions, ["open", "infer", "close"]);
});

test("OpenCD denies cross-site tokens, nested frame senders, cancellation and expired entry", async () => {
  for (const change of [current => {current.sender.url = "https://hdsky.me/";}, current => {current.sender.frameId = 1;}, current => {current.sender.url = "https://open.cd/plugin_sign-in.php";}, current => {current.state.sites["open.cd"].refreshOnly = true;}, current => {current.state.operation.deadline = 0;}]) {
    const current = runtime({}, "open.cd");
    change(current);
    assert.equal((await current.service.handle({type: "captcha-open", operationId: 123}, current.sender)).accepted, false);
    assert.equal((await current.service.handle(recognition, current.sender)).accepted, false);
    assert.deepEqual(current.actions, []);
  }
  const hdskyRuntime = runtime();
  const hdskyTicket = await hdskyRuntime.service.handle(recognition, hdskyRuntime.sender);
  const current = runtime({}, "open.cd");
  await current.service.handle(recognition, current.sender);
  assert.equal((await current.service.handle({type: "captcha-submit", operationId: 123, ticket: hdskyTicket.ticket}, current.sender)).accepted, false);
});

test("wrong source, frame, operation, permissions, expired and cancelled attempts cannot load OCR", async () => {
  for (const change of [current => { current.sender.id = "other"; }, current => { current.sender.frameId = 1; }, current => { current.sender.url = "https://piggo.me/"; }, current => { current.sender.tab.id = 8; }, current => { current.state.operation.startedAt = 456; }, current => { current.state.operation.deadline = 0; }, current => { current.state.operation.day = "2000-1-1"; }, current => { current.state.sites["hdsky.me"].enabled = false; }, current => { current.state.sites["hdsky.me"].refreshOnly = true; }, current => { current.state.operation.automatic = true; current.state.autoEnabled = false; }, current => { current.state.verifiedDay = sites.day(); }, current => { current.chrome.permissions.contains = async () => false; }, current => { current.chrome.tabs.get = async () => ({url: "https://hdsky.me/logout.php"}); }]) {
    const current = runtime();
    change(current);
    assert.equal((await current.service.handle(recognition, current.sender)).accepted, false);
    assert.deepEqual(current.actions, []);
  }
});

test("unreliable inference and settings changes during inference do not grant submission", async () => {
  for (const changed of [false, true]) {
    const current = runtime();
    current.setReply(() => { if (changed) current.state.sites["hdsky.me"].refreshOnly = true; return {answer: changed ? "ABC123" : null}; });
    assert.equal((await current.service.handle(recognition, current.sender)).accepted, false);
    assert.equal(current.state.operation.phase, "recognizing");
    assert.deepEqual(current.actions, ["open", "infer", "close"]);
  }
});

test("disabled auto or explicit refresh-only after recognition revokes final submission", async () => {
  for (const field of ["refreshOnly", "enabled", "automatic"]) {
    const current = runtime();
    const recognized = await current.service.handle(recognition, current.sender);
    if (field === "refreshOnly") current.state.sites["hdsky.me"].refreshOnly = true;
    if (field === "enabled") current.state.sites["hdsky.me"].enabled = false;
    if (field === "automatic") { current.state.operation.automatic = true; current.state.autoEnabled = false; }
    assert.equal((await current.service.handle({type: "captcha-submit", operationId: 123, ticket: recognized.ticket}, current.sender)).accepted, false);
  }
});
