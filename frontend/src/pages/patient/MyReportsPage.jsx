/**
 * pages/patient/MyReportsPage.jsx
 * -------------------------------
 * Every prescription, lab report and scan in one list.
 *
 *   Upload   POST /records/upload/ (apps/records) — one request for the whole
 *            selection; each file is then read (RapidOCR) and classified
 *            (keyword rules, Ollama when they score under 75) in the
 *            background. The list refreshes itself while any file is still
 *            being processed.
 *   Read     GET/DELETE /portal/documents/[<id>/], POST /portal/documents/zip/
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  FileText, Pill, FlaskConical, ScanLine, X, Download, Trash2, PenLine, Camera,
  Upload, FolderUp, Plus, Search, CheckSquare, Lock, Unlock, Clock,
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

const MAX_FILE_BYTES = 12 * 1024 * 1024;   // same limits as POST /records/upload/ (apps/records/serializers.py)
const MAX_TOTAL_BYTES = 200 * 1024 * 1024;
const MAX_UPLOAD_FILES = 200;
const HARD_PICK_LIMIT = 1500;              // a folder pick past this is a whole drive, not a reports folder
const OK_EXT = /\.(pdf|jpe?g|png)$/i;

const TYPE_META = {
  prescription:      { tag: "RX", label: "Prescription", Icon: Pill },
  lab_report:        { tag: "LAB", label: "Lab report", Icon: FlaskConical },
  scan:              { tag: "SCAN", label: "Scan", Icon: ScanLine },
  discharge_summary: { tag: "DISCH", label: "Discharge summary", Icon: FileText },
  other:             { tag: "DOC", label: "Document", Icon: FileText },
};
const typeMeta = (t) => TYPE_META[t] || { ...TYPE_META.other, tag: (t || "doc").slice(0, 5).toUpperCase(), label: (t || "Document").replace(/_/g, " ") };
const TABS = [["all", "All"], ["prescription", "Prescriptions"], ["lab_report", "Lab reports"], ["scan", "Scans"], ["other", "Other"]];
const IN_PROGRESS = new Set(["queued", "ocr", "classifying"]);
const STATUS_LABEL = { queued: "Waiting to be read…", ocr: "Reading the page…", classifying: "Classifying…", failed: "Couldn’t process this file" };

function fmtDate(iso) {
  return iso ? new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }) : "";
}
function classifiedBy(doc) {
  if (doc.method === "staff") return "Issued by the hospital";
  const who = { rule: "Keyword rules", llm: "AI (Ollama)" }[doc.method];
  return who ? `${who}${doc.score != null ? ` · ${Math.round(doc.score)}%` : ""}` : "";
}

function isMobile() {
  try {
    if (/Android|iPhone|iPod|iPad|Mobile|Opera Mini/i.test(navigator.userAgent || "")) return true;
    return window.matchMedia("(pointer: coarse)").matches && window.matchMedia("(max-width: 860px)").matches;
  } catch { return false; }
}

/* ─────────────────────────────────────────────────────────── row */
function DocRow({ doc, picking, selected, onToggle, onOpen, priv, onLock }) {
  const m = typeMeta(doc.doc_type);
  const busy = IN_PROGRESS.has(doc.processing_status);
  const failed = doc.processing_status === "failed";
  const locked = priv?.private && !priv?.revealed_for_visit;
  const meta = [
    fmtDate(doc.document_date || doc.created_at), doc.hospital_label,
    busy || failed ? STATUS_LABEL[doc.processing_status] : (doc.method === "staff" ? "" : classifiedBy(doc)),
  ].filter(Boolean).join(" · ");
  return (
    <div className="card" onClick={() => (picking ? onToggle() : onOpen())}
      style={{ display: "flex", alignItems: "center", gap: 12, padding: "12px 14px", marginBottom: 8, cursor: "pointer",
               borderColor: selected ? "var(--color-primary)" : undefined }}>
      {picking && <input type="checkbox" checked={selected} readOnly />}
      <span style={{ width: 36, height: 36, borderRadius: 8, flexShrink: 0, display: "inline-flex", alignItems: "center", justifyContent: "center",
                     background: "var(--color-bg)", color: "var(--color-primary)" }}>
        {busy ? <Clock size={17} /> : <m.Icon size={17} />}
      </span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontWeight: 600, fontSize: 14, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{doc.title}</div>
        <div style={{ fontSize: 12, color: failed ? "var(--color-error)" : "var(--color-text-muted)" }}>{meta}</div>
      </div>
      <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: ".05em", padding: "3px 7px", borderRadius: 6,
                     background: "var(--color-bg)", color: "var(--color-text-muted)" }}>{busy ? "…" : m.tag}</span>
      {priv && onLock && !busy && (
        <button title={locked ? "Private — hidden from doctors" : "Shown to doctors you share with"} style={iconBtn}
          onClick={(e) => { e.stopPropagation(); onLock(doc); }}>
          {locked ? <Lock size={15} /> : <Unlock size={15} />}
        </button>
      )}
    </div>
  );
}

