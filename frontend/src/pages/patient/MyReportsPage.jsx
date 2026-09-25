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
  FileText, Pill, FlaskConical, ShieldCheck, X, Download, Tag, Trash2, PenLine, Camera, Upload, FolderUp,
  Plus, Search, CheckSquare, Lock, Unlock, Clock, TrendingUp, TrendingDown, Sparkles, ChevronDown, ChevronUp,
  ThumbsUp, FolderClosed, Image as ImageIcon, Calendar, Building2, UserRound, Eye, MoreVertical, Info, Share2,
  Check, Loader2,
} from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";
import { AppShell } from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import { usePaginatedList } from "../../hooks/usePaginatedList";
import { useToast } from "../../hooks/useToast";
import apiClient from "../../services/api.client";
import API_ENDPOINTS from "../../config/api.config";
import ROUTES from "../../config/routes.config";
import { usePatientContext } from "../../context/PatientContext";
import { openDataUrlInNewTab } from "../../utils/fileViewer";
import HealthInsightsPanel from "./components/HealthInsightsPanel";
import { useUploads } from "../../context/UploadContext";
import OrganizeDocuments from "./components/OrganizeDocuments";
import { CATEGORY_LABELS, CATEGORY_ORDER, catLabel, inFlight, pct, TYPE_TONE } from "./reportMeta";

const MAX_PDF_BYTES = 11 * 1024 * 1024;   // the backend's single-upload guard
const MAX_IMAGE_BYTES = 40 * 1024 * 1024; // photos are shrunk on the device before upload (context/UploadContext)
const OK_EXT = /\.(pdf|jpe?g|png)$/i;
// Folder upload uses the OS "pick a directory" dialog, which happily lets you
// choose a whole drive. These bound what the modal will actually take on:
// past HARD_PICK_LIMIT it's a drive, not a reports folder; the others cap one
// Add session so the browser isn't asked to base64 hundreds of MB in a loop.
const HARD_PICK_LIMIT = 1500;
const MAX_UPLOAD_FILES = 200;

const TYPE_META = {
  prescription: { tag: "RX", label: "Prescription", Icon: Pill },
  lab_report:   { tag: "LAB", label: "Lab report", Icon: FlaskConical },
  scan:         { tag: "SCAN", label: "Scan", Icon: FileText },
  discharge_summary: { tag: "DISCH", label: "Discharge summary", Icon: FileText },
  other:        { tag: "DOC", label: "Document", Icon: FileText },
};

