export function fileToDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload  = () => resolve(reader.result);
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

// What the server accepts for an upload (apps/documents/serializers.py): checked here first so a file that will be refused
// gets a clear reason in the list instead of a failed upload.
const MB = 1024 * 1024;
export const MAX_FILE_BYTES = 5 * MB;
export const MAX_TOTAL_BYTES = 250 * MB;
export const MAX_FILES = 50;

/** A size the way a patient reads it: "7.2 MB", "300 KB". */
export function sizeText(bytes) {
  if (bytes >= MB) return `${Number((bytes / MB).toFixed(1))} MB`;
  if (bytes >= 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${bytes} bytes`;
}

/** The limits in one line, for the places that tell the patient what can be uploaded. */
export const LIMITS_LINE = `PDF, JPG or PNG · up to ${sizeText(MAX_FILE_BYTES)} per file · up to ${MAX_FILES} files (${sizeText(MAX_TOTAL_BYTES)}) at a time`;

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