/* ─────────────────────────────────────────────────────────── detail */
function DetailModal({ doc, patientAwpid, onClose, onChanged }) {
  const { toastSuccess, toastApiError } = useToast();
  const [busy, setBusy] = useState(false);
  const hospital = !!doc.source_tenant_id || doc.uploaded_by === "staff";
  const awpidParam = patientAwpid ? { patient_awpid: patientAwpid } : {};

  async function view(docId = doc.id) {
    const win = window.open("", "_blank");
    try {
      const res = await apiClient.get(API_ENDPOINTS.PORTAL.DOCUMENT(docId), { params: awpidParam });
      const fd = (res.data?.data || res.data)?.file_data;
      if (fd) openDataUrlInNewTab(win, fd); else win?.close();
    } catch (err) { win?.close(); toastApiError(err, "Could not open the file."); }
  }
  async function remove() {
    setBusy(true);
    try {
      await apiClient.delete(API_ENDPOINTS.PORTAL.DOCUMENT(doc.id), { params: awpidParam });
      toastSuccess("Deleted from your reports.");
      onChanged(); onClose();
    } catch (err) { toastApiError(err, "Could not remove."); } finally { setBusy(false); }
  }

  const rows = [
    ["Type", IN_PROGRESS.has(doc.processing_status) ? STATUS_LABEL[doc.processing_status] : typeMeta(doc.doc_type).label],
    ["Classified by", classifiedBy(doc) || "—"],
    ["Document date", fmtDate(doc.document_date) || "—"],
    ["Doctor", doc.doctor_label || "—"],
    ["Hospital / lab", doc.hospital_label || "—"],
    ["Source", hospital ? "Issued by hospital" : "Uploaded by you"],
    ["Document ID", doc.public_document_id || "—"],
    ["Added on", fmtDate(doc.created_at)],
    ...(doc.processing_status === "failed" ? [["Problem", doc.error || STATUS_LABEL.failed]] : []),
  ];

  return (
    <div style={backdrop} onClick={onClose}>
      <div className="card" style={sheet} onClick={e => e.stopPropagation()}>
        <div style={{ display: "flex", alignItems: "flex-start", gap: 12, marginBottom: 14 }}>
          <div style={{ flex: 1, ...h3 }}>{doc.title}</div>
          <button onClick={onClose} style={iconBtn}><X size={18} /></button>
        </div>
        {rows.map(([k, v]) => (
          <div key={k} style={{ display: "grid", gridTemplateColumns: "130px 1fr", gap: 12, padding: "9px 0", borderTop: "1px solid var(--color-border)", fontSize: 13 }}>
            <span style={{ color: "var(--color-text-muted)" }}>{k}</span>
            <span style={{ fontWeight: 500, wordBreak: "break-word" }}>{v}</span>
          </div>
        ))}
        <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 16 }}>
          <button className="btn-primary" onClick={() => view()}><Download size={15} /> View / Download</button>
          {doc.handwritten_doc_id && (
            <button className="btn-outline" onClick={() => view(doc.handwritten_doc_id)}><PenLine size={15} /> View handwritten prescription</button>
          )}
          <button className="btn-outline" style={{ color: "var(--color-danger)", borderColor: "var(--color-danger)" }} disabled={busy} onClick={remove}>
            <Trash2 size={15} /> Delete from my reports
          </button>
          {hospital && (
            <div style={{ fontSize: 11, color: "var(--color-text-muted)" }}>
              Your hospital keeps its own copy. This removes it from your reports and from other hospitals.
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
  const [result, setResult] = useState({ sent: 0, skipped: 0, error: "" });
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
        reason: badType ? "not a PDF/image" : tooBig ? "over 12 MB" : "",
      };
    });

    const keptSoFar = items.filter(i => !i.skip);
    const newKept = arr.filter(a => !a.skip);
    if (!newKept.length) {
      toastError("None of those are PDFs or images under 12 MB.");
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
    if (!ready.length) { toastError("Nothing to upload."); return; }
    setPhase("upload");
    setProg({ done: 0, total: ready.length, name: "" });
    // One request for the whole selection: the server checks every file first
    // (12 MB each, 200 MB total) and rejects the lot if any one is invalid.
    const form = new FormData();
    ready.forEach(it => form.append("files", it.file, it.name));
    if (patientAwpid) form.append("patient_awpid", patientAwpid);
    try {
      const res = await apiClient.post(API_ENDPOINTS.RECORDS.UPLOAD, form, {
        // apiClient defaults to JSON; multipart makes axios send the files with their boundary
        headers: { "Content-Type": "multipart/form-data" },
        timeout: 0,
        onUploadProgress: (e) => setProg({ done: e.total ? Math.round((e.loaded / e.total) * ready.length) : 0, total: ready.length, name: "" }),
      });
      const docs = (res.data?.data || res.data)?.documents || [];
      setResult({ sent: docs.length, skipped: items.length - ready.length, error: "" });
    } catch (e) {
      const errs = e?.response?.data?.errors?.files;
      setResult({ sent: 0, skipped: 0, error: (Array.isArray(errs) ? errs.join(" ") : "") || e?.response?.data?.message || "Upload failed — try again." });
    }
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
            <p style={sub}>We read each page and file it for you.</p>
            {mob && (
              <div style={{ marginTop: 6 }}>
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
            <p style={sub}>{ready.length} ready{skipped ? ` · ${skipped} skipped (not a PDF/image, or over 12 MB)` : ""}</p>
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
            <h3 style={h3}>{result.error ? "Upload rejected" : "Uploaded"}</h3>
            {result.error ? (
              <p style={{ ...sub, color: "var(--color-error)" }}>{result.error} Nothing was saved — fix or remove that file and try again.</p>
            ) : (
              <>
                <SumRow label="Files uploaded" n={result.sent} ok />
                {result.skipped > 0 && <SumRow label="Skipped (not a PDF/image, or over 12 MB)" n={result.skipped} />}
                <p style={sub}>Each one is being read and classified now — its type appears in your list in a moment. You can leave this page.</p>
              </>
            )}
            <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
              <button className="btn-primary" style={{ flex: 1 }} onClick={() => onDone("all")}>Done</button>
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
  const { toastApiError, toastError } = useToast();

  const { items: docs, isLoading, hasMore, loadMore, refetch } = usePaginatedList(
    API_ENDPOINTS.PORTAL.DOCUMENTS,
    { pageSize: 50, params: patientAwpid ? { patient_awpid: patientAwpid } : {} },
  );

  // Files still being read / classified → refresh every 4 s until they're done.
  const processing = docs.some(d => IN_PROGRESS.has(d.processing_status));
  useEffect(() => {
    if (!processing) return undefined;
    const t = setInterval(refetch, 4000);
    return () => clearInterval(t);
  }, [processing, refetch]);

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

  const tabOf = (d) => (TYPE_META[d.doc_type] && d.doc_type !== "discharge_summary" ? d.doc_type : "other");
  const counts = useMemo(() => {
    const c = { all: docs.length };
    docs.forEach(d => { c[tabOf(d)] = (c[tabOf(d)] || 0) + 1; });
    return c;
  }, [docs]);
  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return docs.filter(d => (tab === "all" || tabOf(d) === tab)
      && (!needle || `${d.title} ${d.hospital_label || ""} ${d.doctor_label || ""}`.toLowerCase().includes(needle)));
  }, [docs, tab, q]);

  function toggleSel(id) {
    setSel(prev => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n; });
  }
  async function downloadSelected() {
    const ids = [...sel];
    if (!ids.length) return;
    try {
      const res = await apiClient.post(API_ENDPOINTS.PORTAL.DOCUMENTS_ZIP,
        { ids, ...(patientAwpid ? { patient_awpid: patientAwpid } : {}) }, { responseType: "blob" });
      const url = URL.createObjectURL(res.data);
      const a = document.createElement("a");
      a.href = url; a.download = `my-reports-${new Date().toISOString().slice(0, 10)}.zip`;
      a.click(); URL.revokeObjectURL(url);
      setPicking(false); setSel(new Set());
    } catch { toastError("Could not build the ZIP."); }
  }

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
          <div style={{ display: "flex", border: "1px solid var(--color-border)", borderRadius: 9, overflowX: "auto", maxWidth: "100%" }}>
            {TABS.map(([id, label]) => (
              <button key={id} onClick={() => setTab(id)} style={{
                padding: "7px 13px", fontSize: 13, border: "none", cursor: "pointer", whiteSpace: "nowrap",
                background: tab === id ? "var(--color-primary)" : "transparent",
                color: tab === id ? "#fff" : "var(--color-text-secondary)", fontWeight: tab === id ? 600 : 400,
              }}>{label} {counts[id] ? `(${counts[id]})` : ""}</button>
            ))}
          </div>
          <div style={{ flex: 1, minWidth: 180, display: "flex", alignItems: "center", gap: 6, border: "1px solid var(--color-border)", borderRadius: 9, padding: "6px 10px" }}>
            <Search size={14} color="var(--color-text-muted)" />
            <input value={q} onChange={e => setQ(e.target.value)} placeholder="Search title, hospital, doctor"
              style={{ border: "none", outline: "none", flex: 1, fontSize: 13, background: "transparent" }} />
          </div>
          {picking ? (
            <>
              <button className="btn-primary" disabled={!sel.size} onClick={downloadSelected}><Download size={14} /> Download {sel.size || ""}</button>
              <button className="btn-outline" onClick={() => { setPicking(false); setSel(new Set()); }}>Cancel</button>
            </>
          ) : (
            <button className="btn-outline" onClick={() => setPicking(true)}><CheckSquare size={14} /> Select</button>
          )}
        </div>

        {processing && (
          <div style={{ fontSize: 12.5, color: "var(--color-text-muted)", marginBottom: 10, display: "flex", alignItems: "center", gap: 6 }}>
            <Clock size={13} /> Reading and classifying your new files — this list updates by itself.
          </div>
        )}

        {isLoading && !docs.length ? (
          <div className="card" style={{ padding: 30, textAlign: "center", color: "var(--color-text-muted)" }}>Loading…</div>
        ) : !shown.length ? (
          <div className="card" style={{ padding: 30, textAlign: "center", color: "var(--color-text-muted)", fontSize: 13 }}>
            {docs.length ? "Nothing matches." : "No reports yet — tap “Add” to upload a prescription or report."}
          </div>
        ) : (
          <>
            {shown.map(d => (
              <DocRow key={d.id} doc={d} picking={picking} selected={sel.has(d.id)}
                priv={privEnabled ? privMap.get(d.id) : undefined} onLock={privEnabled ? onLock : undefined}
                onToggle={() => toggleSel(d.id)} onOpen={() => setDetail(d)} />
            ))}
            {hasMore && <button className="btn-outline" style={{ width: "100%" }} onClick={loadMore}>Load more</button>}
          </>
        )}
      </PageShell>

      {addOpen && (
        <AddModal patientAwpid={patientAwpid} onClose={() => setAddOpen(false)}
          onDone={() => { setAddOpen(false); setTab("all"); refetch(); }} />
      )}
      {detail && (
        <DetailModal doc={detail} patientAwpid={patientAwpid} onClose={() => setDetail(null)} onChanged={refetch} />
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
const iconBtn = { background: "none", border: "none", cursor: "pointer", color: "var(--color-text-muted)", padding: 4, display: "inline-flex" };
