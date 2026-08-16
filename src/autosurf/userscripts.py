from __future__ import annotations

import json
from urllib.parse import urlparse


def build_rousi_userscript(endpoint: str, upload_key: str) -> str:
    parsed = urlparse(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("userscript endpoint must be HTTP(S)")
    return _ROUSI_USERSCRIPT.replace(
        "__AUTOSURF_ENDPOINT__", json.dumps(endpoint),
    ).replace(
        "__AUTOSURF_UPLOAD_KEY__", json.dumps(upload_key),
    ).replace(
        "__AUTOSURF_CONNECT_HOST__", parsed.hostname,
    )


_ROUSI_USERSCRIPT = r'''// ==UserScript==
// @name         AutoSurf Rousi Token 同步
// @namespace    https://github.com/fengzhanhuaer/AutoSurf
// @version      1.0.0
// @description  将 Rousi 登录 Token 安全同步到 AutoSurf
// @match        https://rousi.pro/*
// @grant        GM_xmlhttpRequest
// @grant        GM_getValue
// @grant        GM_setValue
// @grant        unsafeWindow
// @connect      __AUTOSURF_CONNECT_HOST__
// @run-at       document-idle
// ==/UserScript==

(() => {
  "use strict";

  const endpoint = __AUTOSURF_ENDPOINT__;
  const uploadKey = __AUTOSURF_UPLOAD_KEY__;
  const markerKey = "autosurf_rousi_token_marker";
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
      <section class="panel" hidden aria-label="AutoSurf Token 同步">
        <div class="heading"><strong>AutoSurf Token 同步</strong><button class="close" type="button" aria-label="关闭">×</button></div>
        <div class="body">
          <div class="state"><span>Rousi</span><span class="badge">正在检测</span></div>
          <p class="detail">等待读取浏览器登录状态</p>
          <div class="token-row">
            <input class="token" type="password" readonly aria-label="Rousi Token">
            <button class="token-action reveal" type="button">显示</button>
            <button class="token-action copy" type="button">复制</button>
          </div>
          <button class="sync" type="button">立即同步</button>
        </div>
      </section>
      <button class="trigger" type="button" title="AutoSurf Token 同步" aria-label="打开 AutoSurf Token 同步">A</button>
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
    tokenField.value = token();
    revealButton.disabled = !tokenField.value;
    copyButton.disabled = !tokenField.value;
    syncButton.disabled = syncing;
    syncButton.textContent = syncing ? "同步中..." : "立即同步";
  };
  const token = () => unsafeWindow.localStorage.getItem("token") || "";
  const marker = async (value) => {
    const data = new TextEncoder().encode(value);
    const digest = await crypto.subtle.digest("SHA-256", data);
    return [...new Uint8Array(digest)].map((item) => item.toString(16).padStart(2, "0")).join("");
  };
  const upload = (value) => new Promise((resolve, reject) => {
    GM_xmlhttpRequest({
      method: "POST",
      url: endpoint,
      headers: { "Authorization": `Bearer ${uploadKey}`, "Content-Type": "application/json" },
      data: JSON.stringify({ token: value }),
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
    const value = token();
    if (!value) {
      status = "未登录";
      detail = "浏览器中没有检测到 Rousi Token";
      render("error");
      return;
    }
    const currentMarker = await marker(value);
    if (!force && GM_getValue(markerKey, "") === currentMarker) {
      status = "已同步";
      detail = "Token 未发生变化";
      render("ok");
      return;
    }
    syncing = true;
    status = "同步中";
    detail = "正在安全写入 AutoSurf";
    render();
    try {
      const result = await upload(value);
      GM_setValue(markerKey, currentMarker);
      status = "同步成功";
      detail = `${result.changed ? "Token 已更新" : "Token 已确认"} · ${new Date().toLocaleString()}`;
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
    const value = token();
    if (!value) return;
    try {
      await navigator.clipboard.writeText(value);
      copyButton.textContent = "已复制";
      setTimeout(() => { copyButton.textContent = "复制"; }, 1200);
    } catch (_) {
      detail = "浏览器未允许复制 Token";
      render("error");
    }
  });
  syncButton.addEventListener("click", () => sync(true));
  window.addEventListener("storage", (event) => { if (event.key === "token") sync(false); });
  document.addEventListener("visibilitychange", () => { if (!document.hidden) sync(false); });
  setInterval(() => sync(false), 60000);
  setTimeout(() => sync(false), 1000);
  render();
})();
'''
