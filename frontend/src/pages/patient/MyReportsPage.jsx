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
import { useMemo, useRef, useState } from "react";
import {
  FileText, Pill, FlaskConical, HelpCircle, ShieldCheck, X, Download,
  Tag, Trash2, EyeOff, Camera, QrCode, Upload, FolderUp, Plus, Search, CheckSquare,
} from "lucide-react";
import { AppShell } from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import { usePaginatedList } from "../../hooks/usePaginatedList";
import { useToast } from "../../hooks/useToast";
import apiClient from "../../services/api.client";
import API_ENDPOINTS from "../../config/api.config";
import { usePatientContext } from "../../context/PatientContext";
import { openDataUrlInNewTab } from "../../utils/fileViewer";

const MAX_FILE_BYTES = 5 * 1024 * 1024; // matches the backend's single-upload guard
const OK_EXT = /\.(pdf|jpe?g|png)$/i;

const TYPE_META = {
  prescription: { tag: "RX", label: "Prescription", Icon: Pill },
  lab_report:   { tag: "LAB", label: "Lab report", Icon: FlaskConical },
  scan:         { tag: "SCAN", label: "Scan", Icon: FileText },
  discharge_summary: { tag: "DISCH", label: "Discharge summary", Icon: FileText },
  other:        { tag: "DOC", label: "Document", Icon: FileText },
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

/* ─────────────────────────────────────────────────────────── one row */
function DocRow({ doc, picking, selected, onToggle, onOpen, onClassify }) {
  const m = TYPE_META[doc.doc_type] || TYPE_META.other;
  const unsorted = doc.review_state === "unsorted";
  const sub = unsorted
    ? "Not yet filed — tell us what this is"
    : [doc.hospital_label || (doc.doctor_label ? "" : ""), doc.doctor_label].filter(Boolean).join(" · ")
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
        </div>
      </div>

      {unsorted && (
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 10, paddingTop: 10, borderTop: "1px dashed var(--color-border)" }}>
          <span style={{ fontSize: 12, color: "var(--color-text-muted)" }}>File as</span>
          <button className="btn-outline" style={{ fontSize: 12, padding: "4px 10px" }} onClick={e => { e.stopPropagation(); onClassify("prescription"); }}>Prescription</button>
          <button className="btn-outline" style={{ fontSize: 12, padding: "4px 10px" }} onClick={e => { e.stopPropagation(); onClassify("lab_report"); }}>Lab report</button>
          <button style={{ fontSize: 12, padding: "4px 10px", background: "none", border: "1px solid var(--color-border)", borderRadius: 6, color: "var(--color-text-muted)", cursor: "pointer" }}
            onClick={e => { e.stopPropagation(); onClassify("__remove__"); }}>Not medical</button>
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
  const hospital = !!doc.source_tenant_id;

  async function view(download) {
    const win = window.open("", "_blank");
    try {
      const res = await apiClient.get(API_ENDPOINTS.PORTAL.DOCUMENT(doc.id), { params: download ? { download: 1 } : {} });
      const fd = (res.data?.data || res.data)?.file_data;
      if (fd) openDataUrlInNewTab(win, fd); else win?.close();
    } catch (err) { win?.close(); toastApiError(err, "Could not open the file."); }
  }
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
      toastSuccess(hospital ? "Hidden from your reports." : "Deleted.");
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
            <button className="btn-primary" style={{ flex: 1 }} onClick={() => view(false)}><Download size={15} /> View / Download</button>
            {doc.verification_status !== "verified" && (
              <button className="btn-outline" style={{ flex: 1 }} disabled={busy} onClick={() => setRecat(v => !v)}><Tag size={15} /> Re-categorise</button>
            )}
          </div>
          {recat && (
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", padding: 10, background: "var(--color-bg)", borderRadius: 8 }}>
              <span style={{ width: "100%", fontSize: 12, color: "var(--color-text-muted)" }}>Move to</span>
              <button className="btn-outline" style={{ fontSize: 12, padding: "4px 10px" }} disabled={busy} onClick={() => move("prescription")}>Prescription</button>
              <button className="btn-outline" style={{ fontSize: 12, padding: "4px 10px" }} disabled={busy} onClick={() => move("lab_report")}>Lab report</button>
            </div>
          )}
          <button className="btn-outline" style={{ color: "var(--color-danger)", borderColor: "var(--color-danger)" }} disabled={busy} onClick={remove}>
            {hospital ? <><EyeOff size={15} /> Hide from my reports</> : <><Trash2 size={15} /> Delete</>}
          </button>
          {hospital && (
            <div style={{ fontSize: 11, color: "var(--color-text-muted)" }}>
              Hiding removes it from your list only — the hospital's record is unchanged.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────── add flow */
function AddModal({ onClose, onDone, patientAwpid }) {
  const { toastError } = useToast();
  const [phase, setPhase] = useState("pick");        // pick | stage | upload | done
  const [items, setItems] = useState([]);            // {file, name, size, skip}
  const [prog, setProg] = useState({ done: 0, total: 0, name: "" });
  const [result, setResult] = useState({ rx: 0, lab: 0, unsorted: 0, dup: 0, failed: 0 });
  const filesRef = useRef(null);
  const folderRef = useRef(null);
  const camRef = useRef(null);
  const mob = isMobile();

  function stage(fileList) {
    const arr = Array.from(fileList || []).map(f => ({
      file: f, name: f.name || "photo.jpg", size: f.size,
      skip: !(OK_EXT.test(f.name || "") || /^image\/(jpeg|png)$|^application\/pdf$/.test(f.type)),
    }));
    if (!arr.length) return;
    setItems(prev => [...prev, ...arr]);
    setPhase("stage");
  }

  async function run() {
    const ready = items.filter(i => !i.skip);
    if (!ready.length) { toastError("Nothing to upload."); return; }
    setPhase("upload");
    const r = { rx: 0, lab: 0, unsorted: 0, dup: 0, failed: 0 };
    for (let i = 0; i < ready.length; i++) {
      const it = ready[i];
      setProg({ done: i, total: ready.length, name: it.name });
      try {
        if (it.size > MAX_FILE_BYTES) { r.failed++; continue; }
        const dataUrl = await fileToDataUrl(it.file);
        const qr = it.file.type.startsWith("image/") ? await tryDecodeQR(it.file) : "";
        const res = await apiClient.post(API_ENDPOINTS.PORTAL.DOCUMENTS, {
          title: it.name.replace(OK_EXT, ""),
          file_data: dataUrl, file_name: it.name, mime_type: it.file.type || "application/pdf",
          ...(qr ? { qr_token: qr } : {}),
          ...(patientAwpid ? { patient_awpid: patientAwpid } : {}),
        });
        const d = res.data?.data || res.data;
        if (res.status === 200 && d?.duplicate) { r.dup++; continue; }
        if (d?.review_state === "unsorted") r.unsorted++;
        else if (d?.doc_type === "prescription") r.rx++;
        else if (d?.doc_type === "lab_report") r.lab++;
        else r.unsorted++;
      } catch { r.failed++; }
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
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginTop: 6 }}>
              <Method Icon={QrCode} title="Scan QR" desc="Point at the code on a hospital document" off={!mob} onClick={() => camRef.current?.click()} />
              <Method Icon={Camera} title="Take photo" desc="Capture a printed document" off={!mob} onClick={() => camRef.current?.click()} />
              <Method Icon={Upload} title="Upload files" desc="One or more PDFs or images" onClick={() => filesRef.current?.click()} />
              <Method Icon={FolderUp} title="Upload folder" desc="We keep the reports, skip the rest" onClick={() => folderRef.current?.click()} />
            </div>
            {!mob && <p style={{ ...sub, marginTop: 10 }}>Scan QR and Take photo need a camera — open My Reports on your phone.</p>}
          </>
        )}

        {phase === "stage" && (
          <>
            <h3 style={h3}>Review {ready.length} file{ready.length !== 1 ? "s" : ""}</h3>
            <p style={sub}>{ready.length} ready{skipped ? ` · ${skipped} skipped (not a PDF or image)` : ""}</p>
            <div style={{ maxHeight: 300, overflowY: "auto", border: "1px solid var(--color-border)", borderRadius: 8, padding: 4, margin: "10px 0" }}>
              {items.map((it, idx) => (
                <div key={idx} style={{ display: "flex", alignItems: "center", gap: 10, padding: "7px 8px", fontSize: 12.5, opacity: it.skip ? 0.5 : 1 }}>
                  <FileText size={15} style={{ color: "var(--color-text-muted)" }} />
                  <span style={{ flex: 1, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", textDecoration: it.skip ? "line-through" : "none" }}>{it.name}</span>
                  <span style={{ color: "var(--color-text-muted)", fontSize: 11 }}>{(it.size / 1024 / 1024).toFixed(1)} MB</span>
                  {it.skip
                    ? <span style={{ fontSize: 10, color: "var(--color-text-muted)" }}>SKIPPED</span>
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
              {result.failed > 0 && <SumRow label="Failed (too large or unreadable)" n={result.failed} />}
            </div>
            {result.unsorted > 0 && (
              <p style={sub}>The {result.unsorted} unrecognised item{result.unsorted !== 1 ? "s" : ""} wait in the Unsorted tab — one tap tells us what they are.</p>
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

  const [tab, setTab] = useState("all");
  const [q, setQ] = useState("");
  const [picking, setPicking] = useState(false);
  const [sel, setSel] = useState(() => new Set());
  const [addOpen, setAddOpen] = useState(false);
  const [detail, setDetail] = useState(null);

  const counts = useMemo(() => {
    const c = { all: 0, prescription: 0, lab_report: 0, unsorted: 0 };
    docs.forEach(d => {
      if (d.review_state === "unsorted") c.unsorted++;
      else { c.all++; if (d.doc_type === "prescription") c.prescription++; if (d.doc_type === "lab_report") c.lab_report++; }
    });
    return c;
  }, [docs]);

  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return docs
      .filter(d => (tab === "all" ? d.review_state !== "unsorted" : tab === "unsorted" ? d.review_state === "unsorted" : d.doc_type === tab && d.review_state !== "unsorted"))
      .filter(d => !needle || [d.title, d.hospital_label, d.doctor_label, d.public_document_id].join(" ").toLowerCase().includes(needle));
  }, [docs, tab, q]);

  const groups = useMemo(() => {
    const map = new Map();
    shown.forEach(d => {
      const k = fmtDate(d.document_date || d.created_at) || "—";
      if (!map.has(k)) map.set(k, []);
      map.get(k).push(d);
    });
    return [...map.entries()];
  }, [shown]);

  function toggleSel(id) {
    setSel(prev => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n; });
  }
  async function classify(doc, type) {
    try {
      if (type === "__remove__") {
        await apiClient.delete(API_ENDPOINTS.PORTAL.DOCUMENT(doc.id));
        toastSuccess("Removed.");
      } else {
        await apiClient.patch(API_ENDPOINTS.PORTAL.DOCUMENT(doc.id), { doc_type: type });
        toastSuccess(`Filed under ${type === "prescription" ? "Prescriptions" : "Lab reports"}.`);
      }
      refetch();
    } catch (err) { toastApiError(err, "Could not update."); }
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
          {tab !== "unsorted" && (
            <button className="btn-outline" onClick={() => { setPicking(p => !p); setSel(new Set()); }}>
              <CheckSquare size={14} /> {picking ? "Cancel" : "Select"}
            </button>
          )}
        </div>

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
            <span style={{ fontSize: 13 }}><b>{counts.unsorted}</b> uploaded file{counts.unsorted !== 1 ? "s" : ""} need your review.</span>
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
              {q ? `Nothing matches “${q}”.` : tab === "unsorted" ? "Nothing to review." : "No reports yet."}
            </div>
            {!q && tab !== "unsorted" && <div style={{ fontSize: 13, color: "var(--color-text-muted)" }}>Tap “Add” to upload a prescription or report.</div>}
          </div>
        ) : (
          <>
            {groups.map(([day, list]) => (
              <div key={day} style={{ marginBottom: 20 }}>
                <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: ".06em", textTransform: "uppercase", color: "var(--color-text-muted)", marginBottom: 8 }}>{day}</div>
                {list.map(d => (
                  <DocRow key={d.id} doc={d} picking={picking} selected={sel.has(d.id)}
                    onToggle={() => toggleSel(d.id)} onOpen={() => setDetail(d)}
                    onClassify={type => classify(d, type)} />
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
