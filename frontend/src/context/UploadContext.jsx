/**
 * context/UploadContext.jsx
 * -------------------------
 * App-wide My Reports uploader. Lives above the router, so an upload keeps
 * going while the patient moves to any other page — nobody waits on a
 * dialog. Two phases per file:
 *
 *   1. upload   (this browser → server) — photos are shrunk on the device
 *               first (long edge ≤ 2200 px, JPEG ~0.82: an 8–11 MB phone
 *               photo becomes ~1 MB, still sharp for OCR) and up to
 *               CONCURRENCY files go at once. The hospital QR is read from
 *               the ORIGINAL photo before shrinking.
 *   2. sorting  (on the server — core/pipeline/, Celery) — polled via
 *               /portal/documents/status/ until every file is done.
 *
 * Only phase 1 needs the tab open; the browser warns if they try to close
 * it mid-upload. Phase 2 carries on with the app closed.
 *
 * Consumers: the header chip (components/layout/UploadChip.jsx) and
 * My Reports (reads `version` to refetch when something finishes).
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import apiClient from "../services/api.client";
import API_ENDPOINTS from "../config/api.config";
import { useAuth } from "../hooks/useAuth";
import { ROLES } from "../constants/roles";

const UploadContext = createContext(null);

const CONCURRENCY = 3;
const MAX_UPLOAD_BYTES = 11 * 1024 * 1024;       // server's per-file limit (after shrinking)
const MAX_PICK_BYTES = 40 * 1024 * 1024;         // raw pick limit — photos get shrunk
const OK_EXT = /\.(pdf|jpe?g|png)$/i;
const IN_FLIGHT = new Set(["queued", "extracting", "classifying"]);
const POLL_MS = 4000;
let seq = 0;

function fileToDataUrl(blob) {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(r.result);
    r.onerror = reject;
    r.readAsDataURL(blob);
  });
}

async function tryDecodeQR(file) {
  try {
    if (!("BarcodeDetector" in window)) return "";
    const det = new window.BarcodeDetector({ formats: ["qr_code"] });
    const codes = await det.detect(await createImageBitmap(file));
    return codes?.[0]?.rawValue || "";
  } catch { return ""; }
}

/** Shrink a photo on the device. Returns the original when that's smaller. */
async function shrinkImage(file) {
  if (!/^image\/(jpeg|png)$/.test(file.type)) return file;
  try {
    const bmp = await createImageBitmap(file);
    const scale = Math.min(1, 2200 / Math.max(bmp.width, bmp.height));
    const w = Math.round(bmp.width * scale), h = Math.round(bmp.height * scale);
    const canvas = document.createElement("canvas");
    canvas.width = w; canvas.height = h;
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, w, h);   // PNG transparency → white paper
    ctx.drawImage(bmp, 0, 0, w, h);
    const blob = await new Promise(res => canvas.toBlob(res, "image/jpeg", 0.82));
    if (!blob || blob.size >= file.size) return file;
    return new File([blob], file.name.replace(/\.(png|jpe?g)$/i, "") + ".jpg", { type: "image/jpeg" });
  } catch { return file; }
}

