(function (root) {
  function supported(url) {
    try {
      const target = new URL(url);
      return target.protocol === "https:" && ["hdsky.me", "www.hdsky.me"].includes(target.hostname) && !target.port && ["/", "/index.php"].includes(target.pathname) && !target.search && !target.hash;
    } catch { return false; }
  }

  function controls(document, visible) {
    const unique = selector => {
      const elements = Array.from(document.querySelectorAll(selector)).filter(visible);
      return elements.length === 1 ? elements[0] : null;
    };
    const image = unique("img#showupimg");
    const input = unique('input#imagestring:not([type="hidden"]):not([type="password"])');
    const button = unique('#showupbutton');
    return image && input && button && /^(?:Let's Go|签到|簽到)$/i.test((button.textContent || button.value || "").trim()) ? {image, input, button} : null;
  }

  function inspect(document, url, visible) {
    if (!supported(url)) return null;
    const entry = document.querySelector?.("#showup");
    const label = (entry?.textContent || "").trim();
    if (entry && visible(entry) && /^(?:\[\s*)?(?:今日)?已[签簽]到(?:\s*\])?(?:\s*\(Show(?:ed)? Up\))?$/i.test(label)) return {status: "already_done", control: null};
    const messages = Array.from(document.querySelectorAll(".jconfirm-content, .layui-layer-content, #showupmessage, #showupresult, #showupdiv")).filter(visible);
    if (messages.some(element => /成功[,，\s]*已连续签到\d+天[,，\s]*魔力值加\d+/.test(element.textContent || ""))) return {status: "success", control: null};
    const known = controls(document, visible);
    if (known) return {status: "ready", control: known.button};
    if (entry && visible(entry) && /^(?:\[\s*)?[签簽]到(?:\s*\])?(?:\s*\(Show Up\))?$/i.test(label)) return {status: "ready", control: entry};
    return null;
  }

  function capture(image, url) {
    const target = new URL(image.currentSrc || image.src, url);
    if (target.origin !== new URL(url).origin || !image.complete || image.naturalWidth < 8 || image.naturalHeight < 8 || image.naturalWidth > 800 || image.naturalHeight > 300 || image.naturalWidth * image.naturalHeight > 120000) throw new Error("invalid_image");
    const canvas = image.ownerDocument.createElement("canvas");
    canvas.width = image.naturalWidth;
    canvas.height = image.naturalHeight;
    canvas.getContext("2d").drawImage(image, 0, 0);
    return canvas.toDataURL("image/png");
  }

  async function signin(document, url, visible, operationId, timeoutMs, send) {
    const deadline = Date.now() + timeoutMs;
    const stopped = message => ({status: "manual_required", message, attempted: false});
    if (!supported(url)) return stopped("当前页面不支持本地图片识别，未提交签到");
    const initial = inspect(document, url, visible);
    if (["success", "already_done"].includes(initial?.status)) return {...initial, attempted: false};
    let current = controls(document, visible);
    if (!current) {
      if (initial?.status !== "ready" || initial.control?.id !== "showup") return stopped("未识别到 HDSky 图片签到控件，未提交签到");
      initial.control.click();
      while (Date.now() < deadline && !(current = controls(document, visible))) await new Promise(resolve => setTimeout(resolve, 100));
    }
    return submitImage(document, url, visible, current, operationId, deadline, send, {controls, inspect, name: "HDSky"});
  }

  async function submitImage(document, url, visible, current, operationId, deadline, send, adapter) {
    const stopped = message => ({status: "manual_required", message, attempted: false});
    while (current && Date.now() < deadline && !current.image.complete) await new Promise(resolve => setTimeout(resolve, 100));
    if (!current || Date.now() >= deadline) return stopped(`${adapter.name} 验证码加载超时，未提交签到`);
    let image;
    try { image = capture(current.image, url); } catch { return stopped(`无法读取 ${adapter.name} 验证码图片，未提交签到`); }
    const recognized = await send({type: "captcha-recognize", operationId, image});
    const completed = adapter.inspect(document, url, visible);
    if (["success", "already_done"].includes(completed?.status)) return {status: completed.status, attempted: false};
    if (!recognized?.accepted || !/^[A-Z0-9]{6}$/.test(recognized.answer || "")) return stopped(recognized?.message || "验证码识别结果不可靠，未提交签到");
    const unchanged = () => {
      const latest = adapter.controls(document, visible, url);
      return Date.now() < deadline && document.location?.href === url && latest?.image === current.image && latest?.input === current.input && latest?.button === current.button && latest?.binding === current.binding && capture(latest.image, url) === image;
    };
    try { if (!unchanged()) return stopped("验证码或页面已变化，未提交签到"); } catch { return stopped("验证码已失效，未提交签到"); }
    const permit = await send({type: "captcha-submit", operationId, ticket: recognized.ticket});
    if (!permit?.accepted) return stopped("签到许可已失效，未提交签到");
    try { if (!unchanged()) return {status: "error", message: "提交许可生效后验证码变化，已停止且不会自动重试", attempted: true}; } catch { return {status: "error", message: "提交许可生效后图片失效，已停止且不会自动重试", attempted: true}; }
    current.input.value = recognized.answer;
    current.input.dispatchEvent(new Event("input", {bubbles: true}));
    current.input.dispatchEvent(new Event("change", {bubbles: true}));
    try { if (!unchanged() || current.input.value !== recognized.answer) return {status: "error", message: "填写后验证码变化，已停止且不会自动重试", attempted: true}; } catch { return {status: "error", message: "填写后图片失效，已停止且不会自动重试", attempted: true}; }
    current.button.click();
    return {status: "pending", attempted: true};
  }

  const api = {supported, controls, inspect, signin, submitImage};
  root.NetSurfHdsky = api;
  if (typeof module !== "undefined") module.exports = api;
})(globalThis);
