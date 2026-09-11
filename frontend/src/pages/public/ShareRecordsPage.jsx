/**
 * pages/public/ShareRecordsPage.jsx
 * --------------------------------
 * "Share Records" — what a doctor's laptop opens.
 *
 * The PATIENT starts the flow in their app: they create a share link and
 * send it to the doctor. The doctor opens that link here (no account):
 *
 *   /s  (or /share-records)   no token — the doctor types the 6-digit code
 *                             the patient reads out. That claims the session
 *                             (binds this browser, mints a device token) and
 *                             redirects to /share-records/<token>.
 *   /share-records/<token>    shows a QR (carrying the session's `pairing`)
 *                             + that pairing as text, and waits. The patient
 *                             scans it in their app and confirms; this page
 *                             then fills in with the records, read-only, for
 *                             2 hours. Opening this path directly (a link the
 *                             patient sent) self-claims by token.
 *
 * There is NO web approve path — approval only ever happens in the app.
 * Deliberately outside AppShell / ProtectedRoute. Every read carries the
 * X-Share-Device token from the claim, so a leaked link/QR reads nothing.
 * Backend: apps/patients/records_share_views.py.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  ShieldCheck, ShieldAlert, Clock, QrCode, FileText, Pill, FlaskConical,
  Stethoscope, Activity, AlertTriangle, Download, Hourglass, Eye,
  Search, RotateCw, SlidersHorizontal, LayoutGrid, Syringe, HeartPulse, Lock,
  X, ChevronLeft, ChevronRight,
} from "lucide-react";
import { publicClient } from "../../services/api.client";
import API_ENDPOINTS from "../../config/api.config";

/* ── the one place the feature is named ─────────────────────────────────── */
const FEATURE_NAME = "Share Records";

/* ── small helpers ─────────────────────────────────────────────────────── */
const unwrap = (res) => res.data?.data ?? res.data;

/* ── laptop binding ────────────────────────────────────────────────────────
 * When this browser "claims" a session it gets a one-time device token. We
 * keep it in sessionStorage (per tab, gone when the tab closes) and send it
 * as X-Share-Device on every read — the backend refuses a claimed session's
 * data to anyone without it, so a forwarded link or a photographed QR sees
 * nothing.
 */
const devKey = (token) => `rshare:dev:${token}`;
const getDev = (token) => {
  try { return sessionStorage.getItem(devKey(token)) || ""; } catch { return ""; }
};
const setDev = (token, v) => {
  try { sessionStorage.setItem(devKey(token), v); } catch { /* private mode — the in-memory flow still works this session */ }
};
const devHeaders = (token) => {
  const d = getDev(token);
  return d ? { headers: { "X-Share-Device": d } } : {};
};
const shareGet = (token, url) => publicClient.get(url, devHeaders(token));
const sharePost = (token, url, body) => publicClient.post(url, body, devHeaders(token));

function useIsWide(bp = 860) {
  const [wide, setWide] = useState(
    typeof window === "undefined" ? true : window.innerWidth >= bp,
  );
  useEffect(() => {
    const on = () => setWide(window.innerWidth >= bp);
    window.addEventListener("resize", on);
    return () => window.removeEventListener("resize", on);
  }, [bp]);
  return wide;
}

function useCountdown(secondsLeft) {
  const [left, setLeft] = useState(secondsLeft ?? 0);
  useEffect(() => { setLeft(secondsLeft ?? 0); }, [secondsLeft]);
  useEffect(() => {
    if (left <= 0) return;
    const id = setInterval(() => setLeft((n) => Math.max(0, n - 1)), 1000);
    return () => clearInterval(id);
  }, [left]);
  const mm = String(Math.floor(left / 60)).padStart(2, "0");
  const ss = String(left % 60).padStart(2, "0");
  return { left, label: `${mm}:${ss}` };
}