const TYPE_OPTIONS = [
  ["prescription", "Prescription"], ["lab_report", "Lab report"], ["scan", "Imaging"],
  ["discharge_summary", "Discharge summary"], ["other", "Other"],
];
const TYPE_LABEL = Object.fromEntries(TYPE_OPTIONS);
function isMobile() {
  try {
    if (/Android|iPhone|iPod|iPad|Mobile|Opera Mini/i.test(navigator.userAgent || "")) return true;
    return window.matchMedia("(pointer: coarse)").matches && window.matchMedia("(max-width: 860px)").matches;
  } catch { return false; }
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
const LAB_STATUS_COLOR = { high: "var(--color-error)", low: "var(--color-error)", normal: "var(--color-success, #1F8F6E)" };
const LAB_STATUS_LABEL = { high: "High", low: "Low", normal: "Normal" };

function fmtLabDate(value) {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

/** Key Parameters + Comparison with Previous Report — the per-document
 * drill-down for the extraction pipeline's stored values (core.lab_value_
 * extractor -> ExtractedLabValue), fetched from
 * PortalDocumentLabValuesView. Read-only, lab_report documents only; a
 * document with nothing confidently extracted renders nothing (it already
 * surfaces in Health Insights' "Reports Needing Review" instead). */
function LabValuesSection({ docId, patientAwpid }) {
  const [values, setValues] = useState(null); // null = loading, [] = none
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setValues(null); setFailed(false);
    apiClient.get(API_ENDPOINTS.PORTAL.DOCUMENT_LAB_VALUES(docId), { params: patientAwpid ? { patient_awpid: patientAwpid } : {} })
      .then(res => { if (!cancelled) setValues((res.data?.data || res.data)?.values || []); })
      .catch(() => { if (!cancelled) setFailed(true); });
    return () => { cancelled = true; };
  }, [docId, patientAwpid]);

  if (failed || (values && values.length === 0)) return null;
  if (values === null) {
    return <div style={{ fontSize: 12, color: "var(--color-text-muted)", marginBottom: 16 }}>Loading key parameters…</div>;
  }

  const withPrevious = values.filter(v => v.previous);

  return (
    <div style={{ marginBottom: 16 }}>
      <div className="dot-label dot-label--blue" style={{ marginBottom: 10 }}>Key Parameters</div>
      <div style={{ overflowX: "auto", marginBottom: withPrevious.length ? 16 : 0 }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12.5 }}>
          <thead>
            <tr style={{ textAlign: "left", color: "var(--color-text-muted)" }}>
              <th style={{ padding: "5px 7px", fontWeight: 600 }}>Parameter</th>
              <th style={{ padding: "5px 7px", fontWeight: 600 }}>Value</th>
              <th style={{ padding: "5px 7px", fontWeight: 600 }}>Reference Range</th>
              <th style={{ padding: "5px 7px", fontWeight: 600 }}>Status</th>
            </tr>
          </thead>
          <tbody>
            {values.map(v => (
              <tr key={v.parameter_slug} style={{ borderTop: "1px solid var(--color-border)" }}>
                <td style={{ padding: "7px" }}>{v.parameter_label}</td>
                <td style={{ padding: "7px", fontWeight: 700 }}>{v.value}{v.unit}</td>
                <td style={{ padding: "7px", color: "var(--color-text-muted)" }}>{v.reference_range_text || "—"}</td>
                <td style={{ padding: "7px" }}>
                  {v.status
                    ? <span style={{ fontSize: 11, fontWeight: 700, color: LAB_STATUS_COLOR[v.status] }}>{LAB_STATUS_LABEL[v.status]}</span>
                    : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {withPrevious.length > 0 && (
        <>
          <div className="dot-label dot-label--gold" style={{ marginBottom: 10 }}>Comparison with Previous Report</div>
          <div style={{ display: "grid", gap: 6 }}>
            {withPrevious.map(v => {
              const Icon = v.previous.direction === "up" ? TrendingUp : v.previous.direction === "down" ? TrendingDown : null;
              const concerning = (v.concern === "higher_is_concern" && v.previous.direction === "up")
                || (v.concern === "lower_is_concern" && v.previous.direction === "down");
              return (
                <div key={v.parameter_slug} style={{
                  display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10,
                  padding: "8px 10px", borderRadius: 8, border: "1px solid var(--color-border)", fontSize: 12.5,
                }}>
                  <span style={{ fontWeight: 600 }}>{v.parameter_label}</span>
                  <span style={{ display: "flex", alignItems: "center", gap: 6, color: concerning ? "var(--color-error)" : "var(--color-text-secondary)" }}>
                    {v.previous.value}{v.unit} <span style={{ color: "var(--color-text-muted)" }}>→</span> {v.value}{v.unit}
                    {Icon && <Icon size={14} />}
                  </span>
                </div>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}

/* ─────────────────────────────────────────────────────────── detail modal */
function DetailModal({ doc, patientAwpid, onClose, onChanged }) {
  const { toastSuccess, toastApiError } = useToast();
  const [busy, setBusy] = useState(false);
  const [recat, setRecat] = useState(false);
  const m = TYPE_META[doc.doc_type] || TYPE_META.other;
  const hospital = !!doc.source_tenant_id || doc.uploaded_by === "staff";
  const awpidParam = patientAwpid ? { patient_awpid: patientAwpid } : {};

  async function view(download, docId = doc.id) {
    const win = window.open("", "_blank");
    try {
      const res = await apiClient.get(API_ENDPOINTS.PORTAL.DOCUMENT(docId), { params: { ...(download ? { download: 1 } : {}), ...awpidParam } });
      const fd = (res.data?.data || res.data)?.file_data;
      if (fd) openDataUrlInNewTab(win, fd); else win?.close();
    } catch (err) { win?.close(); toastApiError(err, "Could not open the file."); }
  }
  const hasHandwritten = !!doc.handwritten_doc_id;
  async function move(type) {
    setBusy(true);
    try {
      if (type === "__remove__") {
        await apiClient.delete(API_ENDPOINTS.PORTAL.DOCUMENT(doc.id), { params: awpidParam });
        toastSuccess("Removed.");
      } else {
        await apiClient.patch(API_ENDPOINTS.PORTAL.DOCUMENT(doc.id), { doc_type: type, ...awpidParam });
        toastSuccess(`Moved to ${type === "prescription" ? "Prescriptions" : "Lab reports"}.`);
      }
      onChanged(); onClose();
    } catch (err) { toastApiError(err, "Could not update."); } finally { setBusy(false); }
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
    ["Type", m.label],
    ["Document date", fmtDate(doc.document_date) || "—"],
    ["Doctor", doc.doctor_label || "—"],
    ["Hospital / lab", doc.hospital_label || (hospital ? "Your hospital" : "—")],
    ["Source", hospital ? "Issued by hospital" : "Uploaded by you"],
    ["Document ID", doc.public_document_id || "—"],
    ["Added on", fmtDate(doc.created_at)],
    ["Status", doc.verification_status === "verified" ? "Verified · QR authenticated" : "Not verified"],
    ...(doc.verification_status !== "verified" && (doc.rule_doc_type || doc.llm_doc_type || doc.human_action) ? [[
      "Sorted by",
      [
        doc.rule_doc_type && `Rules: ${TYPE_LABEL[doc.rule_doc_type] || doc.rule_doc_type} ${pct(doc.rule_confidence)}`,
        doc.llm_doc_type && `AI: ${TYPE_LABEL[doc.llm_doc_type] || doc.llm_doc_type} ${pct(doc.llm_confidence)}`,
        doc.human_action === "accepted" ? "Confirmed by you"
          : doc.human_action === "changed" ? "Corrected by you"
          : doc.classification_status === "partial" ? "Not yet confirmed" : null,
      ].filter(Boolean).join(" · "),
    ]] : []),
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

        {doc.doc_type === "lab_report" && <LabValuesSection docId={doc.id} patientAwpid={patientAwpid} />}

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

function AddModal({ onClose, onManual, onAuto }) {
  const { toastError } = useToast();
  const [step, setStep] = useState("select");        // select | method
  const [items, setItems] = useState([]);            // {file, name, size, skip, reason}
  const [method, setMethod] = useState("");          // manual | auto
  const [dragOver, setDragOver] = useState(false);
  const filesRef = useRef(null);
  const folderRef = useRef(null);
  const camRef = useRef(null);
  const mob = isMobile();

  async function onDrop(e) {
    e.preventDefault();
    setDragOver(false);
    stage(await filesFromDrop(e.dataTransfer));
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
      const isPdf = f.type === "application/pdf" || /\.pdf$/i.test(f.name || "");
      // Photos are shrunk on the device before upload, so only PDFs keep the 11 MB cap.
      const tooBig = f.size > (isPdf ? MAX_PDF_BYTES : MAX_IMAGE_BYTES);
      return { file: f, name: f.name || "photo.jpg", size: f.size, skip: badType || tooBig,
        reason: badType ? "not a PDF or image" : tooBig ? (isPdf ? "PDF over 11 MB" : "image over 40 MB") : "" };
    });
    const skipped = arr.filter(a => a.skip);
    if (skipped.length) toastError(`${skipped.length} skipped — ${skipped[0].name}: ${skipped[0].reason}${skipped.length > 1 ? " …" : ""}`);
    const kept = [...items, ...arr.filter(a => !a.skip)];
    if (kept.length > MAX_UPLOAD_FILES) {
      toastError(`Up to ${MAX_UPLOAD_FILES} documents at a time — add the rest afterwards.`);
      return;
    }
    setItems(kept);
  }

  const files = items.map(i => i.file);

  return (
    <div style={backdrop} onClick={onClose}>
      <div className="card" style={{ ...sheet, padding: 0, display: "flex", flexDirection: "column" }} onClick={e => e.stopPropagation()}>
        <input ref={filesRef} type="file" accept=".pdf,image/jpeg,image/png" multiple hidden onChange={e => { stage(e.target.files); e.target.value = ""; }} />
        <input ref={folderRef} type="file" hidden webkitdirectory="" directory="" multiple onChange={e => { stage(e.target.files); e.target.value = ""; }} />
        <input ref={camRef} type="file" accept="image/*" capture="environment" hidden onChange={e => { stage(e.target.files); e.target.value = ""; }} />

        <div style={{ display: "flex", alignItems: "center", padding: "18px 22px", borderBottom: "1px solid var(--color-border)" }}>
          <h3 style={{ ...h3, flex: 1 }}>{step === "select" ? "Add Documents" : "How would you like to organize your documents?"}</h3>
          <button onClick={onClose} style={iconBtn} aria-label="Close"><X size={18} /></button>
        </div>

        <div style={{ padding: "18px 22px", overflowY: "auto", flex: 1 }}>
          {step === "select" ? (
            <>
              <div
                onDragOver={e => { e.preventDefault(); setDragOver(true); }}
                onDragLeave={() => setDragOver(false)}
                onDrop={onDrop}
                style={{
                  border: `2px dashed ${dragOver ? "var(--color-primary)" : "var(--color-border)"}`, borderRadius: 14,
                  padding: "30px 16px", textAlign: "center",
                  background: dragOver ? "var(--color-primary-light, #f0fdf4)" : "var(--color-bg)",
                }}
              >
                <span style={{ width: 52, height: 52, borderRadius: "50%", background: "var(--color-surface, #fff)", display: "inline-flex", alignItems: "center", justifyContent: "center", boxShadow: "0 1px 4px rgba(0,0,0,.08)", marginBottom: 10 }}>
                  <Upload size={22} style={{ color: "var(--color-primary)" }} />
                </span>
                <div style={{ fontSize: 15, fontWeight: 600 }}>Drag and drop files here</div>
                <div style={{ fontSize: 12.5, color: "var(--color-text-muted)", margin: "4px 0 10px" }}>or</div>
                <div style={{ display: "flex", gap: 8, justifyContent: "center", flexWrap: "wrap" }}>
                  <button className="btn-primary" onClick={() => filesRef.current?.click()}>Choose Files</button>
                  {!mob && <button className="btn-outline" onClick={() => folderRef.current?.click()}><FolderUp size={14} /> Choose a folder</button>}
                  {mob && <button className="btn-outline" onClick={() => camRef.current?.click()}><Camera size={14} /> Take photo</button>}
                </div>
                <div style={{ fontSize: 12, color: "var(--color-text-muted)", marginTop: 12, lineHeight: 1.6 }}>
                  Supported formats: PDF, JPG, JPEG, PNG<br />Max file size: 11 MB per PDF, 40 MB per photo
                </div>
              </div>

              {items.length > 0 && (
                <>
                  <div style={{ display: "flex", alignItems: "center", margin: "18px 0 8px" }}>
                    <b style={{ flex: 1, fontSize: 14 }}>Selected Documents ({items.length})</b>
                    <button onClick={() => setItems([])} style={{ background: "none", border: "none", color: "var(--color-primary)", fontWeight: 600, fontSize: 13, cursor: "pointer" }}>Remove All</button>
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                    {items.map((it, idx) => (
                      <div key={idx} style={{ display: "flex", alignItems: "center", gap: 12, padding: "10px 12px", border: "1px solid var(--color-border)", borderRadius: 10 }}>
                        <span style={{ width: 36, height: 36, borderRadius: 8, background: "var(--color-primary-light, rgba(21,119,74,.10))", color: "var(--color-primary)", display: "inline-flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
                          <FileText size={16} />
                        </span>
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ fontSize: 13.5, fontWeight: 600, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{it.name}</div>
                          <div style={{ fontSize: 12, color: "var(--color-text-muted)" }}>
                            {(it.name.split(".").pop() || "").toUpperCase()} · {it.size >= 1048576 ? `${(it.size / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(it.size / 1024))} KB`}
                          </div>
                        </div>
                        <button onClick={() => setItems(p => p.filter((_, i) => i !== idx))} style={iconBtn} aria-label={`Remove ${it.name}`}><X size={15} /></button>
                      </div>
                    ))}
                  </div>
                </>
              )}
            </>
          ) : (
            <>
              <p style={{ margin: "0 0 14px", color: "var(--color-text-muted)", fontSize: 14 }}>You've selected {items.length} document{items.length !== 1 ? "s" : ""}</p>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(210px, 1fr))", gap: 12 }}>
                {[
                  ["manual", FolderUp, "#E0A526", "Organize Manually", "I'll choose where each document should go."],
                  ["auto", Sparkles, "#7C6CE0", "Auto-Segregate", "Let the system identify and organize my documents — I'll check them once at the end."],
                ].map(([id, Icon, color, title, desc]) => (
                  <button key={id} onClick={() => setMethod(id)} style={{
                    position: "relative", textAlign: "left", padding: 18, borderRadius: 14, cursor: "pointer", background: "var(--color-surface, #fff)",
                    border: `1.5px solid ${method === id ? "var(--color-primary)" : "var(--color-border)"}`,
                    boxShadow: method === id ? "0 0 0 3px var(--color-primary-light, rgba(21,119,74,.12))" : "none",
                  }}>
                    <span style={{ width: 44, height: 44, borderRadius: "50%", background: `${color}22`, color, display: "inline-flex", alignItems: "center", justifyContent: "center", marginBottom: 12 }}>
                      <Icon size={20} />
                    </span>
                    <div style={{ fontWeight: 700, fontSize: 15, marginBottom: 4 }}>{title}</div>
                    <div style={{ fontSize: 13, color: "var(--color-text-muted)", lineHeight: 1.45, paddingRight: 18 }}>{desc}</div>
                    <span style={{ position: "absolute", right: 14, bottom: 14, width: 18, height: 18, borderRadius: "50%", border: `2px solid ${method === id ? "var(--color-primary)" : "var(--color-border)"}`, display: "inline-flex", alignItems: "center", justifyContent: "center" }}>
                      {method === id && <span style={{ width: 8, height: 8, borderRadius: "50%", background: "var(--color-primary)" }} />}
                    </span>
                  </button>
                ))}
              </div>
              <div style={{ marginTop: 14, padding: "10px 12px", borderRadius: 10, background: "var(--color-primary-light, rgba(21,119,74,.08))", color: "var(--color-primary)", fontSize: 13 }}>
                Either way, uploads run in the background — you can keep using the app. You can always change a document's folder later.
              </div>
            </>
          )}
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "14px 22px", borderTop: "1px solid var(--color-border)" }}>
          {step === "select" ? (
            <>
              <span style={{ fontSize: 13, color: "var(--color-text-muted)", flex: 1 }}>
                {items.length ? `${items.length} document${items.length !== 1 ? "s" : ""} selected` : "No documents selected"}
              </span>
              <button className="btn-outline" onClick={onClose}>Cancel</button>
              <button className="btn-primary" disabled={!items.length} onClick={() => setStep("method")}>Continue →</button>
            </>
          ) : (
            <>
              <button onClick={() => setStep("select")} style={{ background: "none", border: "none", cursor: "pointer", color: "var(--color-text-secondary)", fontSize: 13.5 }}>← Back</button>
              <span style={{ flex: 1 }} />
              <button className="btn-primary" disabled={!method} onClick={() => (method === "manual" ? onManual(files) : onAuto(files))}>Continue →</button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────── page parts */
const TYPE_ICON = { prescription: Pill, lab_report: FlaskConical, scan: ImageIcon, discharge_summary: FileText, other: FileText };
const PILL_TABS = [
  ["all", "All"], ["lab_report", "Lab Reports"], ["scan", "Scan Reports"],
  ["prescription", "Prescriptions"], ["discharge_summary", "Discharge"], ["other", "Other"],
];

function fmtDateTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d)) return "";
  const hasTime = /T\d\d:\d\d/.test(String(iso));
  return d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })
    + (hasTime ? `, ${d.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" })}` : "");
}

/** Upload → Sort → Review, always visible while anything is happening. */
function ActivityCard({ uploads, sortingDocs, toVerify, onReview }) {
  const s = uploads?.summary;
  const up = s?.upload || { total: 0, active: 0 };
  const uploading = up.active > 0;
  const sorting = sortingDocs.length;
  const ready = toVerify.length;
  if (!uploading && !sorting && !ready) return null;

  const step = uploading ? 0 : sorting ? 1 : 2;
  const steps = [
    ["Upload", uploading ? `${up.total - up.active} of ${up.total} sent` : "Done"],
    ["Sorting", sorting ? `${sorting} in progress` : uploading ? "Next" : "Done"],
    ["Your review", ready ? `${ready} waiting` : "Last step"],
  ];
  const ahead = Math.min(...sortingDocs.map(d => (d.queue_ahead ?? Infinity)));
  const bulk = sortingDocs.some(d => d.processing_route === "bulk" && d.processing_status === "queued");
  const stageLine = uploading
    ? "Uploading from this device — keep this tab open until it finishes. You can use any other page meanwhile."
    : sorting
      ? bulk
        ? `That's a big upload, so we sort it in batches every few minutes — ${sorting} file${sorting !== 1 ? "s" : ""} to go. You can close the app; we'll notify you.`
        : `We're reading and sorting ${sorting} file${sorting !== 1 ? "s" : ""} on our side${Number.isFinite(ahead) && ahead > 0 ? ` (${ahead} ahead in the queue)` : ""}. You can close the app — we'll notify you.`
      : `${ready} document${ready !== 1 ? "s were" : " was"} sorted automatically. Check them once and fix anything that's wrong.`;

  return (
    <div className="card" style={{ padding: "16px 18px", marginBottom: 16, borderLeft: "4px solid var(--color-primary)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 16, flexWrap: "wrap" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 0, flex: "1 1 420px", minWidth: 0 }}>
          {steps.map(([t, sub], i) => {
            const state = i < step ? "done" : i === step ? "active" : "todo";
            return (
              <div key={t} style={{ display: "flex", alignItems: "center", flex: i < 2 ? 1 : "0 0 auto", minWidth: 0 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 9, minWidth: 0 }}>
                  <span style={{
                    width: 30, height: 30, borderRadius: "50%", flexShrink: 0, display: "inline-flex", alignItems: "center", justifyContent: "center",
                    fontSize: 13, fontWeight: 700,
                    background: state === "todo" ? "var(--color-bg)" : "var(--color-primary)",
                    color: state === "todo" ? "var(--color-text-muted)" : "#fff",
                    border: state === "todo" ? "1.5px solid var(--color-border)" : "none",
                    boxShadow: state === "active" ? "0 0 0 4px var(--color-primary-light, rgba(21,119,74,.15))" : "none",
                  }}>
                    {state === "done" ? <Check size={15} /> : state === "active" && i < 2 ? <Loader2 size={15} className="mr-spin" /> : i + 1}
                  </span>
                  <span style={{ minWidth: 0 }}>
                    <span style={{ display: "block", fontSize: 13.5, fontWeight: 700, color: state === "todo" ? "var(--color-text-muted)" : "var(--color-text)" }}>{t}</span>
                    <span style={{ display: "block", fontSize: 11.5, color: "var(--color-text-muted)", whiteSpace: "nowrap" }}>{sub}</span>
                  </span>
                </div>
                {i < 2 && <span style={{ flex: 1, height: 2, margin: "0 12px", minWidth: 16, background: i < step ? "var(--color-primary)" : "var(--color-border)" }} />}
              </div>
            );
          })}
        </div>
        {ready > 0 && (
          <button className="btn-primary" onClick={onReview} style={{ flexShrink: 0 }}>
            Review {ready} document{ready !== 1 ? "s" : ""} →
          </button>
        )}
      </div>
      <div style={{ fontSize: 12.5, color: "var(--color-text-secondary)", marginTop: 12 }}>{stageLine}</div>
    </div>
  );
}

function StatCard({ icon: Icon, tone, n, title, sub, active, onClick }) {
  return (
    <button onClick={onClick} className="card" style={{
      display: "flex", alignItems: "center", gap: 14, padding: "16px 18px", textAlign: "left", cursor: "pointer",
      background: tone.bg, border: `1.5px solid ${active ? tone.fg : "transparent"}`, borderRadius: 14,
    }}>
      <span style={{ width: 48, height: 48, borderRadius: "50%", background: "var(--color-surface, #fff)", color: tone.fg, display: "inline-flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
        <Icon size={22} />
      </span>
      <span style={{ minWidth: 0 }}>
        <span style={{ display: "block", fontSize: 24, fontWeight: 700, lineHeight: 1.1, color: "var(--color-text)", fontVariantNumeric: "tabular-nums" }}>{n}</span>
        <span style={{ display: "block", fontSize: 13.5, fontWeight: 600, color: "var(--color-text)" }}>{title}</span>
        <span style={{ display: "block", fontSize: 11.5, color: "var(--color-text-muted)" }}>{sub}</span>
      </span>
    </button>
  );
}

function Menu({ items, onClose }) {
  const ref = useRef(null);
  useEffect(() => {
    const h = (e) => { if (ref.current && !ref.current.contains(e.target)) onClose(); };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, [onClose]);
  return (
    <div ref={ref} className="card" style={{ position: "absolute", right: 0, top: "calc(100% + 6px)", zIndex: 30, minWidth: 200, padding: 6 }}>
      {items.map(([label, Icon, fn, danger]) => (
        <button key={label} onClick={() => { onClose(); fn(); }} style={{
          display: "flex", alignItems: "center", gap: 9, width: "100%", padding: "8px 10px", border: "none", borderRadius: 7,
          background: "none", cursor: "pointer", fontSize: 13, textAlign: "left", color: danger ? "var(--color-danger, #B23A2E)" : "var(--color-text)",
        }}>
          <Icon size={14} /> {label}
        </button>
      ))}
    </div>
  );
}

function ReportRow({ doc, picking, selected, onToggle, priv, onView, onDownload, onDetails, onLock, onDelete }) {
  const [menu, setMenu] = useState(false);
  const tone = TYPE_TONE[doc.doc_type] || TYPE_TONE.other;
  const Icon = TYPE_ICON[doc.doc_type] || FileText;
  const cats = doc.doc_type === "lab_report" ? (doc.report_categories || []).filter(c => CATEGORY_LABELS[c]) : [];
  const sub = cats.length ? catLabel(cats[0]) + (cats.length > 1 ? ` +${cats.length - 1}` : "") : doc.folder || "";
  const isPrivate = priv && (priv.private && !priv.revealed_for_visit);
  const title = doc.doc_type === "prescription" && doc.doctor_label ? `Prescription · ${doc.doctor_label}` : doc.title;
  const meta = [
    [Calendar, fmtDateTime(doc.document_date || doc.created_at)],
    [Building2, doc.hospital_label || (doc.uploaded_by === "staff" ? "Your hospital" : "")],
    [UserRound, doc.doctor_label],
  ].filter(([, v]) => v);

  return (
    <div className="card mr-row" style={{
      display: "flex", alignItems: "center", gap: 14, padding: "12px 16px", marginBottom: 8,
      outline: selected ? "2px solid var(--color-primary)" : "none",
    }}>
      {picking && <input type="checkbox" checked={selected} onChange={onToggle} aria-label={`Select ${doc.title}`} />}
      <button onClick={onView} aria-label={`Open ${doc.title}`} style={{
        width: 46, height: 46, borderRadius: 11, flexShrink: 0, border: "none", cursor: "pointer",
        background: tone.bg, color: tone.fg, display: "inline-flex", alignItems: "center", justifyContent: "center",
      }}>
        <Icon size={21} />
      </button>
      <div style={{ flex: "1 1 260px", minWidth: 0, cursor: "pointer" }} onClick={onDetails}>
        <div style={{ fontWeight: 700, fontSize: 14.5, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", display: "flex", alignItems: "center", gap: 7 }}>
          {title}
          {doc.verification_status === "verified" && <ShieldCheck size={14} style={{ color: "#166534", flexShrink: 0 }} aria-label="Verified" />}
          {isPrivate && <Lock size={13} style={{ color: "var(--color-primary)", flexShrink: 0 }} aria-label="Private" />}
        </div>
        <div style={{ display: "flex", gap: 14, flexWrap: "wrap", marginTop: 3, fontSize: 12.5, color: "var(--color-text-muted)" }}>
          {meta.map(([I, v], i) => (
            <span key={i} style={{ display: "inline-flex", alignItems: "center", gap: 5, whiteSpace: "nowrap" }}><I size={13} /> {v}</span>
          ))}
        </div>
      </div>
      <div className="mr-badges" style={{ display: "flex", alignItems: "center", gap: 8, flexShrink: 0 }}>
        <span style={{ display: "inline-flex", alignItems: "center", gap: 5, padding: "4px 10px", borderRadius: 999, fontSize: 12, fontWeight: 600, background: tone.bg, color: tone.fg }}>
          <Icon size={12} /> {tone.label}
        </span>
        {sub && (
          <span style={{ padding: "4px 10px", borderRadius: 999, fontSize: 12, background: "var(--color-bg)", color: "var(--color-text-secondary)", maxWidth: 170, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {doc.folder && !cats.length ? <FolderClosed size={11} style={{ verticalAlign: -1, marginRight: 4 }} /> : null}{sub}
          </span>
        )}
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexShrink: 0, position: "relative" }}>
        <button className="btn-outline" onClick={onView} style={{ padding: "7px 14px", fontSize: 13 }}><Eye size={15} /> View</button>
        <button className="btn-outline" onClick={onDownload} aria-label="Download" style={{ padding: "7px 10px" }}><Download size={15} /></button>
        <button onClick={() => setMenu(m => !m)} aria-label="More" style={{ ...iconBtn, padding: 7 }}><MoreVertical size={17} /></button>
        {menu && (
          <Menu onClose={() => setMenu(false)} items={[
            ["Details", Info, onDetails],
            ...(onLock ? [[isPrivate ? "Sharing: make visible" : "Make private", isPrivate ? Unlock : Lock, onLock]] : []),
            ["Delete", Trash2, onDelete, true],
          ]} />
        )}
      </div>
    </div>
  );
}

function EmptyState({ onUpload }) {
  const steps = [
    [Upload, "Upload", "PDFs or photos — one file or a whole folder."],
    [Sparkles, "We sort them", "Each file is read and filed as a prescription, lab report, scan…"],
    [ThumbsUp, "You check once", "Fix anything that's wrong and save. Done."],
  ];
  return (
    <div className="card" style={{ padding: "40px 24px", textAlign: "center" }}>
      <span style={{ width: 64, height: 64, borderRadius: "50%", background: "var(--color-primary-light, rgba(21,119,74,.10))", color: "var(--color-primary)", display: "inline-flex", alignItems: "center", justifyContent: "center", marginBottom: 14 }}>
        <FileText size={28} />
      </span>
      <div style={{ fontFamily: "var(--font-display)", fontSize: 20, fontWeight: 700, marginBottom: 6 }}>No reports yet</div>
      <div style={{ fontSize: 14, color: "var(--color-text-muted)", marginBottom: 22 }}>Keep every prescription, lab result and scan in one secure place.</div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 14, maxWidth: 680, margin: "0 auto 24px", textAlign: "left" }}>
        {steps.map(([I, t, d], i) => (
          <div key={t} style={{ padding: 14, borderRadius: 12, background: "var(--color-bg)" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, fontWeight: 700, fontSize: 13.5, marginBottom: 4 }}>
              <span style={{ width: 24, height: 24, borderRadius: "50%", background: "var(--color-primary)", color: "#fff", fontSize: 12, display: "inline-flex", alignItems: "center", justifyContent: "center" }}>{i + 1}</span>
              <I size={15} style={{ color: "var(--color-primary)" }} /> {t}
            </div>
            <div style={{ fontSize: 12.5, color: "var(--color-text-muted)", lineHeight: 1.45 }}>{d}</div>
          </div>
        ))}
      </div>
      <button className="btn-primary" onClick={onUpload}><Plus size={16} /> Upload Report</button>
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
    { pageSize: 100, params: patientAwpid ? { patient_awpid: patientAwpid } : {} },
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

  // ── background uploads + sorting (context/UploadContext) ──────────────
  const uploads = useUploads();
  const upVersion = uploads?.version || 0;
  useEffect(() => { if (upVersion) refetch(); }, [upVersion]); // eslint-disable-line react-hooks/exhaustive-deps

  const readyDocs = useMemo(() => docs.filter(d => !inFlight(d)), [docs]);
  // Files the server is still sorting — the list's copy, overlaid with the
  // live status the uploader polls (stage + place in queue).
  const sortingDocs = useMemo(() => {
    const live = new Map((uploads?.docs || []).map(d => [d.id, d]));
    const m = new Map();
    docs.filter(inFlight).forEach(d => m.set(d.id, { ...d, ...(live.get(d.id) || {}) }));
    (uploads?.docs || []).filter(d => inFlight(d) && !d.manual && (d.patientAwpid || "") === patientAwpid)
      .forEach(d => m.set(d.id, { ...(m.get(d.id) || {}), ...d }));
    return [...m.values()].filter(inFlight);
  }, [docs, uploads?.docs, patientAwpid]);
  // One human check per auto-sorted upload (the hospital QR counts as checked).
  const toVerify = useMemo(() => readyDocs.filter(d =>
    d.uploaded_by === "patient" && d.verification_status !== "verified"
    && ["pending", "partial"].includes(d.classification_status)), [readyDocs]);

  // The organize screen: {mode:"manual", files} before upload, or {mode:"verify"}.
  const [organize, setOrganize] = useState(null);
  const [addOpen, setAddOpen] = useState(false);
  function organizeManually(files) { setAddOpen(false); setOrganize({ mode: "manual", files }); }
  function autoSegregate(files) {
    const { accepted, rejected } = uploads.addFiles(files, patientAwpid);
    setAddOpen(false);
    if (rejected.length) toastError(`${rejected.length} skipped: ${rejected.map(r => `${r.name} (${r.reason})`).join(", ")}`);
    if (accepted) setOrganize({ mode: "verify" });
  }

  const [searchParams, setSearchParams] = useSearchParams();
  useEffect(() => {    // Notifications / the header chip link here with ?tab=verify
    if (searchParams.get("tab") === "verify") {
      setOrganize({ mode: "verify" });
      searchParams.delete("tab");
      setSearchParams(searchParams, { replace: true });
    }
  }, [searchParams, setSearchParams]);

  // ── filters ────────────────────────────────────────────────────────────
  const [tab, setTab] = useState("all");
  const [q, setQ] = useState("");
  const [dFrom, setDFrom] = useState("");
  const [dTo, setDTo] = useState("");
  const [showDates, setShowDates] = useState(false);
  const [catSel, setCatSel] = useState(() => new Set());
  const [showCatMenu, setShowCatMenu] = useState(false);
  const [hospital, setHospital] = useState("");
  const [folderSel, setFolderSel] = useState("");
  const [sort, setSort] = useState("newest");
  const [insightsOpen, setInsightsOpen] = useState(false);
  const [picking, setPicking] = useState(false);
  const [sel, setSel] = useState(() => new Set());
  const [detail, setDetail] = useState(null);

  const filed = useMemo(() => readyDocs.filter(d => d.review_state !== "unsorted"), [readyDocs]);
  const counts = useMemo(() => {
    const c = { all: filed.length };
    PILL_TABS.forEach(([t]) => { if (t !== "all") c[t] = 0; });
    filed.forEach(d => { c[d.doc_type] = (c[d.doc_type] || 0) + 1; });
    return c;
  }, [filed]);
  const hospitals = useMemo(() => [...new Set(filed.map(d => d.hospital_label).filter(Boolean))].sort(), [filed]);
  const myFolders = useMemo(() => [...new Set(filed.map(d => d.folder).filter(Boolean))].sort(), [filed]);

  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const list = filed
      .filter(d => tab === "all" || d.doc_type === tab)
      .filter(d => !hospital || d.hospital_label === hospital)
      .filter(d => !folderSel || d.folder === folderSel)
      .filter(d => !catSel.size || (d.report_categories || []).some(c => catSel.has(c)))
      .filter(d => inRange(d.document_date || d.created_at, dFrom, dTo))
      .filter(d => !needle || [d.title, d.hospital_label, d.doctor_label, d.public_document_id, d.folder,
        ...(d.report_categories || []).map(catLabel), (TYPE_TONE[d.doc_type] || {}).label].join(" ").toLowerCase().includes(needle));
    const key = (d) => String(d.document_date || d.created_at || "");
    return list.sort((a, b) => (sort === "oldest" ? key(a).localeCompare(key(b))
      : sort === "name" ? (a.title || "").localeCompare(b.title || "") : key(b).localeCompare(key(a))));
  }, [filed, tab, hospital, folderSel, catSel, dFrom, dTo, q, sort]);

  const groups = useMemo(() => {
    if (sort === "name") return [{ key: "all", label: "", list: shown }];
    const out = [];
    shown.forEach(d => {
      const { key, label } = monthOf(d.document_date || d.created_at);
      if (!out.length || out[out.length - 1].key !== key) out.push({ key, label, list: [] });
      out[out.length - 1].list.push(d);
    });
    return out;
  }, [shown, sort]);

  const anyFilter = tab !== "all" || q || dFrom || dTo || catSel.size || hospital || folderSel;
  const clearFilters = () => { setTab("all"); setQ(""); setDFrom(""); setDTo(""); setCatSel(new Set()); setHospital(""); setFolderSel(""); };

  // ── actions ────────────────────────────────────────────────────────────
  const awpidParam = patientAwpid ? { patient_awpid: patientAwpid } : {};
  async function openFile(doc, download) {
    const win = window.open("", "_blank");
    try {
      const res = await apiClient.get(API_ENDPOINTS.PORTAL.DOCUMENT(doc.id), { params: { ...(download ? { download: 1 } : {}), ...awpidParam } });
      const fd = (res.data?.data || res.data)?.file_data;
      if (fd) openDataUrlInNewTab(win, fd); else win?.close();
    } catch (err) { win?.close(); toastApiError(err, "Could not open the file."); }
  }
  async function deleteDoc(doc) {
    if (!window.confirm(`Delete “${doc.title}” from your reports?`)) return;
    try {
      await apiClient.delete(API_ENDPOINTS.PORTAL.DOCUMENT(doc.id), { params: awpidParam });
      toastSuccess("Deleted from your reports.");
      refetch();
    } catch (err) { toastApiError(err, "Could not delete."); }
  }
  function toggleSel(id) {
    setSel(prev => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n; });
  }
  async function downloadSelected() {
    const ids = [...sel];
    if (!ids.length) return;
    if (ids.length === 1) { openFile(docs.find(d => d.id === ids[0]), true); return; }
    try {
      const res = await apiClient.post(API_ENDPOINTS.PORTAL.DOCUMENTS_ZIP, { ids, ...awpidParam }, { responseType: "blob" });
      const url = URL.createObjectURL(res.data);
      const a = document.createElement("a");
      a.href = url; a.download = `my-reports-${new Date().toISOString().slice(0, 10)}.zip`;
      a.click(); URL.revokeObjectURL(url);
      setPicking(false); setSel(new Set());
    } catch { toastError("Could not build the ZIP."); }
  }

  if (organize) {
    return (
      <AppShell>
        <PageShell>
          <OrganizeDocuments mode={organize.mode} files={organize.files} patientAwpid={patientAwpid}
            onBack={() => setOrganize(null)}
            onDone={() => { setOrganize(null); refetch(); }} />
        </PageShell>
      </AppShell>
    );
  }

  const otherCount = (counts.prescription || 0) + (counts.discharge_summary || 0) + (counts.other || 0);
  const nothingYet = !isLoading && !docs.length && !sortingDocs.length && !(uploads?.summary?.upload?.active);
  const chip = (on) => (on ? { borderColor: "var(--color-primary)", color: "var(--color-primary)" } : {});

  return (
    <AppShell>
      <PageShell>
        {/* ── header ── */}
        <div style={{ display: "flex", alignItems: "flex-start", gap: 12, flexWrap: "wrap", marginBottom: 18 }}>
          <div style={{ flex: 1, minWidth: 240 }}>
            <h1 className="page-title" style={{ margin: 0 }}>
              {selectedPatient?.isSelf === false ? `${selectedPatient?.name || "Family member"}'s Reports` : "My Reports"}
            </h1>
            <div style={{ fontSize: 14, color: "var(--color-text-muted)", marginTop: 4 }}>
              All your medical reports, lab results, scans and documents in one place.
            </div>
          </div>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            {privEnabled && (
              <Link to={ROUTES.PATIENT.SHARED_RECORDS_PRIVACY} className="btn-outline" style={{ display: "inline-flex", alignItems: "center", gap: 7, textDecoration: "none" }}>
                <Share2 size={15} /> Share Records
              </Link>
            )}
            <button className="btn-primary" onClick={() => setAddOpen(true)}><Plus size={16} /> Upload Report</button>
          </div>
        </div>

        {privEnabled && privSession && (
          <div className="card" style={{ padding: "10px 13px", marginBottom: 14, display: "flex", gap: 9, alignItems: "flex-start", borderColor: "var(--color-warning, #b45309)", background: "var(--color-warning-light, #fbf3e6)" }}>
            <Clock size={13} style={{ marginTop: 2, flexShrink: 0, color: "var(--color-warning, #b45309)" }} />
            <span style={{ fontSize: 12.5, lineHeight: 1.5 }}>
              <b>{privSession.requester_label || "A doctor"} is viewing your records now.</b> Making a report visible
              asks whether it&rsquo;s <b>just this visit</b> or <b>always</b>. Locking one takes effect right away.
            </span>
          </div>
        )}

        <ActivityCard uploads={uploads} sortingDocs={sortingDocs} toVerify={toVerify}
          onReview={() => setOrganize({ mode: "verify" })} />

        {nothingYet ? <EmptyState onUpload={() => setAddOpen(true)} /> : (
          <>
            {/* ── stat cards ── */}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 14, marginBottom: 18 }}>
              <StatCard icon={FileText} tone={{ fg: "var(--color-primary)", bg: "var(--color-primary-light, rgba(21,119,74,.10))" }} n={counts.all}
                title="Total Reports" sub="Across all categories" active={tab === "all"} onClick={() => setTab("all")} />
              <StatCard icon={FlaskConical} tone={TYPE_TONE.lab_report} n={counts.lab_report || 0}
                title="Lab Reports" sub="Blood, urine, etc." active={tab === "lab_report"} onClick={() => setTab("lab_report")} />
              <StatCard icon={ImageIcon} tone={TYPE_TONE.scan} n={counts.scan || 0}
                title="Scan Reports" sub="X-ray, MRI, CT, etc." active={tab === "scan"} onClick={() => setTab("scan")} />
              <StatCard icon={Pill} tone={TYPE_TONE.other} n={otherCount}
                title="Other Reports" sub="Prescriptions, discharge, other" active={["prescription", "discharge_summary", "other"].includes(tab)} onClick={() => setTab("prescription")} />
            </div>

            {/* ── search + filters ── */}
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center", marginBottom: 12 }}>
              <label className="form-input" style={{ display: "flex", alignItems: "center", gap: 9, flex: "1 1 320px", padding: "9px 12px" }}>
                <Search size={16} style={{ color: "var(--color-text-muted)" }} />
                <input value={q} onChange={e => setQ(e.target.value)} placeholder="Search by report name, hospital, doctor, or test (e.g. CBC, MRI)"
                  style={{ border: "none", outline: "none", background: "none", width: "100%", fontSize: 13.5 }} />
              </label>
              <div style={{ position: "relative" }}>
                <button className="btn-outline" style={chip(dFrom || dTo)} onClick={() => setShowDates(v => !v)}>
                  <Calendar size={14} /> {dFrom || dTo ? `${dFrom ? fmtShort(dFrom) : "…"} – ${dTo ? fmtShort(dTo) : "…"}` : "Date range"} <ChevronDown size={14} />
                </button>
                {showDates && (
                  <div className="card" style={{ position: "absolute", zIndex: 25, top: "calc(100% + 6px)", left: 0, padding: 12, display: "flex", gap: 10, flexWrap: "wrap", alignItems: "flex-end", minWidth: 300 }}>
                    <label style={{ fontSize: 12, color: "var(--color-text-muted)" }}>From
                      <input type="date" className="form-input" value={dFrom} max={dTo || undefined} onChange={e => setDFrom(e.target.value)} style={{ display: "block", padding: "6px 9px" }} />
                    </label>
                    <label style={{ fontSize: 12, color: "var(--color-text-muted)" }}>To
                      <input type="date" className="form-input" value={dTo} min={dFrom || undefined} onChange={e => setDTo(e.target.value)} style={{ display: "block", padding: "6px 9px" }} />
                    </label>
                    <button className="btn-outline" style={{ fontSize: 12, padding: "6px 10px" }} onClick={() => { setDFrom(""); setDTo(""); setShowDates(false); }}>Clear</button>
                  </div>
                )}
              </div>
              <div style={{ position: "relative" }}>
                <button className="btn-outline" style={chip(catSel.size)} onClick={() => setShowCatMenu(v => !v)}>
                  <Tag size={14} /> {catSel.size ? (catSel.size === 1 ? catLabel([...catSel][0]) : `${catSel.size} categories`) : "All categories"} <ChevronDown size={14} />
                </button>
                {showCatMenu && (
                  <div className="card" style={{ position: "absolute", zIndex: 25, top: "calc(100% + 6px)", left: 0, minWidth: 240, padding: 6, maxHeight: 340, overflowY: "auto" }}>
                    <button onClick={() => setCatSel(new Set())}
                      style={{ display: "flex", width: "100%", padding: "8px 9px", fontSize: 12.5, background: catSel.size ? "transparent" : "var(--color-primary-light)", border: "none", borderRadius: 7, cursor: "pointer", fontWeight: 600 }}>
                      All categories
                    </button>
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
              {hospitals.length > 0 && (
                <select className="form-input" value={hospital} onChange={e => setHospital(e.target.value)} style={{ width: "auto", padding: "9px 12px", ...chip(hospital) }}>
                  <option value="">All hospitals</option>
                  {hospitals.map(h => <option key={h} value={h}>{h}</option>)}
                </select>
              )}
              {myFolders.length > 0 && (
                <select className="form-input" value={folderSel} onChange={e => setFolderSel(e.target.value)} style={{ width: "auto", padding: "9px 12px", ...chip(folderSel) }}>
                  <option value="">All my folders</option>
                  {myFolders.map(f => <option key={f} value={f}>{f}</option>)}
                </select>
              )}
              <select className="form-input" value={sort} onChange={e => setSort(e.target.value)} style={{ width: "auto", padding: "9px 12px" }} aria-label="Sort">
                <option value="newest">Newest first</option>
                <option value="oldest">Oldest first</option>
                <option value="name">Name A–Z</option>
              </select>
            </div>

            {/* ── type pills ── */}
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", marginBottom: 16 }}>
              {PILL_TABS.filter(([t]) => t === "all" || counts[t]).map(([t, l]) => {
                const on = tab === t;
                const I = t === "all" ? null : TYPE_ICON[t];
                return (
                  <button key={t} onClick={() => setTab(t)} style={{
                    display: "inline-flex", alignItems: "center", gap: 6, padding: "7px 14px", borderRadius: 999, cursor: "pointer", fontSize: 13,
                    border: `1px solid ${on ? "var(--color-primary)" : "var(--color-border)"}`,
                    background: on ? "var(--color-primary)" : "var(--color-surface, #fff)", color: on ? "#fff" : "var(--color-text-secondary)", fontWeight: on ? 600 : 500,
                  }}>
                    {I && <I size={13} />} {l} ({counts[t] || 0})
                  </button>
                );
              })}
              <span style={{ flex: 1 }} />
              {anyFilter && <button onClick={clearFilters} style={{ background: "none", border: "none", color: "var(--color-primary)", fontWeight: 600, fontSize: 13, cursor: "pointer" }}>Clear filters</button>}
              <button className="btn-outline" style={{ padding: "6px 12px", fontSize: 13 }} onClick={() => { setPicking(p => !p); setSel(new Set()); }}>
                <CheckSquare size={14} /> {picking ? "Cancel" : "Select"}
              </button>
            </div>

            {picking && (
              <div className="card" style={{ padding: "10px 14px", marginBottom: 12, display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
                <span style={{ fontSize: 13 }}><b>{sel.size}</b> selected</span>
                <button className="btn-outline" style={{ fontSize: 12, padding: "5px 10px" }} onClick={() => setSel(new Set(shown.map(d => d.id)))}>Select all in view</button>
                <span style={{ flex: 1 }} />
                <button className="btn-primary" style={{ fontSize: 13, padding: "6px 14px" }} disabled={!sel.size} onClick={downloadSelected}>
                  <Download size={14} /> {sel.size === 1 ? "Download" : "Download ZIP"}
                </button>
              </div>
            )}

            {/* ── health insights (collapsed) ── */}
            <div className="card" style={{ marginBottom: 16, overflow: "hidden" }}>
              <button type="button" onClick={() => setInsightsOpen(v => !v)} style={{ width: "100%", display: "flex", alignItems: "center", justifyContent: "space-between", padding: "12px 16px", background: "none", border: "none", cursor: "pointer" }}>
                <span style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 14, fontWeight: 700, color: "var(--color-text)" }}>
                  <Sparkles size={15} color="var(--color-primary)" /> Health Insights
                </span>
                {insightsOpen ? <ChevronUp size={16} color="var(--color-text-muted)" /> : <ChevronDown size={16} color="var(--color-text-muted)" />}
              </button>
              {insightsOpen && (
                <div style={{ padding: "0 16px 18px" }}>
                  <HealthInsightsPanel patientAwpid={patientAwpid}
                    onOpenDocument={(id) => { const d = docs.find(x => x.id === id); if (d) setDetail(d); }} />
                </div>
              )}
            </div>

            {/* ── the list ── */}
            {isLoading ? (
              <div className="card" style={{ padding: 40, textAlign: "center", color: "var(--color-text-muted)" }}>Loading…</div>
            ) : shown.length === 0 ? (
              <div className="card" style={{ padding: 40, textAlign: "center" }}>
                <div style={{ fontWeight: 600, marginBottom: 6 }}>{filed.length ? "Nothing matches these filters." : "Your reports will appear here once they're sorted."}</div>
                {anyFilter && <button className="btn-outline" onClick={clearFilters}>Clear filters</button>}
              </div>
            ) : (
              <>
                {groups.map(g => (
                  <div key={g.key} style={{ marginBottom: 18 }}>
                    {g.label && <div style={{ fontSize: 15, fontWeight: 700, margin: "4px 0 10px" }}>{g.label}</div>}
                    {g.list.map(d => (
                      <ReportRow key={d.id} doc={d} picking={picking} selected={sel.has(d.id)} onToggle={() => toggleSel(d.id)}
                        priv={privEnabled ? privMap.get(d.id) : undefined}
                        onView={() => openFile(d, false)} onDownload={() => openFile(d, true)}
                        onDetails={() => setDetail(d)} onLock={privEnabled ? () => onLock(d) : null}
                        onDelete={() => deleteDoc(d)} />
                    ))}
                  </div>
                ))}
                {hasMore && <button className="btn-outline" style={{ width: "100%" }} onClick={loadMore}>Load more</button>}
              </>
            )}

            {privEnabled && (
              <div style={{ fontSize: 12, color: "var(--color-text-muted)", marginTop: 14, display: "flex", alignItems: "center", gap: 6 }}>
                <Lock size={12} />
                <span><b>{privateCount}</b> of {privMap.size || docs.length} reports private — hidden from doctors you share with.</span>
                <Link to={ROUTES.PATIENT.SHARED_RECORDS_PRIVACY} style={{ color: "var(--color-primary)", fontWeight: 600, textDecoration: "none" }}>Manage →</Link>
              </div>
            )}
          </>
        )}

        <style>{`
          .mr-spin { animation: mr-spin 1s linear infinite; }
          @keyframes mr-spin { to { transform: rotate(360deg); } }
          .mr-row { transition: box-shadow .15s; }
          .mr-row:hover { box-shadow: 0 2px 10px rgba(15,23,20,.07); }
          @media (max-width: 760px) {
            .mr-row { flex-wrap: wrap; }
            .mr-badges { order: 3; width: 100%; padding-left: 60px; }
          }
        `}</style>
      </PageShell>

      {addOpen && (
        <AddModal onClose={() => setAddOpen(false)} onManual={organizeManually} onAuto={autoSegregate} />
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

const iconBtn = { background: "none", border: "none", cursor: "pointer", color: "var(--color-text-muted)", padding: 4, display: "inline-flex" };
