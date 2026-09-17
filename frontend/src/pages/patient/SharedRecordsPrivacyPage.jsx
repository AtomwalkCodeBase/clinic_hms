/**
 * pages/patient/SharedRecordsPrivacyPage.jsx
 * -----------------------------------------
 * "Shared records privacy" — the patient chooses what a doctor sees when they
 * share their records (Share Records / RecordsShareRequest). One screen:
 *
 *   - a live readout of how many records are visible right now
 *   - independent filters: Category (multi) · Type (multi) · Month · search
 *   - the vault, grouped by category, each row a Shared / Hidden status pill
 *   - a per-category group pill and a multi-select + bulk Hide / Show
 *
 * "Private" is sticky — a hidden record stays hidden in every future share.
 * The ONLY dialog is the this-visit-vs-always choice, and it appears only
 * while a doctor is actively viewing; otherwise a plain confirm. Hiding is
 * always instant, with Undo.
 *
 * Backend: apps/patients/records_share_views.py
 *   GET/PUT /portal/records-privacy/            config + annotated vault
 *   POST    /portal/records-privacy/toggle/     one-record lock
 *   POST    /portal/records-share/<token>/reveal/  per-visit reveal (scope: visit|always|conceal)
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "react-toastify";
import {
  Lock, Search, ChevronDown, ChevronLeft, ChevronRight, RotateCw, X, Clock,
  FlaskConical, Pill, FileText, Image as ImageIcon,
} from "lucide-react";
import { AppShell } from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import { useToast } from "../../hooks/useToast";
import apiClient from "../../services/api.client";
import API_ENDPOINTS from "../../config/api.config";

const body = (res) => res?.data?.data ?? res?.data ?? {};

const KIND_LABEL = {
  lab_report: "Lab reports", prescription: "Prescriptions",
  scan: "Imaging", discharge_summary: "Discharge summaries", other: "Documents",
};
const KIND_ORDER = ["lab_report", "prescription", "scan", "discharge_summary", "other"];
const KIND_ICON = { lab_report: FlaskConical, prescription: Pill, scan: ImageIcon, discharge_summary: FileText, other: FileText };

const CATEGORY_LABELS = {
  cbc: "Complete Blood Count", lipid: "Lipid Profile", lft: "Liver Function Test",
  kft: "Kidney Function Test", thyroid: "Thyroid Profile", diabetes: "Blood Sugar & HbA1c",
  urine: "Urine Routine", electrolytes: "Serum Electrolytes", vitamin: "Vitamin & Mineral",
  inflammation: "Inflammatory Markers", cardiac: "Cardiac Markers", coagulation: "Coagulation Profile",
  hormone: "Hormone Panel", infection: "Infection Serology", culture: "Culture & Sensitivity",
};
const catLabel = (s) => CATEGORY_LABELS[s] || s;

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const dOf = (d) => d.document_date || d.created_at || "";
const monthLabel = (k) => { const [y, m] = k.split("-"); return `${MONTHS[(+m) - 1]} ${y}`; };
const fmtDate = (iso) => { if (!iso) return "—"; const dt = new Date(iso); return `${String(dt.getDate()).padStart(2, "0")} ${MONTHS[dt.getMonth()]} ${dt.getFullYear()}`; };

// The one bucket a document is grouped under here (its first known panel, or
// a kind bucket). Filtering by Category still matches every panel it carries.
function bucketOf(d) {
  const cats = (d.report_categories || []).filter((c) => CATEGORY_LABELS[c]);
  if (cats.length) return { key: `c:${cats[0]}`, label: catLabel(cats[0]) };
  return { key: `k:${d.doc_type}`, label: KIND_LABEL[d.doc_type] || "Documents" };
}
const bucketRank = (key) => {
  if (key.startsWith("c:")) return Object.keys(CATEGORY_LABELS).indexOf(key.slice(2));
  return 100 + KIND_ORDER.indexOf(key.slice(2));
};

// ── a tiny confirm / choice dialog ──────────────────────────────────────────
function Dialog({ title, message, actions, onClose }) {
  return (
    <div onClick={onClose} style={{ position: "fixed", inset: 0, background: "rgba(15,23,20,.42)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 1000, padding: 20 }}>
      <div onClick={(e) => e.stopPropagation()} className="card" style={{ width: "min(420px,100%)", padding: 22 }}>
        <h3 style={{ margin: "0 0 8px", fontSize: 16 }}>{title}</h3>
        <p style={{ margin: "0 0 16px", fontSize: 13, color: "var(--color-text-secondary)", lineHeight: 1.5 }}>{message}</p>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {actions.map((a, i) => (
            <button key={i} onClick={() => { onClose(); a.onClick?.(); }}
              className={a.primary ? "btn-primary" : "btn-outline"}
              style={{ width: a.sub ? "100%" : "auto", alignSelf: a.sub ? "stretch" : "flex-end", textAlign: a.sub ? "left" : "center", padding: a.sub ? "9px 13px" : "8px 14px" }}>
              <span style={{ fontWeight: 600 }}>{a.label}</span>
              {a.sub && <span style={{ display: "block", fontSize: 11, fontWeight: 400, color: a.primary ? "rgba(255,255,255,.85)" : "var(--color-text-muted)" }}>{a.sub}</span>}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

function toastUndo(msg, undo) {
  toast(({ closeToast }) => (
    <span style={{ display: "flex", gap: 14, alignItems: "center" }}>
      {msg}
      <button onClick={() => { undo(); closeToast(); }}
        style={{ font: "inherit", fontWeight: 700, textDecoration: "underline", background: "none", border: 0, cursor: "pointer", color: "inherit" }}>
        Undo
      </button>
    </span>
  ), { autoClose: 6000 });
}

// ── status pill (the visibility control) ────────────────────────────────────
function StatusPill({ state, onClick, small }) {
  const map = {
    on:    { txt: "Shared", cls: "on" },
    off:   { txt: "Hidden", cls: "off" },
    visit: { txt: "This visit", cls: "on" },
  };
  const m = map[state] || map.off;
  const on = m.cls === "on";
  return (
    <button onClick={onClick} title="What a doctor sees when you share your records"
      style={{
        display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 6,
        font: "inherit", fontSize: small ? 10 : 10.5, fontWeight: 600, letterSpacing: ".02em",
        borderRadius: 999, padding: small ? "3px 10px" : "4px 12px", minWidth: small ? 0 : 78, cursor: "pointer",
        border: `1px solid ${on ? "var(--color-primary)" : "var(--color-border)"}`,
        background: on ? "var(--color-primary-soft, rgba(21,119,74,.10))" : "var(--color-surface, #fff)",
        color: on ? "var(--color-primary)" : "var(--color-text-muted)",
      }}>
      {state === "visit"
        ? <Clock size={11} />
        : <span style={{ width: 6, height: 6, borderRadius: 999, background: on ? "var(--color-primary)" : "var(--color-text-muted)", opacity: on ? 1 : 0.5 }} />}
      {m.txt}
    </button>
  );
}

// ── multi-select filter popover ────────────────────────────────────────────
function MultiFilter({ label, options, selected, onChange }) {
  const [open, setOpen] = useState(false);
  const active = selected.length > 0 && selected.length < options.length;
  return (
    <div style={{ position: "relative" }}>
      <button onClick={() => setOpen((o) => !o)}
        className="btn-outline"
        style={{ fontSize: 12.5, padding: "7px 10px", display: "inline-flex", alignItems: "center", gap: 7,
          ...(active ? { borderColor: "var(--color-primary)", color: "var(--color-primary)" } : {}) }}>
        {label}{active ? ` · ${selected.length}` : ""}<ChevronDown size={12} />
      </button>
      {open && (
        <>
          <div onClick={() => setOpen(false)} style={{ position: "fixed", inset: 0, zIndex: 20 }} />
          <div className="card" style={{ position: "absolute", top: "calc(100% + 6px)", left: 0, zIndex: 30, minWidth: 230, padding: 6 }}>
            <div style={{ display: "flex", justifyContent: "space-between", padding: "6px 8px 8px", borderBottom: "1px solid var(--color-border)", marginBottom: 4, fontSize: 10.5, textTransform: "uppercase", letterSpacing: ".05em", color: "var(--color-text-muted)", fontWeight: 600 }}>
              <span>{label}</span>
              <span>
                <button onClick={() => onChange(options.map((o) => o.value))} style={linkBtn}>All</button>
                {" · "}
                <button onClick={() => onChange([])} style={linkBtn}>Clear</button>
              </span>
            </div>
            {options.map((o) => (
              <label key={o.value} style={{ display: "flex", alignItems: "center", gap: 9, padding: "7px 8px", borderRadius: 6, fontSize: 12.5, cursor: "pointer" }}>
                <input type="checkbox" checked={selected.includes(o.value)}
                  onChange={(e) => onChange(e.target.checked ? [...selected, o.value] : selected.filter((v) => v !== o.value))} />
                <span style={{ flex: 1 }}>{o.label}</span>
                <span style={{ fontFamily: "monospace", fontSize: 10.5, color: "var(--color-text-muted)" }}>{o.count}</span>
              </label>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
const linkBtn = { font: "inherit", fontSize: 11, fontWeight: 600, color: "var(--color-primary)", background: "none", border: 0, cursor: "pointer", textTransform: "none", letterSpacing: 0 };

// debounce a fast-changing value (the search box) so it drives one request
// when the user pauses, not one per keystroke.
function useDebounced(value, ms) {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

// ── page navigator ────────────────────────────────────────────────────────
// The list is paged on category boundaries server-side (whole panels per
// page), so this only ever steps between page numbers.
function Pager({ meta, onPage }) {
  const { page, total_pages, has_next, has_previous } = meta;
  if (total_pages <= 1) return null;
  const btn = (dis) => ({
    display: "inline-flex", alignItems: "center", gap: 4, font: "inherit", fontSize: 12.5,
    padding: "6px 12px", borderRadius: 8, border: "1px solid var(--color-border)",
    background: "var(--color-surface, #fff)", cursor: dis ? "default" : "pointer",
    opacity: dis ? 0.45 : 1,
  });
  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 14, margin: "18px 0 4px" }}>
      <button style={btn(!has_previous)} disabled={!has_previous} onClick={() => onPage(page - 1)}>
        <ChevronLeft size={14} /> Prev
      </button>
      <span style={{ fontSize: 12, color: "var(--color-text-muted)", fontVariantNumeric: "tabular-nums" }}>
        Page {page} of {total_pages}
      </span>
      <button style={btn(!has_next)} disabled={!has_next} onClick={() => onPage(page + 1)}>
        Next <ChevronRight size={14} />
      </button>
    </div>
  );
}

// ───────────────────────────────────────────────────────────────────────────
export default function SharedRecordsPrivacyPage() {
  const { toastApiError } = useToast();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [dialog, setDialog] = useState(null);

  const [catSel, setCatSel] = useState([]);
  const [kindSel, setKindSel] = useState([]);
  const [month, setMonth] = useState("all");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [sel, setSel] = useState(new Set());

  const qDebounced = useDebounced(q, 300);
  const listTopRef = useRef(null);

  // Any filter change: back to page 1 and drop a selection that spanned the
  // old result set. Wrapped setters keep both updates in one render so the
  // fetch fires once.
  const onFilter = (fn) => (v) => { fn(v); setPage(1); setSel(new Set()); };
  const setCat = onFilter(setCatSel);
  const setKind = onFilter(setKindSel);
  const setMonthF = onFilter(setMonth);
  const firstQ = useRef(true);
  useEffect(() => {
    if (firstQ.current) { firstQ.current = false; return; }
    setPage(1); setSel(new Set());
  }, [qDebounced]);

  const load = useCallback(async () => {
    try {
      const params = { page };
      if (catSel.length) params.category = catSel.join(",");
      if (kindSel.length) params.kind = kindSel.join(",");
      if (month !== "all") params.month = month;
      if (qDebounced.trim()) params.q = qDebounced.trim();
      setData(body(await apiClient.get(API_ENDPOINTS.PORTAL.RECORDS_PRIVACY, { params })));
    } catch (err) {
      toastApiError(err, "Could not load your privacy settings.");
    } finally { setLoading(false); }
  }, [toastApiError, page, catSel, kindSel, month, qDebounced]);

  useEffect(() => { load(); }, [load]);

  const docs = useMemo(() => data?.documents || [], [data]);          // one page
  const summary = data?.summary || {};
  const pagination = data?.pagination || null;
  const session = data?.active_session || null;

  const vaultTotal = summary.vault_total || 0;
  const shownCount = summary.shown || 0;
  const filteredTotal = summary.filtered_total ?? docs.length;

  const catOptions = useMemo(() => {
    const counts = summary.category_counts || {};
    const labels = summary.category_labels || {};
    return Object.keys(counts)
      .sort((a, b) => bucketRank(`c:${a}`) - bucketRank(`c:${b}`))
      .map((value) => ({ value, label: labels[value] || catLabel(value), count: counts[value] }));
  }, [summary]);
  const kindOptions = useMemo(() => {
    const counts = summary.kind_counts || {};
    return KIND_ORDER.filter((k) => counts[k]).map((k) => ({ value: k, label: KIND_LABEL[k], count: counts[k] }));
  }, [summary]);
  const monthOptions = summary.months || [];

  // `docs` is already this page's rows in category order; just re-bucket them
  // for the section headers. The server never splits a group across pages.
  const groups = useMemo(() => {
    const m = new Map();
    docs.forEach((d) => {
      const b = bucketOf(d);
      if (!m.has(b.key)) m.set(b.key, { ...b, list: [] });
      m.get(b.key).list.push(d);
    });
    return [...m.values()].sort((a, b) => bucketRank(a.key) - bucketRank(b.key));
  }, [docs]);

  const stateOf = (d) => (d.revealed_for_visit ? "visit" : d.private ? "off" : "on");

  const filtersOn = catSel.length || kindSel.length || month !== "all" || q.trim();

  const goPage = (n) => {
    setPage(n);
    listTopRef.current?.scrollIntoView({ block: "start", behavior: "smooth" });
  };

  // ── mutations ────────────────────────────────────────────────────────────
  async function setPrivate(ids, makePrivate) {
    // hide: instant. show: caller has already run the dialog / confirm.
    const list = Array.isArray(ids) ? ids : [ids];
    if (!list.length) return;
    try {
      if (list.length === 1) {
        await apiClient.post(API_ENDPOINTS.PORTAL.RECORDS_PRIVACY_TOGGLE, { doc_id: list[0], private: makePrivate });
      } else {
        // paged list → send a delta, not a full replacement set
        await apiClient.put(API_ENDPOINTS.PORTAL.RECORDS_PRIVACY,
          makePrivate ? { add_hidden_doc_ids: list } : { remove_hidden_doc_ids: list });
      }
      await load();
    } catch (err) { toastApiError(err, "Could not update."); }
  }
  async function reveal(ids, scope) {
    if (!session) return;
    try {
      await apiClient.post(API_ENDPOINTS.PORTAL.RECORDS_SHARE_REVEAL(session.token), { doc_ids: Array.isArray(ids) ? ids : [ids], scope });
      await load();
    } catch (err) { toastApiError(err, "Could not update."); }
  }
  async function putConfig(patch, undoPatch, msg) {
    try {
      await apiClient.put(API_ENDPOINTS.PORTAL.RECORDS_PRIVACY, patch);
      await load();
      if (msg) toastUndo(msg, async () => { await apiClient.put(API_ENDPOINTS.PORTAL.RECORDS_PRIVACY, undoPatch); load(); });
    } catch (err) { toastApiError(err, "Could not update."); }
  }

  function askHide(count, name, onConfirm) {
    setDialog({
      title: count > 1 ? `Hide ${count} records from doctors?` : "Hide this from doctors?",
      message: `A doctor you share with won't see ${name}. You can show ${count > 1 ? "them" : "it"} again anytime.`,
      actions: [{ label: "Cancel" }, { label: "Hide", primary: true, onClick: onConfirm }],
    });
  }

  function onRowPill(d) {
    const st = stateOf(d);
    const name = d.title;
    if (st === "on") {
      askHide(1, name, () => setPrivate(d.id, true).then(() => toastUndo(`${name} is now private.`, () => setPrivate(d.id, false))));
    } else if (st === "visit") {
      reveal(d.id, "conceal").then(() => toastUndo(`${name} hidden again.`, () => reveal(d.id, "visit")));
    } else if (session) {
      setDialog({
        title: "A doctor is viewing now",
        message: `Show ${name} to ${session.requester_label || "the doctor"} —`,
        actions: [
          { label: "Just this visit", sub: "Hides again when the visit ends", primary: true, onClick: () => reveal(d.id, "visit") },
          { label: "Always", sub: "Stays visible for future visits too", onClick: () => setPrivate(d.id, false) },
          { label: "Cancel" },
        ],
      });
    } else {
      setDialog({
        title: "Show this to doctors again?",
        message: `Doctors you share with will be able to see ${name}.`,
        actions: [{ label: "Cancel" }, { label: "Show", primary: true, onClick: () => setPrivate(d.id, false) }],
      });
    }
  }

  function bulkShow(ids) {
    if (!ids.length) return;
    const n = ids.length;
    if (session) {
      setDialog({
        title: `Show ${n} record${n > 1 ? "s" : ""} to the doctor`,
        message: "For this visit only, or always?",
        actions: [
          { label: "Just this visit", sub: `All ${n} hide again when the visit ends`, primary: true, onClick: () => { reveal(ids, "visit"); setSel(new Set()); } },
          { label: "Always", sub: "Visible to future visits too", onClick: () => { setPrivate(ids, false); setSel(new Set()); } },
          { label: "Cancel" },
        ],
      });
    } else {
      setDialog({
        title: `Show ${n} record${n > 1 ? "s" : ""} to doctors?`,
        message: "Doctors you share with will be able to see them.",
        actions: [{ label: "Cancel" }, { label: "Show", primary: true, onClick: () => { setPrivate(ids, false); setSel(new Set()); } }],
      });
    }
  }
  function bulkHide(ids) {
    if (!ids.length) return;
    setPrivate(ids, true).then(() => { setSel(new Set()); toastUndo(`${ids.length} record${ids.length > 1 ? "s" : ""} hidden.`, () => setPrivate(ids, false)); });
  }

  function groupPill(g) {
    const shownIds = g.list.filter((d) => stateOf(d) !== "off").map((d) => d.id);
    const hiddenIds = g.list.filter((d) => stateOf(d) === "off").map((d) => d.id);
    if (hiddenIds.length === 0) askHide(shownIds.length, `every report in ${g.label}`, () => bulkHide(shownIds));
    else bulkShow(hiddenIds);
  }

  const selectedIds = [...sel];

  return (
    <AppShell>
      <PageShell title="Shared records privacy">
        <p style={{ marginTop: -8, marginBottom: 16, fontSize: 13, color: "var(--color-text-secondary)", maxWidth: "62ch" }}>
          Choose what a doctor sees when you share your records. Nothing here is hidden from you, and nothing is deleted.
        </p>

        {loading ? (
          <div className="card" style={{ padding: 40, textAlign: "center", color: "var(--color-text-muted)" }}>Loading…</div>
        ) : (
          <>
            {session && (
              <div className="card" style={{ padding: "11px 14px", marginBottom: 14, display: "flex", gap: 10, alignItems: "flex-start", borderColor: "var(--color-warning, #b45309)", background: "var(--color-warning-soft, #fbf3e6)" }}>
                <Clock size={14} style={{ marginTop: 2, flexShrink: 0, color: "var(--color-warning, #b45309)" }} />
                <span style={{ fontSize: 12, lineHeight: 1.5 }}>
                  <b>{session.requester_label || "A doctor"} is viewing your records now.</b> Showing a private record
                  asks whether it&rsquo;s <b>just this visit</b> or <b>always</b>. Locking one takes effect right away.
                </span>
              </div>
            )}

            {/* readout */}
            <div className="card" style={{ padding: 16, marginBottom: 16 }}>
              <div style={{ fontSize: 10.5, letterSpacing: ".06em", textTransform: "uppercase", color: "var(--color-text-muted)", fontWeight: 600 }}>Visible to a doctor</div>
              <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginTop: 4 }}>
                <span style={{ fontFamily: "monospace", fontSize: 20, fontWeight: 600, color: "var(--color-primary)" }}>{shownCount} / {vaultTotal}</span>
                <span style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>records</span>
                <span style={{ marginLeft: "auto", display: "flex", gap: 10, fontSize: 12.5 }}>
                  <button style={linkBtn} onClick={() => bulkShow(summary.showable_ids || [])}>Show all</button>
                  <span style={{ color: "var(--color-border)" }}>·</span>
                  <button style={{ ...linkBtn, color: "var(--color-text-muted)" }} onClick={() => askHide((summary.hideable_ids || []).length, "every record", () => bulkHide(summary.hideable_ids || []))}>Hide all</button>
                </span>
              </div>
              <div style={{ marginTop: 10, height: 6, borderRadius: 999, background: "var(--color-border)", overflow: "hidden" }}>
                <div style={{ height: "100%", width: `${vaultTotal ? (shownCount / vaultTotal) * 100 : 0}%`, background: "var(--color-primary)" }} />
              </div>
              {summary.truncated && (
                <div style={{ marginTop: 8, fontSize: 11, color: "var(--color-text-muted)" }}>
                  Showing your {vaultTotal} most recent records.
                </div>
              )}
            </div>

            {/* broad rules */}
            <details className="card" style={{ padding: 0, marginBottom: 16 }}>
              <summary style={{ padding: "13px 16px", cursor: "pointer", fontSize: 13, fontWeight: 600, listStyle: "none" }}>
                Broad rules <span style={{ fontWeight: 400, fontSize: 11, color: "var(--color-text-muted)" }}>— hide whole categories, kinds or sections</span>
              </summary>
              <div style={{ borderTop: "1px solid var(--color-border)", padding: "6px 0 10px" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "12px 16px" }}>
                  <span style={{ flex: 1 }}>
                    <span style={{ fontSize: 13, fontWeight: 600 }}>Hide everything by default</span>
                    <span style={{ display: "block", fontSize: 11, color: "var(--color-text-muted)" }}>Every new share starts empty; you reveal what to show.</span>
                  </span>
                  <input type="checkbox" checked={!!data.hide_all}
                    onChange={(e) => putConfig({ hide_all: e.target.checked }, { hide_all: !e.target.checked },
                      e.target.checked ? "Hiding everything by default." : "Showing by your other rules.")} />
                </div>
                <RuleChips label="Hidden categories — also catches future reports"
                  options={catOptions} selected={data.hidden_categories || []}
                  onToggle={(next) => putConfig({ hidden_categories: next }, { hidden_categories: data.hidden_categories || [] }, "Category rules updated.")} />
                <RuleChips label="Hidden kinds"
                  options={kindOptions} selected={data.hidden_kinds || []}
                  onToggle={(next) => putConfig({ hidden_kinds: next }, { hidden_kinds: data.hidden_kinds || [] }, "Kind rules updated.")} />
                <RuleChips label="Hidden sections of the shared view"
                  options={(data.sections || []).map((s) => ({ value: s, label: (data.section_labels || {})[s] || s, count: "" }))}
                  selected={data.hidden_sections || []}
                  onToggle={(next) => putConfig({ hidden_sections: next }, { hidden_sections: data.hidden_sections || [] }, "Section rules updated.")} />
              </div>
            </details>

            {/* filter bar */}
            <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginBottom: 4 }}>
              <MultiFilter label="Categories" options={catOptions} selected={catSel} onChange={setCat} />
              <MultiFilter label="Type" options={kindOptions} selected={kindSel} onChange={setKind} />
              <select className="form-input" value={month} onChange={(e) => setMonthF(e.target.value)} style={{ fontSize: 12.5, padding: "7px 9px", maxWidth: 150 }}>
                <option value="all">Any month</option>
                {monthOptions.map((k) => <option key={k} value={k}>{monthLabel(k)}</option>)}
              </select>
              <label style={{ position: "relative", flex: "1 1 160px", minWidth: 140, marginLeft: "auto" }}>
                <Search size={13} style={{ position: "absolute", left: 9, top: "50%", transform: "translateY(-50%)", color: "var(--color-text-muted)" }} />
                <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search" className="form-input" style={{ fontSize: 12.5, padding: "7px 10px 7px 28px", width: "100%" }} />
              </label>
              <button className="btn-outline" style={{ fontSize: 12, padding: "6px 10px" }} onClick={load}><RotateCw size={12} /></button>
            </div>
            {filtersOn ? (
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center", margin: "10px 0 2px" }}>
                {catSel.map((c) => <Chip key={c} label={catLabel(c)} onX={() => setCat(catSel.filter((v) => v !== c))} />)}
                {kindSel.map((k) => <Chip key={k} label={KIND_LABEL[k]} onX={() => setKind(kindSel.filter((v) => v !== k))} />)}
                {month !== "all" && <Chip label={monthLabel(month)} onX={() => setMonthF("all")} />}
                <button style={{ ...linkBtn, color: "var(--color-text-muted)", textDecoration: "underline" }}
                  onClick={() => { setCatSel([]); setKindSel([]); setMonth("all"); setQ(""); setPage(1); setSel(new Set()); }}>Clear all</button>
              </div>
            ) : null}

            <div ref={listTopRef} style={{ fontSize: 11.5, color: "var(--color-text-muted)", margin: "14px 0 2px", scrollMarginTop: 12 }}>
              {filteredTotal} of {vaultTotal} records
              {selectedIds.length ? ` · ${selectedIds.length} selected` : ""}
              {(summary.filtered_ids || []).length ? <>
                {" · "}
                <button style={{ ...linkBtn, fontSize: 11.5, textTransform: "none", letterSpacing: 0, color: "var(--color-text-muted)" }}
                  onClick={() => setSel((prev) => {
                    const fids = summary.filtered_ids || [];
                    const all = fids.length && fids.every((id) => prev.has(id));
                    const n = new Set(prev);
                    fids.forEach((id) => (all ? n.delete(id) : n.add(id)));
                    return n;
                  })}>
                  {(summary.filtered_ids || []).every((id) => sel.has(id)) ? "Clear selection" : `Select all ${filteredTotal}`}
                </button>
              </> : null}
            </div>

            {groups.length === 0 ? (
              <div className="card" style={{ padding: 40, textAlign: "center", color: "var(--color-text-muted)", fontSize: 13 }}>No records match these filters.</div>
            ) : groups.map((g) => {
              const shown = g.list.filter((d) => stateOf(d) !== "off").length;
              const allShown = shown === g.list.length, none = shown === 0;
              return (
                <div key={g.key} style={{ borderTop: "1px solid var(--color-border)" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "12px 2px" }}>
                    <span style={{ fontSize: 12.5, fontWeight: 600 }}>{g.label}</span>
                    <span style={{ fontFamily: "monospace", fontSize: 10.5, color: "var(--color-text-muted)" }}>{g.list.length}</span>
                    <span style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 12 }}>
                      <button style={{ ...linkBtn, fontSize: 11 }} onClick={() => setSel((prev) => {
                        const ids = g.list.map((d) => d.id);
                        const all = ids.every((id) => prev.has(id));
                        const n = new Set(prev); ids.forEach((id) => (all ? n.delete(id) : n.add(id)));
                        return n;
                      })}>{g.list.every((d) => sel.has(d.id)) ? "Deselect" : "Select"}</button>
                      <button onClick={() => groupPill(g)}
                        style={{ font: "inherit", fontSize: 10, fontWeight: 600, borderRadius: 999, padding: "4px 11px", cursor: "pointer",
                          border: `1px solid ${allShown ? "var(--color-primary)" : "var(--color-border)"}`,
                          background: allShown ? "var(--color-primary-soft, rgba(21,119,74,.10))" : "transparent",
                          color: allShown ? "var(--color-primary)" : none ? "var(--color-text-muted)" : "var(--color-text-primary, inherit)" }}>
                        {allShown ? "All shared" : none ? "All hidden" : `${shown} / ${g.list.length} shared`}
                      </button>
                    </span>
                  </div>
                  {g.list.map((d) => {
                    const Icon = KIND_ICON[d.doc_type] || FileText;
                    const picked = sel.has(d.id);
                    return (
                      <div key={d.id} style={{ display: "flex", alignItems: "center", gap: 12, padding: "10px 2px 10px 22px", borderTop: "1px solid var(--color-border)", background: picked ? "var(--color-primary-soft, rgba(21,119,74,.07))" : "transparent" }}>
                        <input type="checkbox" checked={picked}
                          onChange={(e) => setSel((prev) => { const n = new Set(prev); e.target.checked ? n.add(d.id) : n.delete(d.id); return n; })} />
                        <span style={{ width: 28, height: 28, borderRadius: 7, flexShrink: 0, display: "flex", alignItems: "center", justifyContent: "center", background: "var(--color-surface-2, #f2f4f2)", color: "var(--color-text-muted)" }}>
                          <Icon size={14} />
                        </span>
                        <span style={{ flex: 1, minWidth: 0 }}>
                          <span style={{ fontSize: 12.5, fontWeight: 500, display: "block", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", color: stateOf(d) === "off" ? "var(--color-text-muted)" : "inherit" }}>
                            {d.doc_type === "prescription" && d.doctor_label ? `Prescription · ${d.doctor_label}` : d.title}
                          </span>
                          <span style={{ fontSize: 10.5, fontFamily: "monospace", color: "var(--color-text-muted)" }}>
                            {[fmtDate(dOf(d)), d.hospital_label, catLabel((d.report_categories || [])[0] || "")].filter(Boolean).join(" · ")}
                            {d.private_by_rule ? " · by rule" : ""}
                          </span>
                        </span>
                        <StatusPill state={stateOf(d)} onClick={() => onRowPill(d)} />
                      </div>
                    );
                  })}
                </div>
              );
            })}

            {pagination && <Pager meta={pagination} onPage={goPage} />}

            {selectedIds.length > 0 && (
              <div className="card" style={{ position: "sticky", bottom: 16, marginTop: 16, display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap", padding: "10px 14px" }}>
                <b style={{ fontSize: 12.5 }}>{selectedIds.length} selected</b>
                <span style={{ flex: 1 }} />
                <button className="btn-outline" style={{ fontSize: 12, padding: "7px 13px" }} onClick={() => askHide(selectedIds.length, "the selected records", () => bulkHide(selectedIds))}>Hide</button>
                <button className="btn-primary" style={{ fontSize: 12, padding: "7px 13px" }} onClick={() => bulkShow(selectedIds)}>Show</button>
                <button style={{ ...linkBtn, color: "var(--color-text-muted)", textDecoration: "underline" }} onClick={() => setSel(new Set())}>Clear</button>
              </div>
            )}

            <p style={{ marginTop: 22, fontSize: 11, color: "var(--color-text-muted)", lineHeight: 1.6, maxWidth: "74ch" }}>
              <Lock size={11} style={{ verticalAlign: "-1px" }} /> Locking a record only changes what a doctor sees
              when you share your records — it never removes it from your own view and never deletes it.
            </p>
          </>
        )}
      </PageShell>

      {dialog && <Dialog {...dialog} onClose={() => setDialog(null)} />}
    </AppShell>
  );
}

