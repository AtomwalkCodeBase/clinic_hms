/**
 * pages/patient/MyReportsPage.jsx
 * -------------------------------
 * One place for every prescription and lab report. Uploads are classified
 * automatically on the server (QR / page text) — the patient never picks a
 * type. Anything the classifier is unsure about lands in the Unsorted tray
 * for a one-tap confirmation.
 *
 * Backend: apps/patients/portal_views.py
 *   GET/POST  /portal/documents/         list (metadata) + single upload
 *   GET/PATCH/DELETE /portal/documents/<id>/   view file / re-categorise / hide|delete
 *   POST      /portal/documents/zip/     bundle selected
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  FileText, Pill, FlaskConical, HelpCircle, ShieldCheck, X, Download,
  Tag, Trash2, PenLine, Camera, QrCode, Upload, FolderUp, Plus, Search, CheckSquare, SlidersHorizontal,
  Lock, Unlock, Clock,
} from "lucide-react";
import { Link } from "react-router-dom";
import { AppShell } from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import { usePaginatedList } from "../../hooks/usePaginatedList";
import { useToast } from "../../hooks/useToast";
import apiClient from "../../services/api.client";
import API_ENDPOINTS from "../../config/api.config";
import ROUTES from "../../config/routes.config";
import { usePatientContext } from "../../context/PatientContext";
import { openDataUrlInNewTab } from "../../utils/fileViewer";

const MAX_FILE_BYTES = 11 * 1024 * 1024; // matches the backend's single-upload guard (a modern phone photo runs ~8-11 MB)
const OK_EXT = /\.(pdf|jpe?g|png)$/i;
// Folder upload uses the OS "pick a directory" dialog, which happily lets you
// choose a whole drive. These bound what the modal will actually take on:
// past HARD_PICK_LIMIT it's a drive, not a reports folder; the others cap one
// Add session so the browser isn't asked to base64 hundreds of MB in a loop.
const HARD_PICK_LIMIT = 1500;
const MAX_UPLOAD_FILES = 200;
const MAX_TOTAL_BYTES = 200 * 1024 * 1024;

const TYPE_META = {
  prescription: { tag: "RX", label: "Prescription", Icon: Pill },
  lab_report:   { tag: "LAB", label: "Lab report", Icon: FlaskConical },
  scan:         { tag: "SCAN", label: "Scan", Icon: FileText },
  discharge_summary: { tag: "DISCH", label: "Discharge summary", Icon: FileText },
  other:        { tag: "DOC", label: "Document", Icon: FileText },
};

// Lab-report panel slugs -> label. Mirrors core/report_types.py; kept short
// here because the row only ever shows the label the server already chose.
const CATEGORY_LABELS = {
  cbc: "Complete Blood Count", lipid: "Lipid Profile", lft: "Liver Function Test",
  kft: "Kidney Function Test", thyroid: "Thyroid Profile", diabetes: "Blood Sugar & HbA1c",
  urine: "Urine Routine", electrolytes: "Serum Electrolytes", vitamin: "Vitamin & Mineral",
  inflammation: "Inflammatory Markers", cardiac: "Cardiac Markers", coagulation: "Coagulation Profile",
  hormone: "Hormone Panel", infection: "Infection Serology", culture: "Culture & Sensitivity",
};
const CATEGORY_ORDER = Object.keys(CATEGORY_LABELS);
const catLabel = (slug) => CATEGORY_LABELS[slug] || slug;

// Which folder(s) a document belongs in on the category-grouped Reports view.
// A lab report goes under each of its panels; a health-package under all of
// them. Everything else gets a single non-panel bucket.
const NONPANEL = { prescription: "Prescriptions", scan: "Imaging", discharge_summary: "Discharge summaries", other: "Other" };
function sectionsFor(doc) {
  if (doc.doc_type === "lab_report") {
    const cats = (doc.report_categories || []).filter((c) => CATEGORY_LABELS[c]);
    return cats.length ? cats.map((c) => ({ key: `cat:${c}`, label: catLabel(c) })) : [{ key: "cat:_lab", label: "Other lab reports" }];
  }
  const b = NONPANEL[doc.doc_type] || "Other";
  return [{ key: `t:${doc.doc_type}`, label: b }];
}
const SECTION_RANK = (key) => {
  if (key.startsWith("cat:")) {
    const s = key.slice(4);
    const i = CATEGORY_ORDER.indexOf(s);
    return i === -1 ? 90 : i;                       // panels first, in catalogue order
  }
  return { "t:prescription": 100, "t:scan": 110, "t:discharge_summary": 120, "t:other": 130 }[key] ?? 95;
};

function isMobile() {
  try {
    if (/Android|iPhone|iPod|iPad|Mobile|Opera Mini/i.test(navigator.userAgent || "")) return true;
    return window.matchMedia("(pointer: coarse)").matches && window.matchMedia("(max-width: 860px)").matches;
  } catch { return false; }
}

function fileToDataUrl(file) {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(r.result);
    r.onerror = reject;
    r.readAsDataURL(file);
  });
}

async function tryDecodeQR(file) {
  try {
    if (!("BarcodeDetector" in window)) return "";
    const det = new window.BarcodeDetector({ formats: ["qr_code"] });
    const bmp = await createImageBitmap(file);
    const codes = await det.detect(bmp);
    return codes?.[0]?.rawValue || "";
  } catch { return ""; }
}

function fmtDate(iso) {
  if (!iso) return "";
  return new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}
function fmtShort(iso) {
  if (!iso) return "";
  return new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}
function monthOf(iso) {
  const d = new Date(iso);
  if (isNaN(d)) return { key: "0000-00", label: "—" };
  return {
    key: `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`,
    label: d.toLocaleDateString("en-IN", { month: "long", year: "numeric" }),
  };
}
function inRange(iso, from, to) {
  if (!from && !to) return true;
  const d = new Date(iso);
  if (isNaN(d)) return true;
  const day = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  if (from && day < from) return false;
  if (to && day > to) return false;
  return true;
}
const ymKey = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
function ymLabel(key) {
  const [y, m] = key.split("-").map(Number);
  return new Date(y, m - 1, 1).toLocaleDateString("en-IN", { month: "long", year: "numeric" });
}
function ymShort(key) {
  const [y, m] = key.split("-").map(Number);
  return new Date(y, m - 1, 1).toLocaleDateString("en-IN", { month: "short", year: "numeric" });
}
const lastCompletedMonthKey = () => {
  const n = new Date();
  return ymKey(new Date(n.getFullYear(), n.getMonth() - 1, 1));
};
// Every month from the newest report (or this month, whichever is later) back
// to the oldest report — so the picker is a continuous list, gaps and all.
function monthOptions(docs) {
  const keys = docs
    .filter(d => d.review_state !== "unsorted")
    .map(d => { const dt = new Date(d.document_date || d.created_at); return isNaN(dt) ? null : ymKey(dt); })
    .filter(Boolean);
  const nowK = ymKey(new Date());
  const newest = keys.reduce((a, b) => (a > b ? a : b), nowK);
  const oldest = keys.reduce((a, b) => (a < b ? a : b), nowK);
  const [oy, om] = oldest.split("-").map(Number);
  let [y, m] = newest.split("-").map(Number);
  const has = new Set(keys);
  const out = [];
  for (let i = 0; i < 60; i++) {
    const k = `${y}-${String(m).padStart(2, "0")}`;
    out.push({ key: k, label: ymLabel(k), has: has.has(k) });
    if (y < oy || (y === oy && m <= om)) break;
    m -= 1; if (m === 0) { m = 12; y -= 1; }
  }
  return out;
}

/* ─────────────────────────────────────────────────────────── one row */
function DocRow({ doc, picking, selected, onToggle, onOpen, showCat, priv, onLock }) {
  const m = TYPE_META[doc.doc_type] || TYPE_META.other;
  const unsorted = doc.review_state === "unsorted";
  const rxWithDr = doc.doc_type === "prescription" && doc.doctor_label;
  const cats = doc.doc_type === "lab_report" ? (doc.report_categories || []).filter((c) => CATEGORY_LABELS[c]) : [];
  const sub = unsorted
    ? "Not yet filed — tell us what this is"
    : (showCat && cats.length)
      ? cats.map(catLabel).join(" · ")
      : rxWithDr
        ? (doc.hospital_label || "Issued by your hospital")
        : [doc.doctor_label, doc.hospital_label].filter(Boolean).join(" · ")
          || (doc.uploaded_by === "staff" ? "Issued by your hospital" : "Uploaded by you");

  return (
    <div
      className="card"
      style={{
        padding: "12px 14px", marginBottom: 8, cursor: picking || unsorted ? "default" : "pointer",
        borderLeft: selected ? "3px solid var(--color-primary)" : "3px solid transparent",
        background: selected ? "var(--color-primary-light)" : undefined,
      }}
      onClick={() => { if (picking) onToggle(); else if (!unsorted) onOpen(); }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        {picking && (
          <input type="checkbox" checked={selected} onChange={onToggle} onClick={e => e.stopPropagation()} />
        )}
        <m.Icon size={17} style={{ color: "var(--color-text-muted)", flexShrink: 0 }} />
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ fontWeight: 600, fontSize: 14, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
            {doc.doc_type === "prescription" && doc.doctor_label ? `Prescription · ${doc.doctor_label}` : doc.title}
          </div>
          <div style={{ fontSize: 12, color: "var(--color-text-muted)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
            {sub}
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexShrink: 0 }}>
          <span style={{
            fontSize: 10.5, fontWeight: 700, letterSpacing: ".04em", color: "var(--color-text-muted)",
            border: "1px solid var(--color-border)", borderRadius: 5, padding: "2px 6px",
          }}>{unsorted ? "REVIEW" : m.tag}</span>
          {doc.verification_status === "verified" && (
            <span style={{ display: "inline-flex", alignItems: "center", gap: 3, fontSize: 11, fontWeight: 600, color: "#166534" }}>
              <ShieldCheck size={13} /> Verified
            </span>
          )}
          <span style={{ fontFamily: "monospace", fontSize: 12, color: "var(--color-text-muted)" }}>
            {fmtShort(doc.document_date || doc.created_at)}
          </span>
          {!unsorted && priv && onLock && (() => {
            const state = priv.revealed_for_visit ? "visit" : priv.private ? "private" : "shared";
            const Icon = state === "shared" ? Unlock : Lock;
            return (
              <button
                onClick={(e) => { e.stopPropagation(); onLock(doc); }}
                title={
                  state === "visit" ? "Shown for this visit only — tap to change"
                  : state === "private" ? "Private — hidden from shared records. Tap to change."
                  : "Visible when you share records. Tap to make private."
                }
                aria-label={`Sharing privacy for ${doc.title}`}
                style={{
                  width: 30, height: 30, borderRadius: 8, display: "flex", alignItems: "center", justifyContent: "center",
                  cursor: "pointer",
                  border: `1px solid ${state === "shared" ? "var(--color-border)" : "var(--color-primary)"}`,
                  background: state === "shared" ? "transparent" : "var(--color-primary-light, rgba(21,119,74,.10))",
                  color: state === "shared" ? "var(--color-text-muted)" : "var(--color-primary)",
                }}
              >
                <Icon size={14} />
              </button>
            );
          })()}
        </div>
      </div>
      {priv && (priv.private || priv.revealed_for_visit) && (
        <div style={{ marginTop: 6, fontSize: 10, fontWeight: 700, letterSpacing: ".04em", textTransform: "uppercase", color: "var(--color-primary)", display: "inline-flex", alignItems: "center", gap: 4 }}>
          {priv.revealed_for_visit ? <><Clock size={10} /> Shown this visit</> : <><Lock size={10} /> Private{priv.private_by_rule ? " · by rule" : ""}</>}
        </div>
      )}
    </div>
  );
}

/* ────────────────────────────────────── review row (Unsorted tray) */
// One card per file the classifier couldn't file. It asks ONLY the field(s)
// that are missing — type, and for a lab report the panel and the date — and
// shows a plain "retake" for a photo it couldn't read at all. The original
// file is untouched throughout.
function ReviewRow({ doc, onFile, onRemove }) {
  const unreadable = doc.classification_method === "unreadable";
  // review_needs (when present) says precisely which field is unresolved —
  // "other" can be a real, confirmed kind (a discharge summary, say), not
  // just the placeholder for "unknown". Legacy rows with no review_needs
  // stored fall back to the old heuristic.
  const needs = doc.review_needs && doc.review_needs.length ? doc.review_needs : null;
  const kindUnknown = needs ? needs.includes("kind") || needs.includes("file") : (doc.doc_type === "other" || unreadable);
  const [kind, setKind] = useState(kindUnknown ? "" : doc.doc_type);
  const [cats, setCats] = useState((doc.report_categories || []).filter((c) => CATEGORY_LABELS[c]));
  const [dateStr, setDateStr] = useState((doc.document_date || "").slice(0, 10));
  const [busy, setBusy] = useState(false);
  const [manual, setManual] = useState(!unreadable);

  const needCat = kind === "lab_report";
  const canFile = kind && (!needCat || cats.length > 0) && dateStr;

  async function file() {
    setBusy(true);
    try {
      await onFile(doc, {
        doc_type: kind,
        ...(needCat ? { report_categories: cats } : {}),
        ...(dateStr ? { document_date: dateStr } : {}),
      });
    } finally { setBusy(false); }
  }

  return (
    <div className="card" style={{ padding: "12px 14px", marginBottom: 8, borderLeft: `3px solid var(--color-warning)` }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <HelpCircle size={17} style={{ color: "var(--color-warning)", flexShrink: 0 }} />
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ fontWeight: 600, fontSize: 14, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{doc.title}</div>
          <div style={{ fontSize: 12, color: "var(--color-text-muted)" }}>
            {unreadable
              ? (doc.review_notes || "We couldn’t read this clearly")
              : "Filed automatically — check the details below"}
          </div>
        </div>
        <span style={{ fontSize: 10.5, fontWeight: 700, letterSpacing: ".04em", color: "var(--color-warning)", border: "1px solid var(--color-border)", borderRadius: 5, padding: "2px 6px" }}>
          {unreadable ? "UNREADABLE" : "REVIEW"}
        </span>
      </div>

      {unreadable && !manual && (
        <div style={{ marginTop: 10, paddingTop: 10, borderTop: "1px dashed var(--color-border)", fontSize: 12.5, color: "var(--color-text-muted)" }}>
          Retake it in good light with the whole page flat and in frame, then upload again — or enter the details by hand.
          <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
            <button className="btn-outline" style={{ fontSize: 12, padding: "5px 12px" }} onClick={() => setManual(true)}>Enter details</button>
            <button style={{ fontSize: 12, padding: "5px 12px", background: "none", border: "1px solid var(--color-border)", borderRadius: 6, color: "var(--color-text-muted)", cursor: "pointer" }} onClick={() => onRemove(doc)}>Remove</button>
          </div>
        </div>
      )}

      {manual && (
        <div style={{ marginTop: 10, paddingTop: 10, borderTop: "1px dashed var(--color-border)", display: "flex", flexDirection: "column", gap: 10 }}>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
            <span style={{ fontSize: 12, color: "var(--color-text-muted)", width: 70 }}>Type</span>
            {[["prescription", "Prescription"], ["lab_report", "Lab report"], ["scan", "Imaging"], ["other", "Other"]].map(([v, l]) => (
              <button key={v} onClick={() => setKind(v)} className={kind === v ? "btn-primary" : "btn-outline"}
                style={{ fontSize: 12, padding: "4px 11px" }}>{l}</button>
            ))}
          </div>
          {needCat && (
            <label style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 12, color: "var(--color-text-muted)" }}>
              <span style={{ width: 70 }}>Panel</span>
              <select className="form-input" style={{ padding: "6px 10px", maxWidth: 260 }}
                value={cats[0] || ""} onChange={e => setCats(e.target.value ? [e.target.value] : [])}>
                <option value="">Choose a panel…</option>
                {CATEGORY_ORDER.map(s => <option key={s} value={s}>{CATEGORY_LABELS[s]}</option>)}
              </select>
            </label>
          )}
          <label style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 12, color: "var(--color-text-muted)" }}>
            <span style={{ width: 70 }}>Date</span>
            <input type="date" className="form-input" style={{ padding: "6px 10px", maxWidth: 200 }}
              max={new Date().toISOString().slice(0, 10)}
              value={dateStr} onChange={e => setDateStr(e.target.value)} />
          </label>
          <div style={{ display: "flex", gap: 8 }}>
            <button className="btn-primary" style={{ fontSize: 12.5, padding: "6px 14px" }} disabled={!canFile || busy} onClick={file}>
              {busy ? "Filing…" : "File it"}
            </button>
            <button style={{ fontSize: 12, padding: "6px 12px", background: "none", border: "1px solid var(--color-border)", borderRadius: 6, color: "var(--color-text-muted)", cursor: "pointer" }} onClick={() => onRemove(doc)}>Not medical — remove</button>
          </div>
        </div>
      )}
    </div>
  );
}

