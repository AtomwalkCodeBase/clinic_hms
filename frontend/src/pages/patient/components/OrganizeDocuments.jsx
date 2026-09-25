/**
 * pages/patient/components/OrganizeDocuments.jsx
 * ----------------------------------------------
 * The one screen where a patient files their uploads — built to stay usable
 * at 100+ documents. Folders on the left (counts; click to filter), every
 * document on the right with its folder dropdown, one Save at the bottom.
 *
 *   mode="manual"  "Organize manually" — the files are still on this device.
 *                  The patient assigns each one; Save hands them to the
 *                  background uploader already filed (no AI at all).
 *   mode="verify"  "Auto-segregate" — the files were uploaded and the server
 *                  sorted them. Every row is pre-filled with the machine's
 *                  answer; files still being sorted show as "Sorting…" and
 *                  fill in live. The patient changes what's wrong and saves
 *                  once — untouched rows count as correct, edited rows as
 *                  human corrections (decided on the server).
 *
 * Folders are the medical types (Prescriptions, Lab Reports, …) plus the
 * patient's own folders ("My folders") — a personal label on top of the type.
 * Lab panel and date appear per row only where they matter: the panel for
 * lab reports, and the date highlighted when it's missing.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowLeft, FileText, Image as ImageIcon, FolderClosed, FolderPlus, Files, AlertTriangle, Search,
  Eye, X, Trash2, Loader2, Check, MoreVertical, Sparkles, Pill, FlaskConical,
} from "lucide-react";
import apiClient from "../../../services/api.client";
import API_ENDPOINTS from "../../../config/api.config";
import { useToast } from "../../../hooks/useToast";
import { useUploads } from "../../../context/UploadContext";
import { openDataUrlInNewTab } from "../../../utils/fileViewer";
import {
  TYPE_OPTIONS, TYPE_LABEL, CATEGORY_LABELS, CATEGORY_ORDER, inFlight, suggestedType, pct, TYPE_TONE, STAGE,
} from "../reportMeta";

const REMOVE = "__remove__";
const TYPE_ICON = { prescription: Pill, lab_report: FlaskConical, scan: ImageIcon, discharge_summary: FileText, other: FolderClosed };
const CONFIDENT = 0.75;
const today = () => new Date().toISOString().slice(0, 10);
const fmtSize = (b) => (b >= 1048576 ? `${(b / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(b / 1024))} KB`);
const extOf = (name = "") => (name.split(".").pop() || "").toUpperCase();

/* ─────────────────────────────── rows: one shape for both modes */
function manualRows(files) {
  return files.map((f, i) => ({
    key: `f${i}`, file: f, name: f.name, meta: `${extOf(f.name)} · ${fmtSize(f.size)}`,
    isImage: /^image\//.test(f.type), sorting: false,
    machine: { type: "", cat: "", date: "", folder: "" },
    attention: [],
  }));
}

function verifyRow(d) {
  const machine = {
    type: suggestedType(d),
    cat: (d.report_categories || []).find(c => CATEGORY_LABELS[c]) || "",
    date: (d.document_date || "").slice(0, 10),
    folder: d.folder || "",
  };
  const attention = [];
  if (d.review_needs?.includes("file")) attention.push("couldn't read it — open it and choose");
  else if (d.llm_doc_type === "not_medical" || d.rule_doc_type === "not_medical") attention.push("may not be a medical record");
  else if (!machine.type) attention.push("couldn't tell what it is");
  else {
    const conf = Math.max(d.rule_doc_type === machine.type ? d.rule_confidence || 0 : 0,
      d.llm_doc_type === machine.type ? d.llm_confidence || 0 : 0);
    if (conf < CONFIDENT) attention.push("not sure of the type");
    if (d.llm_doc_type && d.rule_doc_type && TYPE_LABEL[d.llm_doc_type] && TYPE_LABEL[d.rule_doc_type]
        && d.llm_doc_type !== d.rule_doc_type) attention.push("AI and rules disagree");
  }
  if (machine.type === "lab_report" && !machine.cat) attention.push("panel missing");
  if (!machine.date) attention.push("date missing");

  const who = [];
  if (d.rule_doc_type && TYPE_LABEL[d.rule_doc_type]) who.push(`Rules ${pct(d.rule_confidence)}`);
  if (d.llm_doc_type && TYPE_LABEL[d.llm_doc_type]) who.push(`AI ${pct(d.llm_confidence)}`);
  return {
    key: `d${d.id}`, doc: d, name: d.title, isImage: false, sorting: false,
    meta: [`PDF · uploaded ${new Date(d.created_at).toLocaleDateString("en-IN", { day: "numeric", month: "short" })}`,
      who.length ? `sorted by ${who.join(" · ")}` : "",
      ["queued", "running"].includes(d.llm_status) ? "AI check pending" : ""].filter(Boolean).join(" · "),
    machine, attention,
  };
}