const ymKey = (iso) => {
  const d = new Date(iso || "");
  return isNaN(d) ? "" : `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
};
const ymLabel = (key) => {
  const [y, m] = key.split("-").map(Number);
  return new Date(y, m - 1, 1).toLocaleDateString("en-IN", { month: "long", year: "numeric" });
};
const fmtShort = (iso) => {
  const d = new Date(iso || "");
  return isNaN(d) ? "" : d.toLocaleDateString("en-IN", { day: "numeric", month: "short" });
};
const fmtLong = (iso) => {
  const d = new Date(iso || "");
  return isNaN(d) ? "—" : d.toLocaleDateString("en-IN", { day: "numeric", month: "long", year: "numeric" });
};

const DOC_META = {
  prescription: { tag: "RX", label: "Prescription", Icon: Pill },
  lab_report:   { tag: "LAB", label: "Lab report", Icon: FlaskConical },
  scan:         { tag: "SCAN", label: "Scan", Icon: FileText },
  discharge_summary: { tag: "DISCH", label: "Discharge summary", Icon: FileText },
  other:        { tag: "DOC", label: "Document", Icon: FileText },
};
const metaFor = (t) => DOC_META[t] || DOC_META.other;

/* ── shared shell ──────────────────────────────────────────────────────── */
function Shell({ children, wide, xwide }) {
  return (
    <div style={{ minHeight: "100vh", background: "#f4f6f8", padding: "24px 16px" }}>
      <div style={{ maxWidth: xwide ? 960 : wide ? 760 : 460, margin: "0 auto" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 16, color: "#1B5E43", fontWeight: 800, fontSize: 15 }}>
          <ShieldCheck size={18} /> {FEATURE_NAME}
        </div>
        {children}
      </div>
    </div>
  );
}
const card = { background: "#fff", border: "1px solid #e5e7eb", borderRadius: 14, padding: 18 };
const btnPrimary = { background: "#1B5E43", color: "#fff", border: "none", borderRadius: 9, padding: "10px 16px", fontWeight: 600, fontSize: 14, cursor: "pointer" };
const btnOutline = { background: "#fff", color: "#374151", border: "1px solid #d1d5db", borderRadius: 9, padding: "10px 16px", fontWeight: 600, fontSize: 14, cursor: "pointer" };

/* ═══════════════════════════════════════════ front door — doctor types the patient's 6-digit code */
function EntryForm() {
  const navigate = useNavigate();
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  async function submit(e) {
    e?.preventDefault?.();
    if (code.length !== 6 || busy) return;
    setBusy(true); setErr("");
    try {
      const d = unwrap(await publicClient.post(API_ENDPOINTS.RECORDS_SHARE.CLAIM, { code }));
      setDev(d.token, d.device_token);
      navigate(`/share-records/${d.token}`);
    } catch (e2) {
      const s = e2?.status;
      setErr(
        s === 404 ? "That code doesn't match a waiting request. Check the 6 digits on the patient's phone."
        : s === 423 ? "Too many tries. Ask the patient to start a new share."
        : s === 409 ? "That share has already been opened or has ended. Ask the patient for a fresh code."
        : "Couldn't open that. Check your connection and try again.",
      );
    } finally { setBusy(false); }
  }

  return (
    <Shell>
      <form style={{ ...card, textAlign: "center" }} onSubmit={submit}>
        <h1 style={{ fontSize: 17, fontWeight: 700, margin: "0 0 6px" }}>Enter the patient's code</h1>
        <p style={{ fontSize: 13, color: "#6b7280", margin: "0 0 16px", lineHeight: 1.5 }}>
          Ask the patient to open <b>Share Records</b> in their HealthNet app and read you the
          6-digit code. Type it below.
        </p>
        <input
          value={code}
          onChange={(e) => { setErr(""); setCode(e.target.value.replace(/\D/g, "").slice(0, 6)); }}
          inputMode="numeric"
          autoFocus
          aria-label="6-digit code"
          placeholder="______"
          style={{
            width: "100%", boxSizing: "border-box", textAlign: "center",
            fontFamily: "monospace", fontSize: 30, fontWeight: 800, letterSpacing: 10,
            padding: "12px 0", border: "1px solid #d1d5db", borderRadius: 10, color: "#1B5E43",
          }}
        />
        {err && <div style={{ color: "#b91c1c", fontSize: 12.5, marginTop: 10 }}>{err}</div>}
        <button type="submit" disabled={code.length !== 6 || busy} style={{ ...btnPrimary, width: "100%", marginTop: 14, opacity: code.length !== 6 || busy ? 0.5 : 1 }}>
          {busy ? "Opening…" : "Open"}
        </button>
        <p style={{ fontSize: 11.5, color: "#9ca3af", marginTop: 12 }}>
          If the patient sent you a link instead, just open that link.
        </p>
      </form>
    </Shell>
  );
}

/* ═══════════════════════════════════════════ clinician: showing the QR, waiting for approval */
function ClinicianWait({ token }) {
  const [state, setState] = useState({ status: "loading" });
  const timer = useRef(null);

  const poll = useCallback(async () => {
    try {
      const d = unwrap(await shareGet(token, API_ENDPOINTS.RECORDS_SHARE.STATUS(token)));
      setState(d);
    } catch (e) {
      const s = e?.status;
      setState({
        status: s === 404 ? "invalid"
          : s === 403 && e?.errors?.reason === "device_mismatch" ? "other_device"
          : "error",
        message: e?.message,
      });
    }
  }, [token]);

  // The status endpoint returns the pairing code and a server-rendered QR
  // image while the request is still pending, so this screen survives a
  // reload without needing the original create response. If this browser has
  // no device token yet (the doctor opened a full share link rather than
  // coming through /s), claim the session by its token first so later reads
  // carry X-Share-Device.
  useEffect(() => {
    let stop = false;
    (async () => {
      if (!getDev(token)) {
        try {
          const d = unwrap(await publicClient.post(API_ENDPOINTS.RECORDS_SHARE.CLAIM, { token }));
          if (!stop) setDev(token, d.device_token);
        } catch (e) {
          // 409 = already approved elsewhere (or ended) — fall through to a
          // normal poll, which will show the right end state.
          if (!stop && e?.status && ![409, 404].includes(e.status)) {
            setState({ status: "error", message: e?.message });
          }
        }
      }
      if (stop) return;
      poll();
      timer.current = setInterval(poll, 4000);
    })();
    return () => { stop = true; clearInterval(timer.current); };
  }, [poll, token]);

  if (state.status === "approved") return <RecordsView token={token} />;

  if (state.status === "loading") {
    return <Shell><div style={card}>Loading…</div></Shell>;
  }
  if (["invalid", "error"].includes(state.status)) {
    return (
      <Shell>
        <div style={card}>
          <div style={{ display: "flex", gap: 8, alignItems: "center", color: "#b91c1c", fontWeight: 600 }}>
            <AlertTriangle size={16} /> {state.status === "invalid" ? "This link is not valid." : "Something went wrong."}
          </div>
          <p style={{ fontSize: 12.5, color: "#6b7280", marginTop: 10 }}>Ask the patient to create a fresh share link in their app.</p>
        </div>
      </Shell>
    );
  }
  if (state.status === "other_device") {
    return (
      <Shell>
        <div style={card}>
          <div style={{ display: "flex", gap: 8, alignItems: "center", color: "#b91c1c", fontWeight: 600 }}>
            <AlertTriangle size={16} /> This session is tied to another computer.
          </div>
          <p style={{ fontSize: 12.5, color: "#6b7280", marginTop: 10 }}>
            It was started on a different browser. Ask the patient to open <b>Share Records</b> and give you a
            new code, then enter it at <b>{window.location.host}/share</b>.
          </p>
        </div>
      </Shell>
    );
  }
  if (["denied", "ended", "expired"].includes(state.status)) {
    const msg = state.status === "denied" ? "The patient declined this."
      : state.status === "expired" ? "This access window has ended."
      : "The patient ended this access.";
    return (
      <Shell>
        <div style={card}>
          <div style={{ display: "flex", gap: 8, alignItems: "center", color: "#6b7280", fontWeight: 600 }}>
            <ShieldAlert size={16} /> {msg}
          </div>
          <p style={{ fontSize: 12.5, color: "#6b7280", marginTop: 10 }}>Ask the patient to create a new share link if you still need access.</p>
        </div>
      </Shell>
    );
  }

  // pending
  return (
    <Shell>
      <div style={{ ...card, textAlign: "center" }}>
        <h1 style={{ fontSize: 17, fontWeight: 700, margin: "0 0 4px" }}>Show this to the patient</h1>
        <p style={{ fontSize: 13, color: "#6b7280", margin: "0 0 16px" }}>
          In their app they tap <b>Scan to approve</b> and point their camera at this screen, then confirm.
        </p>
        {state.qr_image && (
          <img
            alt={`${FEATURE_NAME} QR`}
            src={state.qr_image}
            style={{ width: 240, height: 240, border: "1px solid #e5e7eb", borderRadius: 10 }}
          />
        )}
        <div style={{ marginTop: 14, fontSize: 12.5, color: "#9ca3af" }}>Can't scan? Read this code to the patient to type in the app</div>
        <div style={{ fontSize: 30, fontWeight: 800, letterSpacing: 6, color: "#1B5E43", fontFamily: "monospace" }}>
          {state.pairing || "······"}
        </div>
        <div style={{ marginTop: 18, display: "inline-flex", alignItems: "center", gap: 8, fontSize: 13, color: "#6b7280" }}>
          <Hourglass size={14} /> Waiting for the patient to approve…
        </div>
      </div>
      <p style={{ fontSize: 12, color: "#9ca3af", marginTop: 12, textAlign: "center" }}>
        Keep this page open. It fills in with the patient's records the moment they approve.
      </p>
    </Shell>
  );
}

/* ═══════════════════════════════════════════ the records — doctor's laptop app-shell */
const catOf = (t) => (t === "prescription" ? "prescription" : t === "lab_report" ? "lab" : "doc");
const CAT_LABEL = { prescription: "Prescription", lab: "Lab report", doc: "Document" };

// Lab-report panels — mirrors core/report_types.py. Used to group the doctor's
// "My Reports" list category by category (the same way the patient sees it).
const PANEL_LABELS = {
  cbc: "Complete Blood Count", lipid: "Lipid Profile", lft: "Liver Function Test",
  kft: "Kidney Function Test", thyroid: "Thyroid Profile", diabetes: "Blood Sugar & HbA1c",
  urine: "Urine Routine", electrolytes: "Serum Electrolytes", vitamin: "Vitamin & Mineral",
  inflammation: "Inflammatory Markers", cardiac: "Cardiac Markers", coagulation: "Coagulation Profile",
  hormone: "Hormone Panel", infection: "Infection Serology", culture: "Culture & Sensitivity",
};
const PANEL_ORDER = Object.keys(PANEL_LABELS);
const NONPANEL_LABEL = { prescription: "Prescriptions", scan: "Imaging", discharge_summary: "Discharge summaries", other: "Other" };
function docSections(d) {
  if (d.doc_type === "lab_report") {
    const cs = (d.report_categories || []).filter((c) => PANEL_LABELS[c]);
    return cs.length ? cs.map((c) => ({ key: `p:${c}`, label: PANEL_LABELS[c] })) : [{ key: "p:_lab", label: "Other lab reports" }];
  }
  return [{ key: `t:${d.doc_type}`, label: NONPANEL_LABEL[d.doc_type] || "Other" }];
}
const sectionRank = (key) => {
  if (key.startsWith("p:")) { const i = PANEL_ORDER.indexOf(key.slice(2)); return i === -1 ? 90 : i; }
  return { "t:prescription": 100, "t:scan": 110, "t:discharge_summary": 120, "t:other": 130 }[key] ?? 95;
};
const ui = {
  ink: "#16201C", muted: "#667069", faint: "#8B938D",
  border: "#E3E7E4", borderStrong: "#D3D9D4", surface2: "#F0F3F0",
  primary: "#1B5E43", tint: "#E7F1EB", tintInk: "#12503A",
  verified: "#1F7A47", warn: "#A85B18", warnBg: "#FBEEDD", warnBorder: "#EDCFA6",
};
const sBtn = {
  font: "inherit", fontSize: 12.5, fontWeight: 600, cursor: "pointer",
  borderRadius: 8, padding: "7px 13px", border: `1px solid ${ui.borderStrong}`,
  background: "#fff", color: ui.ink, whiteSpace: "nowrap",
};

function DocRow({ d, token, onChanged }) {
  const meta = metaFor(d.doc_type);
  const [busy, setBusy] = useState("");
  // { kind: "pdf", pages: [dataUri, ...], page: 0 } | { kind: "image", url: "blob:..." } | null
  // Deliberately never a raw file URL handed to window.open() — that opens
  // the browser's own PDF/image viewer, which carries its own Download
  // button and bypasses the patient-approval gate on RecordsShareDownloadView
  // entirely. See RecordsShareDocumentViewView's docstring for why.
  const [viewer, setViewer] = useState(null);

  async function onView() {
    setBusy("view");
    try {
      const r = unwrap(await shareGet(token, API_ENDPOINTS.RECORDS_SHARE.DOC_VIEW(token, d.id)));
      if (r.pages) {
        setViewer({ kind: "pdf", pages: r.pages, page: 0 });
      } else if (r.file_url) {
        // Fetched into a blob and shown in our own <img>, never navigated to
        // directly — a direct-navigated image URL gets the browser's own
        // image-viewer chrome (download button included) same as a PDF would.
        const blob = await fetch(r.file_url).then((res) => res.blob());
        setViewer({ kind: "image", url: URL.createObjectURL(blob) });
      }
    } catch { /* surfaced by the empty state; keep the row calm */ }
    finally { setBusy(""); }
  }

  function closeViewer() {
    if (viewer?.kind === "image") URL.revokeObjectURL(viewer.url);
    setViewer(null);
  }
  async function onDownload() {
    setBusy("dl");
    try {
      const r = unwrap(await sharePost(token, API_ENDPOINTS.RECORDS_SHARE.DOWNLOADS(token), { doc_id: d.id }));
      if (r.state === "unlocked" && r.file_url) window.open(r.file_url, "_blank", "noopener");
      onChanged();
    } catch { /* keep calm */ }
    finally { setBusy(""); }
  }

  const title = d.doc_type === "prescription" && d.doctor_label ? `Prescription · ${d.doctor_label}` : d.title;
  const sub = [meta.label, d.hospital_label, fmtShort(d.document_date || d.created_at)].filter(Boolean).join(" · ");
  const state = d.download_state;

  return (
    <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: "8px 12px", padding: "12px 4px", borderTop: `1px solid ${ui.border}` }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, flex: "1 1 220px", minWidth: 0 }}>
        <div style={{ width: 30, height: 30, borderRadius: 8, flexShrink: 0, background: ui.surface2, color: ui.muted, display: "flex", alignItems: "center", justifyContent: "center" }}>
          <meta.Icon size={15} />
        </div>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ fontSize: 13.5, fontWeight: 600, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{title}</div>
          <div style={{ fontSize: 11.5, color: ui.muted, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{sub}</div>
        </div>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexShrink: 0, flexWrap: "wrap" }}>
        {d.verification_status === "verified" && (
          <span style={{ display: "inline-flex", alignItems: "center", gap: 3, fontSize: 11, fontWeight: 600, color: ui.verified }}>
            <ShieldCheck size={12} /> Verified
          </span>
        )}
        <span style={{ fontFamily: "monospace", fontSize: 9.5, fontWeight: 600, letterSpacing: ".06em", color: ui.muted, border: `1px solid ${ui.borderStrong}`, borderRadius: 5, padding: "2px 6px" }}>
          {meta.tag}
        </span>
        <button style={{ ...sBtn, fontSize: 11.5, padding: "5px 10px" }} disabled={busy === "view"} onClick={onView}>
          <Eye size={12} style={{ verticalAlign: "-2px" }} /> View
        </button>
        {state === "requested" ? (
          <span style={{ display: "inline-flex", alignItems: "center", gap: 5, fontSize: 11.5, fontWeight: 600, color: ui.warn, background: ui.warnBg, border: `1px solid ${ui.warnBorder}`, borderRadius: 8, padding: "6px 10px" }}>
            <Hourglass size={12} /> Waiting for patient…
          </span>
        ) : (
          <button
            style={{ ...sBtn, fontSize: 11.5, padding: "5px 10px", ...(state === "unlocked" ? { color: ui.verified, borderColor: "#B7DCC5" } : {}) }}
            disabled={busy === "dl"} onClick={onDownload}
          >
            <Download size={12} style={{ verticalAlign: "-2px" }} /> Download
          </button>
        )}
      </div>

      {viewer && (
        <div
          style={{ position: "fixed", inset: 0, zIndex: 100, background: "rgba(10,15,12,.82)", display: "flex", flexDirection: "column" }}
          onClick={closeViewer}
        >
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "12px 18px", flexShrink: 0 }}>
            <span style={{ color: "#fff", fontSize: 13, fontWeight: 600, opacity: 0.9 }}>{title}</span>
            <button
              onClick={closeViewer}
              style={{ ...sBtn, background: "rgba(255,255,255,.08)", borderColor: "rgba(255,255,255,.2)", color: "#fff" }}
            >
              <X size={14} style={{ verticalAlign: "-2px" }} /> Close
            </button>
          </div>
          <div
            style={{ flex: 1, minHeight: 0, display: "flex", alignItems: "center", justifyContent: "center", padding: "0 16px 16px", overflow: "auto" }}
            onClick={(e) => e.stopPropagation()}
          >
            {viewer.kind === "image" && (
              <img src={viewer.url} alt={title} style={{ maxWidth: "100%", maxHeight: "100%", borderRadius: 6, boxShadow: "0 12px 40px rgba(0,0,0,.4)" }} />
            )}
            {viewer.kind === "pdf" && (
              <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 10, maxHeight: "100%" }}>
                <img
                  src={viewer.pages[viewer.page]}
                  alt={`Page ${viewer.page + 1}`}
                  style={{ maxWidth: "100%", maxHeight: "calc(100vh - 140px)", borderRadius: 6, boxShadow: "0 12px 40px rgba(0,0,0,.4)" }}
                />
                {viewer.pages.length > 1 && (
                  <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
                    <button
                      disabled={viewer.page === 0}
                      onClick={() => setViewer((v) => ({ ...v, page: v.page - 1 }))}
                      style={{ ...sBtn, background: "rgba(255,255,255,.08)", borderColor: "rgba(255,255,255,.2)", color: "#fff", opacity: viewer.page === 0 ? 0.4 : 1 }}
                    >
                      <ChevronLeft size={14} />
                    </button>
                    <span style={{ color: "#fff", fontSize: 12, fontFamily: "monospace" }}>
                      {viewer.page + 1} / {viewer.pages.length}
                    </span>
                    <button
                      disabled={viewer.page === viewer.pages.length - 1}
                      onClick={() => setViewer((v) => ({ ...v, page: v.page + 1 }))}
                      style={{ ...sBtn, background: "rgba(255,255,255,.08)", borderColor: "rgba(255,255,255,.2)", color: "#fff", opacity: viewer.page === viewer.pages.length - 1 ? 0.4 : 1 }}
                    >
                      <ChevronRight size={14} />
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function ClinScreen({ title, lead, children }) {
  return (
    <div>
      <h2 style={{ fontSize: 15, fontWeight: 700, margin: "0 0 4px" }}>{title}</h2>
      {lead && <p style={{ fontSize: 12.5, color: ui.muted, margin: "0 0 16px" }}>{lead}</p>}
      {children}
    </div>
  );
}
function KV({ rows }) {
  return (
    <dl style={{ display: "grid", gridTemplateColumns: "150px 1fr", gap: 0, fontSize: 13, margin: 0 }}>
      {rows.map(([k, v], i) => (
        <div key={i} style={{ display: "contents" }}>
          <dt style={{ color: ui.muted, padding: "8px 0", borderTop: i ? `1px solid ${ui.border}` : "none" }}>{k}</dt>
          <dd style={{ margin: 0, padding: "8px 0", fontWeight: 500, borderTop: i ? `1px solid ${ui.border}` : "none" }}>{v || "—"}</dd>
        </div>
      ))}
    </dl>
  );
}

function RecordsView({ token }) {
  const [data, setData] = useState(null);
  const [err, setErr] = useState("");
  const [ended, setEnded] = useState(false);
  const [screen, setScreen] = useState("reports");
  const [tab, setTab] = useState("all");
  const [q, setQ] = useState("");
  const [showFilter, setShowFilter] = useState(false);
  const [filterMode, setFilterMode] = useState("all"); // all | month | year | dates
  const [filterMonth, setFilterMonth] = useState("");
  const [filterYear, setFilterYear] = useState("");
  const [dFrom, setDFrom] = useState("");
  const [dTo, setDTo] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const timer = useRef(null);
  const wide = useIsWide();

  const load = useCallback(async () => {
    try {
      setData(unwrap(await shareGet(token, API_ENDPOINTS.RECORDS_SHARE.RECORDS(token))));
      setErr("");
    } catch (e) {
      if (e?.status === 403 || e?.status === 404) { setEnded(true); clearInterval(timer.current); }
      else setErr(e?.message || "Could not load the records.");
    }
  }, [token]);

  async function onRefresh() {
    setRefreshing(true);
    try { await load(); } finally { setRefreshing(false); }
  }

  useEffect(() => {
    load();
    timer.current = setInterval(load, 12000);
    return () => clearInterval(timer.current);
  }, [load]);

  const { label: countdown, left } = useCountdown(data?.seconds_left);
  // Only treat "0 on the clock" as ended once the clock has actually been
  // running — otherwise the first render (data in, countdown not yet seeded)
  // reads left===0 and ends the session immediately.
  const tickedRef = useRef(false);
  useEffect(() => {
    if (left > 0) tickedRef.current = true;
    if (tickedRef.current && left === 0) setEnded(true);
  }, [left]);

  async function endNow() {
    try { await sharePost(token, API_ENDPOINTS.RECORDS_SHARE.CLOSE(token)); } catch { /* ignore */ }
    setEnded(true);
    clearInterval(timer.current);
  }

  const docs = useMemo(() => data?.documents || [], [data]);
  const counts = useMemo(() => {
    const c = { all: docs.length, prescription: 0, lab: 0, doc: 0 };
    docs.forEach((d) => { c[catOf(d.doc_type)]++; });
    return c;
  }, [docs]);

  // Only months/years that actually have a record — a doctor scanning one
  // patient's history doesn't need every calendar month back to year zero.
  const monthOpts = useMemo(() => {
    const keys = new Set(docs.map((d) => ymKey(d.document_date || d.created_at)).filter(Boolean));
    return [...keys].sort((a, b) => b.localeCompare(a)).map((k) => ({ key: k, label: ymLabel(k) }));
  }, [docs]);
  const yearOpts = useMemo(() => {
    const years = new Set(docs.map((d) => {
      const dt = new Date(d.document_date || d.created_at || "");
      return isNaN(dt) ? null : dt.getFullYear();
    }).filter(Boolean));
    return [...years].sort((a, b) => b - a);
  }, [docs]);
  const filterActive = (filterMode === "month" && !!filterMonth)
    || (filterMode === "year" && !!filterYear)
    || (filterMode === "dates" && (!!dFrom || !!dTo));

  const groups = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const list = docs
      .filter((d) => tab === "all" || catOf(d.doc_type) === tab)
      .filter((d) => !needle || [d.title, d.hospital_label, d.doctor_label, d.public_document_id].filter(Boolean).join(" ").toLowerCase().includes(needle))
      .filter((d) => {
        const day = (d.document_date || d.created_at || "").slice(0, 10);
        if (filterMode === "month" && filterMonth) return day && ymKey(day) === filterMonth;
        if (filterMode === "year" && filterYear) return day && day.slice(0, 4) === filterYear;
        if (filterMode === "dates" && (dFrom || dTo)) {
          if (!day) return false;
          return (!dFrom || day >= dFrom) && (!dTo || day <= dTo);
        }
        return true;
      })
      .slice()
      .sort((a, b) => (b.document_date || b.created_at).localeCompare(a.document_date || a.created_at));

    // All / Lab reports: group category by category (matches the patient's
    // own view). Prescriptions / Documents: month-grouped.
    if (tab === "all" || tab === "lab") {
      const map = new Map();
      list.forEach((d) => docSections(d).forEach(({ key, label }) => {
        if (!map.has(key)) map.set(key, { key, label, list: [] });
        map.get(key).list.push(d);
      }));
      return [...map.values()].sort((a, b) => sectionRank(a.key) - sectionRank(b.key));
    }
    const map = new Map();
    list.forEach((d) => {
      const k = ymKey(d.document_date || d.created_at) || "0000-00";
      if (!map.has(k)) map.set(k, []);
      map.get(k).push(d);
    });
    return [...map.entries()].sort((a, b) => b[0].localeCompare(a[0])).map(([k, l]) => ({ key: k, label: ymLabel(k), list: l }));
  }, [docs, tab, q, filterMode, filterMonth, filterYear, dFrom, dTo]);

  if (ended) {
    return (
      <Shell>
        <div style={card}>
          <div style={{ display: "flex", gap: 8, alignItems: "center", color: "#6b7280", fontWeight: 600 }}>
            <ShieldAlert size={16} /> This access has ended.
          </div>
          <p style={{ fontSize: 12.5, color: "#6b7280", marginTop: 10 }}>
            The patient stopped sharing, or the 2-hour window closed. Ask them to create a new share link if you still need it.
          </p>
        </div>
      </Shell>
    );
  }
  if (err) return <Shell><div style={card}><span style={{ color: "#b91c1c" }}>{err}</span></div></Shell>;
  if (!data) return <Shell xwide><div style={card}>Loading records…</div></Shell>;

  const p = data.patient || {};
  const sum = data.summary || {};
  const ec = sum.emergency_contact;
  // Sections the patient keeps private this session are dropped from the rail
  // entirely. `sections_withheld` carries the backend's own labels.
  const withheldSet = new Set(data.sections_withheld || []);
  const SECTION_LABEL = { summary: "Summary", vitals: "Recent vitals", diagnoses: "Diagnoses & clinical notes", vaccinations: "Vaccinations" };
  const nav = [
    ["reports", "My Reports", LayoutGrid, null],
    ["summary", "Summary", HeartPulse, null],
    ["vitals", "Vitals", Activity, null],
    ["diagnoses", "Diagnoses", Stethoscope, (data.diagnoses || []).length || null],
    ["vaccinations", "Vaccinations", Syringe, null],
  ].filter(([id]) => !withheldSet.has(SECTION_LABEL[id]));
  const anyWithheld = !!data.records_withheld || withheldSet.size > 0;

  return (
    <div style={{ height: "100vh", display: "flex", flexDirection: "column", background: "#fff", overflow: "hidden" }}>
      <style>{"@keyframes share-spin { to { transform: rotate(360deg); } }"}</style>
      {/* brand strip */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "10px 20px", borderBottom: `1px solid ${ui.border}`, color: ui.primary, fontWeight: 800, fontSize: 14, flexShrink: 0 }}>
        <ShieldCheck size={17} /> {FEATURE_NAME}
      </div>

      {/* patient bar */}
      <div style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap", padding: "11px 20px", borderBottom: `1px solid ${ui.border}`, flexShrink: 0 }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: 15, fontWeight: 600 }}>{p.full_name || "Patient"}</div>
          <div style={{ fontFamily: "monospace", fontSize: 11.5, color: ui.muted }}>
            {[p.awpid, p.age_years != null ? `${p.age_years} yrs` : null, p.gender].filter(Boolean).join(" · ")}
          </div>
        </div>
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 10, flexShrink: 0 }}>
          <span style={{ display: "inline-flex", alignItems: "center", gap: 6, fontFamily: "monospace", fontSize: 12.5, color: ui.warn, background: ui.warnBg, border: `1px solid ${ui.warnBorder}`, padding: "5px 10px", borderRadius: 999 }}>
            <Clock size={13} /> Ends in {countdown}
          </span>
          <button style={{ ...sBtn, color: "#B42318", borderColor: "#E4B9B4" }} onClick={endNow}>End</button>
        </div>
      </div>

      {/* body: sidebar + scrolling content, fills the rest of the viewport */}
      <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: wide ? "row" : "column" }}>
        {/* sidebar — full-height rail on desktop, scrollable strip on narrow */}
        <nav style={{
          display: "flex", gap: wide ? 2 : 4,
          ...(wide
            ? { width: 240, flexShrink: 0, borderRight: `1px solid ${ui.border}`, background: "#FAFBFA", padding: "14px 12px", flexDirection: "column", overflowY: "auto" }
            : { width: "100%", flexShrink: 0, borderBottom: `1px solid ${ui.border}`, padding: "8px 12px", flexDirection: "row", overflowX: "auto" }),
        }}>
          {nav.map(([id, label, Icon, badge], i) => (
            <div key={id} style={{ display: "contents" }}>
              {i === 1 && wide && (
                <div style={{ fontFamily: "monospace", fontSize: 10, fontWeight: 600, letterSpacing: ".14em", textTransform: "uppercase", color: ui.faint, padding: "14px 10px 6px" }}>Clinical</div>
              )}
              <button
                onClick={() => setScreen(id)}
                style={{
                  display: "flex", alignItems: "center", gap: 10, width: wide ? "100%" : "auto", font: "inherit",
                  fontSize: 13.5, fontWeight: screen === id ? 600 : 500, textAlign: "left", cursor: "pointer",
                  border: 0, borderRadius: 8, padding: "9px 10px", whiteSpace: "nowrap", flexShrink: 0,
                  background: screen === id ? ui.tint : "transparent",
                  color: screen === id ? ui.tintInk : ui.muted,
                }}
              >
                <Icon size={16} style={{ flexShrink: 0 }} />
                {label}
                {badge != null && (
                  <span style={{ marginLeft: wide ? "auto" : 4, fontFamily: "monospace", fontSize: 10.5, fontWeight: 600, background: screen === id ? "#fff" : ui.surface2, color: ui.muted, borderRadius: 999, padding: "1px 7px" }}>{badge}</span>
                )}
              </button>
            </div>
          ))}
        </nav>

        {/* scrolling content area — chrome above/left stays put */}
        <div style={{ flex: 1, minWidth: 0, minHeight: 0, overflowY: "auto" }}>
          <div style={{ maxWidth: 1000, margin: "0 auto", padding: wide ? "22px 28px 48px" : "14px 14px 28px" }}>
            {screen === "reports" && (
              <>
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 12 }}>
                  {[["all", "All"], ["prescription", "Prescriptions"], ["lab", "Lab reports"], ["doc", "Documents"]].map(([k, l]) => (
                    <button key={k} onClick={() => setTab(k)}
                      style={{ font: "inherit", fontSize: 12.5, fontWeight: tab === k ? 600 : 500, cursor: "pointer", borderRadius: 999, padding: "6px 12px",
                        border: `1px solid ${tab === k ? ui.primary : ui.border}`, background: tab === k ? ui.primary : "#fff", color: tab === k ? "#fff" : ui.muted }}>
                      {l} <span style={{ fontFamily: "monospace", fontSize: 10.5, opacity: 0.8, marginLeft: 3 }}>{counts[k]}</span>
                    </button>
                  ))}
                </div>
                <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 16 }}>
                  <label style={{ flex: 1, display: "flex", alignItems: "center", gap: 8, border: `1px solid ${ui.borderStrong}`, borderRadius: 8, padding: "7px 11px", minWidth: 0 }}>
                    <Search size={15} style={{ color: ui.faint, flexShrink: 0 }} />
                    <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search name, hospital, doctor, ID"
                      style={{ border: "none", outline: "none", background: "none", width: "100%", fontSize: 13 }} />
                  </label>
                  <div style={{ position: "relative" }}>
                    <button
                      style={{ ...sBtn, ...(filterActive ? { borderColor: ui.primary, color: ui.primary } : null) }}
                      onClick={() => setShowFilter((v) => !v)}
                    >
                      <SlidersHorizontal size={13} style={{ verticalAlign: "-2px" }} />{" "}
                      {filterMode === "month" && filterMonth ? ymLabel(filterMonth)
                        : filterMode === "year" && filterYear ? filterYear
                        : filterMode === "dates" && (dFrom || dTo) ? "Custom range"
                        : "Filter"}
                    </button>
                    {showFilter && (
                      <div style={{ position: "absolute", zIndex: 20, top: "calc(100% + 6px)", right: 0, minWidth: 260, background: "#fff", border: `1px solid ${ui.border}`, borderRadius: 10, padding: 12, boxShadow: "0 8px 24px rgba(0,0,0,.08)" }}>
                        <div style={{ display: "inline-flex", border: `1px solid ${ui.borderStrong}`, borderRadius: 8, overflow: "hidden", marginBottom: 10 }}>
                          {[["all", "All"], ["month", "Month"], ["year", "Year"], ["dates", "Custom"]].map(([m, l]) => (
                            <button key={m} onClick={() => setFilterMode(m)}
                              style={{
                                font: "inherit", padding: "6px 11px", fontSize: 12, border: "none", cursor: "pointer",
                                background: filterMode === m ? ui.primary : "transparent",
                                color: filterMode === m ? "#fff" : ui.muted, fontWeight: filterMode === m ? 600 : 400,
                              }}>
                              {l}
                            </button>
                          ))}
                        </div>

                        {filterMode === "month" && (
                          monthOpts.length === 0 ? (
                            <div style={{ fontSize: 12, color: ui.faint }}>No dated records yet.</div>
                          ) : (
                            <select value={filterMonth} onChange={(e) => setFilterMonth(e.target.value)}
                              style={{ font: "inherit", fontSize: 12.5, padding: "7px 8px", border: `1px solid ${ui.borderStrong}`, borderRadius: 7, width: "100%" }}>
                              <option value="">All months</option>
                              {monthOpts.map((o) => <option key={o.key} value={o.key}>{o.label}</option>)}
                            </select>
                          )
                        )}

                        {filterMode === "year" && (
                          yearOpts.length === 0 ? (
                            <div style={{ fontSize: 12, color: ui.faint }}>No dated records yet.</div>
                          ) : (
                            <select value={filterYear} onChange={(e) => setFilterYear(e.target.value)}
                              style={{ font: "inherit", fontSize: 12.5, padding: "7px 8px", border: `1px solid ${ui.borderStrong}`, borderRadius: 7, width: "100%" }}>
                              <option value="">All years</option>
                              {yearOpts.map((y) => <option key={y} value={String(y)}>{y}</option>)}
                            </select>
                          )
                        )}

                        {filterMode === "dates" && (
                          <div style={{ display: "flex", gap: 10 }}>
                            <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 11, color: ui.muted }}>
                              From
                              <input type="date" value={dFrom} max={dTo || undefined}
                                onChange={(e) => setDFrom(e.target.value)}
                                style={{ font: "inherit", fontSize: 12.5, padding: "6px 8px", border: `1px solid ${ui.borderStrong}`, borderRadius: 7 }} />
                            </label>
                            <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 11, color: ui.muted }}>
                              To
                              <input type="date" value={dTo} min={dFrom || undefined}
                                onChange={(e) => setDTo(e.target.value)}
                                style={{ font: "inherit", fontSize: 12.5, padding: "6px 8px", border: `1px solid ${ui.borderStrong}`, borderRadius: 7 }} />
                            </label>
                          </div>
                        )}

                        {filterMode === "all" && (
                          <div style={{ fontSize: 12, color: ui.faint }}>Showing every record, newest first.</div>
                        )}

                        {filterActive && (
                          <button
                            style={{ ...sBtn, marginTop: 10, width: "100%", borderColor: "transparent", color: ui.muted }}
                            onClick={() => { setFilterMode("all"); setFilterMonth(""); setFilterYear(""); setDFrom(""); setDTo(""); }}
                          >
                            Clear
                          </button>
                        )}
                      </div>
                    )}
                  </div>
                  <button style={{ ...sBtn, borderColor: "transparent", color: ui.muted }} onClick={onRefresh} disabled={refreshing}>
                    <RotateCw size={13} style={{ verticalAlign: "-2px", ...(refreshing ? { animation: "share-spin 0.8s linear infinite" } : null) }} /> {refreshing ? "Refreshing…" : "Refresh"}
                  </button>
                </div>

                {anyWithheld && (
                  <div style={{ display: "flex", gap: 8, alignItems: "flex-start", fontSize: 11.5, color: ui.muted, background: "#FBF3E6", border: "1px solid #EDDCBB", borderRadius: 8, padding: "9px 11px", marginBottom: 14, lineHeight: 1.5 }}>
                    <Lock size={13} style={{ marginTop: 1, flexShrink: 0, color: "#B45309" }} />
                    <span>Some records{withheldSet.size ? ` and section${withheldSet.size > 1 ? "s" : ""} (${[...withheldSet].join(", ")})` : ""} are marked private by the patient and aren&rsquo;t shown here.</span>
                  </div>
                )}
                {groups.length === 0 ? (
                  <div style={{ fontSize: 12.5, color: ui.faint, padding: "24px 0", textAlign: "center" }}>Nothing here.</div>
                ) : groups.map((g) => (
                  <div key={g.key}>
                    <div style={{ fontFamily: "monospace", fontSize: 10.5, fontWeight: 600, letterSpacing: ".12em", textTransform: "uppercase", color: ui.faint, margin: "12px 0 4px", display: "flex", gap: 8, alignItems: "baseline" }}>
                      {g.label}<span style={{ opacity: 0.7 }}>{g.list.length}</span>
                    </div>
                    {g.list.map((d) => <DocRow key={`${g.key}:${d.id}`} d={d} token={token} onChanged={load} />)}
                  </div>
                ))}

                <p style={{ marginTop: 18, fontSize: 11.5, color: ui.faint, lineHeight: 1.55, borderTop: `1px dashed ${ui.border}`, paddingTop: 12 }}>
                  The same <b>My Reports</b> the patient has — grouped category by category. <b>View</b> opens
                  the file now. <b>Download</b> asks the patient's phone first, then unlocks.
                </p>
              </>
            )}

            {screen === "summary" && (
              <ClinScreen title="Patient summary" lead="Cross-hospital snapshot the patient shared. Read-only.">
                <KV rows={[
                  ["Blood group", p.blood_group],
                  ["Allergies", (data.allergies || []).map((a) => a.substance + (a.reaction ? ` (${a.reaction})` : "")).join(" · ")],
                  ["Active diagnoses", (data.diagnoses || []).map((d) => d.description || d.icd10_code).join(" · ")],
                  ["Current meds", (sum.current_meds || []).join(" · ")],
                  ["Emergency contact", ec ? `${ec.name}${ec.relation ? ` (${ec.relation})` : ""}${ec.phone ? ` · ${ec.phone}` : ""}` : ""],
                ]} />
              </ClinScreen>
            )}

            {screen === "vitals" && (
              <ClinScreen title="Recent vitals" lead={`Last ${Math.min(6, (data.vitals || []).length)} recordings across hospitals.`}>
                {(data.vitals || []).length === 0
                  ? <div style={{ fontSize: 12.5, color: ui.faint }}>No vitals on record.</div>
                  : <KV rows={(data.vitals || []).slice(0, 6).map((v) => [
                      fmtShort(v.recorded_at),
                      [
                        v.bp_systolic && `BP ${v.bp_systolic}/${v.bp_diastolic}`,
                        v.pulse_rate && `Pulse ${v.pulse_rate}`,
                        v.spo2 && `SpO₂ ${v.spo2}%`,
                        v.temperature && `Temp ${v.temperature}°`,
                        v.weight_kg && `Wt ${v.weight_kg} kg`,
                      ].filter(Boolean).join(" · "),
                    ])} />}
              </ClinScreen>
            )}

            {screen === "diagnoses" && (
              <ClinScreen title="Diagnoses" lead={`${(data.diagnoses || []).length} on record. Coded, from signed encounters.`}>
                {(data.diagnoses || []).length === 0
                  ? <div style={{ fontSize: 12.5, color: ui.faint }}>No diagnoses shared.</div>
                  : (data.diagnoses || []).map((d, i) => (
                    <div key={i} style={{ border: `1px solid ${ui.border}`, borderLeft: `3px solid ${ui.warn}`, borderRadius: 8, padding: "10px 12px", marginBottom: 8 }}>
                      <b style={{ fontSize: 13 }}>{d.description || d.icd10_code}</b>
                      {d.clinical_status && <span style={{ fontSize: 10.5, fontWeight: 600, color: ui.warn, textTransform: "uppercase", letterSpacing: ".05em", marginLeft: 6 }}>{d.clinical_status}</span>}
                      <div style={{ fontFamily: "monospace", fontSize: 11, color: ui.muted, marginTop: 3 }}>
                        {[d.icd10_code, d.onset_date && `onset ${fmtShort(d.onset_date)}`].filter(Boolean).join(" · ")}
                      </div>
                    </div>
                  ))}
              </ClinScreen>
            )}

            {screen === "vaccinations" && (
              <ClinScreen title="Vaccinations" lead="Clinic-administered and self-reported, clearly labelled.">
                {(data.vaccinations || []).length === 0
                  ? <div style={{ fontSize: 12.5, color: ui.faint }}>No vaccination records shared.</div>
                  : (data.vaccinations || []).map((v, i) => (
                    <div key={i} style={{ display: "flex", justifyContent: "space-between", gap: 12, padding: "9px 0", borderTop: i ? `1px solid ${ui.border}` : "none", fontSize: 13 }}>
                      <span>{v.vaccine_name}{v.dose_number ? ` · dose ${v.dose_number}` : ""}</span>
                      <span style={{ fontFamily: "monospace", fontSize: 11, color: ui.muted, textAlign: "right" }}>
                        {[fmtShort(v.administered_date), v.source, v.verification_status !== "verified" && v.verification_status].filter(Boolean).join(" · ")}
                      </span>
                    </div>
                  ))}
              </ClinScreen>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════ router */
export default function ShareRecordsPage() {
  const { token } = useParams();

  // No token — the doctor is at /s (or /share-records). Show the code entry.
  if (!token) return <EntryForm />;

  // The link, opened on any device, always shows the QR + waiting → records.
  // The patient approves ONLY from their app by scanning that QR — there is
  // no web approve path.
  return <ClinicianWait token={token} />;
}
