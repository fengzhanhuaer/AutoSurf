(function (root) {
  function controls(document, url) {
    try {
      const target = new URL(url);
      if (target.protocol !== "https:" || !["52pt.site", "www.52pt.site"].includes(target.hostname) || target.port || target.pathname !== "/bakatest.php" || target.search || target.hash) return null;
      const unique = selector => { const elements = document.querySelectorAll(selector); return elements.length === 1 ? elements[0] : null; };
      const container = unique("#slider-container");
      const handler = unique("#slider-btn");
      const background = unique("#slider-bg");
      const captcha = unique('input#sign_captcha[name="sign_captcha"][type="hidden"]');
      const token = unique('input[name="sign_token"][type="hidden"]');
      const marker = unique('input[name="sign_submit"][type="hidden"]');
      const button = unique('button#submit-btn[type="submit"]');
      const form = button?.form;
      if (!container || !handler || !background || !captcha || !token || !marker || !form || form.method.toLowerCase() !== "post" || form.getAttribute("target") || button.name || new URL(form.getAttribute("action") || url, url).href !== url || !/^[a-zA-Z0-9_-]{16,128}$/.test(token.value) || marker.value !== "1" || form.elements.length !== 4 || ![captcha, token, marker, button].every(element => element.form === form) || !form.contains(container) || container.children.length !== 2 || handler.parentElement !== container || background.parentElement !== container || document.querySelector('iframe, input[type="password"], .cf-turnstile')) return null;
      if (button.disabled ? button.textContent.trim() !== "请先完成滑块" || captcha.value !== "" : button.textContent.trim() !== "提交签到" || !/^\d{1,8}$/.test(captcha.value)) return null;
      return {container, handler, background, captcha, token, marker, button, form, tokenValue: token.value};
    } catch { return null; }
  }

  function inspect(document, url) {
    const current = controls(document, url);
    if (current) return {status: "ready", control: current.button, captchaElements: [current.captcha]};
    if (document.querySelector?.("#slider-container, #slider-btn, #sign_captcha")) return {status: "manual_required", control: null, message: "52PT 滑块或表单结构已变化，请在网页中处理"};
    return null;
  }

  async function signin(document, url, visible, operationId, timeoutMs, send) {
    const stopped = (message, attempted = false) => ({status: "manual_required", message, attempted});
    const current = controls(document, url);
    if (!current || document.readyState !== "complete" || ![current.handler, current.container].every(visible) || !current.button.disabled || timeoutMs < 1000) return stopped("52PT 签到表单尚未就绪，未提交");
    const rect = current.container.getBoundingClientRect();
    const handleRect = current.handler.getBoundingClientRect();
    if (current.container.clientWidth !== 260 || current.handler.clientWidth !== 50 || current.handler.offsetLeft !== 2 || handleRect.height !== 36) return stopped("52PT 滑块尺寸已变化，未拖动");
    const deadline = Date.now() + timeoutMs;
    const valid = () => {
      const next = controls(document, url);
      return Date.now() < deadline && next && Object.keys(current).every(key => next[key] === current[key]) && [current.handler, current.container].every(visible) && current.container.clientWidth === 260 && current.handler.clientWidth === 50 && current.handler.getBoundingClientRect().height === 36 && current.handler.getBoundingClientRect().top === handleRect.top && current.container.getBoundingClientRect().left === rect.left && current.container.getBoundingClientRect().top === rect.top;
    };
    const permit = await send({type: "submission-stage", operationId, stage: "submitted"});
    if (!permit?.accepted || !valid()) return stopped("52PT 提交许可或页面已变化，未操作");
    const Mouse = document.defaultView.MouseEvent;
    const startX = handleRect.left + handleRect.width / 2;
    const endX = startX + 204;
    const centerY = handleRect.top + handleRect.height / 2;
    current.handler.dispatchEvent(new Mouse("mousedown", {bubbles: true, cancelable: true, clientX: startX, clientY: centerY, button: 0, buttons: 1}));
    for (let step = 1; step <= 32; step += 1) {
      if (!valid()) return stopped("52PT 拖动期间页面变化，已停止", true);
      document.dispatchEvent(new Mouse("mousemove", {bubbles: true, clientX: startX + 204 * step / 32, clientY: centerY, buttons: 1}));
    }
    if (!valid()) return stopped("52PT 拖动已停止，未提交", true);
    document.dispatchEvent(new Mouse("mouseup", {bubbles: true, clientX: endX, clientY: centerY, button: 0}));
    if (!valid() || current.button.disabled || current.button.textContent.trim() !== "提交签到" || !/^\d{1,8}$/.test(current.captcha.value)) return stopped("52PT 原生滑块未通过，未提交", true);
    current.button.click();
    return {status: "pending", attempted: true};
  }

  const api = {controls, inspect, signin};
  root.NetSurfPt52 = api;
  if (typeof module !== "undefined") module.exports = api;
})(globalThis);
