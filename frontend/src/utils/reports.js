/** Pure helpers behind the My Reports screens, so the list, the detail dialog and the banners all say the same thing. */

export const typeLabel = (t) => (t ? t.replace(/_/g, " ").replace(/^./, c => c.toUpperCase()) : "Unable to classify");
export const IN_PROGRESS = new Set(["queued", "extracting", "classifying"]);
export const PROGRESS_TEXT = { queued: "Waiting to be read…", extracting: "Reading the pages…", classifying: "Working out what it is…" };

// One report is always in exactly one of these states; the message and the actions below follow from it, so
// every screen says the same thing.
//   processing    being read       ready         filed under a type
//   unclassified  no type fit      failed        could not be read
//   duplicate     same file as one already in the reports
export function stateOf(d) {
  const s = d.processing_status;
  if (IN_PROGRESS.has(s)) return "processing";
  if (s === "failed") return "failed";
  if (s === "rejected") return "duplicate";
  return d.doc_type ? "ready" : "unclassified";
}
export const NEEDS_ATTENTION = new Set(["unclassified", "failed", "duplicate"]);

export function fmtDate(iso) {
  return iso ? new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }) : "";
}
export function closestMatch(doc) {
  return doc.best_guess ? `closest: ${typeLabel(doc.best_guess)}, ${Math.round(doc.score || 0)}% confident` : "";
}
// The one line under a report's name: what it is, or what happened to it.
export function statusLine(doc) {
  switch (stateOf(doc)) {
    case "processing": return { tone: "muted", text: PROGRESS_TEXT[doc.processing_status] };
    case "failed": return { tone: "error", text: `Couldn’t read this file${doc.error ? ` — ${doc.error}` : ""}` };
    case "duplicate": return { tone: "warn", text: `Already in your reports${doc.error ? ` — ${doc.error}` : ""}` };
    case "unclassified": return { tone: "warn", text: `Unable to classify${closestMatch(doc) ? ` (${closestMatch(doc)})` : ""}` };
    default: return { tone: "muted", text: doc.method === "staff" ? typeLabel(doc.doc_type) : `${typeLabel(doc.doc_type)} · ${Math.round(doc.score || 0)}% confident` };
  }
}

// ── what the list shows for a report ───────────────────────────────────────

/** "pdf" | "image" | "other", from the real mime type, else the file name. */
export function fileKind(doc) {
  const mime = (doc.mime_type || "").toLowerCase();
  const name = (doc.file_name || doc.title || "").toLowerCase();
  if (mime === "application/pdf" || name.endsWith(".pdf")) return "pdf";
  if (mime.startsWith("image/") || /\.(jpe?g|png)$/.test(name)) return "image";
  return "other";
}

export function formatSize(bytes) {
  if (!bytes) return "";
  if (bytes >= 1048576) return `${(bytes / 1048576).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

/** How much to trust a confidence: "good" 70+, "mid" 40–69, "low" under 40. */
export function confidenceTone(score) {
  const n = score || 0;
  return n >= 70 ? "good" : n >= 40 ? "mid" : "low";
}

/** The two chips on a row: what it is, and how sure we are (or who decided). */
export function chipsFor(doc) {
  switch (stateOf(doc)) {
    case "processing": return { type: { text: "Reading…", tone: "neutral" }, extra: null };
    case "failed": return { type: { text: "Couldn’t read", tone: "bad" }, extra: null };
    case "duplicate": return { type: { text: "Duplicate", tone: "warn" }, extra: null };
    case "unclassified":
      return { type: { text: "Unable to classify", tone: "warn" },
               extra: doc.score > 0 ? { text: `${Math.round(doc.score)}% confident`, tone: confidenceTone(doc.score) } : null };
    default: {
      const type = { text: typeLabel(doc.doc_type), tone: "type" };
      if (doc.source_tenant_id || doc.uploaded_by === "staff") return { type, extra: { text: "Issued by hospital", tone: "neutral" } };
      if (doc.method === "staff") return { type, extra: { text: "Set by you", tone: "neutral" } };
      return { type, extra: { text: `${Math.round(doc.score || 0)}% confident`, tone: confidenceTone(doc.score) } };
    }
  }
}

export const SORTS = [
  ["newest", "Date (newest first)"], ["oldest", "Date (oldest first)"], ["name", "Name (A–Z)"], ["size", "Size (largest first)"],
];
export function sortReports(docs, key) {
  const by = {
    newest: (a, b) => String(b.created_at).localeCompare(String(a.created_at)) || b.id - a.id,
    oldest: (a, b) => String(a.created_at).localeCompare(String(b.created_at)) || a.id - b.id,
    name: (a, b) => (a.title || "").localeCompare(b.title || "", undefined, { sensitivity: "base" }),
    size: (a, b) => (b.size || 0) - (a.size || 0),
  };
  return [...docs].sort(by[key] || by.newest);
}

/** File name, type, the closest guess, or a state word ("duplicate", "failed"). */
export function matchesSearch(doc, query) {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  const words = [doc.title, doc.file_name, doc.hospital_label, doc.doctor_label, doc.public_document_id,
    doc.doc_type && typeLabel(doc.doc_type), doc.best_guess && typeLabel(doc.best_guess), stateOf(doc)];
  return words.filter(Boolean).join(" ").toLowerCase().includes(q);
}
