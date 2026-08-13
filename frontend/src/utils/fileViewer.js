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
 * Opens a base64 data URI in an already-open browser tab/window.
 *
 * Pass the `win` reference from a synchronous `window.open()` call made
 * directly inside the click handler (before any `await`) so the popup
 * isn't blocked; this function then points that tab at a blob: URL once
 * the file data is available.
 */
export function openDataUrlInNewTab(win, dataUrl) {
  if (!win) return null;
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
