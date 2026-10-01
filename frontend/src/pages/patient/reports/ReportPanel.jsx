/**
 * The details of one report: Details · Preview · Activity, and what the patient can do about it.
 * Loads the full record (GET /portal/documents/<id>/) for the signed file link, the types the patient can
 * choose from, and the activity.
 */
import { useEffect, useState } from "react";
import { Download, FileText, Image as ImageIcon, Lock, Trash2, Unlock, X } from "lucide-react";
import { useToast } from "../../../hooks/useToast";
import apiClient from "../../../services/api.client";
import API_ENDPOINTS from "../../../config/api.config";
import { chipsFor, closestMatch, fileKind, fmtDate, formatSize, stateOf, typeLabel } from "../../../utils/reports";
import { FILE_TILE, TONE, chip, h3, iconBtn, inputStyle } from "./reportStyles";

const STATE_LABEL = { processing: "Being read", ready: "Available", unclassified: "Available — type unknown", failed: "Couldn’t read", duplicate: "Not added (duplicate)" };

// What happened and what to do about it — the message at the top of the panel.
function explain(doc, original) {
  switch (stateOf(doc)) {
    case "processing": return { tone: "muted", title: "Still being read", body: "We’re reading this file now. This page updates by itself — you don’t need to wait." };
    case "failed": return { tone: "error", title: "We couldn’t read this file", body: `${doc.error || "Something went wrong while reading it."} You can try again, file it under a type yourself, or delete it.` };
    case "duplicate": return { tone: "warn", title: "This file is already in your reports",
      body: `${original ? `It’s the same as “${original.title}”. ` : doc.error ? `${doc.error} ` : ""}We didn’t add it a second time. Keep it anyway if you want both copies, or delete this one.` };
    case "unclassified": return { tone: "warn", title: "We couldn’t tell what this is",
      body: `None of the report types set up here matched it${closestMatch(doc) ? ` (${closestMatch(doc)})` : ""}. Choose the right type so it’s filed correctly.` };
    default: return null;
  }
}

function InfoRow({ label, children }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "150px 1fr", gap: 12, padding: "10px 0", borderTop: "1px solid var(--color-border)", fontSize: 13, alignItems: "center" }}>
      <span style={{ color: "var(--color-text-muted)" }}>{label}</span>
      <span style={{ fontWeight: 500, wordBreak: "break-word", display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>{children}</span>
    </div>
  );
}