export function UploadProvider({ children }) {
  const { user } = useAuth();
  const isPatient = user?.role === ROLES.PATIENT;
  // jobs: one per picked file — upload phase
  const [jobs, setJobs] = useState([]);
  // docs: id -> latest status row — sorting phase (server)
  const [docs, setDocs] = useState(() => new Map());
  // bumped whenever a file finishes uploading or sorting → pages refetch
  const [version, setVersion] = useState(0);
  const running = useRef(0);
  const jobsRef = useRef(jobs);
  jobsRef.current = jobs;

  const patchJob = (key, fields) => setJobs(js => js.map(j => (j.key === key ? { ...j, ...fields } : j)));
  const trackDocs = useCallback((rows) => {
    setDocs(prev => {
      const n = new Map(prev);
      rows.forEach(r => n.set(r.id, { ...(n.get(r.id) || {}), ...r }));
      return n;
    });
  }, []);

  /**
   * Queue files for upload. Returns {accepted, rejected:[{name, reason}]}.
   * `metas` (optional, same order as the files) = the patient's own
   * "Organize manually" choice per file: {doc_type, report_categories,
   * document_date, folder} — such a file is filed as-is, no AI.
   */
  const addFiles = useCallback((fileList, patientAwpid = "", metas = null) => {
    const rejected = [];
    const add = [];
    Array.from(fileList || []).forEach((f, i) => {
      const okType = OK_EXT.test(f.name || "") || /^image\/(jpeg|png)$|^application\/pdf$/.test(f.type);
      if (!okType) { rejected.push({ name: f.name, reason: "not a PDF or image" }); return; }
      const isPdf = f.type === "application/pdf" || /\.pdf$/i.test(f.name || "");
      if (f.size > (isPdf ? MAX_UPLOAD_BYTES : MAX_PICK_BYTES)) {
        rejected.push({ name: f.name, reason: isPdf ? "PDF over 11 MB" : "image over 40 MB" }); return;
      }
      add.push({ key: `u${++seq}`, file: f, name: f.name || "photo.jpg", size: f.size, patientAwpid,
        meta: metas?.[i] || null, status: "waiting", reason: "", docId: null });
    });
    // The server sorts small uploads on the spot and sends big ones to the
    // scheduled bulk job — it decides from how many files came together.
    add.forEach(j => { j.batchSize = add.length; });
    if (add.length) setJobs(js => [...js, ...add]);
    return { accepted: add.length, rejected };
  }, []);

  const uploadOne = useCallback(async (job) => {
    try {
      patchJob(job.key, { status: "preparing" });
      const qr = job.file.type.startsWith("image/") ? await tryDecodeQR(job.file) : "";
      const small = await shrinkImage(job.file);
      if (small.size > MAX_UPLOAD_BYTES) { patchJob(job.key, { status: "failed", reason: "still over 11 MB" }); return; }
      patchJob(job.key, { status: "uploading", sentSize: small.size });
      const res = await apiClient.post(API_ENDPOINTS.PORTAL.DOCUMENTS, {
        title: job.name.replace(OK_EXT, ""),
        file_data: await fileToDataUrl(small), file_name: small.name,
        mime_type: small.type || "application/pdf",
        ...(qr ? { qr_token: qr } : {}),
        batch_size: job.batchSize || 1,
        ...(job.patientAwpid ? { patient_awpid: job.patientAwpid } : {}),
        ...(job.meta ? {
          manual: true, doc_type: job.meta.doc_type,
          report_categories: job.meta.report_categories || [],
          ...(job.meta.document_date ? { document_date: job.meta.document_date } : {}),
          ...(job.meta.folder ? { folder: job.meta.folder } : {}),
        } : {}),
      });
      const d = res.data?.data || res.data;
      if (d?.duplicate) { patchJob(job.key, { status: "duplicate", reason: "already in your reports" }); return; }
      patchJob(job.key, { status: "done", docId: d?.id, file: null });
      if (d?.id) {
        trackDocs([{ ...d, processing_status: d.processing_status || "queued",
          patientAwpid: job.patientAwpid, manual: !!job.meta }]);
        setVersion(v => v + 1);
      }
    } catch (e) {
      patchJob(job.key, { status: "failed", reason: (e?.response?.data?.message || "upload failed — try again").slice(0, 120) });
    }
  }, [trackDocs]);

  // ── pump: keep up to CONCURRENCY uploads running ──────────────────────
  useEffect(() => {
    const waiting = jobs.filter(j => j.status === "waiting");
    while (running.current < CONCURRENCY && waiting.length) {
      const job = waiting.shift();
      running.current += 1;
      patchJob(job.key, { status: "preparing" });
      uploadOne(job).finally(() => { running.current -= 1; setJobs(js => [...js]); });
    }
  }, [jobs, uploadOne]);

  const uploading = jobs.some(j => ["waiting", "preparing", "uploading"].includes(j.status));

  // Closing the tab mid-upload loses the files still on this device.
  useEffect(() => {
    if (!uploading) return undefined;
    const h = (e) => { e.preventDefault(); e.returnValue = ""; };
    window.addEventListener("beforeunload", h);
    return () => window.removeEventListener("beforeunload", h);
  }, [uploading]);

  // ── pick up files still sorting from an earlier visit (self only) ─────
  useEffect(() => {
    if (!isPatient) return;
    apiClient.get(API_ENDPOINTS.PORTAL.DOCUMENTS_STATUS)
      .then(res => {
        const rows = (res.data?.data || res.data)?.items || [];
        if (rows.length) trackDocs(rows.map(r => ({ ...r, patientAwpid: "" })));
      })
      .catch(() => {});
  }, [isPatient, trackDocs]);

  // ── poll the server while anything is sorting ─────────────────────────
  const sortingIds = useMemo(() => [...docs.values()].filter(d => IN_FLIGHT.has(d.processing_status)), [docs]);
  const sortingKey = sortingIds.map(d => d.id).join(",");
  useEffect(() => {
    if (!sortingKey) return undefined;
    let stop = false;
    const tick = async () => {
      const byPatient = new Map();
      sortingIds.forEach(d => {
        const k = d.patientAwpid || "";
        byPatient.set(k, [...(byPatient.get(k) || []), d.id]);
      });
      for (const [awpid, ids] of byPatient) {
        try {
          const res = await apiClient.get(API_ENDPOINTS.PORTAL.DOCUMENTS_STATUS, {
            params: { ids: ids.join(","), ...(awpid ? { patient_awpid: awpid } : {}) },
          });
          if (stop) return;
          const rows = (res.data?.data || res.data)?.items || [];
          const finished = rows.some(r => !IN_FLIGHT.has(r.processing_status));
          trackDocs(rows);
          if (finished) setVersion(v => v + 1);
        } catch { /* a blip — try again next tick */ }
      }
    };
    const t = setInterval(tick, POLL_MS);
    return () => { stop = true; clearInterval(t); };
  }, [sortingKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const clearFinished = useCallback(() => {
    setJobs(js => js.filter(j => ["waiting", "preparing", "uploading"].includes(j.status)));
    setDocs(prev => new Map([...prev].filter(([, d]) => IN_FLIGHT.has(d.processing_status))));
  }, []);

  const summary = useMemo(() => {
    const docList = [...docs.values()];
    const up = {
      total: jobs.length,
      sent: jobs.filter(j => j.status === "done").length,
      active: jobs.filter(j => ["waiting", "preparing", "uploading"].includes(j.status)).length,
      duplicate: jobs.filter(j => j.status === "duplicate").length,
      failed: jobs.filter(j => j.status === "failed").length,
    };
    const sort = {
      total: docList.length,
      sorting: docList.filter(d => IN_FLIGHT.has(d.processing_status)).length,
      done: docList.filter(d => !IN_FLIGHT.has(d.processing_status)).length,
    };
    const phase = up.active ? "uploading" : sort.sorting ? "sorting" : (up.total || sort.total) ? "finished" : "idle";
    return { upload: up, sort, phase };
  }, [jobs, docs]);

  const value = useMemo(() => ({
    addFiles, jobs, docs: [...docs.values()].sort((a, b) => a.id - b.id),
    summary, version, clearFinished, trackDocs,
  }), [addFiles, jobs, docs, summary, version, clearFinished, trackDocs]);

  return <UploadContext.Provider value={value}>{children}</UploadContext.Provider>;
}

export function useUploads() {
  return useContext(UploadContext);
}
