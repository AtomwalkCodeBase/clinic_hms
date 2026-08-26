// Chrome/Edge block navigating a top-level tab directly to a `data:` URL
// (blocked since ~2018 as an anti-phishing measure — the tab opens blank
// with a console error: "Not allowed to navigate top frame to data URL").
// Every "View" action in this app loads a file as a base64 data URI from
// the API, so we convert it to a Blob URL first — blob: URLs are exempt
// from that restriction and open normally.

/**
 * Converts a base64 "data:<mime>;base64,<data>" URI into a Blob.
 */
export function dataUrlToBlob(dataUrl) {
  const [header, base64] = dataUrl.split(",");
  const mimeMatch = header.match(/data:(.*?);base64/);
  const mime = mimeMatch ? mimeMatch[1] : "application/octet-stream";
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return new Blob([bytes], { type: mime });
}

/**
 * Opens a file — either a base64 data URI or a real (signed S3) URL — in an
 * already-open browser tab/window.
 *
 * Most upload/document endpoints (lab reports, vaccination certificates,
 * patient documents, photos, signatures, logos) now return a short-lived
 * signed S3 URL instead of the raw base64 payload — see core/storage.py on
 * the backend. A handful of endpoints that generate a file on the fly and
 * never persist it (e.g. invoice PDF receipts) still return a plain "data:"
 * URI. Both shapes land here, so this checks which one it got: a real URL
 * is opened directly (no CORS issue navigating a tab cross-origin — that's
 * different from fetching it via JS); a data URI still goes through the
 * blob-conversion path, since Chrome/Edge block navigating a top-level tab
 * straight to a "data:" URL.
 *
 * Pass the `win` reference from a synchronous `window.open()` call made
 * directly inside the click handler (before any `await`) so the popup
 * isn't blocked; this function then points that tab at the file once it's
 * available.
 */
export function openDataUrlInNewTab(win, dataUrl) {
  if (!win) return null;
  if (!dataUrl) {
    win.close();
    return null;
  }
  if (!dataUrl.startsWith("data:")) {
    // Already a real URL (signed S3 link, or any other http(s) URL) — no
    // blob conversion needed, just navigate the already-open tab to it.
    win.location.href = dataUrl;
    return dataUrl;
  }
  try {
    const blobUrl = URL.createObjectURL(dataUrlToBlob(dataUrl));
    win.location.href = blobUrl;
    // Give the tab time to load the blob before releasing it.
    setTimeout(() => URL.revokeObjectURL(blobUrl), 60_000);
    return blobUrl;
  } catch (err) {
    console.error("Failed to open file:", err);
    win.close();
    return null;
  }
}