export default function ReportPanel({ doc, original, patientAwpid, priv, onLock, onClose, onAct, onDelete, onChanged }) {
  const { toastSuccess, toastApiError } = useToast();
  const [tab, setTab] = useState("details");
  const [detail, setDetail] = useState(null);           // the full record: file link, choosable types, activity
  const [choosing, setChoosing] = useState(false);
  const [newType, setNewType] = useState(doc.doc_type || "");
  const [busy, setBusy] = useState(false);
  const state = stateOf(doc);
  const kind = fileKind(doc);
  const chips = chipsFor(doc);
  const hospital = !!doc.source_tenant_id || doc.uploaded_by === "staff";
  const canRetype = !hospital && state !== "duplicate" && state !== "processing";
  const note = explain(doc, original);
  const params = patientAwpid ? { patient_awpid: patientAwpid } : {};
  const Icon = kind === "image" ? ImageIcon : FileText;

  useEffect(() => {          // a different report: start again on Details
    setTab("details"); setChoosing(false); setNewType(doc.doc_type || ""); setDetail(null);
    let alive = true;
    apiClient.get(API_ENDPOINTS.PORTAL.DOCUMENT(doc.id), { params })
      .then(res => { if (alive) setDetail(res.data?.data || res.data); })
      .catch(() => { if (alive) setDetail({ file_data: "", doc_types: [], events: [] }); });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reload only when another report (or its state) is shown
  }, [doc.id, doc.processing_status, doc.doc_type]);

  async function saveType() {
    setBusy(true);
    try {
      await apiClient.patch(API_ENDPOINTS.PORTAL.DOCUMENT(doc.id), { doc_type: newType }, { params });
      toastSuccess(`Filed under ${typeLabel(newType)}.`);
      setChoosing(false); onChanged();
    } catch (err) { toastApiError(err, "Could not change the type."); } finally { setBusy(false); }
  }
  async function act(payload, message) { setBusy(true); await onAct(doc, payload, message); setBusy(false); }
  const openInNewTab = () => { if (detail?.file_data) window.open(detail.file_data, "_blank", "noopener"); };
  async function download() {
    try {
      const res = await apiClient.get(API_ENDPOINTS.PORTAL.DOCUMENT(doc.id), { params: { ...params, download: 1 } });
      const url = (res.data?.data || res.data)?.file_data;
      if (url) window.open(url, "_blank", "noopener");
    } catch (err) { toastApiError(err, "Could not download the file."); }
  }

  return (
    <div className="card" style={{ padding: 20 }}>
      <div style={{ display: "flex", alignItems: "flex-start", gap: 12, marginBottom: 14 }}>
        <div style={{ flex: 1, ...h3, wordBreak: "break-word" }}>{doc.title}</div>
        <button aria-label="Close details" onClick={onClose} style={iconBtn}><X size={18} /></button>
      </div>

      <div role="tablist" style={{ display: "flex", gap: 4, borderBottom: "1px solid var(--color-border)", marginBottom: 14 }}>
        {[["details", "Details"], ["preview", "Preview"], ["activity", "Activity"]].map(([id, label]) => (
          <button key={id} role="tab" aria-selected={tab === id} onClick={() => setTab(id)}
            style={{ padding: "8px 14px", fontSize: 13, background: "none", border: "none", cursor: "pointer",
                     borderBottom: `2px solid ${tab === id ? "var(--color-primary)" : "transparent"}`,
                     color: tab === id ? "var(--color-primary)" : "var(--color-text-secondary)", fontWeight: tab === id ? 600 : 400 }}>{label}</button>
        ))}
      </div>

      {tab === "details" && (
        <>
          {note && (
            <div style={{ padding: "10px 12px", borderRadius: 9, marginBottom: 14, fontSize: 12.5, lineHeight: 1.5, border: `1px solid ${TONE[note.tone]}`, background: "var(--color-bg)" }}>
              <b style={{ color: TONE[note.tone] }}>{note.title}</b>
              <div style={{ color: "var(--color-text-secondary)", marginTop: 2 }}>{note.body}</div>
            </div>
          )}
          <div style={{ display: "flex", gap: 16, alignItems: "flex-start", flexWrap: "wrap" }}>
            <div style={{ width: 120, flexShrink: 0, textAlign: "center" }}>
              <div style={{ height: 130, borderRadius: 10, display: "flex", alignItems: "center", justifyContent: "center", ...FILE_TILE[kind] }}>
                {kind === "image" && detail?.file_data
                  ? <img src={detail.file_data} alt="" style={{ maxWidth: "100%", maxHeight: "100%", borderRadius: 8, objectFit: "cover" }} />
                  : <Icon size={40} />}
              </div>
              <button className="btn-outline" style={{ fontSize: 12, padding: "5px 8px", marginTop: 8, width: "100%" }}
                disabled={!detail?.file_data} onClick={openInNewTab}>Open in new tab</button>
            </div>
            <div style={{ flex: 1, minWidth: 260 }}>
              <InfoRow label="File name">{doc.file_name || doc.title}</InfoRow>
              <InfoRow label="Document type">
                <span style={chip(chips.type.tone)}>{chips.type.text}</span>
                {canRetype && (detail?.doc_types || []).length > 0 && (
                  <button className="btn-outline" style={{ fontSize: 12, padding: "3px 10px", marginLeft: "auto" }} onClick={() => setChoosing(c => !c)}>
                    {doc.doc_type ? "Change type" : "Choose type"}
                  </button>
                )}
              </InfoRow>
              {choosing && (
                <div style={{ display: "flex", gap: 8, padding: "0 0 10px" }}>
                  <select style={{ ...inputStyle, flex: 1 }} value={newType} onChange={e => setNewType(e.target.value)}>
                    {!doc.doc_type && <option value="">Choose a type…</option>}
                    {detail.doc_types.map(t => <option key={t} value={t}>{typeLabel(t)}</option>)}
                  </select>
                  <button className="btn-primary" disabled={busy || !newType || newType === doc.doc_type} onClick={saveType}>Save</button>
                </div>
              )}
              <InfoRow label="Classification">
                {chips.extra ? <span style={chip(chips.extra.tone)}>{chips.extra.text}</span> : <span style={{ color: "var(--color-text-muted)" }}>—</span>}
              </InfoRow>
              <InfoRow label="Source">{hospital ? "Issued by your hospital" : "Uploaded by you"}</InfoRow>
              {doc.hospital_label ? <InfoRow label="Hospital / lab">{doc.hospital_label}</InfoRow> : null}
              {doc.doctor_label ? <InfoRow label="Doctor">{doc.doctor_label}</InfoRow> : null}
              {doc.document_date ? <InfoRow label="Document date">{fmtDate(doc.document_date)}</InfoRow> : null}
              {doc.public_document_id ? <InfoRow label="Document ID">{doc.public_document_id}</InfoRow> : null}
              <InfoRow label="Added on">{fmtDate(doc.created_at)}</InfoRow>
              {doc.size ? <InfoRow label="File size">{formatSize(doc.size)}</InfoRow> : null}
              <InfoRow label="Status">
                <span style={{ width: 9, height: 9, borderRadius: "50%", background: state === "failed" ? "var(--color-error)" : state === "ready" ? "#1e8e3e" : "var(--color-warning, #b45309)" }} />
                {STATE_LABEL[state]}
              </InfoRow>
            </div>
          </div>
        </>
      )}

      {tab === "preview" && (
        <div style={{ minHeight: 320, display: "flex", alignItems: "center", justifyContent: "center", background: "var(--color-bg)", borderRadius: 10, overflow: "hidden" }}>
          {!detail ? <span style={{ color: "var(--color-text-muted)", fontSize: 13 }}>Loading…</span>
            : !detail.file_data ? <span style={{ color: "var(--color-text-muted)", fontSize: 13, padding: 20, textAlign: "center" }}>A preview isn’t available for this file.</span>
            : kind === "image" ? <img src={detail.file_data} alt={doc.title} style={{ maxWidth: "100%", maxHeight: 560 }} />
            : <iframe title={doc.title} src={detail.file_data} style={{ width: "100%", height: 560, border: "none" }} />}
        </div>
      )}

      {tab === "activity" && (
        !detail ? <span style={{ color: "var(--color-text-muted)", fontSize: 13 }}>Loading…</span> : (
          <ol style={{ listStyle: "none", margin: 0, padding: 0 }}>
            {(detail.events || []).map((e, i) => (
              <li key={i} style={{ display: "flex", gap: 12, padding: "10px 0", borderTop: i ? "1px solid var(--color-border)" : "none", fontSize: 13 }}>
                <span style={{ width: 110, flexShrink: 0, color: "var(--color-text-muted)" }}>{fmtDate(e.at)}</span>
                <span>{e.text}</span>
              </li>
            ))}
            {!(detail.events || []).length && <li style={{ fontSize: 13, color: "var(--color-text-muted)" }}>Nothing to show yet.</li>}
          </ol>
        )
      )}

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 18, paddingTop: 14, borderTop: "1px solid var(--color-border)" }}>
        {state === "failed" && <button className="btn-primary" disabled={busy} onClick={() => act({ action: "retry" }, "Trying again…")}>Try again</button>}
        {state === "duplicate" && <button className="btn-primary" disabled={busy} onClick={() => act({ action: "keep" }, "Keeping it — reading it now.")}>Keep anyway</button>}
        {state !== "processing" && <button className="btn-outline" onClick={download}><Download size={15} /> Download</button>}
        {priv && onLock && state !== "processing" && (
          <button className="btn-outline" onClick={() => onLock(doc)}>
            {priv.private ? <><Unlock size={15} /> Share with doctors</> : <><Lock size={15} /> Hide from doctors</>}
          </button>
        )}
        <button className="btn-outline" style={{ color: "var(--color-danger)", borderColor: "var(--color-danger)", marginLeft: "auto" }} disabled={busy}
          onClick={() => onDelete([doc])}>
          <Trash2 size={15} /> Delete from my reports
        </button>
      </div>
      {hospital && (
        <div style={{ fontSize: 11, color: "var(--color-text-muted)", marginTop: 8 }}>
          Your hospital keeps its own copy. Deleting removes it from your reports and from other hospitals.
        </div>
      )}
    </div>
  );
}
