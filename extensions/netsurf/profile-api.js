(function (root) {
  function size(value) {
    const bytes = Number(value);
    if (value === undefined || value === null || !Number.isFinite(bytes) || bytes < 0) return null;
    const units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"];
    const index = bytes > 0 ? Math.max(0, Math.min(units.length - 1, Math.floor(Math.log(bytes) / Math.log(1024)))) : 0;
    return `${(bytes / 1024 ** index).toFixed(index ? 2 : 0)} ${units[index]}`;
  }

  function profile(kind, data) {
    const count = kind === "mteam" ? data.memberCount || data : data;
    const rank = kind === "mteam" ? data.memberStatus || {} : data.class || {};
    const uploaded = count.uploaded ?? count.upload;
    const downloaded = count.downloaded ?? count.download;
    const ratio = count.ratio ?? (Number(downloaded) > 0 ? (Number(uploaded) / Number(downloaded)).toFixed(3) : Number(uploaded) > 0 && Number(downloaded) === 0 ? "∞" : null);
    const seedingPoints = count.seedingPoints ?? (kind === "zhuque" ? count.seedBonus : undefined);
    return {level: rank.name || rank.title || rank.level || data.roleName || null, bonus: String(count.bonus ?? count.seedBonus ?? "") || null, seedingPoints: seedingPoints === undefined ? null : String(seedingPoints), uploaded: size(uploaded), downloaded: size(downloaded), ratio: ratio === null ? null : String(ratio)};
  }

  async function read(origin, kind, signal, environment = root) {
    const host = new URL(origin).hostname.replace(/^www\./, "");
    const hosts = {mteam: ["kp.m-team.cc"], zhuque: ["zhuque.in"], rousi: ["rousi.pro", "rousi.zip"], sunny: ["sunnypt.top"]};
    if (new URL(origin).protocol !== "https:" || new URL(origin).port || !hosts[kind]?.includes(host)) throw new Error("资料接口不属于当前站点");
    if (["rousi", "sunny"].includes(kind)) return modernRead(origin, kind, signal, environment);
    if (kind === "mteam" && environment.document?.documentElement) {
      const deadline = Date.now() + 15000;
      while (Date.now() < deadline && !signal?.aborted) {
        try {
          const observed = JSON.parse(environment.document.documentElement.getAttribute("data-netsurf-mteam-profile"));
          if (observed?.data?.id && observed.time <= Date.now() && Date.now() - observed.time < 60000) return {status: "profile_only", profile: profile(kind, observed.data), diagnostic: {path: "/api/member/profile", httpStatus: 200, accountFound: true, source: "page-client", entries: []}};
        } catch {}
        if (/\/login\/?$/.test(environment.location?.pathname || "")) return {status: "login_required", message: "M-Team 网页已跳转登录页，请在网页完成登录"};
        await new Promise(resolve => setTimeout(resolve, 100));
      }
      if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
      return {status: "error", message: "M-Team 网页尚未返回账号资料，未判定登录失效，请稍后刷新"};
    }
    const auth = kind === "mteam" ? environment.localStorage.getItem("auth") : null;
    if (kind === "mteam" && !auth) return {status: "login_required", message: "M-Team 当前浏览器没有有效登录状态"};
    const endpoints = kind === "mteam" ? ["https://api.m-team.cc/api/member/profile", "https://api.m-team.io/api/member/profile", "https://api2.m-team.cc/api/member/profile"] : [`${origin}/api/user/getInfo`];
    let lastStatus = 0;
    for (const endpoint of endpoints) {
      try {
        const options = {credentials: "include", cache: "no-store", redirect: "error", signal};
        if (kind === "zhuque") {
          const csrf = environment.document?.querySelector?.('meta[name="x-csrf-token"]')?.content?.trim();
          if (csrf) options.headers = {"x-csrf-token": csrf};
        }
        if (kind === "mteam") {
          const timestamp = Date.now();
          const encoder = new environment.TextEncoder();
          const key = await environment.crypto.subtle.importKey("raw", encoder.encode("HLkPcWmycL57mfJt"), {name: "HMAC", hash: "SHA-1"}, false, ["sign"]);
          const signature = new Uint8Array(await environment.crypto.subtle.sign("HMAC", key, encoder.encode(`POST&/api/member/profile&${timestamp}`)));
          options.method = "POST";
          options.body = new environment.FormData();
          options.body.append("_timestamp", String(timestamp));
          options.body.append("_sgin", environment.btoa(String.fromCharCode(...signature)));
          options.headers = {Accept: "application/json, text/plain, */*", authorization: auth, ts: String(Math.floor(timestamp / 1000)), visitorId: environment.localStorage.getItem("visitorId") || "", version: "1.1.7", webVersion: "1170"};
          const device = environment.localStorage.getItem("did");
          if (device) options.headers.did = device;
        }
        const response = await environment.fetch(endpoint, options);
        lastStatus = response.status;
        const diagnostic = {path: new URL(endpoint).pathname, httpStatus: response.status, accountFound: false, entries: []};
        if (response.status === 468) return {status: "blocked", diagnostic};
        if (response.status === 403 && kind === "mteam") return {status: "blocked", message: "M-Team 资料接口拒绝访问，当前网页登录状态可能仍有效", diagnostic};
        if ([401, 403].includes(response.status)) return {status: "login_required", diagnostic};
        if (!response.ok) {
          if (kind === "zhuque" && response.status === 400 && environment.document) {
            const deadline = Date.now() + 5000;
            while (Date.now() < deadline && !signal?.aborted) {
              try {
                const observed = JSON.parse(environment.document.documentElement.getAttribute("data-netsurf-zhuque-profile"));
                if (observed?.time <= Date.now() && Date.now() - observed.time < 60000) return {status: "profile_only", profile: profile(kind, observed.data), diagnostic: {...diagnostic, httpStatus: 200, accountFound: true, source: "page-client"}};
              } catch {}
              await new Promise(resolve => setTimeout(resolve, 100));
            }
          }
          return {status: "error", message: `资料接口返回 HTTP ${response.status}`, diagnostic};
        }
        const payload = await response.json();
        if (kind === "mteam" && Number(payload.code) !== 0) return {status: [1, 401].includes(Number(payload.code)) ? "login_required" : Number(payload.code) === 403 ? "blocked" : "error", message: `M-Team 资料接口返回状态 ${Number(payload.code)}`, diagnostic};
        const data = payload.data;
        if (!data?.id) return {status: "unknown", message: "资料接口未返回当前账号信息", diagnostic};
        if (kind === "mteam") {
          const updatedAuth = response.headers.get("authorization");
          const updatedDevice = response.headers.get("did");
          if (environment.localStorage.getItem("auth") === auth) {
            if (updatedAuth) environment.localStorage.setItem("auth", updatedAuth);
            if (updatedDevice) environment.localStorage.setItem("did", updatedDevice);
          }
        }
        return {status: "profile_only", profile: profile(kind, data), diagnostic: {...diagnostic, accountFound: true}};
      } catch (error) {
        if (signal?.aborted) throw error;
      }
    }
    return {status: "error", message: "资料接口请求失败，请检查网络及登录状态", diagnostic: {httpStatus: lastStatus, path: new URL(endpoints[0]).pathname, accountFound: false, entries: []}};
  }

  async function modernSession(origin, kind, signal, environment) {
    const path = kind === "rousi" ? "/api/v1/session" : "/api/auth/session";
    const response = await environment.fetch(origin + path, {credentials: "same-origin", cache: "no-store", signal});
    if (!response.ok) return {failure: {status: [401, 403].includes(response.status) ? "login_required" : "error", message: `登录会话接口返回 HTTP ${response.status}`}};
    const body = await response.json();
    if (kind === "rousi" && !body.user || kind === "sunny" && !body.data?.accessToken) return {failure: {status: "login_required", message: "当前浏览器登录会话已失效"}};
    return {body, options: {credentials: "include", cache: "no-store", signal, ...(kind === "sunny" ? {headers: {Authorization: `Bearer ${body.data.accessToken}`}} : {})}};
  }

  function attended(kind, body) {
    if (kind === "sunny") return typeof body.data?.checked_in === "boolean" ? body.data.checked_in : null;
    if (typeof body.claimed_today === "boolean") return body.claimed_today;
    const attendance = body.attendance;
    return attendance?.server_today && Array.isArray(attendance.attended_dates) ? attendance.attended_dates.includes(attendance.server_today) : null;
  }

  async function modernRead(origin, kind, signal, environment) {
    const session = await modernSession(origin, kind, signal, environment);
    if (session.failure) return session.failure;
    const base = kind === "rousi" ? origin : "https://api.sunnypt.top";
    const paths = kind === "rousi" ? ["/api/v1/me/traffic", "/api/v1/me/economy", "/api/v1/me/attendance"] : ["/api/v1/user/details/info", "/api/v1/attendance/status"];
    const bodies = [];
    for (const path of paths) {
      const response = await environment.fetch(base + path, session.options);
      const diagnostic = {path, httpStatus: response.status, accountFound: false, entries: []};
      if (!response.ok) return {status: [401, 403].includes(response.status) ? "login_required" : "error", message: `账号接口返回 HTTP ${response.status}`, diagnostic};
      bodies.push(await response.json());
    }
    let stats;
    if (kind === "rousi") {
      const traffic = bodies[0].totals || {};
      const economy = bodies[1];
      stats = profile("zhuque", {class: {name: economy.progress?.level === undefined ? null : `Lv. ${economy.progress.level}`}, upload: traffic.credited_uploaded_bytes ?? traffic.raw_uploaded_bytes, download: traffic.charged_downloaded_bytes ?? traffic.raw_downloaded_bytes, bonus: economy.magic_balance});
    } else {
      const data = bodies[0].data;
      if (!data || !data.id && !data.username) return {status: "login_required", message: "资料接口没有返回当前账号"};
      stats = profile("zhuque", {...data, class: {name: data.title || data.class}, bonus: data.seed_bonus ?? data.bonus});
    }
    const done = attended(kind, bodies.at(-1));
    return {status: done === true ? "already_done" : done === false ? "ready" : "unknown", ...(done === null ? {message: "账号数据已读取，但接口没有返回明确的今日签到状态"} : {}), profile: stats, diagnostic: {path: paths.at(-1), httpStatus: 200, accountFound: true, entries: []}};
  }

  async function signIn(origin, kind, signal, environment = root, allowSubmit = async () => true) {
    const before = await read(origin, kind, signal, environment);
    if (before.status !== "ready") return before;
    const session = await modernSession(origin, kind, signal, environment);
    if (session.failure) return session.failure;
    const token = kind === "rousi" ? session.body.csrf_token : session.body.data.accessToken;
    if (!token) return {status: "error", message: "登录会话没有返回签到令牌"};
    if (!await allowSubmit()) return {...before, status: "refreshed", message: "仅刷新已开启，不提交签到"};
    if (signal?.aborted) return {...before, status: "error", message: "操作已超时，未提交签到"};
    const target = kind === "rousi" ? origin + "/api/v1/me/attendance" : "https://api.sunnypt.top/api/v1/attendance/check-in";
    try {
      const options = {...session.options, method: "POST"};
      if (kind === "rousi") {
        options.headers = {"Content-Type": "application/json", "X-CSRF-Token": token, "Idempotency-Key": environment.crypto.randomUUID()};
        options.body = JSON.stringify({mode: "fixed"});
      }
      const response = await environment.fetch(target, options);
      if ([401, 403].includes(response.status)) return {...before, status: "login_required", message: "签到接口确认登录已失效"};
      const after = await read(origin, kind, signal, environment);
      if (after.status === "already_done") return {...after, status: "success"};
    } catch {}
    return {...before, status: "pending", message: "已提交一次，今日结果尚未确认，不会重复提交"};
  }
  const api = {read, profile, size, signIn};
  root.NetSurfProfileApi = api;
  if (typeof module !== "undefined") module.exports = api;
})(globalThis);
