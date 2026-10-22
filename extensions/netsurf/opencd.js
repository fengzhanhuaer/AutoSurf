(function (root) {
  const images = root.NetSurfHdsky || (typeof module !== "undefined" ? require("./hdsky.js") : null);

  function supported(url) {
    try {
      const target = new URL(url);
      return target.protocol === "https:" && ["open.cd", "www.open.cd"].includes(target.hostname) && !target.port && ["/", "/index.php"].includes(target.pathname) && !target.search && !target.hash;
    } catch { return false; }
  }

  function frameDocument(document, url, visible) {
    try {
      const frames = Array.from(document.querySelectorAll("iframe#i_signin")).filter(visible);
      if (frames.length !== 1) return null;
      const expected = new URL("/plugin_sign-in.php", url).href;
      const frame = frames[0];
      return frame.src === expected && frame.contentDocument?.URL === expected ? frame.contentDocument : null;
    } catch { return null; }
  }

  function controls(document, visible, url = document.location?.href) {
    if (!supported(url)) return null;
    const frame = frameDocument(document, url, visible);
    if (!frame) return null;
    if (frame.querySelector('iframe, input[name*="captcha" i], input[name="recaptcha_response_field"]')) return null;
    const unique = selector => {
      const elements = Array.from(frame.querySelectorAll(selector));
      return elements.length === 1 ? elements[0] : null;
    };
    const form = unique("form#frmSignin");
    const input = unique('input#imagestring[name="imagestring"]');
    const hash = unique('input[name="imagehash"][type="hidden"]');
    const button = unique('button#ok');
    if (!form || !input || !hash || !button || input.type !== "text" || button.type !== "submit" || !hash.value || hash.value.length > 256 || form.method.toLowerCase() !== "post" || form.action !== new URL("/plugin_sign-in.php?cmd=signin", url).href || input.form !== form || hash.form !== form || button.form !== form || ![input, button].every(visible) || !/^[签簽]到$/.test(button.textContent.trim()) || !/^javascript:do_signin\(this\);return false;$/.test(button.getAttribute("onclick") || "")) return null;
    const candidates = Array.from(form.querySelectorAll("img")).filter(image => {
      try {
        const target = new URL(image.src);
        return visible(image) && target.origin === new URL(url).origin && target.pathname === "/image.php" && !target.hash && [...target.searchParams.keys()].sort().join(",") === "action,imagehash" && target.searchParams.get("imagehash") === hash.value;
      } catch { return false; }
    });
    if (candidates.length !== 1) return null;
    return {image: candidates[0], input, button, binding: JSON.stringify([hash.value, form.action, candidates[0].src, button.getAttribute("onclick")])};
  }

  function entry(document, url, visible) {
    const entries = Array.from(document.querySelectorAll("a[onclick]")).filter(element => {
      try {
        const target = new URL(element.getAttribute("href") || url, url);
        return visible(element) && /^[签簽]到$/.test(element.textContent.trim()) && element.getAttribute("onclick") === "javascript:signin(this);" && supported(target.href) && target.origin === new URL(url).origin;
      } catch { return false; }
    });
    return entries.length === 1 ? entries[0] : null;
  }

  function inspect(document, url, visible) {
    if (!supported(url)) return null;
    const completed = Array.from(document.querySelectorAll('a[href]')).some(element => {
      try { return visible(element) && /^(?:今日)?已[签簽]到$/.test(element.textContent.trim()) && !element.hasAttribute("onclick") && new URL(element.getAttribute("href"), url).href === new URL("/plugin_sign-in.php?cmd=show-log", url).href; } catch { return false; }
    });
    if (completed) return {status: "already_done", control: null};
    const known = controls(document, visible, url);
    if (known) return {status: "ready", control: known.button, captchaElements: [known.image, known.input]};
    const frame = frameDocument(document, url, visible);
    if (frame && frame.readyState === "complete") return {status: "manual_required", control: null, message: "OpenCD 签到表单不符合已适配结构，未提交签到"};
    const control = entry(document, url, visible);
    return control ? {status: "ready", control} : null;
  }

  async function signin(document, url, visible, operationId, timeoutMs, send) {
    const deadline = Date.now() + timeoutMs;
    const stopped = message => ({status: "manual_required", message, attempted: false});
    const initial = inspect(document, url, visible);
    if (initial?.status === "already_done") return {status: initial.status, attempted: false};
    if (!supported(url) || initial?.status !== "ready") return stopped("未识别到 OpenCD 图片签到入口，未提交签到");
    let current = controls(document, visible, url);
    if (!current) {
      const permit = await send({type: "captcha-open", operationId});
      if (!permit?.accepted) return stopped("OpenCD 签到入口许可失效，未打开验证码");
      if (entry(document, url, visible) !== initial.control) return stopped("OpenCD 签到入口已变化，未打开验证码");
      initial.control.addEventListener("click", event => event.preventDefault(), {once: true});
      initial.control.click();
      while (Date.now() < deadline && !(current = controls(document, visible, url))) {
        const status = inspect(document, url, visible);
        if (status?.status === "already_done") return {status: status.status, attempted: false};
        if (status?.status === "manual_required") return stopped(status.message);
        await new Promise(resolve => setTimeout(resolve, 100));
      }
    }
    return images.submitImage(document, url, visible, current, operationId, deadline, send, {controls, inspect, name: "OpenCD"});
  }

  const api = {supported, controls, inspect, signin};
  root.NetSurfOpenCd = api;
  if (typeof module !== "undefined") module.exports = api;
})(globalThis);
