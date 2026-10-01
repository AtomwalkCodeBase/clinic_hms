export function fileToDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload  = () => resolve(reader.result);
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

/** Split `items` ({size}) into consecutive groups of at most maxFiles files and maxBytes bytes, in order. */
export function chunkBySize(items, maxFiles, maxBytes) {
  const chunks = [];
  let cur = [], curBytes = 0;
  for (const it of items) {
    if (cur.length && (cur.length >= maxFiles || curBytes + it.size > maxBytes)) { chunks.push(cur); cur = []; curBytes = 0; }
    cur.push(it);
    curBytes += it.size;
  }
  if (cur.length) chunks.push(cur);
  return chunks;
}
