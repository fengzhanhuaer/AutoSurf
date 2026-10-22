(function (root) {
  const images = root.NetSurfHdsky || (typeof module !== "undefined" ? require("./hdsky.js") : null);

  function supported(url) {
    try {
      const target = new URL(url);
      return target.protocol === "https:" && ["ptsbao.club", "www.ptsbao.club"].includes(target.hostname) && !target.port && ["/", "/index.php", "/attendance.php"].includes(target.pathname) && !target.search && !target.hash;
    } catch { return false; }
  }

  function controls(document, visible, url = document.location?.href) {
    if (!supported(url) || new URL(url).pathname !== "/attendance.php" || document.querySelector('iframe, input[name*="captcha" i], input[name="recaptcha_response_field"], input[type="password"]')) return null;
    const unique = selector => {
      const elements = Array.from(document.querySelectorAll(selector));
      return elements.length === 1 ? elements[0] : null;
    };
    const input = unique('input[name="imagestring"]');
    const hash = unique('input[name="imagehash"][type="hidden"]');
    const button = unique('input[type="submit"]');
    const form = input?.form;
    if (!form || input.type !== "text" || !hash?.value || hash.value.length > 256 || !button || hash.form !== form || button.form !== form || form.elements.length !== 3 || !Array.from(form.elements).every(element => [input, hash, button].includes(element)) || form.method.toLowerCase() !== "post" || new URL(form.getAttribute("action") || url, url).href !== new URL("/attendance.php", url).href || form.hasAttribute("onsubmit") || form.hasAttribute("target") || input.hasAttribute("oninput") || ["onclick", "formaction", "formmethod", "formtarget"].some(attribute => button.hasAttribute(attribute)) || ![input, button].every(visible) || button.value.trim() !== "立即签到") return null;
    const candidates = Array.from(form.querySelectorAll("img")).filter(image => {
      try {
        const target = new URL(image.getAttribute("src"), url);
        const keys = [...target.searchParams.keys()].sort().join(",");
        return visible(image) && target.origin === new URL(url).origin && target.pathname === "/image.php" && !target.hash && ["action,imagehash", "action,imagehash,secret"].includes(keys) && target.searchParams.get("action") === "regimage" && target.searchParams.get("imagehash") === hash.value && !target.searchParams.get("secret");
      } catch { return false; }
    });
    if (candidates.length !== 1) return null;
    return {image: candidates[0], input, button, binding: JSON.stringify([hash.value, form.getAttribute("action"), candidates[0].getAttribute("src")])};
  }

  function entry(document, url, visible) {
    if (!supported(url) || new URL(url).pathname === "/attendance.php") return null;
    const entries = Array.from(document.querySelectorAll('a[href]')).filter(element => {
      try {
        return visible(element) && /^\[签到得魔力\]$/.test(element.textContent.trim()) && !element.hasAttribute("onclick") && new URL(element.getAttribute("href"), url).href === new URL("/attendance.php", url).href;
      } catch { return false; }
    });
    return entries.length === 1 ? entries[0] : null;
  }

  function inspect(document, url, visible) {
    if (!supported(url) || new URL(url).pathname !== "/attendance.php") return null;
    const known = controls(document, visible, url);
    if (known) return {status: "ready", control: known.button, captchaElements: [known.input, known.image]};
    return null;
  }

  async function signin(document, url, visible, operationId, timeoutMs, send) {
    const stopped = message => ({status: "manual_required", message, attempted: false});
    if (!supported(url)) return stopped("当前页面不是已适配的 PTSBao 签到页，未提交签到");
    if (new URL(url).pathname !== "/attendance.php") {
      const control = entry(document, url, visible);
      if (!control) return stopped("未找到唯一 PTSBao 签到入口，未打开验证页");
      const permit = await send({type: "submission-stage", operationId, stage: "entry"});
      if (!permit?.accepted || entry(document, url, visible) !== control) return stopped("PTSBao 签到入口许可已失效，未打开验证页");
      control.click();
      return {status: "pending", attempted: true};
    }
    const current = controls(document, visible, url);
    if (!current) return stopped("PTSBao 验证码表单不符合已适配结构，未提交签到");
    return images.submitImage(document, url, visible, current, operationId, Date.now() + timeoutMs, send, {controls, inspect, name: "PTSBao"});
  }

  const api = {supported, controls, inspect, signin};
  root.NetSurfPtsbao = api;
  if (typeof module !== "undefined") module.exports = api;
})(globalThis);
