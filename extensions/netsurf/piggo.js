(function (root) {
  const siteTools = root.NetSurfSites || (typeof module !== "undefined" ? require("./sites.js") : null);
  const siteRules = root.NetSurfRules || (typeof module !== "undefined" ? require("./site-rules.js") : null);
  const hdsky = root.NetSurfHdsky || (typeof module !== "undefined" ? require("./hdsky.js") : null);
  const opencd = root.NetSurfOpenCd || (typeof module !== "undefined" ? require("./opencd.js") : null);
  const ptsbao = root.NetSurfPtsbao || (typeof module !== "undefined" ? require("./ptsbao.js") : null);
  const freefarm = root.NetSurfFreeFarm || (typeof module !== "undefined" ? require("./freefarm.js") : null);
  const pt52 = root.NetSurfPt52 || (typeof module !== "undefined" ? require("./pt52.js") : null);
  function create(origin = "https://piggo.me", signinPath = "/attendance.php", profileOnly = false, name = "PigGo") {
  const rule = siteRules?.get(origin);
  const labels = {
    ready: "可以尝试签到",
    success: "签到成功",
    already_done: "今日已签到",
    blocked: "遇到安全验证，请在网页中处理",
    debugging: "雷池提示当前环境正在被调试",
    login_required: `请先在当前浏览器登录 ${name}`,
    profile_only: "无需每日签到，已检查账号页面",
    refreshed: "账号数据已刷新，本次不签到",
    manual_required: rule?.manualMessage || "需要人工选择补签或完成验证码",
    ambiguous: "找到多个签到控件，请在网页中操作",
    unknown: "尚未识别到签到入口或明确结果",
    pending: "已操作一次，等待页面确认",
    error: "页面通信失败，请刷新站点后重试"
  };

  function isPiggo(url) {
    try {
      return new URL(url).origin === origin;
    } catch {
      return false;
    }
  }

  function classify({url, text = "", password = false, captcha = false}) {
    if (!isPiggo(url)) return "unknown";
    if (/当前环境正在被调试|當前環境正在被調試/.test(text)) return "debugging";
    if (/雷池\s*WAF|sl-challenge|客户端异常|验证您是真人|人机验证|人機驗證|安全验证中|just a moment|cloudflare ray id/i.test(text)) return "blocked";
    if (password || /\/(?:login|takelogin)\.php$/i.test(new URL(url).pathname) || /请(?:先|重新)?登录|登录状态已失效|not logged in/i.test(text)) return "login_required";
    if (/已断签\s*\d+\s*天|请选择补签|放弃补签重新开始签到/.test(text)) return "manual_required";
    if (rule?.attendanceUrl && new URL(url).href === new URL(rule.attendanceUrl, origin).href || new URL(url).pathname === new URL(signinPath, origin).pathname && new URL(url).pathname !== "/") {
      if (/今日已[签簽]到|今天已[签簽]到|今天已经签过到了|\[已[签簽]到\]|已签到.{0,20}无需再签|checked in today|already (?:checked|signed) in/i.test(text)) return "already_done";
      if (/签到成功|簽到成功|本次[签簽]到获得|本次簽到獲得|今天签到您获得|成功.{0,16}(?:连续|連續)(?:签到|簽到)/.test(text)) return "success";
    }
    if (captcha) return "manual_required";
    return "unknown";
  }

  function visible(element) {
    if (element.disabled || element.hidden) return false;
    const view = element.ownerDocument.defaultView;
    if (!view) return !element.closest('[hidden], [style*="display: none"], [style*="display:none"]');
    const style = view.getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
  }

  function safeAttendanceLink(href, currentUrl) {
    try {
      const target = new URL(href, currentUrl);
      if (rule?.attendanceUrl && target.href === new URL(rule.attendanceUrl, origin).href) return true;
      const scopedQuery = rule?.attendanceQuery === true && target.pathname === "/attendance.php" && target.searchParams.get("type") === "sign" && /^\d+$/.test(target.searchParams.get("uid")) && [...target.searchParams.keys()].sort().join(",") === "type,uid";
      return target.origin === origin && !target.hash && (!target.search || scopedQuery) && (target.href === new URL(signinPath, origin).href || scopedQuery || rule?.attendancePaths?.includes(target.pathname) || (signinPath === "/" && target.pathname === "/attendance.php"));
    } catch {
      return false;
    }
  }

  function inlineAttendance(element, requireHandler = true) {
    if (!rule?.inlineAttendance || element.tagName !== "A") return false;
    if (rule.inlineAttendanceSelector) return element.matches?.(rule.inlineAttendanceSelector) === true;
    const scoped = element.closest?.("#info_block, #userinfo, #user-info, .userinfo");
    return ["", "#", "javascript:;", "javascript:void(0)", "javascript:void(0);"].includes(element.getAttribute("href") || "") && (!requireHandler || element.hasAttribute?.("onclick")) && Boolean(scoped);
  }

  function action(document, url, includeScopedHidden = false) {
    if (profileOnly) return null;
    if (!isPiggo(url)) return null;
    if (rule?.modalAttendance) return modalAttendance(document, url)?.control || null;
    const candidates = Array.from(document.querySelectorAll('a[href], button, input[type="submit"], input[type="button"]'))
      .filter(element => visible(element) || includeScopedHidden && rule?.hiddenAttendanceSelector && element.tagName === "A" && !element.disabled && !element.hidden && element.matches?.(rule.hiddenAttendanceSelector) === true && rule.attendanceLabel?.test((element.textContent || "").trim()) && safeAttendanceLink(element.getAttribute("href"), url))
      .filter(element => {
        const label = (element.innerText || element.value || element.textContent || element.getAttribute("title") || "").trim();
        if (!/^[\[【]?\s*(?:每日|今日|立即)?(?:签到|簽到|打卡)(?:得魔力|领奖)?\s*[\]】]?$/.test(label) && !rule?.attendanceLabel?.test(label)) return false;
        if (element.tagName === "A") {
          const href = element.getAttribute("href");
          if (rule?.attendanceQuery && safeAttendanceLink(href, url)) {
            const target = new URL(href, url);
            if (target.search) {
              const ownAccount = accountLink(document);
              if (!ownAccount || target.searchParams.get("uid") !== new URL(ownAccount).searchParams.get("id")) return false;
            }
          }
          return safeAttendanceLink(href, url) || inlineAttendance(element);
        }
        if (new URL(url).pathname !== new URL(signinPath, origin).pathname) return false;
        const form = element.form;
        if (!form) return false;
        const destination = new URL(form.getAttribute("action") || url, url);
        return safeAttendanceLink(destination.href, url);
      });
    if (candidates.length > 1) {
      const submissions = candidates.filter(element => element.tagName !== "A");
      if (rule?.preferAttendanceSubmit && submissions.length === 1 && new URL(url).pathname === new URL(signinPath, origin).pathname) return submissions[0];
      if (rule?.duplicateAttendanceLinks && candidates.every(element => element.tagName === "A" && safeAttendanceLink(element.getAttribute("href"), url)) && new Set(candidates.map(element => new URL(element.getAttribute("href"), url).href)).size === 1) return candidates[0];
      return "ambiguous";
    }
    return candidates[0] || null;
  }

  function modalAttendance(document, url) {
    const target = new URL(url);
    if (!isPiggo(url) || !["/", "/index.php"].includes(target.pathname) || target.search || target.hash) return null;
    const buttons = document.querySelectorAll('#modalBtn');
    const success = document.querySelectorAll('#simpleModal');
    const failure = document.querySelectorAll('#signinFailModal');
    if (buttons.length !== 1) return {status: "unknown", control: null};
    const button = buttons[0];
    if (!button.matches('input[type="submit"].dt_button') || button.form || button.hidden || button.closest('[hidden], [style*="display: none"], [style*="display:none"]')) return {status: "unknown", control: null};
    const view = document.defaultView;
    if (view && (view.getComputedStyle(button).visibility === "hidden" || button.getBoundingClientRect().width <= 0 || button.getBoundingClientRect().height <= 0)) return {status: "unknown", control: null};
    if (button.disabled && button.value.trim() === "已经打卡") return {status: view ? "pending" : "already_done", control: null};
    if (success.length !== 1 || failure.length !== 1) return {status: "unknown", control: null};
    if (failure[0].style.display === "block") return {status: "error", control: null, message: "海胆打卡接口返回错误，未确认成功"};
    if (success[0].style.display === "block") return {status: "pending", control: null};
    return {status: !button.disabled && button.value.trim() === "每日打卡" ? "ready" : "unknown", control: !button.disabled && button.value.trim() === "每日打卡" ? button : null};
  }

  function inspect(document, url) {
    const text = (document.body?.innerText || document.body?.textContent || "").slice(0, 120000);
    const password = Array.from(document.querySelectorAll('input[type="password"]')).some(visible);
    const imageInspection = {hdsky, opencd, ptsbao}[rule?.imageCaptcha]?.inspect(document, url, visible);
    const pt52Inspection = rule?.sliderCaptcha === "pt52" ? pt52.inspect(document, url) : null;
    const captcha = Array.from(document.querySelectorAll('input[name*="captcha" i], input[name="imagestring"], iframe[src*="captcha"], img[src*="image.php"]')).filter(visible).some(element => !pt52Inspection?.captchaElements?.includes(element) && (!imageInspection || !(rule?.imageCaptcha === "hdsky" && ["imagestring", "showupimg"].includes(element.id) || imageInspection.captchaElements?.includes(element))));
    const status = classify({url, text, password, captcha});
    if (pt52Inspection?.status === "ready" && ["success", "already_done"].includes(status)) return pt52Inspection;
    if (status === "blocked" && rule?.turnstileAttendance && new URL(url).pathname === "/attendance.php" && !new URL(url).search && !new URL(url).hash && !/验证失败|验证已过期|无法加载|error|failed|expired/i.test((document.querySelector?.('.attendance-card')?.textContent || "").replace(/\s+/g, " ")) && document.querySelectorAll('form#attendance-form').length === 1) {
      const form = document.querySelector('form#attendance-form');
      const widgets = form.querySelectorAll('.cf-turnstile[data-sitekey]');
      const scripts = Array.from(document.querySelectorAll('script[src]'));
      if (form.getAttribute("method")?.toLowerCase() === "post" && new URL(form.getAttribute("action"), url).href === url && widgets.length === 1 && widgets[0].getAttribute("data-sitekey") === "0x4AAAAAABfcR5-BOyur3FT4" && form.querySelector('input[type="hidden"][name="cf-token"]') && scripts.some(script => script.getAttribute("src") === "https://challenges.cloudflare.com/turnstile/v0/api.js")) return {status, control: null, challengePending: true, message: "等待 Audiences 官方人机验证，验证通过后由站点自动签到"};
    }
    if (status === "blocked" && /无法连接人机验证服务/.test(text)) return {status, control: null, message: "无法连接人机验证服务，请稍后在站点重试验证"};
    if (status === "blocked" && rule?.waitForSecurityChallenge && text.trim().length < 500 && /安全检测能力由\s*雷池\s*WAF\s*驱动/.test(text) && !/拦截|禁止|失败|异常|无法|过高|forbidden|failed|error/i.test(text) && Array.from(document.querySelectorAll('script[src]')).some(script => {
      try {
        const source = new URL(script.getAttribute("src"), url);
        return source.href === "https://challenge.rivers.chaitin.cn/challenge/v2/challenge.js" || source.origin === origin && source.pathname === "/.safeline/challenge/v2/challenge.js" && !source.search && !source.hash;
      } catch { return false; }
    })) return {status, control: null, challengePending: true, message: "等待站点自动安全验证"};
    if (status !== "unknown") return {status, control: null};
    if (rule?.modalAttendance) return modalAttendance(document, url) || {status: "unknown", control: null};
    if (rule?.sliderCaptcha === "freefarm") {
      const sliderInspection = freefarm.inspect(document, url, visible);
      if (sliderInspection) return sliderInspection;
    }
    if (imageInspection) return imageInspection;
    if (pt52Inspection) return pt52Inspection;
    if (rule?.manualSelector && Array.from(document.querySelectorAll(rule.manualSelector)).some(visible)) return {status: "manual_required", control: null};
    if (rule?.attendanceDoneText && Array.from(document.querySelectorAll?.("tr") || []).some(row => rule.profileRow?.test(row.textContent || "") && rule.attendanceDoneText.test(row.textContent || ""))) return {status: "already_done", control: null};
    const attendance = Array.from(document.querySelectorAll('a[href]')).filter(visible)
      .filter(element => safeAttendanceLink(element.getAttribute("href"), url) || inlineAttendance(element, false));
    const completed = attendance.some(element => {
      const label = (element.innerText || element.textContent || "").trim();
      return /^\[?\s*签到已得\s*[\d,.]+\s*(?:[,，]\s*补签卡\s*[:：]\s*\d+)?\s*\]?$/.test(label) || rule?.attendanceDoneLabel?.test(label) || inlineAttendance(element, false) && /^[\[【]?\s*(?:今日)?已[签簽]到\s*[\]】]?$/.test(label);
    });
    if (completed) return {status: "already_done", control: null};
    const control = action(document, url);
    if (control === "ambiguous") return {status: "ambiguous", control: null};
    return {status: control ? "ready" : profileOnly && (accountLink(document) || Object.values(profile(document)).some(Boolean)) ? "profile_only" : "unknown", control};
  }

  function result(status, url) {
    return {status, message: labels[status] || labels.unknown, path: isPiggo(url) ? new URL(url).pathname : "", time: new Date().toISOString()};
  }

  function accountLink(document) {
    const selectors = rule?.accountSelector ? [rule.accountSelector] : [
      '#info_block a[href]',
      '#userinfo a[href]',
      '#user-info a[href]',
      '.userinfo a[href]',
      rule?.profileSelector ? `${rule.profileSelector} a[href]` : null,
    ].filter(Boolean);
    let links = [...new Set(selectors.flatMap(selector => Array.from(document.querySelectorAll?.(selector) || [])))];
    if (rule?.accountRow) {
      for (const row of document.querySelectorAll?.("tr") || []) {
        if (rule.accountRow.test(row.textContent || "")) links = links.concat(Array.from(row.querySelectorAll?.('a[href]') || []));
      }
    }
    const urls = links.map(link => {
      try {
        const target = new URL(link.getAttribute("href"), origin);
        target.hash = "";
        return target.origin === origin && target.pathname === (rule?.accountPath || "/userdetails.php") && /^\d+$/.test(target.searchParams.get("id")) && [...target.searchParams.keys()].length === 1 ? target.href : null;
      } catch { return null; }
    }).filter(Boolean);
    return new Set(urls).size === 1 ? urls[0] : null;
  }

  function classLink(document, details = false) {
    const selectors = [
      '#info_block a[href]',
      '#userinfo a[href]',
      '#user-info a[href]',
      '.userinfo a[href]',
      rule?.profileSelector ? `${rule.profileSelector} a[href]` : null,
    ].filter(Boolean);
    let links = [...new Set(selectors.flatMap(selector => Array.from(document.querySelectorAll?.(selector) || [])))];
    if (details) {
      for (const row of document.querySelectorAll("tr")) {
        const cells = Array.from(row.querySelectorAll(":scope > td, :scope > th"));
        if (cells.length === 2 && /^(?:用户等级|用戶等級|用户组|等级|等級|class)$/i.test(cells[0].textContent.replace(/[\s:：]/g, ""))) links = links.concat(Array.from(cells[1].querySelectorAll?.("a[href]") || []));
      }
    }
    const urls = links.map(link => {
      try {
        const target = new URL(link.getAttribute("href"), origin);
        return target.origin === origin && target.pathname === "/classes.php" && !target.search && /^#\d+$/.test(target.hash) ? target.href : null;
      } catch { return null; }
    }).filter(Boolean);
    return new Set(urls).size === 1 ? urls[0] : null;
  }

  function classLevel(document, url) {
    if (!isPiggo(url) || new URL(url).pathname !== "/classes.php" || !/^#\d+$/.test(new URL(url).hash)) return null;
    const fragment = new URL(url).hash.slice(1);
    const anchor = document.getElementById(fragment) || Array.from(document.querySelectorAll("a[name]")).find(element => element.getAttribute("name") === fragment);
    const cell = anchor?.closest("tr")?.querySelector(":scope > td, :scope > th");
    if (!cell) return null;
    const rank = cell.textContent.match(/\b(?:Nexus\s*Master|Staff\s*Leader|Ultimate\s*User|Extreme\s*User|Crazy\s*User|Insane\s*User|Veteran\s*User|Elite\s*User|Power\s*User|Administrator|Moderator|Uploader|Sysop|Peasant|VIP|User)\b/i)?.[0];
    if (rank) return siteTools.level(rank);
    return Array.from(cell.querySelectorAll("img[title], img[alt]")).map(image => siteTools.level(image.getAttribute("title") || image.getAttribute("alt"))).find(Boolean) || null;
  }

  function strictLevel(value) {
    const level = siteTools.level(value);
    return /^(?:Nexus Master|Staff Leader|Ultimate User|Extreme User|Crazy User|Insane User|Veteran User|Elite User|Power User|Administrator|Moderator|Uploader|Sysop|Peasant|VIP|User)$/i.test(level || "") ? level : null;
  }

  function profile(document, details = false) {
    const aliases = {level: /^(?:用户等级|用戶等級|用户组|等级|等級|class)$/i, bonus: /^(?:魔力值?|积分|積分|爆米花(?:系统)?|bonus)$/i, seedingPoints: /^(?:做[种種][积積]分|[种種]子[积積]分|seedingpoints?|seedingscore)$/i, uploaded: /^(?:上传量?|上傳量?|uploaded)$/i, downloaded: /^(?:下载量?|下載量?|downloaded)$/i, ratio: /^(?:分享率|分享比率|ratio)$/i};
    const values = {};
    const blockSelector = ['#info_block', '#userinfo', '#user-info', '.userinfo', rule?.profileSelector].filter(Boolean).join(', ');
    const blocks = Array.from(document.querySelectorAll?.(blockSelector) || []);
    const rowText = rule?.profileRow ? Array.from(document.querySelectorAll?.("tr") || []).filter(row => rule.profileRow.test(row.textContent || "")).map(row => row.textContent || "").join("\n") : "";
    const text = blocks.map(block => {
      const copy = block.cloneNode(true);
      for (const image of copy.querySelectorAll("img[title], img[alt]")) image.replaceWith(` ${image.getAttribute("title") || image.getAttribute("alt")}： `);
      return copy.textContent;
    }).join("\n") + `\n${rowText}` + (details && rule?.fullProfileText ? `\n${document.body?.textContent || ""}` : "");
    const headerRanks = rule?.levelFromUserbar ? Array.from(text.matchAll(/[（(]\s*((?:Nexus\s*Master|Staff\s*Leader|Ultimate\s*User|Extreme\s*User|Crazy\s*User|Insane\s*User|Veteran\s*User|Elite\s*User|Power\s*User|Administrator|Moderator|Uploader|Sysop|Peasant|VIP|User))\s*[)）]/gi), match => siteTools.level(match[1])) : [];
    const headerLevel = new Set(headerRanks).size === 1 ? headerRanks[0] : null;
    const patterns = {level: /(?:用户等级|用戶等級|等级|等級)\s*[:：]\s*\[?([\w -]{1,40})/i, bonus: /(?<!做[种種]|[种種]子|Seeding\s)(?:魔力值?|[积積]分|爆米花(?:系统)?|Bonus)\s*[:：]?\s*([\d,.]+)/i, seedingPoints: /(?:做[种種][积積]分|[种種]子[积積]分|Seeding\s*(?:Points?|Score))\s*[:：]?\s*([\d,.]+)/i, uploaded: /(?:上传量?|上傳量?|Uploaded)\s*[:：]?\s*([\d,.]+\s*(?:[KMGTPE]i?B|B|Bytes?))/i, downloaded: /(?:下载量?|下載量?|Downloaded)\s*[:：]?\s*([\d,.]+\s*(?:[KMGTPE]i?B|B|Bytes?))/i, ratio: /(?:分享率|分享比率|Ratio)\s*[:：]?\s*([\d,.]+|∞|Inf|无限|無限)/i};
    for (const [field, pattern] of Object.entries(patterns)) values[field] = text.match(pattern)?.[1]?.trim() || null;
    for (const [field, pattern] of Object.entries(rule?.profilePatterns || {})) if (!values[field]) values[field] = text.match(pattern)?.[1]?.trim() || null;
    if (!values.level && rule?.levelListSelector) {
      const ranks = Array.from(document.querySelectorAll(rule.levelListSelector)).map(entry => entry.textContent.match(/^\s*Class\s*:\s*([^\r\n:]{1,40})\s*$/i)?.[1]?.trim()).filter(Boolean);
      if (new Set(ranks).size === 1) values.level = ranks[0];
    }
    for (const [field, selector] of Object.entries(rule?.profileMetrics || {})) {
      const element = document.querySelector?.(selector);
      const source = `${element?.getAttribute?.("aria-label") || ""} ${element?.getAttribute?.("title") || ""} ${element?.textContent || ""}`;
      const value = ["uploaded", "downloaded"].includes(field)
        ? source.match(/[\d,.]+\s*(?:[KMGTPE]i?B|Bytes?|B)\b/i)?.[0]
        : source.match(/[+-]?\d+(?:,\d{3})*(?:\.\d+)?|∞/)?.[0];
      if (value) values[field] = value;
    }
    if (details) {
      for (const container of document.querySelectorAll('[class*="stat"], [class*="metric"]')) {
        const labelElement = container.querySelector?.('[class*="label"], [class*="title"], [class*="name"]');
        const valueElement = container.querySelector?.('[class*="value"], [class*="number"], [class*="amount"]');
        if (!labelElement || !valueElement) continue;
        const label = labelElement.textContent.replace(/[\s:：]/g, "");
        for (const [field, pattern] of Object.entries(aliases)) if (pattern.test(label)) values[field] = valueElement.textContent.replace(/\s+/g, " ").trim().slice(0, 64) || null;
      }
      for (const row of document.querySelectorAll("tr")) {
        const cells = Array.from(row.querySelectorAll(":scope > td, :scope > th"));
        if (cells.length !== 2) continue;
        const label = cells[0].textContent.replace(/[\s:：]/g, "");
        if (rule?.transferLabel?.test(label)) {
          for (const cell of cells[1].querySelectorAll("td")) {
            const inline = cell.textContent.trim();
            for (const field of ["ratio", "uploaded", "downloaded"]) {
              const match = inline.match(patterns[field]);
              if (match && match.index === 0) values[field] = match[1];
            }
          }
        }
        for (const [field, pattern] of Object.entries({...aliases, ...rule?.profileLabels})) {
          if (pattern.test(label)) {
            values[field] = cells[1].textContent.replace(/\s+/g, " ").trim().slice(0, 64) || null;
            if (field === "level" && !siteTools.level(values.level)) {
              const images = Array.from(cells[1].querySelectorAll?.("img[title], img[alt]") || []);
              values.level = images.map(image => siteTools.level(image.getAttribute("title") || image.getAttribute("alt"))).find(Boolean) || null;
            }
          }
        }
      }
      if (!values.level && rule?.levelFromProfileImage) {
        const levels = Array.from(document.querySelectorAll('img[title], img[alt]'))
          .map(image => strictLevel(image.getAttribute("title") || image.getAttribute("alt")))
          .filter(Boolean);
        if (new Set(levels).size === 1) values.level = levels[0];
      }
      if (!values.level && rule?.levelFromProfileText) {
        const bodyText = document.body?.textContent || "";
        const current = bodyText.match(/(?:\([^)]{1,20}\)|（[^）]{1,20}）)?\s*(Nexus\s*Master|Staff\s*Leader|Ultimate\s*User|Extreme\s*User|Crazy\s*User|Insane\s*User|Veteran\s*User|Elite\s*User|Power\s*User|Administrator|Moderator|Uploader|Sysop|Peasant|VIP|User)\s*(?=加入日期|加入日期：|Join\s*date)/i);
        if (current) values.level = strictLevel(current[1]);
        if (!values.level) {
          const levels = Array.from(bodyText.matchAll(/(?:\([^)]{1,20}\)|（[^）]{1,20}）)?\s*(Nexus\s*Master|Staff\s*Leader|Ultimate\s*User|Extreme\s*User|Crazy\s*User|Insane\s*User|Veteran\s*User|Elite\s*User|Power\s*User|Administrator|Moderator|Uploader|Sysop|Peasant|VIP|User)(?=$|[^a-z])/gi), match => strictLevel(match[1])).filter(Boolean);
          if (new Set(levels).size === 1) values.level = levels[0];
        }
      }
    }
    if (values.level && rule?.levelPattern) values.level = values.level.match(rule.levelPattern)?.[1] || values.level;
    if (headerLevel) values.level = headerLevel;
    if (/^(?:无限|無限)$/.test(values.ratio)) values.ratio = "∞";
    return siteTools.profile(values);
  }

  function profileHints(document) {
    const field = /用户|用戶|等级|等級|上传|上傳|下载|下載|分享|魔力|爆米花|积分|積分|传输|傳輸|ratio|uploaded|downloaded|bonus|class/i;
    const redact = value => String(value || "")
      .replace(/[\d,.]+(?:\s*[KMGTPE]i?B)?/gi, "#")
      .replace(/[A-Za-z0-9_.-]{2,}/g, word => /^(?:User|Power|Elite|Veteran|Insane|Crazy|Extreme|Ultimate|Nexus|Master|Staff|Leader|Ratio|Uploaded|Downloaded|Bonus|Class)$/i.test(word) ? word : "*")
      .replace(/\s+/g, " ").trim().slice(0, 160);
    const describe = element => ({
      tag: element.tagName || "",
      id: element.id || "",
      className: typeof element.className === "string" ? element.className.slice(0, 120) : "",
      title: redact(element.getAttribute?.("title")),
      aria: redact(element.getAttribute?.("aria-label")),
      text: redact(element.textContent)
    });
    const selector = ['[class*="userbar"], [class*="profile"], [class*="stat"], [class*="metric"], tr, dt, img[title], img[alt]', rule?.profileSelector].filter(Boolean).join(', ');
    return Array.from(document.querySelectorAll?.(selector) || [])
      .filter(element => field.test(`${element.getAttribute?.("title") || ""} ${element.getAttribute?.("aria-label") || ""} ${element.textContent || ""}`) || Boolean(strictLevel(element.getAttribute?.("title") || element.getAttribute?.("alt") || "")))
      .slice(0, 40)
      .map(describe);
  }

  const api = {origin, statusPath: rule?.statusPath, profileApi: rule?.profileApi, revealAttendanceSelector: rule?.revealAttendanceSelector, continueAttendanceForm: rule?.continueAttendanceForm === true, nativeAttendanceNavigation: rule?.nativeAttendanceNavigation === true, homePaths: rule?.homePaths || [], detailFillOnly: rule?.detailFillOnly === true, reuseRecentPage: rule?.reuseRecentPage === true, navigationRetries: rule?.navigationRetries || 0, labels, isPiggo, classify, visible, safeAttendanceLink, action, inspect, result, profile, profileHints, accountLink, classLink, classLevel};
  return api;
  }
  const api = {...create(), create};
  root.NetSurfPiggo = api;
  if (typeof module !== "undefined") module.exports = api;
})(globalThis);
