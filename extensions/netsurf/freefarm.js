(function (root) {
  function controls(document, url, visible) {
    try {
      const target = new URL(url);
      if (target.protocol !== "https:" || !["pt.0ff.cc", "www.pt.0ff.cc"].includes(target.hostname) || target.port || target.pathname !== "/attendance.php" || target.search || target.hash || document.readyState !== "complete" || document.querySelector('form, input, iframe, [class*="captcha" i]')) return null;
      const unique = selector => {
        const elements = Array.from(document.querySelectorAll(selector));
        return elements.length === 1 ? elements[0] : null;
      };
      const container = unique("#dragContainer");
      const handler = unique("#dragHandler");
      const background = unique("#dragBg");
      const text = unique("#dragText");
      if (!container || !handler || !background || !text || container.children.length !== 3 || ![handler, background, text].every(element => element.parentElement === container) || ![container, handler, text].every(visible) || text.textContent.trim() !== "拖动滑块验证" || handler.className !== "dragHandlerBg") return null;
      const scripts = Array.from(document.querySelectorAll("script[src]")).filter(script => {
        const source = new URL(script.getAttribute("src"), url);
        return source.origin === target.origin && /^\/slide_check_[A-Za-z0-9_+-]+\.js$/.test(source.pathname) && !source.search && !source.hash;
      });
      const rect = container.getBoundingClientRect();
      const handleRect = handler.getBoundingClientRect();
      const distance = container.clientWidth - handler.clientWidth;
      if (scripts.length !== 1 || distance < 50 || distance > 1000 || handler.offsetLeft > 1 || rect.width < handleRect.width || handleRect.height <= 0) return null;
      return {container, handler, background, text, script: scripts[0], scriptSource: scripts[0].getAttribute("src"), distance, startX: handleRect.left + handleRect.width / 2, endX: rect.left + distance + handler.clientWidth / 2, centerY: handleRect.top + handleRect.height / 2};
    } catch { return null; }
  }

  function inspect(document, url, visible) {
    if (document.readyState !== "complete") return null;
    const current = controls(document, url, visible);
    if (current) return {status: "ready", control: current.handler};
    if (new URL(url).hostname.replace(/^www\./, "") === "pt.0ff.cc" && document.querySelector("#dragContainer, #dragHandler")) return {status: "manual_required", control: null, message: "Free Farm 滑块结构尚未就绪或已变化，请在网页中处理"};
    return null;
  }

  async function signin(document, url, visible, operationId, timeoutMs, send) {
    const stopped = message => ({status: "manual_required", message, attempted: false});
    const current = controls(document, url, visible);
    if (!current || timeoutMs < 1000) return stopped("Free Farm 滑块不符合已适配结构，未拖动");
    const deadline = Date.now() + timeoutMs;
    const permit = await send({type: "submission-stage", operationId, stage: "submitted"});
    const same = () => {
      const next = controls(document, url, visible);
      return next && Object.keys(current).every(field => next[field] === current[field]);
    };
    if (!permit?.accepted || Date.now() >= deadline || !same()) return stopped("Free Farm 滑块许可或页面已变化，未拖动");
    const Mouse = document.defaultView.MouseEvent;
    const validGesture = () => Date.now() < deadline && Object.values(current).filter(value => value?.nodeType === 1).every(element => element.isConnected) && current.container.children.length === 3 && [current.handler, current.background, current.text].every(element => element.parentElement === current.container) && current.script.getAttribute("src") === current.scriptSource && current.container.clientWidth - current.handler.clientWidth === current.distance && current.container.getBoundingClientRect().left + current.distance + current.handler.clientWidth / 2 === current.endX && current.text.textContent.trim() === "拖动滑块验证" && current.handler.className === "dragHandlerBg" && !document.querySelector('form, input, iframe, [class*="captcha" i]');
    const interrupted = () => ({status: "manual_required", message: "Free Farm 拖动期间页面发生变化或超时，已停止", attempted: true});
    current.handler.dispatchEvent(new Mouse("mousedown", {bubbles: true, cancelable: true, clientX: current.startX, clientY: current.centerY, buttons: 1, button: 0}));
    for (let step = 1; step <= 32; step += 1) {
      if (!validGesture()) return interrupted();
      document.dispatchEvent(new Mouse("mousemove", {bubbles: true, clientX: current.startX + (current.endX - current.startX) * step / 32, clientY: current.centerY, buttons: 1}));
    }
    if (!validGesture()) return interrupted();
    document.dispatchEvent(new Mouse("mouseup", {bubbles: true, clientX: current.endX, clientY: current.centerY, button: 0}));
    return {status: "pending", attempted: true};
  }

  const api = {controls, inspect, signin};
  root.NetSurfFreeFarm = api;
  if (typeof module !== "undefined") module.exports = api;
})(globalThis);
