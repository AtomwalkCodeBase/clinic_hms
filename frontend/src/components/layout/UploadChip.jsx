/**
 * components/layout/UploadChip.jsx
 * --------------------------------
 * Topbar status for background My Reports uploads (context/UploadContext):
 *   "Uploading 3 of 10"  →  "Sorting 4 of 10"  →  "10 ready — verify"
 * Click for the per-file list. Shown on every patient page, so the patient
 * can keep working anywhere while it runs.
 */
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useUploads } from "../../context/UploadContext";
import { ROUTES } from "../../config/routes.config";

const STAGE = {
  waiting: ["Waiting to upload", 5], preparing: ["Preparing", 12], uploading: ["Uploading", 30],
  queued: ["Waiting to be sorted", 45], bulk: ["Scheduled — bulk run", 30], extracting: ["Reading the page", 65], classifying: ["Sorting", 85],
  done: ["Ready to review", 100], filed: ["Filed in your folders", 100], failed: ["Couldn't process", 100], duplicate: ["Already uploaded", 100],
};

export function UploadChip() {
  const up = useUploads();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const h = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, [open]);
  if (!up || up.summary.phase === "idle") return null;

  const { upload, sort, phase } = up.summary;
  // Manually organised files are filed as-is; only auto-sorted ones need a review.
  const toReview = up.docs.filter(d => !d.manual && d.processing_status
    && !["queued", "extracting", "classifying"].includes(d.processing_status)).length;
  const label = phase === "uploading" ? `Uploading ${upload.sent + upload.duplicate + upload.failed} of ${upload.total}`
    : phase === "sorting" ? `Sorting ${sort.done} of ${sort.total}`
    : toReview ? `${toReview} ready — review` : "All filed";
  const pctDone = phase === "uploading" ? (upload.total ? (upload.total - upload.active) / upload.total : 0)
    : sort.total ? sort.done / sort.total : 1;

  // one row per file: the upload job until the server has it, then its doc
  const rows = [
    ...up.jobs.filter(j => !j.docId).map(j => ({ key: j.key, name: j.name, st: j.status, note: j.reason })),
    ...up.docs.map(d => ({ key: `d${d.id}`, name: d.title || "Document", st: d.processing_status === "done" ? (d.manual ? "filed" : "done") : (d.processing_status === "queued" && d.processing_route === "bulk" ? "bulk" : d.processing_status), note: d.processing_status === "failed" ? "waits in Review" : "" })),
  ];
  const goVerify = () => { setOpen(false); navigate(`${ROUTES.PATIENT.MY_REPORTS}?tab=verify`); };

  return (
    <div ref={ref} style={{ position: "relative" }}>
      <button onClick={() => setOpen(o => !o)} style={{
        display: "flex", alignItems: "center", gap: 8, padding: "5px 12px", borderRadius: 999, cursor: "pointer",
        border: "1px solid rgba(255,255,255,.25)", background: "rgba(255,255,255,.08)", color: "var(--color-hero-text, #fff)", fontSize: 12.5,
      }}>
        <span style={{ width: 52, height: 4, borderRadius: 4, background: "rgba(255,255,255,.2)", overflow: "hidden" }}>
          <span style={{ display: "block", height: "100%", width: `${Math.round(pctDone * 100)}%`, background: phase === "finished" ? "#7FD1AE" : "#fff", transition: "width .4s" }} />
        </span>
        {label}
      </button>
      {open && (
        <div className="card" style={{ position: "absolute", right: 0, top: "calc(100% + 8px)", width: 360, zIndex: 50, padding: 14, color: "var(--color-text)" }}>
          <div style={{ display: "flex", alignItems: "center", marginBottom: 8 }}>
            <b style={{ fontSize: 13.5, flex: 1 }}>{phase === "finished" ? "All done" : "Working in the background"}</b>
            {phase === "finished" && (
              <button className="btn-outline" style={{ fontSize: 11.5, padding: "3px 9px" }} onClick={() => { up.clearFinished(); setOpen(false); }}>Clear</button>
            )}
          </div>
          <div style={{ fontSize: 11.5, color: "var(--color-text-muted)", marginBottom: 10 }}>
            {phase === "uploading"
              ? "Keep this tab open until uploading finishes — you can use any other page meanwhile."
              : "Sorting happens on our side — you can close the app. We'll let you know in Notifications."}
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8, maxHeight: 300, overflowY: "auto" }}>
            {rows.map(r => {
              const [txt, pct] = STAGE[r.st] || STAGE.queued;
              const bad = r.st === "failed";
              return (
                <div key={r.key} style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) 90px", gap: 10, alignItems: "center" }}>
                  <div style={{ minWidth: 0 }}>
                    <div style={{ fontSize: 12.5, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{r.name}</div>
                    <div style={{ fontSize: 11, color: bad ? "var(--color-error)" : "var(--color-text-muted)" }}>{txt}{r.note ? ` — ${r.note}` : ""}</div>
                  </div>
                  <div style={{ height: 4, borderRadius: 4, background: "var(--color-border)", overflow: "hidden" }}>
                    <div style={{ height: "100%", width: `${pct}%`, transition: "width .4s", background: bad ? "var(--color-error)" : pct === 100 ? "var(--color-success, #1F8F6E)" : "var(--color-primary)" }} />
                  </div>
                </div>
              );
            })}
          </div>
          {toReview > 0 && (
            <button className="btn-primary" style={{ width: "100%", marginTop: 12 }} onClick={goVerify}>Review sorted reports</button>
          )}
        </div>
      )}
    </div>
  );
}

export default UploadChip;
