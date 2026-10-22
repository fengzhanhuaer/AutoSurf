(function (root) {
  function candidates({width, height, data}) {
    if (!Number.isInteger(width) || !Number.isInteger(height) || width < 8 || height < 8 || width > 800 || height > 300 || width * height > 120000 || data.length !== width * height * 4) throw new Error("invalid_image");
    const croppedWidth = width - 4;
    const croppedHeight = height - 4;
    const dark = new Uint8Array(croppedWidth * croppedHeight);
    const gray = new Uint8Array(dark.length);
    for (let row = 0; row < croppedHeight; row += 1) {
      for (let column = 0; column < croppedWidth; column += 1) {
        const offset = ((row + 2) * width + column + 2) * 4;
        const position = row * croppedWidth + column;
        const alpha = data[offset + 3] / 255;
        const red = data[offset] * alpha + 255 * (1 - alpha);
        const green = data[offset + 1] * alpha + 255 * (1 - alpha);
        const blue = data[offset + 2] * alpha + 255 * (1 - alpha);
        dark[position] = Math.max(red, green, blue) < 40 ? 1 : 0;
        gray[position] = Math.round(red * 0.299 + green * 0.587 + blue * 0.114);
      }
    }
    const retained = new Uint8Array(dark.length);
    const queue = new Int32Array(dark.length);
    for (let position = 0; position < dark.length; position += 1) {
      if (!dark[position]) continue;
      let count = 1;
      queue[0] = position;
      dark[position] = 0;
      for (let head = 0; head < count; head += 1) {
        const current = queue[head];
        const row = Math.floor(current / croppedWidth);
        const column = current % croppedWidth;
        for (let vertical = -1; vertical <= 1; vertical += 1) {
          for (let horizontal = -1; horizontal <= 1; horizontal += 1) {
            const nextRow = row + vertical;
            const nextColumn = column + horizontal;
            const next = nextRow * croppedWidth + nextColumn;
            if (nextRow < 0 || nextRow >= croppedHeight || nextColumn < 0 || nextColumn >= croppedWidth || !dark[next]) continue;
            dark[next] = 0;
            queue[count++] = next;
          }
        }
      }
      if (count >= 2) for (let index = 0; index < count; index += 1) retained[queue[index]] = 1;
    }
    const prepared = [];
    let top = croppedHeight;
    let bottom = -1;
    let left = croppedWidth;
    let right = -1;
    for (let position = 0; position < retained.length; position += 1) {
      if (!retained[position]) continue;
      const row = Math.floor(position / croppedWidth);
      const column = position % croppedWidth;
      top = Math.min(top, row);
      bottom = Math.max(bottom, row);
      left = Math.min(left, column);
      right = Math.max(right, column);
    }
    if (bottom >= 0) {
      top = Math.max(0, top - 3);
      bottom = Math.min(croppedHeight - 1, bottom + 3);
      left = Math.max(0, left - 3);
      right = Math.min(croppedWidth - 1, right + 3);
      const preparedWidth = right - left + 1;
      const preparedHeight = bottom - top + 1;
      const pixels = new Uint8Array(preparedWidth * preparedHeight);
      for (let row = 0; row < preparedHeight; row += 1) {
        for (let column = 0; column < preparedWidth; column += 1) pixels[row * preparedWidth + column] = retained[(row + top) * croppedWidth + column + left] ? 0 : 255;
      }
      prepared.push({width: preparedWidth, height: preparedHeight, pixels});
    }
    for (const threshold of [80, 160]) prepared.push({width: croppedWidth, height: croppedHeight, pixels: gray.map(value => value > threshold ? 255 : 0)});
    return prepared;
  }

  function decode(output, charset) {
    const {dims, data} = output;
    const indices = [];
    if (dims.length === 3 && (dims[0] === 1 || dims[1] === 1) && dims[2] === charset.length) {
      for (let offset = 0; offset < data.length; offset += charset.length) {
        let best = 0;
        for (let index = 1; index < charset.length; index += 1) if (data[offset + index] > data[offset + best]) best = index;
        indices.push(best);
      }
    } else if (dims.length === 2 && dims[0] === 1) {
      for (const value of data) {
        if (!Number.isInteger(Number(value)) || value < 0 || value >= charset.length) throw new Error("invalid_output");
        indices.push(Number(value));
      }
    } else throw new Error("invalid_output");
    let previous = -1;
    let value = "";
    for (const index of indices) {
      if (index !== previous && index !== 0) value += charset[index];
      previous = index;
    }
    return value.trim().toUpperCase();
  }

  function consensus(values) {
    const counts = new Map();
    for (const value of values) if (/^[A-Z0-9]{6}$/.test(value || "")) counts.set(value, (counts.get(value) || 0) + 1);
    return [...counts].find(([, count]) => count >= 2)?.[0] || null;
  }

  const api = {candidates, decode, consensus};
  root.NetSurfOcrCore = api;
  if (typeof module !== "undefined") module.exports = api;
})(globalThis);