/* ─────────────────────────────────────────────── the screen */
export default function OrganizeDocuments({ mode, files = [], patientAwpid = "", onBack, onDone }) {
  const { toastSuccess, toastError, toastApiError } = useToast();
  const uploads = useUploads();
  const manual = mode === "manual";

  // ── verify mode: everything waiting for a check, plus files still sorting
  const [serverDocs, setServerDocs] = useState(manual ? [] : null);
  const loadDocs = useCallback(async () => {
    if (manual) return;
    try {
      const res = await apiClient.get(API_ENDPOINTS.PORTAL.DOCUMENTS, {
        params: { to_verify: 1, page_size: 1000, ...(patientAwpid ? { patient_awpid: patientAwpid } : {}) },
      });
      setServerDocs(res.data?.results || res.data?.data?.results || []);
    } catch (err) { toastApiError(err, "Could not load your documents."); setServerDocs([]); }
  }, [manual, patientAwpid, toastApiError]);
  useEffect(() => { loadDocs(); }, [loadDocs, uploads?.version]);

  // Thumbnails for photos still on this device (manual mode).
  const thumbs = useMemo(() => files.map(f => (/^image\//.test(f.type) ? URL.createObjectURL(f) : "")), [files]);
  useEffect(() => () => thumbs.forEach(u => u && URL.revokeObjectURL(u)), [thumbs]);

  const rows = useMemo(() => {
    if (manual) return manualRows(files).map((r, i) => ({ ...r, thumb: thumbs[i] }));
    const list = serverDocs || [];
    const ready = list.filter(d => !inFlight(d)).map(verifyRow);
    const seen = new Set(list.map(d => d.id));
    // Live stage + place in queue come from the uploader's poll.
    const liveById = new Map((uploads?.docs || []).map(d => [d.id, d]));
    const sorting = [
      ...list.filter(inFlight).map(d => ({ ...d, ...(liveById.get(d.id) || {}) })).filter(inFlight),
      ...(uploads?.docs || []).filter(d => inFlight(d) && !d.manual && !seen.has(d.id)
        && (d.patientAwpid || "") === patientAwpid),
    ].map(d => ({ key: `d${d.id}`, doc: d, name: d.title || "Document", sorting: true, meta: "Sorting…",
      machine: { type: "", cat: "", date: "", folder: "" }, attention: [] }));
    return [...sorting, ...ready];
  }, [manual, files, thumbs, serverDocs, uploads?.docs, patientAwpid]);

  // ── the patient's edits, keyed by row
  const [edits, setEdits] = useState({});          // key -> {type?, cat?, date?, folder?}
  const [removed, setRemoved] = useState(() => new Set());   // manual: dropped from this upload
  const [myFolders, setMyFolders] = useState([]);
  const [creating, setCreating] = useState(false);
  const [newFolder, setNewFolder] = useState("");
  const [filter, setFilter] = useState("all");     // all | attention | unassigned | remove | type:<t> | folder:<name>
  const [q, setQ] = useState("");
  const [sort, setSort] = useState("attention");   // attention | name | newest
  const [sel, setSel] = useState(() => new Set());
  const [busy, setBusy] = useState(false);

  const live = rows.filter(r => !removed.has(r.key));
  const cur = (r) => ({ ...r.machine, ...(edits[r.key] || {}) });
  const setField = (keys, k, v) => setEdits(p => {
    const n = { ...p };
    keys.forEach(key => { n[key] = { ...(n[key] || {}), [k]: v }; });
    return n;
  });

  const folders = useMemo(() => {
    const s = new Set(myFolders);
    live.forEach(r => { const f = cur(r).folder; if (f) s.add(f); });
    return [...s].sort((a, b) => a.localeCompare(b));
  }, [myFolders, live, edits]); // eslint-disable-line react-hooks/exhaustive-deps

  // counts for the sidebar
  const counts = useMemo(() => {
    const c = { all: live.length, attention: 0, unassigned: 0, remove: 0, sorting: 0 };
    TYPE_OPTIONS.forEach(([t]) => { c[`type:${t}`] = 0; });
    live.forEach(r => {
      const v = cur(r);
      if (r.sorting) { c.sorting++; return; }
      if (v.type === REMOVE) { c.remove++; return; }
      if (!v.type) c.unassigned++;
      else c[`type:${v.type}`] = (c[`type:${v.type}`] || 0) + 1;
      if (v.folder) c[`folder:${v.folder}`] = (c[`folder:${v.folder}`] || 0) + 1;
      if (!manual && r.attention.length && !edits[r.key]) c.attention++;
    });
    return c;
  }, [live, edits, manual]); // eslint-disable-line react-hooks/exhaustive-deps

  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return live.filter(r => {
      const v = cur(r);
      if (needle && !(r.name || "").toLowerCase().includes(needle)) return false;
      if (filter === "all") return true;
      if (r.sorting) return false;
      if (filter === "attention") return r.attention.length && !edits[r.key];
      if (filter === "unassigned") return !v.type;
      if (filter === "remove") return v.type === REMOVE;
      if (filter.startsWith("type:")) return v.type === filter.slice(5);
      if (filter.startsWith("folder:")) return v.folder === filter.slice(7);
      return true;
    }).sort((a, b) => {
      if (a.sorting !== b.sorting) return a.sorting ? 1 : -1;       // ready rows first
      if (sort === "name") return (a.name || "").localeCompare(b.name || "");
      if (sort === "newest") return (b.doc?.id || 0) - (a.doc?.id || 0);
      const fa = a.attention.length && !edits[a.key] ? 0 : 1, fb = b.attention.length && !edits[b.key] ? 0 : 1;
      return fa - fb;                                                 // needs-attention first
    });
  }, [live, filter, q, edits, sort]); // eslint-disable-line react-hooks/exhaustive-deps
  const filterLabel = filter === "all" ? "All Documents" : filter === "attention" ? "Needs attention"
    : filter === "unassigned" ? "Not assigned yet" : filter === "remove" ? "To remove"
    : filter.startsWith("type:") ? TYPE_LABEL[filter.slice(5)] : filter.slice(7);

  const selectable = shown.filter(r => !r.sorting);
  const allSel = selectable.length > 0 && selectable.every(r => sel.has(r.key));
  const toggle = (key) => setSel(p => { const n = new Set(p); n.has(key) ? n.delete(key) : n.add(key); return n; });

  const done = live.filter(r => !r.sorting && cur(r).type).length;
  const pending = live.filter(r => !r.sorting && !cur(r).type).length;
  const correctedCount = manual ? 0 : live.filter(r => {
    const v = cur(r);
    return !r.sorting && v.type && v.type !== REMOVE
      && (v.type !== r.machine.type || v.cat !== r.machine.cat || v.date !== r.machine.date);
  }).length;

  function addFolder() {
    const name = newFolder.trim().slice(0, 60);
    if (!name) { setCreating(false); return; }
    if (TYPE_OPTIONS.some(([, l]) => l.toLowerCase() === name.toLowerCase())) { toastError("That's already a built-in folder."); return; }
    setMyFolders(p => (p.includes(name) ? p : [...p, name]));
    if (sel.size) setField([...sel], "folder", name);
    setNewFolder(""); setCreating(false);
  }

  async function view(r) {
    if (r.file) { window.open(URL.createObjectURL(r.file), "_blank"); return; }
    const win = window.open("", "_blank");
    try {
      const res = await apiClient.get(API_ENDPOINTS.PORTAL.DOCUMENT(r.doc.id), { params: patientAwpid ? { patient_awpid: patientAwpid } : {} });
      const fd = (res.data?.data || res.data)?.file_data;
      if (fd) openDataUrlInNewTab(win, fd); else win?.close();
    } catch (err) { win?.close(); toastApiError(err, "Could not open the file."); }
  }

  async function save() {
    setBusy(true);
    try {
      if (manual) {
        const keep = live.filter(r => cur(r).type);
        const metas = keep.map(r => {
          const v = cur(r);
          return { doc_type: v.type, report_categories: v.type === "lab_report" && v.cat ? [v.cat] : [],
            document_date: v.date || "", folder: v.folder || "" };
        });
        const { accepted, rejected } = uploads.addFiles(keep.map(r => r.file), patientAwpid, metas);
        if (accepted) toastSuccess(`Uploading ${accepted} file${accepted !== 1 ? "s" : ""} into your folders — you can carry on.`);
        if (rejected.length) toastError(`${rejected.length} skipped: ${rejected.map(x => `${x.name} (${x.reason})`).join(", ")}`);
        onDone();
        return;
      }
      const items = live.filter(r => !r.sorting && cur(r).type).map(r => {
        const v = cur(r);
        if (v.type === REMOVE) return { id: r.doc.id, action: "reject" };
        return {
          id: r.doc.id, action: "accept", doc_type: v.type,
          report_categories: v.type === "lab_report" && v.cat ? [v.cat] : [],
          ...(v.date ? { document_date: v.date } : {}), folder: v.folder || "",
        };
      });
      let right = 0, fixed = 0, gone = 0;
      for (let i = 0; i < items.length; i += 300) {
        const res = await apiClient.post(API_ENDPOINTS.PORTAL.DOCUMENTS_REVIEW, {
          items: items.slice(i, i + 300), ...(patientAwpid ? { patient_awpid: patientAwpid } : {}),
        });
        ((res.data?.data || res.data)?.results || []).filter(x => x.ok).forEach(x => {
          if (x.removed) gone++; else if (x.human_action === "changed") fixed++; else right++;
        });
      }
      toastSuccess(`Saved — ${right} as sorted${fixed ? `, ${fixed} corrected` : ""}${gone ? `, ${gone} removed` : ""}.`);
      const leftover = counts.sorting;
      setEdits({}); setSel(new Set());
      if (leftover) loadDocs(); else onDone();
    } catch (err) { toastApiError(err, "Could not save."); } finally { setBusy(false); }
  }

  if (!manual && serverDocs === null) {
    return <div className="card" style={{ padding: 40, textAlign: "center", color: "var(--color-text-muted)" }}>Loading your documents…</div>;
  }

  const SideItem = ({ id, icon: Icon, label, n, tone }) => (
    <button onClick={() => { setFilter(id); setSel(new Set()); }} style={{
      display: "flex", alignItems: "center", gap: 10, width: "100%", padding: "9px 11px", borderRadius: 9,
      border: "none", cursor: "pointer", textAlign: "left", fontSize: 13.5,
      background: filter === id ? "var(--color-primary-light, rgba(21,119,74,.10))" : "transparent",
      color: filter === id ? "var(--color-primary)" : "var(--color-text)", fontWeight: filter === id ? 600 : 400,
    }}>
      <Icon size={16} style={{ color: tone || (filter === id ? "var(--color-primary)" : "#E0A526"), flexShrink: 0 }} />
      <span style={{ flex: 1, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{label}</span>
      <span style={{ fontSize: 12, color: "var(--color-text-muted)", fontVariantNumeric: "tabular-nums" }}>{n}</span>
    </button>
  );

  return (
    <div style={{ paddingBottom: 90 }}>
      <button onClick={onBack} style={{ display: "inline-flex", alignItems: "center", gap: 6, background: "none", border: "none", cursor: "pointer", color: "var(--color-text-secondary)", fontSize: 13.5, padding: 0, marginBottom: 14 }}>
        <ArrowLeft size={16} /> Back
      </button>
      <h1 style={{ fontFamily: "var(--font-display)", fontSize: 26, margin: "0 0 4px" }}>
        {manual ? "Organize Documents Manually" : "Review Sorted Documents"}
      </h1>
      <p style={{ margin: "0 0 20px", color: "var(--color-text-muted)", fontSize: 14 }}>
        {manual
          ? "Assign each document to a folder. They upload in the background once you save."
          : "We sorted these for you. Check each folder, move anything that's wrong, then save."}
      </p>

      <div className="org-grid" style={{ display: "grid", gridTemplateColumns: "250px minmax(0,1fr)", gap: 24, alignItems: "start" }}>
        {/* ── folders ── */}
        <aside className="org-side" style={{ position: "sticky", top: 12 }}>
          <div style={{ display: "flex", alignItems: "center", marginBottom: 8 }}>
            <span style={{ flex: 1, fontSize: 11.5, fontWeight: 700, letterSpacing: ".06em", color: "var(--color-text-muted)" }}>FOLDERS</span>
            <button onClick={() => setCreating(true)} style={{ display: "inline-flex", alignItems: "center", gap: 5, background: "none", border: "none", color: "var(--color-primary)", fontSize: 12.5, fontWeight: 600, cursor: "pointer" }}>
              <FolderPlus size={14} /> Create Folder
            </button>
          </div>
          <SideItem id="all" icon={Files} label="All Documents" n={counts.all} tone="var(--color-text-muted)" />
          {!manual && counts.attention > 0 && <SideItem id="attention" icon={AlertTriangle} label="Needs attention" n={counts.attention} tone="var(--color-warning)" />}
          {counts.unassigned > 0 && <SideItem id="unassigned" icon={FolderClosed} label="Not assigned yet" n={counts.unassigned} tone="var(--color-warning)" />}
          {TYPE_OPTIONS.map(([t, l]) => <SideItem key={t} id={`type:${t}`} icon={TYPE_ICON[t]} label={l} n={counts[`type:${t}`] || 0} tone={TYPE_TONE[t].fg} />)}
          {!manual && counts.remove > 0 && <SideItem id="remove" icon={Trash2} label="To remove" n={counts.remove} tone="var(--color-error)" />}

          {(folders.length > 0 || creating) && (
            <div style={{ fontSize: 11.5, fontWeight: 700, letterSpacing: ".06em", color: "var(--color-text-muted)", margin: "16px 0 6px" }}>MY FOLDERS</div>
          )}
          {folders.map(f => <SideItem key={f} id={`folder:${f}`} icon={FolderClosed} label={f} n={counts[`folder:${f}`] || 0} tone="#7C6CE0" />)}
          {creating && (
            <div style={{ display: "flex", gap: 6, marginTop: 6 }}>
              <input autoFocus className="form-input" value={newFolder} maxLength={60} placeholder="Folder name"
                onChange={e => setNewFolder(e.target.value)}
                onKeyDown={e => { if (e.key === "Enter") addFolder(); if (e.key === "Escape") setCreating(false); }}
                style={{ padding: "6px 9px", fontSize: 13, flex: 1, minWidth: 0 }} />
              <button className="btn-primary" style={{ padding: "5px 10px" }} onClick={addFolder}><Check size={14} /></button>
            </div>
          )}
          {creating && sel.size > 0 && (
            <div style={{ fontSize: 11.5, color: "var(--color-text-muted)", marginTop: 5 }}>The {sel.size} selected will go in it.</div>
          )}
        </aside>

        {/* ── documents ── */}
        <section style={{ minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10, flexWrap: "wrap" }}>
            <label style={{ display: "flex", alignItems: "center", gap: 8, fontWeight: 600, fontSize: 14 }}>
              <input type="checkbox" checked={allSel} disabled={!selectable.length}
                onChange={() => setSel(allSel ? new Set() : new Set(selectable.map(r => r.key)))} />
              <span style={{ fontSize: 16, fontWeight: 700 }}>{filterLabel} ({shown.length})</span>
            </label>
            <label className="form-input" style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 12px", flex: 1, minWidth: 200, maxWidth: 340, marginLeft: "auto" }}>
              <Search size={15} style={{ color: "var(--color-text-muted)" }} />
              <input value={q} onChange={e => setQ(e.target.value)} placeholder="Search by file name"
                style={{ border: "none", outline: "none", background: "none", width: "100%", fontSize: 13 }} />
            </label>
            {!manual && (
              <select className="form-input" value={sort} onChange={e => setSort(e.target.value)} aria-label="Sort" style={{ width: "auto", padding: "8px 12px", fontSize: 13 }}>
                <option value="attention">Needs attention first</option>
                <option value="newest">Newest first</option>
                <option value="name">Name A–Z</option>
              </select>
            )}
          </div>

          {sel.size > 0 && (
            <div className="card" style={{ padding: "9px 12px", marginBottom: 10, display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", fontSize: 13 }}>
              <b>{sel.size} selected</b>
              <select className="form-input" style={{ padding: "5px 8px", fontSize: 12.5, width: "auto" }} value=""
                onChange={e => { if (e.target.value) setField([...sel], "type", e.target.value); }}>
                <option value="">Move to…</option>
                {TYPE_OPTIONS.map(([t, l]) => <option key={t} value={t}>{l}</option>)}
                {!manual && <option value={REMOVE}>Not medical — remove</option>}
              </select>
              <select className="form-input" style={{ padding: "5px 8px", fontSize: 12.5, width: "auto" }} value=""
                onChange={e => {
                  if (e.target.value === "__new__") setCreating(true);
                  else if (e.target.value !== "") setField([...sel], "folder", e.target.value === "__none__" ? "" : e.target.value);
                }}>
                <option value="">Add to my folder…</option>
                {folders.map(f => <option key={f} value={f}>{f}</option>)}
                <option value="__none__">No personal folder</option>
                <option value="__new__">+ New folder…</option>
              </select>
              {manual && (
                <button className="btn-outline" style={{ fontSize: 12, padding: "4px 10px" }}
                  onClick={() => { setRemoved(p => new Set([...p, ...sel])); setSel(new Set()); }}>Don't upload</button>
              )}
              <button onClick={() => setSel(new Set())} style={{ marginLeft: "auto", background: "none", border: "none", color: "var(--color-text-muted)", cursor: "pointer", fontSize: 12.5 }}>Clear</button>
            </div>
          )}

          {shown.length === 0 ? (
            <div className="card" style={{ padding: 36, textAlign: "center", color: "var(--color-text-muted)", fontSize: 13.5 }}>
              {filter === "attention" ? "Nothing needs attention here." : "No documents in this folder."}
            </div>
          ) : shown.map(r => (
            <DocRow key={r.key} r={r} v={cur(r)} manual={manual} folders={folders}
              selected={sel.has(r.key)} onToggle={() => toggle(r.key)}
              edited={!!edits[r.key]}
              onSet={(k, v) => setField([r.key], k, v)} onView={() => view(r)}
              onDrop={manual ? () => setRemoved(p => new Set([...p, r.key])) : null}
              onNewFolder={() => { setSel(new Set([r.key])); setCreating(true); }} />
          ))}
        </section>
      </div>

      {/* ── footer ── */}
      <div style={{
        position: "sticky", bottom: 0, marginTop: 16, padding: "12px 16px", borderTop: "1px solid var(--color-border)",
        background: "var(--color-bg)", display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap", zIndex: 5,
      }}>
        <span style={{ display: "flex", gap: 16, flexWrap: "wrap", fontSize: 13, color: "var(--color-text-secondary)" }}>
          <Dot c="#0F766E"><b>{done}</b> of {live.length - counts.sorting} assigned</Dot>
          {counts.sorting > 0 && <Dot c="#2563EB">{counts.sorting} still sorting</Dot>}
          {!manual && correctedCount > 0 && <Dot c="#7C3AED">{correctedCount} corrected</Dot>}
          {!manual && counts.remove > 0 && <Dot c="#DC2626">{counts.remove} to remove</Dot>}
          {pending > 0 && <Dot c="#D97706">{pending} not assigned{manual ? "" : " (kept for later)"}</Dot>}
        </span>
        <span style={{ flex: 1 }} />
        <button className="btn-outline" onClick={onBack}>Cancel</button>
        <button className="btn-primary" disabled={busy || !done || (manual && pending > 0)} onClick={save}
          title={manual && pending > 0 ? `Assign the ${pending} remaining document${pending !== 1 ? "s" : ""} first` : ""}>
          {busy ? "Saving…" : manual ? "Save Organization" : `Save ${done} document${done !== 1 ? "s" : ""}`}
        </button>
      </div>

      <style>{`
        .spin { animation: org-spin 1s linear infinite; }
        @keyframes org-spin { to { transform: rotate(360deg); } }
        .org-row { transition: box-shadow .15s; }
        .org-row:hover { box-shadow: 0 2px 10px rgba(15,23,20,.07); }
        @media (max-width: 1100px) { .org-ctrls { width: 100%; justify-content: flex-start !important; padding-left: 70px; } }
        @media (max-width: 860px) {
          .org-grid { grid-template-columns: 1fr !important; }
          .org-side { position: static !important; display: flex; flex-wrap: nowrap; overflow-x: auto; gap: 4px; }
          .org-side > div { display: none; }
          .org-side > button { width: auto !important; flex-shrink: 0; }
        }
      `}</style>
    </div>
  );
}

const Dot = ({ c, children }) => (
  <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
    <span style={{ width: 7, height: 7, borderRadius: "50%", background: c }} />{children}
  </span>
);

/* ─────────────────────────────────────────────── one document */
function FileBadge({ r }) {
  const ext = r.file ? extOf(r.name) : "PDF";          // server copies are normalised to PDF
  if (r.thumb) {
    return <img src={r.thumb} alt="" style={{ width: 42, height: 42, borderRadius: 8, objectFit: "cover", flexShrink: 0, border: "1px solid var(--color-border)" }} />;
  }
  const isPdf = ext === "PDF";
  return (
    <span style={{
      width: 42, height: 42, borderRadius: 8, flexShrink: 0, display: "inline-flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
      background: isPdf ? "rgba(220,38,38,.09)" : "var(--color-primary-light, rgba(21,119,74,.10))", color: isPdf ? "#DC2626" : "var(--color-primary)",
    }}>
      {isPdf ? <FileText size={18} /> : <ImageIcon size={18} />}
      <span style={{ fontSize: 8.5, fontWeight: 800, letterSpacing: ".04em", marginTop: 1 }}>{ext.slice(0, 4)}</span>
    </span>
  );
}

function Chip({ tone, icon: Icon, children }) {
  const c = { ok: ["rgba(15,118,110,.10)", "#0F766E"], warn: ["rgba(217,119,6,.12)", "#B45309"], edit: ["rgba(37,99,235,.10)", "#2563EB"], bad: ["rgba(220,38,38,.10)", "#B91C1C"], mute: ["var(--color-bg)", "var(--color-text-muted)"] }[tone];
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "5px 11px", borderRadius: 999, fontSize: 12, fontWeight: 600, background: c[0], color: c[1], maxWidth: 260, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
      {Icon && <Icon size={13} style={{ flexShrink: 0 }} />}{children}
    </span>
  );
}

function DocRow({ r, v, manual, folders, selected, onToggle, edited, onSet, onView, onDrop, onNewFolder }) {
  const [menu, setMenu] = useState(false);
  const removed = v.type === REMOVE;
  const flag = !manual && !edited && r.attention.length > 0;
  const tone = TYPE_TONE[v.type];

  if (r.sorting) {
    const bulkWait = r.doc?.processing_status === "queued" && r.doc?.processing_route === "bulk";
    const st = (bulkWait ? STAGE.bulk : STAGE[r.doc?.processing_status]) || STAGE.queued;
    const ahead = bulkWait ? " · big uploads are sorted in batches every few minutes"
      : r.doc?.processing_status === "queued" && r.doc?.queue_ahead > 0 ? ` · ${r.doc.queue_ahead} ahead of it` : "";
    return (
      <div className="card org-row" style={{ padding: "12px 16px", marginBottom: 8, display: "flex", alignItems: "center", gap: 14 }}>
        <input type="checkbox" disabled aria-label="Still sorting" />
        <span style={{ width: 42, height: 42, borderRadius: 8, flexShrink: 0, display: "inline-flex", alignItems: "center", justifyContent: "center", background: "var(--color-bg)", color: "var(--color-primary)" }}>
          <Loader2 size={18} className="spin" />
        </span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontWeight: 600, fontSize: 14, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{r.name}</div>
          <div style={{ fontSize: 12, color: "var(--color-text-muted)" }}>{st.label}{ahead}</div>
        </div>
        <div style={{ width: 180, height: 6, borderRadius: 6, background: "var(--color-border)", overflow: "hidden", flexShrink: 0 }}>
          <div style={{ height: "100%", width: `${st.pct}%`, background: "var(--color-primary)", transition: "width .5s" }} />
        </div>
      </div>
    );
  }

  let chip;
  if (removed) chip = <Chip tone="bad" icon={Trash2}>Will be removed</Chip>;
  else if (manual) chip = v.type ? <Chip tone="ok" icon={Check}>{TYPE_LABEL[v.type]}</Chip> : <Chip tone="mute">Not assigned</Chip>;
  else if (edited) chip = <Chip tone="edit" icon={Check}>Changed by you</Chip>;
  else if (flag) chip = <Chip tone="warn" icon={AlertTriangle}>Check: {r.attention[0]}</Chip>;
  else chip = <Chip tone="ok" icon={Sparkles}>Suggested: {TYPE_LABEL[r.machine.type] || "Other"}</Chip>;

  return (
    <div className="card org-row" style={{
      padding: "11px 16px", marginBottom: 8, display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap",
      outline: selected ? "2px solid var(--color-primary)" : "none",
      borderLeft: `3px solid ${removed ? "var(--color-error)" : flag ? "#D97706" : "transparent"}`,
    }}>
      <input type="checkbox" checked={selected} onChange={onToggle} aria-label={`Select ${r.name}`} />
      <FileBadge r={r} />
      <div style={{ flex: "1 1 200px", minWidth: 0 }}>
        <div style={{ fontWeight: 600, fontSize: 14, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", textDecoration: removed ? "line-through" : "none" }}>{r.name}</div>
        <div style={{ fontSize: 12, color: "var(--color-text-muted)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
          {r.meta}{flag && r.attention.length > 1 ? ` · also: ${r.attention.slice(1).join(", ")}` : ""}
        </div>
      </div>
      <div className="org-chip">{chip}</div>

      <div className="org-ctrls" style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", justifyContent: "flex-end" }}>
        {v.type === "lab_report" && (
          <select className="form-input" value={v.cat} onChange={e => onSet("cat", e.target.value)} aria-label="Lab panel"
            style={{ ...pill, borderColor: !v.cat ? "#D97706" : undefined, width: 165 }}>
            <option value="">Panel…</option>
            {CATEGORY_ORDER.map(s => <option key={s} value={s}>{CATEGORY_LABELS[s]}</option>)}
          </select>
        )}
        {!removed && (
          <input type="date" className="form-input" value={v.date} max={today()} onChange={e => onSet("date", e.target.value)}
            aria-label="Date on the document" title={v.date ? "Date on the document" : "Add the date on the document"}
            style={{ ...pill, width: 140, color: v.date ? undefined : "var(--color-text-muted)", borderColor: !v.date && !manual ? "#D97706" : undefined }} />
        )}
        <label style={{ position: "relative", display: "inline-flex", alignItems: "center" }}>
          <FolderClosed size={15} style={{ position: "absolute", left: 10, color: tone ? tone.fg : "var(--color-text-muted)", pointerEvents: "none" }} />
          <select className="form-input" value={v.type} onChange={e => onSet("type", e.target.value)} aria-label="Folder"
            style={{ ...pill, width: 200, paddingLeft: 31, fontWeight: 500, borderColor: !v.type ? "#D97706" : undefined }}>
            <option value="">Choose folder…</option>
            {TYPE_OPTIONS.map(([t, l]) => <option key={t} value={t}>{l}</option>)}
            {!manual && <option value={REMOVE}>Not medical — remove</option>}
          </select>
        </label>
        {v.folder && <Chip tone="mute" icon={FolderClosed}>{v.folder}</Chip>}
        <div style={{ position: "relative" }}>
          <button onClick={() => setMenu(m => !m)} aria-label="More" style={iconBtn}><MoreVertical size={16} /></button>
          {menu && (
            <RowMenu onClose={() => setMenu(false)} items={[
              ["View file", Eye, onView],
              ...folders.map(f => [`Put in “${f}”`, FolderClosed, () => onSet("folder", f)]),
              ...(v.folder ? [["Remove from my folder", X, () => onSet("folder", "")]] : []),
              ["New personal folder…", FolderPlus, onNewFolder],
              ...(onDrop ? [["Don't upload this", X, onDrop, true]]
                : [[removed ? "Keep it" : "Not medical — remove", Trash2, () => onSet("type", removed ? r.machine.type : REMOVE), !removed]]),
            ]} />
          )}
        </div>
      </div>
    </div>
  );
}

function RowMenu({ items, onClose }) {
  const ref = useRef(null);
  useEffect(() => {
    const h = (e) => { if (ref.current && !ref.current.contains(e.target)) onClose(); };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, [onClose]);
  return (
    <div ref={ref} className="card" style={{ position: "absolute", right: 0, top: "calc(100% + 6px)", zIndex: 30, minWidth: 220, padding: 6, maxHeight: 320, overflowY: "auto" }}>
      {items.map(([label, Icon, fn, danger]) => (
        <button key={label} onClick={() => { onClose(); fn(); }} style={{
          display: "flex", alignItems: "center", gap: 9, width: "100%", padding: "8px 10px", border: "none", borderRadius: 7,
          background: "none", cursor: "pointer", fontSize: 13, textAlign: "left", color: danger ? "#B91C1C" : "var(--color-text)",
        }}>
          <Icon size={14} /> {label}
        </button>
      ))}
    </div>
  );
}

const pill = { padding: "6px 10px", fontSize: 13, borderRadius: 9, height: 38, boxSizing: "border-box" };
const iconBtn = {
  width: 36, height: 36, borderRadius: 8, display: "inline-flex", alignItems: "center", justifyContent: "center",
  border: "1px solid var(--color-border)", background: "transparent", color: "var(--color-text-muted)", cursor: "pointer",
};
