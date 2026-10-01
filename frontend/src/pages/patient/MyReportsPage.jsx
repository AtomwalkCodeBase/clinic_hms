/**
 * pages/patient/MyReportsPage.jsx
 * -------------------------------
 * Every prescription, lab report and scan in one list, with the details of the open report beside it.
 *
 *   Add      reports/AddReportsModal — files, a folder, a photo; read and classified in the background
 *   List     GET /portal/documents/ — polled while any report is still being read
 *   Panel    reports/ReportPanel — details, preview, activity, change type, keep a duplicate, try again
 *   Select   several reports → download as a ZIP, or delete them all (POST /portal/documents/bulk-delete/)
 *
 * What each report is called, and the message and actions it gets, follow from utils/reports.js (stateOf).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, CheckSquare, Clock, Download, Lock, Plus, Search, Trash2 } from "lucide-react";
import { Link } from "react-router-dom";
import { AppShell } from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import { usePaginatedList } from "../../hooks/usePaginatedList";
import { useToast } from "../../hooks/useToast";
import apiClient from "../../services/api.client";
import API_ENDPOINTS from "../../config/api.config";
import ROUTES from "../../config/routes.config";
import { usePatientContext } from "../../context/PatientContext";
import { todayLocal } from "../../utils/dates";
import { NEEDS_ATTENTION, SORTS, matchesSearch, sortReports, stateOf, typeLabel } from "../../utils/reports";
import AddReportsModal from "./reports/AddReportsModal";
import ReportPanel from "./reports/ReportPanel";
import ReportRow from "./reports/ReportRow";
import { TONE, backdrop, h3, inputStyle } from "./reports/reportStyles";

const ATTENTION = "__attention";            // the tab for reports that need the patient to do something

function useWide(px) {
  const query = `(min-width: ${px}px)`;
  const [wide, setWide] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const mq = window.matchMedia(query);
    const on = () => setWide(mq.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, [query]);
  return wide;
}

function ConfirmDialog({ title, message, confirmLabel, busy, onConfirm, onCancel }) {
  return (
    <div style={{ ...backdrop, zIndex: 1100 }} onClick={onCancel}>
      <div className="card" style={{ width: "min(420px, 96vw)", padding: 22 }} onClick={e => e.stopPropagation()} role="alertdialog" aria-label={title}>
        <h3 style={h3}>{title}</h3>
        <p style={{ fontSize: 13, color: "var(--color-text-secondary)", lineHeight: 1.55, margin: "10px 0 18px" }}>{message}</p>
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <button className="btn-outline" disabled={busy} onClick={onCancel}>Cancel</button>
          <button className="btn-primary" style={{ background: "var(--color-danger)", borderColor: "var(--color-danger)" }} disabled={busy} onClick={onConfirm}>{confirmLabel}</button>
        </div>
      </div>
    </div>
  );
}

export default function MyReportsPage() {
  const { selectedPatient } = usePatientContext();
  const patientAwpid = selectedPatient?.awpid || "";
  const { toastApiError, toastError, toastSuccess, toastWarning, toastInfo } = useToast();

  const { items: docs, isLoading, hasMore, loadMore, refetch } = usePaginatedList(
    API_ENDPOINTS.PORTAL.DOCUMENTS,
    { pageSize: 50, params: patientAwpid ? { patient_awpid: patientAwpid } : {} },
  );
  const awpidParam = patientAwpid ? { patient_awpid: patientAwpid } : {};

  // Files still being read / classified → refresh every 4 s until they're done.
  const processingCount = docs.filter(d => stateOf(d) === "processing").length;
  const attentionCount = docs.filter(d => NEEDS_ATTENTION.has(stateOf(d))).length;
  const processing = processingCount > 0;
  useEffect(() => {
    if (!processing) return undefined;
    const t = setInterval(refetch, 4000);
    return () => clearInterval(t);
  }, [processing, refetch]);

  // Tell the patient when the last file has been read, and whether anything needs them.
  const wasProcessing = useRef(0);
  useEffect(() => {
    if (wasProcessing.current > 0 && processingCount === 0) {
      if (attentionCount) toastWarning(`Your reports have been read. ${attentionCount} need${attentionCount === 1 ? "s" : ""} your attention.`);
      else toastSuccess("Your new reports have been read and filed.");
    }
    wasProcessing.current = processingCount;
  }, [processingCount, attentionCount, toastSuccess, toastWarning]);

  // One place for every action on a report (try again, keep a duplicate).
  async function actOn(doc, payload, message) {
    try {
      await apiClient.patch(API_ENDPOINTS.PORTAL.DOCUMENT(doc.id), payload, { params: awpidParam });
      toastSuccess(message);
      refetch();
    } catch (err) { toastApiError(err, "That didn’t work — please try again."); }
  }
  function afterUpload({ sent, error, background }) {
    refetch();
    if (!background) return;                  // the dialog is still open and says it itself
    if (error) toastError(sent ? `Only ${sent} file${sent === 1 ? "" : "s"} uploaded. ${error}` : `Upload failed. ${error}`);
    else toastInfo(`${sent} file${sent === 1 ? "" : "s"} uploaded — reading ${sent === 1 ? "it" : "them"} now.`);
  }

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
  const [sort, setSort] = useState("newest");
  const [selectMode, setSelectMode] = useState(false);
  const [sel, setSel] = useState(() => new Set());
  const [addOpen, setAddOpen] = useState(false);
  const [openId, setOpenId] = useState(null);
  const [confirm, setConfirm] = useState(null);          // the reports about to be deleted
  const [deleting, setDeleting] = useState(false);
  const wide = useWide(1100);

  // tabs: All, Needs attention, then one tab per type that is actually present (most reports first)
  const counts = useMemo(() => {
    const c = { all: docs.length, [ATTENTION]: attentionCount };
    docs.forEach(d => { if (d.doc_type && stateOf(d) === "ready") c[d.doc_type] = (c[d.doc_type] || 0) + 1; });
    return c;
  }, [docs, attentionCount]);
  const tabs = useMemo(() => [
    ["all", "All"],
    ...(attentionCount ? [[ATTENTION, "Needs attention"]] : []),
    ...Object.keys(counts).filter(k => k !== "all" && k !== ATTENTION).sort((a, b) => counts[b] - counts[a]).map(k => [k, typeLabel(k)]),
  ], [counts, attentionCount]);
  const activeTab = tabs.some(([id]) => id === tab) ? tab : "all";      // a tab that emptied out falls back to All
  const shown = useMemo(() => sortReports(docs.filter(d =>
    (activeTab === "all" || (activeTab === ATTENTION ? NEEDS_ATTENTION.has(stateOf(d)) : stateOf(d) === "ready" && d.doc_type === activeTab))
    && matchesSearch(d, q)), sort), [docs, activeTab, q, sort]);
  const byId = useMemo(() => new Map(docs.map(d => [d.id, d])), [docs]);
  const openDoc = openId ? byId.get(openId) || null : null;           // always the freshest copy from the list

  const toggleSel = (id) => setSel(prev => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const allShownSelected = shown.length > 0 && shown.every(d => sel.has(d.id));
  const stopSelecting = () => { setSelectMode(false); setSel(new Set()); };

  async function downloadSelected() {
    const ids = [...sel];
    if (!ids.length) return;
    try {
      const res = await apiClient.post(API_ENDPOINTS.PORTAL.DOCUMENTS_ZIP, { ids, ...awpidParam }, { responseType: "blob" });
      const url = URL.createObjectURL(res.data);
      const a = document.createElement("a");
      a.href = url; a.download = `my-reports-${todayLocal()}.zip`;
      a.click(); URL.revokeObjectURL(url);
      stopSelecting();
    } catch { toastError("Could not build the ZIP."); }
  }

  // Delete one report or many: always asks first, then says what happened.
  function askDelete(list) { if (list.length) setConfirm(list); }
  async function confirmDelete() {
    const list = confirm;
    setDeleting(true);
    try {
      const res = await apiClient.post(API_ENDPOINTS.PORTAL.DOCUMENTS_BULK_DELETE, { ids: list.map(d => d.id), ...awpidParam });
      const { deleted = 0, skipped = [] } = res.data?.data || res.data || {};
      if (deleted) toastSuccess(deleted === 1 ? "Deleted from your reports." : `Deleted ${deleted} reports from your reports.`);
      if (skipped.length) toastWarning(`${skipped.length} couldn’t be deleted — they weren’t found.`);
      if (list.some(d => d.id === openId)) setOpenId(null);
      stopSelecting();
      refetch();
    } catch (err) { toastApiError(err, "Could not delete — nothing was removed."); }
    finally { setDeleting(false); setConfirm(null); }
  }
  const hospitalIssued = confirm ? confirm.filter(d => d.source_tenant_id || d.uploaded_by === "staff").length : 0;

  const panel = openDoc && (
    <ReportPanel doc={openDoc} original={openDoc.duplicate_of ? byId.get(openDoc.duplicate_of) : null} patientAwpid={patientAwpid}
      priv={privEnabled ? privMap.get(openDoc.id) : undefined} onLock={privEnabled ? onLock : undefined}
      onClose={() => setOpenId(null)} onAct={actOn} onDelete={askDelete} onChanged={refetch} />
  );

  return (
    <AppShell>
      <PageShell
        title={selectedPatient?.isSelf ? "My Reports" : `${selectedPatient?.name || "Family member"}'s Reports`}
        action={<button className="btn-primary" onClick={() => setAddOpen(true)}><Plus size={16} /> Add Report</button>}
      >
        <p style={{ fontSize: 13, color: "var(--color-text-muted)", margin: "-6px 0 14px" }}>
          View and manage your medical documents securely. These are private and only visible to you unless shared with a doctor.
        </p>
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

        {processing && (
          <div className="card" style={{ padding: "10px 13px", marginBottom: 12, display: "flex", gap: 9, alignItems: "center", fontSize: 12.5 }}>
            <Clock size={14} style={{ flexShrink: 0, color: "var(--color-primary)" }} />
            <span><b>Reading {processingCount} report{processingCount === 1 ? "" : "s"}…</b> Their type appears here by itself in a few seconds — you can keep using the app.</span>
          </div>
        )}
        {!processing && attentionCount > 0 && activeTab !== ATTENTION && (
          <div className="card" style={{ padding: "10px 13px", marginBottom: 12, display: "flex", gap: 9, alignItems: "center", fontSize: 12.5, borderColor: TONE.warn, background: "var(--color-warning-light, #fbf3e6)" }}>
            <AlertTriangle size={14} style={{ flexShrink: 0, color: TONE.warn }} />
            <span style={{ flex: 1 }}><b>{attentionCount} report{attentionCount === 1 ? " needs" : "s need"} your attention</b> — we couldn’t read, classify or add {attentionCount === 1 ? "it" : "them"}.</span>
            <button className="btn-outline" style={{ fontSize: 12, padding: "4px 10px" }} onClick={() => setTab(ATTENTION)}>Review</button>
          </div>
        )}

        {/* tabs */}
        <div role="tablist" style={{ display: "flex", gap: 8, overflowX: "auto", paddingBottom: 4, marginBottom: 12 }}>
          {tabs.map(([id, label]) => (
            <button key={id} role="tab" aria-selected={activeTab === id} onClick={() => setTab(id)} style={{
              padding: "8px 16px", fontSize: 13, borderRadius: 10, whiteSpace: "nowrap", cursor: "pointer",
              border: `1px solid ${activeTab === id ? "var(--color-primary)" : "var(--color-border)"}`,
              background: activeTab === id ? "var(--color-primary)" : "var(--color-surface, #fff)",
              color: activeTab === id ? "#fff" : id === ATTENTION ? TONE.warn : "var(--color-text-secondary)",
              fontWeight: activeTab === id || id === ATTENTION ? 600 : 400,
            }}>{label} {counts[id] ? `(${counts[id]})` : ""}</button>
          ))}
        </div>

        {/* search, sort, select */}
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center", marginBottom: 14 }}>
          <div style={{ flex: 1, minWidth: 220, display: "flex", alignItems: "center", gap: 8, border: "1px solid var(--color-border)", borderRadius: 10, padding: "9px 12px", background: "var(--color-surface, #fff)" }}>
            <Search size={15} color="var(--color-text-muted)" />
            <input value={q} onChange={e => setQ(e.target.value)} placeholder="Search by file name, document type or keyword…" aria-label="Search reports"
              style={{ border: "none", outline: "none", flex: 1, fontSize: 13, background: "transparent" }} />
          </div>
          <select aria-label="Sort reports" value={sort} onChange={e => setSort(e.target.value)} style={{ ...inputStyle, padding: "10px 12px", borderRadius: 10 }}>
            {SORTS.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
          </select>
          {!selectMode && <button className="btn-outline" onClick={() => setSelectMode(true)}><CheckSquare size={14} /> Select</button>}
        </div>

        {selectMode && (
          <div className="card" style={{ padding: "10px 14px", marginBottom: 12, display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
            <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, cursor: "pointer" }}>
              <input type="checkbox" checked={allShownSelected}
                onChange={() => setSel(allShownSelected ? new Set() : new Set(shown.map(d => d.id)))} />
              Select all {shown.length}
            </label>
            <span style={{ fontSize: 13, color: "var(--color-text-muted)", flex: 1 }}>{sel.size} selected</span>
            <button className="btn-outline" disabled={!sel.size} onClick={downloadSelected}><Download size={14} /> Download</button>
            <button className="btn-outline" style={{ color: "var(--color-danger)", borderColor: "var(--color-danger)" }} disabled={!sel.size}
              onClick={() => askDelete(docs.filter(d => sel.has(d.id)))}><Trash2 size={14} /> Delete{sel.size ? ` ${sel.size}` : ""}</button>
            <button className="btn-outline" onClick={stopSelecting}>Cancel</button>
          </div>
        )}

        <div style={{ display: "grid", gridTemplateColumns: wide && openDoc ? "minmax(0, 1fr) 460px" : "minmax(0, 1fr)", gap: 16, alignItems: "start" }}>
          <div>
            {isLoading && !docs.length ? (
              <div className="card" style={{ padding: 30, textAlign: "center", color: "var(--color-text-muted)" }}>Loading…</div>
            ) : !shown.length ? (
              <div className="card" style={{ padding: 30, textAlign: "center", color: "var(--color-text-muted)", fontSize: 13 }}>
                {docs.length ? (activeTab === ATTENTION ? "Nothing needs your attention." : "Nothing matches your search.")
                  : "No reports yet — tap “Add Report” to upload a prescription, lab report or scan. You can pick files, a whole folder, or drop them in."}
              </div>
            ) : (
              <>
                {shown.map(d => (
                  <ReportRow key={d.id} doc={d} active={d.id === openId} selectMode={selectMode} selected={sel.has(d.id)}
                    priv={privEnabled ? privMap.get(d.id) : undefined} onLock={privEnabled ? onLock : undefined}
                    onClick={() => (selectMode ? toggleSel(d.id) : setOpenId(d.id))} onOpen={() => setOpenId(d.id)}
                    onAct={actOn} onDelete={askDelete} />
                ))}
                {hasMore && <button className="btn-outline" style={{ width: "100%" }} onClick={loadMore}>Load more</button>}
              </>
            )}
          </div>
          {wide && openDoc && <aside style={{ position: "sticky", top: 12 }}>{panel}</aside>}
        </div>
      </PageShell>

      {!wide && openDoc && (
        <div style={backdrop} onClick={() => setOpenId(null)}>
          <div style={{ width: "min(600px, 96vw)", maxHeight: "92vh", overflowY: "auto" }} onClick={e => e.stopPropagation()}>{panel}</div>
        </div>
      )}
      {addOpen && (
        <AddReportsModal patientAwpid={patientAwpid} onClose={() => setAddOpen(false)} onUploaded={afterUpload}
          onDone={() => { setAddOpen(false); setTab("all"); refetch(); }} />
      )}
      {confirm && (
        <ConfirmDialog
          title={confirm.length === 1 ? "Delete this report?" : `Delete ${confirm.length} reports?`}
          message={`${confirm.length === 1 ? `“${confirm[0].title}” will` : "They will"} be removed from your reports and from other hospitals’ view. This can’t be undone.${hospitalIssued ? " Your hospital keeps its own copy of the reports it issued." : ""}`}
          confirmLabel={confirm.length === 1 ? "Delete" : `Delete ${confirm.length}`} busy={deleting}
          onConfirm={confirmDelete} onCancel={() => setConfirm(null)} />
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
