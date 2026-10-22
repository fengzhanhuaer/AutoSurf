(() => {
  let loading;
  let busy = false;
  ort.env.wasm.numThreads = 1;
  ort.env.wasm.proxy = false;
  ort.env.wasm.wasmPaths = chrome.runtime.getURL("vendor/ocr/");

  async function load() {
    if (!loading) loading = Promise.all([
      ort.InferenceSession.create(chrome.runtime.getURL("vendor/ocr/common_old.onnx"), {executionProviders: ["wasm"]}),
      fetch(chrome.runtime.getURL("vendor/ocr/charset.json")).then(response => response.json())
    ]);
    return loading;
  }

  async function recognize(image) {
    if (typeof image !== "string" || image.length > 1400000 || !/^data:image\/png;base64,[A-Za-z0-9+/=]+$/.test(image)) throw new Error("invalid_image");
    const header = Uint8Array.from(atob(image.slice(image.indexOf(",") + 1, image.indexOf(",") + 45)), character => character.charCodeAt(0));
    const view = new DataView(header.buffer);
    if (header.length < 24 || view.getUint32(0) !== 0x89504e47 || view.getUint32(4) !== 0x0d0a1a0a || view.getUint32(12) !== 0x49484452) throw new Error("invalid_image");
    const width = view.getUint32(16);
    const height = view.getUint32(20);
    if (width < 8 || height < 8 || width > 800 || height > 300 || width * height > 120000) throw new Error("invalid_image");
    const bitmap = await createImageBitmap(await (await fetch(image)).blob());
    try {
      if (bitmap.width < 8 || bitmap.height < 8 || bitmap.width > 800 || bitmap.height > 300 || bitmap.width * bitmap.height > 120000) throw new Error("invalid_image");
      const canvas = document.createElement("canvas");
      canvas.width = bitmap.width;
      canvas.height = bitmap.height;
      const context = canvas.getContext("2d", {willReadFrequently: true});
      context.drawImage(bitmap, 0, 0);
      const prepared = NetSurfOcrCore.candidates(context.getImageData(0, 0, canvas.width, canvas.height));
      const [session, charset] = await load();
      const values = [];
      for (const candidate of prepared) {
        const source = document.createElement("canvas");
        source.width = candidate.width;
        source.height = candidate.height;
        const pixels = new Uint8ClampedArray(candidate.pixels.length * 4);
        candidate.pixels.forEach((value, index) => { pixels[index * 4] = value; pixels[index * 4 + 1] = value; pixels[index * 4 + 2] = value; pixels[index * 4 + 3] = 255; });
        source.getContext("2d").putImageData(new ImageData(pixels, candidate.width, candidate.height), 0, 0);
        canvas.height = 64;
        canvas.width = Math.max(1, Math.floor(candidate.width * 64 / candidate.height));
        if (canvas.width > 1600) continue;
        context.imageSmoothingEnabled = true;
        context.imageSmoothingQuality = "high";
        context.drawImage(source, 0, 0, canvas.width, 64);
        const resized = context.getImageData(0, 0, canvas.width, 64).data;
        const input = Float32Array.from({length: canvas.width * 64}, (_, index) => resized[index * 4] / 255);
        const output = await session.run({[session.inputNames[0]]: new ort.Tensor("float32", input, [1, 1, 64, canvas.width])});
        values.push(NetSurfOcrCore.decode(output[session.outputNames[0]], charset));
      }
      return NetSurfOcrCore.consensus(values);
    } finally { bitmap.close(); }
  }

  chrome.runtime.onMessage.addListener((message, sender, respond) => {
    if (message.type !== "netsurf-ocr-infer" || sender.id !== chrome.runtime.id || sender.tab || sender.url && sender.url !== chrome.runtime.getURL("background.js")) return;
    if (busy) { respond({error: "busy"}); return; }
    busy = true;
    recognize(message.image).then(answer => respond({answer})).catch(() => respond({error: "inference_failed"})).finally(() => { busy = false; });
    return true;
  });
})();