/* ─────────────────────────────────────────────────────────── detail modal */
function DetailModal({ doc, onClose, onChanged }) {
  const { toastSuccess, toastApiError } = useToast();
  const [busy, setBusy] = useState(false);
  const [recat, setRecat] = useState(false);
  const m = TYPE_META[doc.doc_type] || TYPE_META.other;
  const hospital = !!doc.source_tenant_id || doc.uploaded_by === "staff";

  async function view(download, docId = doc.id) {
    const win = window.open("", "_blank");
    try {
      const res = await apiClient.get(API_ENDPOINTS.PORTAL.DOCUMENT(docId), { params: download ? { download: 1 } : {} });
      const fd = (res.data?.data || res.data)?.file_data;
      if (fd) openDataUrlInNewTab(win, fd); else win?.close();
    } catch (err) { win?.close(); toastApiError(err, "Could not open the file."); }
  }
  const hasHandwritten = !!doc.handwritten_doc_id;
  async function move(type) {
    setBusy(true);
    try {
      if (type === "__remove__") {
        await apiClient.delete(API_ENDPOINTS.PORTAL.DOCUMENT(doc.id));
        toastSuccess("Removed.");
      } else {
        await apiClient.patch(API_ENDPOINTS.PORTAL.DOCUMENT(doc.id), { doc_type: type });
        toastSuccess(`Moved to ${type === "prescription" ? "Prescriptions" : "Lab reports"}.`);
      }
      onChanged(); onClose();
    } catch (err) { toastApiError(err, "Could not update."); } finally { setBusy(false); }
  }
  async function remove() {
    setBusy(true);
    try {
      await apiClient.delete(API_ENDPOINTS.PORTAL.DOCUMENT(doc.id));
      toastSuccess("Deleted from your reports.");
      onChanged(); onClose();
    } catch (err) { toastApiError(err, "Could not remove."); } finally { setBusy(false); }
  }

  const rows = [
    ["Type", m.label],
    ["Document date", fmtDate(doc.document_date) || "—"],
    ["Doctor", doc.doctor_label || "—"],
    ["Hospital / lab", doc.hospital_label || (hospital ? "Your hospital" : "—")],
    ["Source", hospital ? "Issued by hospital" : "Uploaded by you"],
    ["Document ID", doc.public_document_id || "—"],
    ["Added on", fmtDate(doc.created_at)],
    ["Status", doc.verification_status === "verified" ? "Verified · QR authenticated" : "Not verified"],
  ];

  return (
    <div className="modal-backdrop" style={backdrop} onClick={onClose}>
      <div className="card" style={sheet} onClick={e => e.stopPropagation()}>
        <div style={{ display: "flex", alignItems: "flex-start", gap: 12, marginBottom: 14 }}>
          <div style={{ flex: 1, fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 16 }}>
            {doc.doc_type === "prescription" && doc.doctor_label ? `Prescription · ${doc.doctor_label}` : doc.title}
          </div>
          <button onClick={onClose} style={iconBtn}><X size={18} /></button>
        </div>

        <div style={{ display: "grid", gap: 0, marginBottom: 16 }}>
          {rows.map(([k, v]) => (
            <div key={k} style={{ display: "grid", gridTemplateColumns: "130px 1fr", gap: 12, padding: "9px 0", borderTop: "1px solid var(--color-border)", fontSize: 13 }}>
              <span style={{ color: "var(--color-text-muted)" }}>{k}</span>
              <span style={{ fontWeight: 500 }}>{v}</span>
            </div>
          ))}
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <div style={{ display: "flex", gap: 8 }}>
            <button className="btn-primary" style={{ flex: 1 }} onClick={() => view(false)}>
              <Download size={15} /> {hasHandwritten ? "View / Download prescription" : "View / Download"}
            </button>
            {doc.verification_status !== "verified" && (
              <button className="btn-outline" style={{ flex: 1 }} disabled={busy} onClick={() => setRecat(v => !v)}><Tag size={15} /> Re-categorise</button>
            )}
          </div>
          {hasHandwritten && (
            <button className="btn-outline" onClick={() => view(false, doc.handwritten_doc_id)}>
              <PenLine size={15} /> View / Download handwritten
            </button>
          )}
          {recat && (
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", padding: 10, background: "var(--color-bg)", borderRadius: 8 }}>
              <span style={{ width: "100%", fontSize: 12, color: "var(--color-text-muted)" }}>Move to</span>
              <button className="btn-outline" style={{ fontSize: 12, padding: "4px 10px" }} disabled={busy} onClick={() => move("prescription")}>Prescription</button>
              <button className="btn-outline" style={{ fontSize: 12, padding: "4px 10px" }} disabled={busy} onClick={() => move("lab_report")}>Lab report</button>
            </div>
          )}
          <button className="btn-outline" style={{ color: "var(--color-danger)", borderColor: "var(--color-danger)" }} disabled={busy} onClick={remove}>
            <Trash2 size={15} /> Delete from my reports
          </button>
          {hospital && (
            <div style={{ fontSize: 11, color: "var(--color-text-muted)" }}>
              Your hospital keeps its own copy for its records. This removes it from your reports and from other hospitals that could otherwise see it.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────── add flow */
// Walk a dropped FileSystemEntry (file or directory, any depth) into a flat
// File[]. Lets one "Upload" drop take a single file, many files, a folder,
// or several folders at once — the browser can't do that through one <input>.
function readEntry(entry, out) {
  return new Promise((resolve) => {
    if (entry.isFile) {
      entry.file((f) => { out.push(f); resolve(); }, () => resolve());
    } else if (entry.isDirectory) {
      const reader = entry.createReader();
      const batch = () => reader.readEntries(async (entries) => {
        if (!entries.length) return resolve();
        await Promise.all(entries.map((e) => readEntry(e, out)));
        batch();
      }, () => resolve());
      batch();
    } else resolve();
  });
}
async function filesFromDrop(dt) {
  const entries = Array.from(dt.items || [])
    .map((it) => (it.webkitGetAsEntry ? it.webkitGetAsEntry() : null))
    .filter(Boolean);
  if (!entries.length) return Array.from(dt.files || []);
  const out = [];
  await Promise.all(entries.map((e) => readEntry(e, out)));
  return out;
}

function AddModal({ onClose, onDone, patientAwpid }) {
  const { toastError } = useToast();
  const [phase, setPhase] = useState("pick");        // pick | choose | stage | upload | done
  const [items, setItems] = useState([]);            // {file, name, size, skip}
  const [prog, setProg] = useState({ done: 0, total: 0, name: "" });
  const [result, setResult] = useState({ rx: 0, lab: 0, unsorted: 0, dup: 0, failed: 0, notMedical: 0, files: [] });
  const [dragOver, setDragOver] = useState(false);
  const filesRef = useRef(null);
  const folderRef = useRef(null);
  const camRef = useRef(null);
  const mob = isMobile();

  async function onDrop(e) {
    e.preventDefault();
    setDragOver(false);
    const files = await filesFromDrop(e.dataTransfer);
    stage(files);
  }

  function stage(fileList) {
    const incoming = Array.from(fileList || []);
    if (!incoming.length) return;

    // Picking a whole drive (or a huge tree) dumps tens of thousands of files
    // here — reject it before doing any per-file work.
    if (incoming.length > HARD_PICK_LIMIT) {
      toastError(`That selection has ${incoming.length.toLocaleString()} files — that's an entire drive, not a reports folder. Pick the folder that actually holds your prescriptions and reports.`);
      return;
    }

    const arr = incoming.map(f => {
      const badType = !(OK_EXT.test(f.name || "") || /^image\/(jpeg|png)$|^application\/pdf$/.test(f.type));
      const tooBig = f.size > MAX_FILE_BYTES;
      return {
        file: f, name: f.name || "photo.jpg", size: f.size,
        skip: badType || tooBig,
        reason: badType ? "not a PDF/image" : tooBig ? "over 11 MB" : "",
      };
    });

    const keptSoFar = items.filter(i => !i.skip);
    const newKept = arr.filter(a => !a.skip);
    if (!newKept.length) {
      toastError("None of those are PDFs or images under 11 MB.");
      return;
    }
    if (keptSoFar.length + newKept.length > MAX_UPLOAD_FILES) {
      toastError(`Up to ${MAX_UPLOAD_FILES} reports at a time — this selection has ${keptSoFar.length + newKept.length}. Choose a smaller folder, or add them in batches.`);
      return;
    }
    const totalBytes = [...keptSoFar, ...newKept].reduce((s, i) => s + (i.size || 0), 0);
    if (totalBytes > MAX_TOTAL_BYTES) {
      toastError(`That's ${Math.round(totalBytes / 1024 / 1024)} MB at once — keep it under ${MAX_TOTAL_BYTES / 1024 / 1024} MB and add the rest afterwards.`);
      return;
    }

    setItems(prev => [...prev, ...arr]);
    setPhase("stage");
  }

  async function run() {
    const ready = items.filter(i => !i.skip);
    const preSkipped = items.filter(i => i.skip);
    if (!ready.length && !preSkipped.length) { toastError("Nothing to upload."); return; }
    setPhase("upload");
    const r = { rx: 0, lab: 0, unsorted: 0, dup: 0, failed: 0, notMedical: 0, files: [] };

    for (const it of preSkipped) {
      r.failed++;
      r.files.push({ name: it.name, outcome: "failed", reason: `not uploaded — ${it.reason || "not a PDF/image under 11 MB"}` });
    }

    for (let i = 0; i < ready.length; i++) {
      const it = ready[i];
      setProg({ done: i, total: ready.length, name: it.name });
      try {
        if (it.size > MAX_FILE_BYTES) {
          r.failed++;
          r.files.push({ name: it.name, outcome: "failed", reason: "over 11 MB" });
          continue;
        }
        const dataUrl = await fileToDataUrl(it.file);
        const qr = it.file.type.startsWith("image/") ? await tryDecodeQR(it.file) : "";
        const res = await apiClient.post(API_ENDPOINTS.PORTAL.DOCUMENTS, {
          title: it.name.replace(OK_EXT, ""),
          file_data: dataUrl, file_name: it.name, mime_type: it.file.type || "application/pdf",
          ...(qr ? { qr_token: qr } : {}),
          ...(patientAwpid ? { patient_awpid: patientAwpid } : {}),
        });
        const d = res.data?.data || res.data;
        if (res.status === 200 && d?.duplicate) {
          r.dup++;
          r.files.push({ name: it.name, outcome: "duplicate", reason: "already in your reports" });
        } else if (res.status === 200 && d?.skipped) {
          r.notMedical++;
          r.files.push({ name: it.name, outcome: "not_medical", reason: "not a medical document — not saved" });
        } else if (d?.unreadable) {
          r.unsorted++;
          r.files.push({ name: it.name, outcome: "unreadable", reason: (d.quality_message || "we couldn't read it clearly").replace(/\s+/g, " ").trim() });
        } else if (d?.review_state === "unsorted") {
          r.unsorted++;
          r.files.push({ name: it.name, outcome: "review", reason: "in the Review tab — needs a quick check" });
        } else if (d?.doc_type === "prescription") {
          r.rx++;
          r.files.push({ name: it.name, outcome: "filed", reason: "filed as Prescription" });
        } else if (d?.doc_type === "lab_report") {
          r.lab++;
          r.files.push({ name: it.name, outcome: "filed", reason: "filed as Lab report" });
        } else {
          r.unsorted++;
          r.files.push({ name: it.name, outcome: "review", reason: "in the Review tab" });
        }
      } catch (e) {
        r.failed++;
        r.files.push({ name: it.name, outcome: "failed", reason: (e?.response?.data?.message || "upload failed — try again").slice(0, 120) });
      }
    }
    setProg({ done: ready.length, total: ready.length, name: "" });
    setResult(r);
    setPhase("done");
  }

  const ready = items.filter(i => !i.skip);
  const skipped = items.length - ready.length;

  return (
    <div style={backdrop} onClick={phase === "upload" ? undefined : onClose}>
      <div className="card" style={sheet} onClick={e => e.stopPropagation()}>
        <input ref={filesRef} type="file" accept=".pdf,image/*" multiple hidden onChange={e => stage(e.target.files)} />
        <input ref={folderRef} type="file" hidden webkitdirectory="" directory="" multiple onChange={e => stage(e.target.files)} />
        <input ref={camRef} type="file" accept="image/*" capture="environment" hidden onChange={e => stage(e.target.files)} />

        {phase === "pick" && (
          <>
            <h3 style={h3}>Add to My Reports</h3>
            <p style={sub}>We read the QR or the page text and file each one for you.</p>
            {mob && (
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginTop: 6 }}>
                <Method Icon={QrCode} title="Scan QR" desc="Point at the code on a hospital document" onClick={() => camRef.current?.click()} />
                <Method Icon={Camera} title="Take photo" desc="Capture a printed document" onClick={() => camRef.current?.click()} />
              </div>
            )}
            <div style={{ marginTop: 10 }}>
              <Method Icon={Upload} title="Upload"
                desc="PDFs or images — one file, many, or whole folders"
                onClick={() => (mob ? filesRef.current?.click() : setPhase("choose"))} />
            </div>
          </>
        )}

        {phase === "choose" && (
          <>
            <h3 style={h3}>Upload to My Reports</h3>
            <p style={sub}>Select the files or folders you want to upload — we keep the reports and skip the rest.</p>
            <div
              onDragOver={e => { e.preventDefault(); setDragOver(true); }}
              onDragLeave={() => setDragOver(false)}
              onDrop={onDrop}
              onClick={() => filesRef.current?.click()}
              style={{
                marginTop: 8, border: `2px dashed ${dragOver ? "var(--color-primary)" : "var(--color-border)"}`,
                borderRadius: 12, padding: "34px 16px", textAlign: "center", cursor: "pointer",
                background: dragOver ? "var(--color-primary-light, #f0fdf4)" : "var(--color-bg)",
              }}
            >
              <FolderUp size={26} style={{ color: "var(--color-text-muted)", marginBottom: 8 }} />
              <div style={{ fontSize: 14, fontWeight: 600 }}>Drop files &amp; folders here</div>
              <div style={{ fontSize: 12.5, color: "var(--color-text-muted)", marginTop: 4 }}>
                or click to browse files
              </div>
            </div>
            <div style={{ display: "flex", gap: 8, marginTop: 12, alignItems: "center" }}>
              <button className="btn-outline" style={{ fontSize: 13 }} onClick={() => filesRef.current?.click()}>
                <Upload size={14} /> Browse files
              </button>
              <button className="btn-outline" style={{ fontSize: 13 }} onClick={() => folderRef.current?.click()}>
                <FolderUp size={14} /> Browse a folder
              </button>
              <span style={{ flex: 1 }} />
              <button className="btn-outline" style={{ fontSize: 13 }} onClick={() => setPhase("pick")}>Back</button>
            </div>
          </>
        )}

        {phase === "stage" && (
          <>
            <h3 style={h3}>Review {ready.length} file{ready.length !== 1 ? "s" : ""}</h3>
            <p style={sub}>{ready.length} ready{skipped ? ` · ${skipped} skipped (not a PDF/image, or over 11 MB)` : ""}</p>
            <div style={{ maxHeight: 300, overflowY: "auto", border: "1px solid var(--color-border)", borderRadius: 8, padding: 4, margin: "10px 0" }}>
              {items.map((it, idx) => (
                <div key={idx} style={{ display: "flex", alignItems: "center", gap: 10, padding: "7px 8px", fontSize: 12.5, opacity: it.skip ? 0.5 : 1 }}>
                  <FileText size={15} style={{ color: "var(--color-text-muted)" }} />
                  <span style={{ flex: 1, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", textDecoration: it.skip ? "line-through" : "none" }}>{it.name}</span>
                  <span style={{ color: "var(--color-text-muted)", fontSize: 11 }}>{(it.size / 1024 / 1024).toFixed(1)} MB</span>
                  {it.skip
                    ? <span style={{ fontSize: 10, color: "var(--color-text-muted)", whiteSpace: "nowrap" }}>{it.reason ? it.reason.toUpperCase() : "SKIPPED"}</span>
                    : <button onClick={() => setItems(p => p.filter((_, i) => i !== idx))} style={iconBtn}><X size={14} /></button>}
                </div>
              ))}
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              <button className="btn-outline" onClick={() => filesRef.current?.click()}><Plus size={14} /> Add more</button>
              <span style={{ flex: 1 }} />
              <button className="btn-outline" onClick={onClose}>Cancel</button>
              <button className="btn-primary" disabled={!ready.length} onClick={run}><Upload size={15} /> Upload {ready.length}</button>
            </div>
          </>
        )}

        {phase === "upload" && (
          <div style={{ padding: "24px 4px" }}>
            <h3 style={h3}>Uploading…</h3>
            <div style={{ height: 8, borderRadius: 6, background: "var(--color-border)", overflow: "hidden", margin: "16px 0 10px" }}>
              <div style={{ height: "100%", width: `${prog.total ? (prog.done / prog.total) * 100 : 0}%`, background: "var(--color-primary)", transition: "width .2s" }} />
            </div>
            <div style={{ fontSize: 12.5, color: "var(--color-text-muted)", textAlign: "center" }}>
              {prog.done} of {prog.total}{prog.name ? ` · ${prog.name}` : ""}
            </div>
          </div>
        )}

        {phase === "done" && (
          <>
            <h3 style={h3}>Upload complete</h3>
            <div style={{ display: "grid", gap: 0, margin: "10px 0" }}>
              {result.rx > 0 && <SumRow label="Prescriptions added" n={result.rx} ok />}
              {result.lab > 0 && <SumRow label="Lab reports added" n={result.lab} ok />}
              {result.unsorted > 0 && <SumRow label="Need your review" n={result.unsorted} />}
              {result.dup > 0 && <SumRow label="Already in your reports (skipped)" n={result.dup} />}
              {result.notMedical > 0 && <SumRow label="Not medical documents — not saved" n={result.notMedical} />}
              {result.failed > 0 && <SumRow label="Not uploaded (too large / unreadable / failed)" n={result.failed} />}
            </div>

            {result.files?.some(f => f.outcome !== "filed") && (
              <div style={{ marginTop: 12, borderTop: "1px solid var(--color-border)", paddingTop: 10 }}>
                <div style={{ fontSize: 10.5, fontWeight: 700, letterSpacing: ".06em", textTransform: "uppercase", color: "var(--color-text-muted)", marginBottom: 8 }}>
                  Files needing attention
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: 8, maxHeight: 230, overflowY: "auto" }}>
                  {result.files.filter(f => f.outcome !== "filed").map((f, i) => (
                    <div key={i} style={{ display: "flex", gap: 8, alignItems: "baseline", fontSize: 12, lineHeight: 1.4 }}>
                      <span style={{ ...OUTCOME_TAG, ...OUTCOME_TAG_COLOR[f.outcome] }}>{OUTCOME_LABEL[f.outcome]}</span>
                      <span style={{ minWidth: 0, flex: 1 }}>
                        <span style={{ fontFamily: "var(--font-mono, monospace)", fontSize: 11, color: "var(--color-text)", wordBreak: "break-all" }}>{f.name}</span>
                        <span style={{ color: "var(--color-text-muted)" }}> — {f.reason}</span>
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {result.unsorted > 0 && (
              <p style={sub}>The {result.unsorted} we weren’t sure about wait in the Review tab — each one asks only for what’s missing (its type, panel, or date).</p>
            )}
            <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
              <button className="btn-primary" style={{ flex: 1 }} onClick={() => { onDone(result.unsorted > 0 ? "unsorted" : "all"); }}>Done</button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function Method({ Icon, title, desc, off, onClick }) {
  return (
    <button
      onClick={off ? undefined : onClick}
      style={{
        display: "flex", flexDirection: "column", alignItems: "flex-start", gap: 6, textAlign: "left",
        padding: 14, border: "1px solid var(--color-border)", borderRadius: 11, background: "var(--color-bg)",
        cursor: off ? "default" : "pointer", opacity: off ? 0.55 : 1,
      }}
    >
      <Icon size={20} style={{ color: "var(--color-primary)" }} />
      <b style={{ fontSize: 13.5 }}>{title}{off && <span style={{ fontFamily: "monospace", fontSize: 9, marginLeft: 6, color: "var(--color-text-muted)", border: "1px solid var(--color-border)", borderRadius: 4, padding: "1px 4px" }}>MOBILE ONLY</span>}</b>
      <small style={{ color: "var(--color-text-muted)", fontSize: 11.5 }}>{desc}</small>
    </button>
  );
}
function SumRow({ label, n, ok }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "9px 0", borderTop: "1px solid var(--color-border)", fontSize: 13.5, color: ok ? "#166534" : "var(--color-text-secondary)" }}>
      {ok ? <CheckSquare size={15} /> : <HelpCircle size={15} />}
      <span style={{ flex: 1 }}>{label}</span>
      <b style={{ fontFamily: "monospace" }}>{n}</b>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────── page */
export default function MyReportsPage() {
  const { selectedPatient } = usePatientContext();
  const patientAwpid = selectedPatient?.awpid || "";
  const { toastSuccess, toastApiError, toastError } = useToast();

  const { items: docs, isLoading, hasMore, loadMore, refetch } = usePaginatedList(
    API_ENDPOINTS.PORTAL.DOCUMENTS,
    { pageSize: 50, params: patientAwpid ? { patient_awpid: patientAwpid } : {} },
  );

  // ── shared-records privacy: the per-report lock ────────────────────────
  // Only for the patient's own reports (a family member's are managed from
  // that member's own login). One map id -> {private, private_by_rule,
  // revealed_for_visit} plus the live share session, if any.
  const [privMap, setPrivMap] = useState(() => new Map());
  const [privSession, setPrivSession] = useState(null);
  const [lockDlg, setLockDlg] = useState(null);
  const privEnabled = !patientAwpid; // self only

  const loadPrivacy = useCallback(async () => {
    if (!privEnabled) return;
    try {
      const res = await apiClient.get(API_ENDPOINTS.PORTAL.RECORDS_PRIVACY);
      const d = res?.data?.data ?? res?.data ?? {};
      const map = new Map();
      (d.documents || []).forEach((x) => map.set(x.id, x));
      setPrivMap(map);
      setPrivSession(d.active_session || null);
    } catch { /* privacy is non-blocking on this screen */ }
  }, [privEnabled]);
  useEffect(() => { loadPrivacy(); }, [loadPrivacy, docs.length]);

  const privateCount = useMemo(
    () => [...privMap.values()].filter((x) => x.private && !x.revealed_for_visit).length,
    [privMap],
  );

  async function privToggle(docId, makePrivate) {
    try {
      await apiClient.post(API_ENDPOINTS.PORTAL.RECORDS_PRIVACY_TOGGLE, { doc_id: docId, private: makePrivate });
      loadPrivacy();
    } catch (err) { toastApiError(err, "Could not update."); }
  }
  async function privReveal(docId, scope) {
    if (!privSession) return;
    try {
      await apiClient.post(API_ENDPOINTS.PORTAL.RECORDS_SHARE_REVEAL(privSession.token), { doc_ids: [docId], scope });
      loadPrivacy();
    } catch (err) { toastApiError(err, "Could not update."); }
  }
  function onLock(doc) {
    const p = privMap.get(doc.id) || {};
    const name = doc.title;
    if (p.revealed_for_visit) {
      setLockDlg({ title: "Hide this again now?", message: `${name} would hide by itself when the visit ends.`,
        actions: [{ label: "Cancel" }, { label: "Hide now", primary: true, onClick: () => privReveal(doc.id, "conceal") }] });
    } else if (p.private_by_rule) {
      setLockDlg({ title: "Hidden by a rule",
        message: `${name} is hidden by a category, kind or "hide everything" rule. Change those in Shared records privacy.`,
        actions: [
          ...(privSession ? [{ label: "Just this visit", sub: "Reveal only for the doctor viewing now", primary: true, onClick: () => privReveal(doc.id, "visit") }] : []),
          { label: "Close" },
        ] });
    } else if (!p.private) {
      setLockDlg({ title: "Make this private?",
        message: `${name} won't be shown to doctors when you share your records. You'll still see it here.`,
        actions: [{ label: "Cancel" }, { label: "Make private", primary: true, onClick: () => privToggle(doc.id, true) }] });
    } else if (privSession) {
      setLockDlg({ title: "A doctor is viewing now",
        message: `Show ${name} to ${privSession.requester_label || "the doctor"} —`,
        actions: [
          { label: "Just this visit", sub: "Hides again when the visit ends", primary: true, onClick: () => privReveal(doc.id, "visit") },
          { label: "Always", sub: "Stays visible for future visits too", onClick: () => privToggle(doc.id, false) },
          { label: "Cancel" },
        ] });
    } else {
      setLockDlg({ title: "Show this to doctors again?",
        message: `Doctors you share with will be able to see ${name}.`,
        actions: [{ label: "Cancel" }, { label: "Show", primary: true, onClick: () => privToggle(doc.id, false) }] });
    }
  }

  const [tab, setTab] = useState("all");
  const [q, setQ] = useState("");
  const [picking, setPicking] = useState(false);
  const [sel, setSel] = useState(() => new Set());
  const [addOpen, setAddOpen] = useState(false);
  const [detail, setDetail] = useState(null);
  const [showFilter, setShowFilter] = useState(false);
  // Filter has three modes. "month" is the default — doctors and patients
  // both scan month-by-month first (recent months), and only drop to exact
  // dates when they need a narrow window.
  const [filterMode, setFilterMode] = useState("month");   // month | dates | all
  const [filterMonth, setFilterMonth] = useState("");        // "YYYY-MM"
  const [dFrom, setDFrom] = useState("");
  const [dTo, setDTo] = useState("");
  // Second, independent filter: which report categories to show. Empty = all.
  // Prescriptions have no category, so this control is hidden on that tab.
  const [catSel, setCatSel] = useState(() => new Set());
  const [showCatMenu, setShowCatMenu] = useState(false);

  const monthOpts = useMemo(() => monthOptions(docs), [docs]);
  // Land on the last *completed* month once reports load (clamped to a month
  // that actually has reports); if everything is in the current month, use the
  // newest option so nothing is hidden.
  useEffect(() => {
    if (filterMonth || !monthOpts.length) return;
    const lc = lastCompletedMonthKey();
    const pick = monthOpts.find(o => o.key === lc && o.has)
      || monthOpts.find(o => o.key <= lc && o.has)
      || monthOpts.find(o => o.has)
      || monthOpts[0];
    setFilterMonth(pick.key);
    // Nothing on file yet — don't greet a new patient with "No reports in September".
    if (!monthOpts.some(o => o.has)) setFilterMode("all");
  }, [monthOpts, filterMonth]);

  const dateFilterOn = !!(dFrom || dTo);
  const filtered = filterMode === "month" ? !!filterMonth
    : filterMode === "dates" ? dateFilterOn
    : false;
  const filterSummary = filterMode === "month" ? (filterMonth ? ymShort(filterMonth) : "Month")
    : filterMode === "dates" ? "Dates" : "";

  const counts = useMemo(() => {
    const c = { all: 0, prescription: 0, lab_report: 0, unsorted: 0 };
    docs.forEach(d => {
      if (d.review_state === "unsorted") c.unsorted++;
      else { c.all++; if (d.doc_type === "prescription") c.prescription++; if (d.doc_type === "lab_report") c.lab_report++; }
    });
    return c;
  }, [docs]);

  // Full transparency on WHY each row is in review — grouped by the exact
  // combination of missing fields, not one flat count. A row uploaded before
  // review_needs existed has none stored, so it falls back to the old
  // assumption (type unknown).
  const reviewSummary = useMemo(() => {
    const REASON_LABEL = {
      "file": "too blurry to read",
      "kind": "couldn't be classified",
      "kind,date": "couldn't be classified, and the date's unclear too",
      "category": "are lab reports missing their panel",
      "category,date": "are lab reports missing their panel and date",
      "date": "just need a date confirmed",
    };
    const ORDER = ["kind", "category", "date"];
    const groups = new Map();
    docs.filter(d => d.review_state === "unsorted").forEach(d => {
      const needs = (d.review_needs && d.review_needs.length) ? d.review_needs : ["kind"];
      const key = needs.includes("file") ? "file" : ORDER.filter(n => needs.includes(n)).join(",");
      groups.set(key, (groups.get(key) || 0) + 1);
    });
    return [...groups.entries()].map(([key, n]) => `${n} ${REASON_LABEL[key] || "need a quick check"}`);
  }, [docs]);

  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return docs
      .filter(d => (tab === "all" ? d.review_state !== "unsorted" : tab === "unsorted" ? d.review_state === "unsorted" : d.doc_type === tab && d.review_state !== "unsorted"))
      .filter(d => !needle || [d.title, d.hospital_label, d.doctor_label, d.public_document_id].join(" ").toLowerCase().includes(needle))
      .filter(d => {
        if (tab === "unsorted" || filterMode === "all") return true;
        const iso = d.document_date || d.created_at;
        if (filterMode === "dates") return inRange(iso, dFrom, dTo);
        const dt = new Date(iso);
        return !isNaN(dt) && ymKey(dt) === filterMonth;
      });
  }, [docs, tab, q, filterMode, filterMonth, dFrom, dTo]);

  // Prescriptions / Unsorted: a flat, date-sorted list (month sub-headers when
  // the date filter isn't already "one month").
  const monthGroups = useMemo(() => {
    const map = new Map();
    shown.forEach(d => {
      const { key, label } = monthOf(d.document_date || d.created_at);
      if (!map.has(key)) map.set(key, { label, list: [] });
      map.get(key).list.push(d);
    });
    return [...map.entries()].sort((a, b) => b[0].localeCompare(a[0])).map(([, v]) => v);
  }, [shown]);

  // Reports (All / Lab reports): grouped category by category, newest first
  // within each. A health-package lab report shows under every panel it holds.
  const catGroups = useMemo(() => {
    const map = new Map();
    shown.forEach(d => {
      sectionsFor(d).forEach(({ key, label }) => {
        if (!map.has(key)) map.set(key, { key, label, list: [] });
        map.get(key).list.push(d);
      });
    });
    let secs = [...map.values()];
    if (catSel.size) {
      secs = secs.filter(s => s.key.startsWith("cat:") && catSel.has(s.key.slice(4)));
    }
    secs.forEach(s => s.list.sort((a, b) =>
      String(b.document_date || b.created_at).localeCompare(String(a.document_date || a.created_at))));
    secs.sort((a, b) => SECTION_RANK(a.key) - SECTION_RANK(b.key));
    return secs;
  }, [shown, catSel]);

  const catMode = tab === "all" || tab === "lab_report";

  function toggleSel(id) {
    setSel(prev => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n; });
  }
  async function fileDoc(doc, patch) {
    try {
      await apiClient.patch(API_ENDPOINTS.PORTAL.DOCUMENT(doc.id), patch);
      const where = patch.doc_type === "prescription" ? "Prescriptions"
        : patch.doc_type === "lab_report" ? (patch.report_categories?.length ? catLabel(patch.report_categories[0]) : "Lab reports")
        : "your reports";
      toastSuccess(`Filed under ${where}.`);
      refetch();
    } catch (err) { toastApiError(err, "Could not file this."); }
  }
  async function removeDoc(doc) {
    try {
      await apiClient.delete(API_ENDPOINTS.PORTAL.DOCUMENT(doc.id));
      toastSuccess("Removed.");
      refetch();
    } catch (err) { toastApiError(err, "Could not remove."); }
  }
  async function downloadSelected() {
    const ids = [...sel];
    if (!ids.length) return;
    if (ids.length === 1) { setDetail(docs.find(d => d.id === ids[0])); return; }
    try {
      const res = await apiClient.post(API_ENDPOINTS.PORTAL.DOCUMENTS_ZIP, { ids, ...(patientAwpid ? { patient_awpid: patientAwpid } : {}) }, { responseType: "blob" });
      const url = URL.createObjectURL(res.data);
      const a = document.createElement("a");
      a.href = url; a.download = `my-reports-${new Date().toISOString().slice(0, 10)}.zip`;
      a.click(); URL.revokeObjectURL(url);
      setPicking(false); setSel(new Set());
    } catch { toastError("Could not build the ZIP."); }
  }

  const TABS = [
    ["all", "All", counts.all],
    ["prescription", "Prescriptions", counts.prescription],
    ["lab_report", "Lab reports", counts.lab_report],
  ];

  return (
    <AppShell>
      <PageShell
        title={selectedPatient?.isSelf ? "My Reports" : `${selectedPatient?.name || "Family member"}'s Reports`}
        action={<button className="btn-primary" onClick={() => setAddOpen(true)}><Plus size={16} /> Add</button>}
      >
        {privEnabled && privSession && (
          <div className="card" style={{ padding: "10px 13px", marginBottom: 12, display: "flex", gap: 9, alignItems: "flex-start", borderColor: "var(--color-warning, #b45309)", background: "var(--color-warning-light, #fbf3e6)" }}>
            <Clock size={13} style={{ marginTop: 2, flexShrink: 0, color: "var(--color-warning, #b45309)" }} />
            <span style={{ fontSize: 12, lineHeight: 1.5 }}>
              <b>{privSession.requester_label || "A doctor"} is viewing your records now.</b> Making a report visible
              asks whether it&rsquo;s <b>just this visit</b> or <b>always</b>. Locking one takes effect right away.
            </span>
          </div>
        )}
        {privEnabled && (
          <div style={{ fontSize: 11.5, color: "var(--color-text-muted)", marginBottom: 12, display: "flex", alignItems: "center", gap: 6 }}>
            <Lock size={12} />
            <span><b>{privateCount}</b> of {privMap.size || docs.length} report{privMap.size === 1 ? "" : "s"} private — hidden from doctors you share with.</span>
            <Link to={ROUTES.PATIENT.SHARED_RECORDS_PRIVACY} style={{ color: "var(--color-primary)", fontWeight: 600, textDecoration: "none", marginLeft: 4 }}>
              Shared records privacy →
            </Link>
          </div>
        )}
        {/* toolbar */}
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center", marginBottom: 14 }}>
          <div style={{ display: "inline-flex", border: "1px solid var(--color-border)", borderRadius: 9, overflow: "hidden" }}>
            {TABS.map(([id, label, n]) => (
              <button key={id} onClick={() => setTab(id)}
                style={{ padding: "7px 13px", fontSize: 13, border: "none", cursor: "pointer",
                  background: tab === id ? "var(--color-primary)" : "transparent",
                  color: tab === id ? "#fff" : "var(--color-text-secondary)", fontWeight: tab === id ? 600 : 400 }}>
                {label} <span style={{ opacity: 0.7, fontFamily: "monospace", fontSize: 11 }}>{n}</span>
              </button>
            ))}
          </div>
          <label className="form-input" style={{ display: "flex", alignItems: "center", gap: 8, flex: 1, minWidth: 180, padding: "6px 10px" }}>
            <Search size={15} style={{ color: "var(--color-text-muted)" }} />
            <input value={q} onChange={e => setQ(e.target.value)} placeholder="Search name, hospital, doctor, ID"
              style={{ border: "none", outline: "none", background: "none", width: "100%" }} />
          </label>
          <button className="btn-outline" onClick={() => setShowFilter(v => !v)}
            style={filtered ? { borderColor: "var(--color-primary)", color: "var(--color-primary)" } : undefined}>
            <SlidersHorizontal size={14} /> {filtered ? filterSummary : "Date"}
          </button>
          {catMode && (
            <div style={{ position: "relative" }}>
              <button className="btn-outline" onClick={() => setShowCatMenu(v => !v)}
                style={catSel.size ? { borderColor: "var(--color-primary)", color: "var(--color-primary)" } : undefined}>
                <Tag size={14} /> {catSel.size ? (catSel.size === 1 ? catLabel([...catSel][0]) : `${catSel.size} categories`) : "All categories"}
              </button>
              {showCatMenu && (
                <div className="card" style={{ position: "absolute", zIndex: 20, top: "calc(100% + 6px)", left: 0, minWidth: 240, padding: 6, maxHeight: 340, overflowY: "auto" }}>
                  <button onClick={() => { setCatSel(new Set()); }}
                    style={{ display: "flex", width: "100%", gap: 9, alignItems: "center", padding: "8px 9px", fontSize: 12.5, background: catSel.size ? "transparent" : "var(--color-primary-light)", border: "none", borderRadius: 7, cursor: "pointer", fontWeight: 600 }}>
                    All categories
                  </button>
                  <div style={{ height: 1, background: "var(--color-border)", margin: "5px 2px" }} />
                  {CATEGORY_ORDER.map(s => (
                    <label key={s} style={{ display: "flex", gap: 9, alignItems: "center", padding: "7px 9px", fontSize: 12.5, borderRadius: 7, cursor: "pointer" }}>
                      <input type="checkbox" checked={catSel.has(s)}
                        onChange={() => setCatSel(prev => { const n = new Set(prev); n.has(s) ? n.delete(s) : n.add(s); return n; })} />
                      {CATEGORY_LABELS[s]}
                    </label>
                  ))}
                </div>
              )}
            </div>
          )}
          {tab !== "unsorted" && (
            <button className="btn-outline" onClick={() => { setPicking(p => !p); setSel(new Set()); }}>
              <CheckSquare size={14} /> {picking ? "Cancel" : "Select"}
            </button>
          )}
        </div>

        {showFilter && (
          <div className="card" style={{ padding: "12px 14px", marginBottom: 12, display: "flex", flexDirection: "column", gap: 12 }}>
            <div style={{ display: "inline-flex", border: "1px solid var(--color-border)", borderRadius: 8, overflow: "hidden", alignSelf: "flex-start" }}>
              {[["month", "By month"], ["dates", "By dates"], ["all", "All reports"]].map(([m, l]) => (
                <button key={m} onClick={() => setFilterMode(m)}
                  style={{ padding: "6px 13px", fontSize: 12.5, border: "none", cursor: "pointer",
                    background: filterMode === m ? "var(--color-primary)" : "transparent",
                    color: filterMode === m ? "#fff" : "var(--color-text-secondary)", fontWeight: filterMode === m ? 600 : 400 }}>
                  {l}
                </button>
              ))}
            </div>

            {filterMode === "month" && (
              <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 12, color: "var(--color-text-muted)", maxWidth: 260 }}>
                Month
                <select className="form-input" value={filterMonth} onChange={e => setFilterMonth(e.target.value)} style={{ padding: "7px 10px" }}>
                  {monthOpts.map(o => (
                    <option key={o.key} value={o.key}>{o.label}{o.has ? "" : " — no reports"}</option>
                  ))}
                </select>
              </label>
            )}

            {filterMode === "dates" && (
              <div style={{ display: "flex", gap: 14, flexWrap: "wrap", alignItems: "flex-end" }}>
                <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 12, color: "var(--color-text-muted)" }}>
                  Date from
                  <input type="date" className="form-input" value={dFrom} max={dTo || undefined}
                    onChange={e => setDFrom(e.target.value)} style={{ padding: "6px 10px" }} />
                </label>
                <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 12, color: "var(--color-text-muted)" }}>
                  Date to
                  <input type="date" className="form-input" value={dTo} min={dFrom || undefined}
                    onChange={e => setDTo(e.target.value)} style={{ padding: "6px 10px" }} />
                </label>
                {dateFilterOn && (
                  <button className="btn-outline" style={{ fontSize: 12, padding: "6px 12px" }}
                    onClick={() => { setDFrom(""); setDTo(""); }}>Clear</button>
                )}
              </div>
            )}

            {filterMode === "all" && (
              <div style={{ fontSize: 12.5, color: "var(--color-text-muted)" }}>Showing every report, newest first.</div>
            )}
          </div>
        )}

        {filtered && tab !== "unsorted" && (
          <div style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 12.5, color: "var(--color-text-secondary)", marginBottom: 12 }}>
            <span>Showing <b>{filterMode === "month" ? (ymLabel(filterMonth)) : "selected dates"}</b> · {shown.length} report{shown.length !== 1 ? "s" : ""}</span>
            <button style={{ background: "none", border: "none", color: "var(--color-primary)", fontWeight: 600, cursor: "pointer", fontSize: 12.5, padding: 0 }}
              onClick={() => { setFilterMode("all"); setShowFilter(false); }}>Show all →</button>
          </div>
        )}

        {picking && (
          <div className="card" style={{ padding: "10px 14px", marginBottom: 12, display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
            <span style={{ fontSize: 13 }}><b style={{ fontFamily: "monospace" }}>{sel.size}</b> selected</span>
            <button className="btn-outline" style={{ fontSize: 12, padding: "5px 10px" }}
              onClick={() => setSel(new Set(shown.map(d => d.id)))}>Select all in view</button>
            <span style={{ flex: 1 }} />
            <button className="btn-primary" style={{ fontSize: 13, padding: "6px 14px" }} disabled={!sel.size} onClick={downloadSelected}>
              <Download size={14} /> {sel.size === 1 ? "Open" : "Download ZIP"}
            </button>
          </div>
        )}

        {counts.unsorted > 0 && tab !== "unsorted" && (
          <div className="card" style={{ padding: "10px 14px", marginBottom: 12, display: "flex", alignItems: "center", gap: 10, borderLeft: "3px solid var(--color-warning)" }}>
            <span style={{ fontSize: 13 }}>
              <b>{counts.unsorted}</b> uploaded file{counts.unsorted !== 1 ? "s" : ""} need your review
              {reviewSummary.length ? <span style={{ color: "var(--color-text-muted)" }}> — {reviewSummary.join(" · ")}</span> : "."}
            </span>
            <button style={{ marginLeft: "auto", background: "none", border: "none", color: "var(--color-primary)", fontWeight: 600, fontSize: 13, cursor: "pointer" }}
              onClick={() => setTab("unsorted")}>Review</button>
          </div>
        )}

        {isLoading ? (
          <div className="card" style={{ padding: 40, textAlign: "center", color: "var(--color-text-muted)" }}>Loading…</div>
        ) : shown.length === 0 ? (
          <div className="card" style={{ padding: 44, textAlign: "center" }}>
            <FileText size={30} style={{ color: "var(--color-border)", marginBottom: 12 }} />
            <div style={{ fontFamily: "var(--font-display)", fontWeight: 600, fontSize: 16, marginBottom: 4 }}>
              {q ? `Nothing matches “${q}”.`
                : tab === "unsorted" ? "Nothing to review."
                : filterMode === "month" && filterMonth ? `No reports in ${ymLabel(filterMonth)}.`
                : filterMode === "dates" && dateFilterOn ? "Nothing in that date range."
                : "No reports yet."}
            </div>
            {filtered && tab !== "unsorted"
              ? <button className="btn-outline" style={{ marginTop: 10 }} onClick={() => { setFilterMode("all"); setShowFilter(false); }}>Show all reports</button>
              : (!q && tab !== "unsorted" && <div style={{ fontSize: 13, color: "var(--color-text-muted)" }}>Tap “Add” to upload a prescription or report.</div>)}
          </div>
        ) : tab === "unsorted" ? (
          <>
            {reviewSummary.length > 0 && (
              <p style={{ fontSize: 12.5, color: "var(--color-text-muted)", margin: "0 0 12px" }}>
                {reviewSummary.join(" · ")} — each row below asks only for what's missing.
              </p>
            )}
            {shown.map(d => (
              <ReviewRow key={d.id} doc={d} onFile={fileDoc} onRemove={removeDoc} />
            ))}
          </>
        ) : catMode ? (
          <>
            {catGroups.map(({ key, label, list }) => (
              <div key={key} style={{ marginBottom: 22 }}>
                <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 8 }}>
                  <span style={{ fontSize: 12.5, fontWeight: 700, color: "var(--color-text-primary)" }}>{label}</span>
                  <span style={{ fontFamily: "monospace", fontSize: 10.5, color: "var(--color-text-muted)" }}>{list.length}</span>
                </div>
                {list.map(d => (
                  <DocRow key={`${key}:${d.id}`} doc={d} picking={picking} selected={sel.has(d.id)} showCat={key.startsWith("t:")}
                    priv={privEnabled ? privMap.get(d.id) : undefined} onLock={privEnabled ? onLock : undefined}
                    onToggle={() => toggleSel(d.id)} onOpen={() => setDetail(d)} />
                ))}
              </div>
            ))}
            {hasMore && (
              <button className="btn-outline" style={{ width: "100%" }} onClick={loadMore}>Load more</button>
            )}
          </>
        ) : (
          <>
            {monthGroups.map(({ label, list }) => (
              <div key={label} style={{ marginBottom: 20 }}>
                {filterMode !== "month" && (
                  <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: ".06em", textTransform: "uppercase", color: "var(--color-text-muted)", marginBottom: 8 }}>{label}</div>
                )}
                {list.map(d => (
                  <DocRow key={d.id} doc={d} picking={picking} selected={sel.has(d.id)}
                    priv={privEnabled ? privMap.get(d.id) : undefined} onLock={privEnabled ? onLock : undefined}
                    onToggle={() => toggleSel(d.id)} onOpen={() => setDetail(d)} />
                ))}
              </div>
            ))}
            {hasMore && (
              <button className="btn-outline" style={{ width: "100%" }} onClick={loadMore}>Load more</button>
            )}
          </>
        )}
      </PageShell>

      {addOpen && (
        <AddModal patientAwpid={patientAwpid} onClose={() => setAddOpen(false)}
          onDone={goto => { setAddOpen(false); setTab(goto); refetch(); }} />
      )}
      {detail && (
        <DetailModal doc={detail} onClose={() => setDetail(null)} onChanged={refetch} />
      )}
      {lockDlg && (
        <div onClick={() => setLockDlg(null)} style={{ position: "fixed", inset: 0, background: "rgba(15,23,20,.42)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 1000, padding: 20 }}>
          <div onClick={e => e.stopPropagation()} className="card" style={{ width: "min(400px,100%)", padding: 22 }}>
            <h3 style={{ margin: "0 0 8px", fontSize: 15.5 }}>{lockDlg.title}</h3>
            <p style={{ margin: "0 0 15px", fontSize: 12.5, color: "var(--color-text-secondary)", lineHeight: 1.5 }}>{lockDlg.message}</p>
            <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
              {lockDlg.actions.map((a, i) => (
                <button key={i} onClick={() => { setLockDlg(null); a.onClick?.(); }}
                  className={a.primary ? "btn-primary" : "btn-outline"}
                  style={{ width: a.sub ? "100%" : "auto", alignSelf: a.sub ? "stretch" : "flex-end", textAlign: a.sub ? "left" : "center", padding: a.sub ? "9px 13px" : "8px 14px" }}>
                  <span style={{ fontWeight: 600 }}>{a.label}</span>
                  {a.sub && <span style={{ display: "block", fontSize: 10.5, fontWeight: 400, color: a.primary ? "rgba(255,255,255,.85)" : "var(--color-text-muted)" }}>{a.sub}</span>}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}
    </AppShell>
  );
}

/* ─── shared inline styles ─── */
const backdrop = {
  position: "fixed", inset: 0, background: "rgba(15,23,42,.45)", zIndex: 1000,
  display: "flex", alignItems: "center", justifyContent: "center", padding: 16,
};
const sheet = { width: "min(560px, 96vw)", maxHeight: "88vh", overflowY: "auto", padding: 22 };
const h3 = { fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 17, margin: 0 };
const sub = { fontSize: 12.5, color: "var(--color-text-muted)", margin: "6px 0 0" };

const OUTCOME_LABEL = {
  not_medical: "NOT SAVED", unreadable: "COULDN’T READ", review: "REVIEW",
  duplicate: "DUPLICATE", failed: "FAILED",
};
const OUTCOME_TAG = {
  flexShrink: 0, fontSize: 9, fontWeight: 700, letterSpacing: ".04em",
  padding: "2px 6px", borderRadius: 5, whiteSpace: "nowrap", marginTop: 1,
};
const OUTCOME_TAG_COLOR = {
  not_medical: { background: "#FBEEDC", color: "#9A5B16" },
  unreadable:  { background: "#FBEAE7", color: "#B23A2E" },
  failed:      { background: "#FBEAE7", color: "#B23A2E" },
  review:      { background: "var(--color-border)", color: "var(--color-text-muted)" },
  duplicate:   { background: "var(--color-border)", color: "var(--color-text-muted)" },
};
const iconBtn = { background: "none", border: "none", cursor: "pointer", color: "var(--color-text-muted)", padding: 4, display: "inline-flex" };
