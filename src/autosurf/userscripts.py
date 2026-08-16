from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class WebCredentialScriptSource:
    key: str
    name: str
    domain: str
    matches: tuple[str, ...]
    storage_keys: tuple[str, ...]
    required_storage_keys: tuple[str, ...]


WEB_CREDENTIAL_SCRIPT_SOURCES = {
    "rousi": WebCredentialScriptSource(
        key="rousi",
        name="Rousi",
        domain="rousi.pro",
        matches=("https://rousi.pro/*",),
        storage_keys=("token",),
        required_storage_keys=("token",),
    ),
    "mteam": WebCredentialScriptSource(
        key="mteam",
        name="M-Team",
        domain="kp.m-team.cc",
        matches=("https://kp.m-team.cc/*",),
        storage_keys=("auth", "did", "visitorId"),
        required_storage_keys=("auth",),
    ),
}


def build_web_credential_userscript(source_key: str, endpoint: str, upload_key: str) -> str:
    return build_web_credential_userscript_bundle({source_key: (endpoint, upload_key)})


def build_web_credential_userscript_bundle(
    configurations: dict[str, tuple[str, str]],
) -> str:
    if not configurations:
        raise ValueError("web credential script requires at least one source")
    script_sources = []
    matches: list[str] = []
    connect_hosts: list[str] = []
    for source_key, (endpoint, upload_key) in configurations.items():
        try:
            source = WEB_CREDENTIAL_SCRIPT_SOURCES[source_key]
        except KeyError as exc:
            raise ValueError("unknown web credential source") from exc
        parsed = urlparse(endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("userscript endpoint must be HTTP(S)")
        matches.extend(source.matches)
        connect_hosts.append(parsed.hostname)
        script_sources.append({
            "key": source.key,
            "name": source.name,
            "domain": source.domain,
            "storageKeys": list(source.storage_keys),
            "requiredStorageKeys": list(source.required_storage_keys),
            "endpoint": endpoint,
            "uploadKey": upload_key,
            "markerKey": f"autosurf_web_credential_{source.key}_marker",
        })
    return _WEB_CREDENTIAL_USERSCRIPT.replace(
        "__AUTOSURF_SOURCE_CONFIG__", json.dumps(script_sources, ensure_ascii=False),
    ).replace(
        "__AUTOSURF_CONNECT_HOSTS__", "\n".join(
            f"// @connect      {item}" for item in dict.fromkeys(connect_hosts)
        ),
    ).replace(
        "__AUTOSURF_MATCHES__", "\n".join(
            f"// @match        {item}" for item in dict.fromkeys(matches)
        ),
    )


def web_credential_script_source(source_key: str) -> WebCredentialScriptSource:
    try:
        return WEB_CREDENTIAL_SCRIPT_SOURCES[source_key]
    except KeyError as exc:
        raise ValueError("unknown web credential source") from exc


_WEB_CREDENTIAL_USERSCRIPT = r'''// ==UserScript==
// @name         AutoSurf Web 凭据同步
// @namespace    https://github.com/fengzhanhuaer/AutoSurf
// @version      1.1.0
// @description  将当前站点的 Web 登录凭据安全同步到 AutoSurf
__AUTOSURF_MATCHES__
// @grant        GM_xmlhttpRequest
// @grant        GM_getValue
// @grant        GM_setValue
// @grant        unsafeWindow
__AUTOSURF_CONNECT_HOSTS__
// @run-at       document-idle
// ==/UserScript==

(() => {
  "use strict";

  const sources = __AUTOSURF_SOURCE_CONFIG__;
  const hostname = location.hostname.toLowerCase();
  const source = sources.find((item) => hostname === item.domain || hostname.endsWith(`.${item.domain}`));
  if (!source) return;
  let status = "正在检测";
  let detail = "等待读取浏览器登录状态";
  let syncing = false;

  const host = document.createElement("div");
  host.id = "autosurf-token-sync";
  document.documentElement.append(host);
  const root = host.attachShadow({ mode: "open" });
  root.innerHTML = `
    <style>
      :host { all: initial; }
      .dock { position: fixed; z-index: 2147483647; top: 50%; right: 0; display: flex; align-items: center;
        transform: translateY(-50%); font-family: "Segoe UI", Arial, sans-serif; letter-spacing: 0; }
      .trigger { width: 42px; height: 48px; padding: 0; border: 1px solid #0b6e5d; border-right: 0;
        border-radius: 6px 0 0 6px; background: #087f6a; color: #fff; font-size: 17px; font-weight: 700;
        box-shadow: 0 4px 14px rgb(0 0 0 / 20%); cursor: pointer; }
      .trigger:hover { background: #066a59; }
      .trigger:focus-visible, button:focus-visible { outline: 3px solid rgb(37 99 235 / 35%); outline-offset: 2px; }
      .panel { width: min(306px, calc(100vw - 54px)); border: 1px solid #cdd5dc; border-right: 0;
        border-radius: 6px 0 0 6px; background: #fff; color: #17212b; box-shadow: 0 12px 34px rgb(0 0 0 / 24%); }
      .panel[hidden] { display: none; }
      .heading { min-height: 54px; padding: 0 14px; display: flex; align-items: center; justify-content: space-between;
        gap: 12px; border-bottom: 1px solid #e1e6ea; }
      .heading strong { font-size: 14px; }
      .close { width: 30px; height: 30px; padding: 0; border: 0; background: transparent; color: #65717d;
        font-size: 22px; line-height: 1; cursor: pointer; }
      .body { padding: 14px; }
      .state { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
      .badge { min-height: 25px; padding: 3px 8px; display: inline-flex; align-items: center; border-radius: 4px;
        background: #eef2f5; color: #52606d; font-size: 12px; font-weight: 700; }
      .badge.ok { background: #e6f5f0; color: #08715f; }
      .badge.error { background: #fff1f0; color: #b42318; }
      .detail { min-height: 36px; margin: 11px 0 14px; color: #65717d; font-size: 12px; line-height: 1.5;
        overflow-wrap: anywhere; }
      .token-row { display: grid; grid-template-columns: minmax(0, 1fr) auto auto; gap: 6px; margin-bottom: 12px; }
      .token { min-width: 0; height: 34px; padding: 0 8px; border: 1px solid #cdd5dc; border-radius: 4px;
        background: #f8fafb; color: #344150; font: 12px/1.2 ui-monospace, Consolas, monospace; }
      .token-action { min-width: 42px; height: 34px; padding: 0 8px; border: 1px solid #cdd5dc; border-radius: 4px;
        background: #fff; color: #344150; font-size: 12px; cursor: pointer; }
      .token-action:hover:not(:disabled) { background: #f4f6f8; }
      .token-action:disabled { cursor: not-allowed; opacity: .45; }
      .sync { width: 100%; min-height: 38px; border: 1px solid #087f6a; border-radius: 5px; background: #087f6a;
        color: #fff; font-size: 13px; font-weight: 700; cursor: pointer; }
      .sync:hover:not(:disabled) { background: #066a59; }
      .sync:disabled { cursor: not-allowed; opacity: .55; }
      @media (max-width: 520px) { .dock { top: auto; bottom: 72px; transform: none; } }
    </style>
    <div class="dock">
      <section class="panel" hidden aria-label="AutoSurf Web 凭据同步">
        <div class="heading"><strong>AutoSurf Web 凭据同步</strong><button class="close" type="button" aria-label="关闭">×</button></div>
        <div class="body">
          <div class="state"><span class="source-name"></span><span class="badge">正在检测</span></div>
          <p class="detail">等待读取浏览器登录状态</p>
          <div class="token-row">
            <input class="token" type="password" readonly aria-label="Web 登录凭据">
            <button class="token-action reveal" type="button">显示</button>
            <button class="token-action copy" type="button">复制</button>
          </div>
          <button class="sync" type="button">立即同步</button>
        </div>
      </section>
      <button class="trigger" type="button" title="AutoSurf Web 凭据同步" aria-label="打开 AutoSurf Web 凭据同步">A</button>
    </div>`;

  const panel = root.querySelector(".panel");
  const badge = root.querySelector(".badge");
  const detailNode = root.querySelector(".detail");
  const syncButton = root.querySelector(".sync");
  const tokenField = root.querySelector(".token");
  const revealButton = root.querySelector(".reveal");
  const copyButton = root.querySelector(".copy");
  const render = (kind = "") => {
    badge.textContent = status;
    badge.className = `badge ${kind}`.trim();
    detailNode.textContent = detail;
    tokenField.value = credential();
    revealButton.disabled = !tokenField.value;
    copyButton.disabled = !tokenField.value;
    syncButton.disabled = syncing;
    syncButton.textContent = syncing ? "同步中..." : "立即同步";
  };
  root.querySelector(".source-name").textContent = source.name;
  const credentialValues = () => Object.fromEntries(source.storageKeys.flatMap((key) => {
    const value = unsafeWindow.localStorage.getItem(key) || "";
    return value ? [[key, value]] : [];
  }));
  const credential = () => {
    const values = credentialValues();
    return Object.keys(values).length ? JSON.stringify(values) : "";
  };
  const marker = async (value) => {
    const data = new TextEncoder().encode(value);
    const digest = await crypto.subtle.digest("SHA-256", data);
    return [...new Uint8Array(digest)].map((item) => item.toString(16).padStart(2, "0")).join("");
  };
  const upload = (value) => new Promise((resolve, reject) => {
    GM_xmlhttpRequest({
      method: "POST",
      url: source.endpoint,
      headers: { "Authorization": `Bearer ${source.uploadKey}`, "Content-Type": "application/json" },
      data: JSON.stringify({ values: value }),
      timeout: 15000,
      onload: (response) => {
        if (response.status < 200 || response.status >= 300) {
          reject(new Error(response.status === 401 ? "上传密钥已失效，请重新安装脚本" : `同步失败 (${response.status})`));
          return;
        }
        try { resolve(JSON.parse(response.responseText || "{}")); }
        catch (_) { reject(new Error("AutoSurf 返回了无法识别的响应")); }
      },
      ontimeout: () => reject(new Error("连接 AutoSurf 超时")),
      onerror: () => reject(new Error("无法连接 AutoSurf")),
    });
  });

  async function sync(force = false) {
    if (syncing) return;
    const values = credentialValues();
    const missing = source.requiredStorageKeys.filter((key) => !values[key]);
    if (missing.length) {
      status = "未登录";
      detail = `浏览器中没有检测到 ${source.name} 登录凭据`;
      render("error");
      return;
    }
    const currentMarker = await marker(JSON.stringify(values));
    if (!force && GM_getValue(source.markerKey, "") === currentMarker) {
      status = "已同步";
      detail = "凭据未发生变化";
      render("ok");
      return;
    }
    syncing = true;
    status = "同步中";
    detail = "正在安全写入 AutoSurf";
    render();
    try {
      const result = await upload(values);
      GM_setValue(source.markerKey, currentMarker);
      status = "同步成功";
      detail = `${result.changed ? "凭据已更新" : "凭据已确认"} · ${new Date().toLocaleString()}`;
      render("ok");
    } catch (error) {
      status = "同步失败";
      detail = error instanceof Error ? error.message : String(error);
      render("error");
    } finally {
      syncing = false;
      render(badge.classList.contains("error") ? "error" : badge.classList.contains("ok") ? "ok" : "");
    }
  }

  root.querySelector(".trigger").addEventListener("click", () => { panel.hidden = !panel.hidden; });
  root.querySelector(".close").addEventListener("click", () => { panel.hidden = true; });
  revealButton.addEventListener("click", () => {
    const revealed = tokenField.type === "text";
    tokenField.type = revealed ? "password" : "text";
    revealButton.textContent = revealed ? "显示" : "隐藏";
  });
  copyButton.addEventListener("click", async () => {
    const value = credential();
    if (!value) return;
    try {
      await navigator.clipboard.writeText(value);
      copyButton.textContent = "已复制";
      setTimeout(() => { copyButton.textContent = "复制"; }, 1200);
    } catch (_) {
      detail = "浏览器未允许复制凭据";
      render("error");
    }
  });
  syncButton.addEventListener("click", () => sync(true));
  window.addEventListener("storage", (event) => { if (source.storageKeys.includes(event.key)) sync(false); });
  document.addEventListener("visibilitychange", () => { if (!document.hidden) sync(false); });
  setInterval(() => sync(false), 60000);
  setTimeout(() => sync(false), 1000);
  render();
})();
'''