function Chip({ label, onX }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 11.5, border: "1px solid var(--color-border)", borderRadius: 999, padding: "4px 6px 4px 10px" }}>
      {label}
      <button onClick={onX} style={{ width: 16, height: 16, border: 0, background: "none", cursor: "pointer", color: "var(--color-text-muted)", display: "flex", alignItems: "center", justifyContent: "center" }}><X size={12} /></button>
    </span>
  );
}

function RuleChips({ label, options, selected, onToggle }) {
  return (
    <>
      <div style={{ fontFamily: "monospace", fontSize: 10, letterSpacing: ".12em", textTransform: "uppercase", color: "var(--color-text-muted)", padding: "12px 16px 6px" }}>{label}</div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8, padding: "0 16px 6px" }}>
        {options.length === 0 && <span style={{ fontSize: 11.5, color: "var(--color-text-muted)" }}>None yet.</span>}
        {options.map((o) => {
          const on = selected.includes(o.value);
          return (
            <button key={o.value}
              onClick={() => onToggle(on ? selected.filter((v) => v !== o.value) : [...selected, o.value])}
              style={{ display: "inline-flex", alignItems: "center", gap: 7, fontSize: 12, padding: "7px 11px", borderRadius: 9, cursor: "pointer",
                border: `1px solid ${on ? "var(--color-primary)" : "var(--color-border)"}`,
                background: on ? "var(--color-primary-soft, rgba(21,119,74,.10))" : "var(--color-surface, #fff)",
                color: on ? "var(--color-primary)" : "var(--color-text-muted)", fontWeight: on ? 600 : 400 }}>
              <span style={{ width: 10, height: 10, borderRadius: 3, border: "1.5px solid currentColor", background: on ? "currentColor" : "transparent" }} />
              {o.label}{o.count !== "" && o.count != null ? <span style={{ opacity: 0.7 }}>{o.count}</span> : null}
            </button>
          );
        })}
      </div>
    </>
  );
}
