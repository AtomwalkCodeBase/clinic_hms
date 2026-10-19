// Chrome/Edge block navigating a top-level tab directly to a `data:` URL

/** Converts a base64 "data:<mime>;base64,<data>" URI into a Blob. */
export function dataUrlToBlob(dataUrl) {
  const [header, base64] = dataUrl.split(",");
  const mimeMatch = header.match(/data:(.*?);base64/);
  const mime = mimeMatch ? mimeMatch[1] : "application/octet-stream";
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return new Blob([bytes], { type: mime });
}

/** Opens a file — either a base64 data URI or a real (signed S3) URL — in an */
export function openDataUrlInNewTab(win, dataUrl) {
  if (!win) return null;
  if (!dataUrl) {
    win.close();
    return null;
  }
  if (!dataUrl.startsWith("data:")) {
    // Already a real URL (signed S3 link, or any other http(s) URL) — no
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

/** Force a "Save As" download rather than opening the file inline — the */
export function downloadFile(fileData, fileName = "download") {
  if (!fileData) return;
  const name = (fileName || "download").replace(/[\\/:*?"<>|]+/g, "_");
  const a = document.createElement("a");
  a.style.display = "none";
  a.download = name;

  if (fileData.startsWith("data:")) {
    const blobUrl = URL.createObjectURL(dataUrlToBlob(fileData));
    a.href = blobUrl;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(blobUrl); a.remove(); }, 4000);
  } else {
    a.href = fileData;
    a.rel = "noopener";
    a.target = "_blank"; // fallback if the browser opens instead of saving
    document.body.appendChild(a);
    a.click();
    setTimeout(() => a.remove(), 4000);
  }
}
