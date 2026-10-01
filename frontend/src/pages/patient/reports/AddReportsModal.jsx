/**
 * Add reports: pick files, drop files or folders, or take a photo; review; upload. A folder or a big selection is
 * sent as several uploads of at most 50 files / 250 MB (one batch each). The dialog can be closed while the
 * upload goes on; `onUploaded` then tells the page how it ended.
 */
import { useEffect, useRef, useState } from "react";
import { Camera, CheckSquare, FileText, FolderUp, HelpCircle, Plus, Upload, X } from "lucide-react";
import { useToast } from "../../../hooks/useToast";
import apiClient from "../../../services/api.client";
import API_ENDPOINTS from "../../../config/api.config";
import { chunkBySize } from "../../../utils/files";
import { backdrop, h3, iconBtn, sheet, sub } from "./reportStyles";

const MAX_FILE_BYTES = 250 * 1024 * 1024;   // same limits as POST /records/upload/ (apps/records/serializers.py)
const CHUNK_BYTES = 250 * 1024 * 1024;     // one upload (= one batch) takes at most 50 files and 250 MB; a bigger
const CHUNK_FILES = 50;                    // selection or folder is sent as several uploads, one after another
const HARD_PICK_LIMIT = 1500;              // a folder pick past this is a whole drive, not a reports folder
const OK_EXT = /\.(pdf|jpe?g|png)$/i;

function isMobile() {
  try {
    if (/Android|iPhone|iPod|iPad|Mobile|Opera Mini/i.test(navigator.userAgent || "")) return true;
    return window.matchMedia("(pointer: coarse)").matches && window.matchMedia("(max-width: 860px)").matches;
  } catch { return false; }
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

export default function AddReportsModal({ onClose, onDone, onUploaded, patientAwpid }) {
  const { toastError } = useToast();
  const alive = useRef(true);                    // false once the dialog was closed while the upload carried on
  useEffect(() => () => { alive.current = false; }, []);
  const mob = isMobile();
  const [phase, setPhase] = useState(mob ? "pick" : "choose");   // pick (phone: camera or files) | choose | stage | upload | done
  const [items, setItems] = useState([]);            // {file, name, size, skip}
  const [prog, setProg] = useState({ done: 0, total: 0, name: "" });
  const [result, setResult] = useState({ sent: 0, skipped: 0, error: "" });
  const [dragOver, setDragOver] = useState(false);
  const filesRef = useRef(null);
  const folderRef = useRef(null);
  const camRef = useRef(null);

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
      const empty = f.size === 0;
      return {
        file: f, name: f.name || "photo.jpg", size: f.size,
        skip: badType || tooBig || empty,
        reason: badType ? "not a PDF/image" : empty ? "empty file" : tooBig ? "over 250 MB" : "",
      };
    });

    const newKept = arr.filter(a => !a.skip);
    if (!newKept.length) {
      toastError("None of those are usable — they must be PDFs or images, not empty, under 250 MB.");
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

    // Split into uploads of at most CHUNK_FILES files / CHUNK_BYTES; each one is a batch of its own on the server.
    const chunks = chunkBySize(ready, CHUNK_FILES, CHUNK_BYTES);

    let sent = 0;
    let result_error = "";
    try {
      for (const chunk of chunks) {
        const form = new FormData();
        chunk.forEach(it => form.append("files", it.file, it.name));
        if (patientAwpid) form.append("patient_awpid", patientAwpid);
        const res = await apiClient.post(API_ENDPOINTS.RECORDS.UPLOAD, form, {
          // apiClient defaults to JSON; multipart makes axios send the files with their boundary
          headers: { "Content-Type": "multipart/form-data" },
          timeout: 0,
          onUploadProgress: (e) => setProg({ done: sent + (e.total ? Math.round((e.loaded / e.total) * chunk.length) : 0), total: ready.length, name: "" }),
        });
        sent += ((res.data?.data || res.data)?.documents || []).length;
      }
      setResult({ sent, skipped: items.length - ready.length, error: "" });
    } catch (e) {
      const errs = e?.response?.data?.errors?.files;
      const msg = (Array.isArray(errs) ? errs.join(" ") : "") || e?.response?.data?.message || "Upload failed — try again.";
      result_error = msg;
      setResult({ sent, skipped: items.length - ready.length, error: msg });
    }
    setPhase("done");
    onUploaded?.({ sent, error: alive.current ? "" : (result_error || ""), background: !alive.current });
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
              <button className="btn-outline" style={{ fontSize: 13 }} onClick={() => (mob ? setPhase("pick") : onClose())}>{mob ? "Back" : "Cancel"}</button>
            </div>
          </>
        )}

        {phase === "stage" && (
          <>
            <h3 style={h3}>Review {ready.length} file{ready.length !== 1 ? "s" : ""}</h3>
            <p style={sub}>{ready.length} ready to upload{skipped ? ` · ${skipped} will be skipped (not a PDF or image, empty, or over 250 MB — see the list below)` : ""}.
              Files that are already in your reports are recognised after upload and left out, and you can still keep them.</p>
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
            <h3 style={h3}>Uploading {prog.total} file{prog.total === 1 ? "" : "s"}…</h3>
            <div style={{ height: 8, borderRadius: 6, background: "var(--color-border)", overflow: "hidden", margin: "16px 0 10px" }}>
              <div style={{ height: "100%", width: `${prog.total ? (prog.done / prog.total) * 100 : 0}%`, background: "var(--color-primary)", transition: "width .2s" }} />
            </div>
            <div style={{ fontSize: 12.5, color: "var(--color-text-muted)", textAlign: "center" }}>
              {prog.done} of {prog.total}{prog.name ? ` · ${prog.name}` : ""}
            </div>
            <p style={{ ...sub, textAlign: "center", marginTop: 14 }}>
              Large uploads can take a minute. You don&apos;t have to wait — keep using the app. We’ll tell you when it’s uploaded and when every file has been read.
            </p>
            <div style={{ display: "flex", justifyContent: "center", marginTop: 6 }}>
              <button className="btn-outline" onClick={onClose}>Continue in background</button>
            </div>
          </div>
        )}

        {phase === "done" && (
          <>
            <h3 style={h3}>{!result.error ? "Uploaded" : result.sent ? "Only some files were uploaded" : "Upload failed"}</h3>
            {result.error && (
              <p style={{ ...sub, color: "var(--color-error)" }}>
                {result.error} {result.sent ? "The files listed below as uploaded are safe; send the rest again." : "Nothing was saved — fix or remove that file and try again."}
              </p>
            )}
            {result.sent > 0 && <SumRow label="Files uploaded" n={result.sent} ok />}
            {result.skipped > 0 && <SumRow label="Skipped (not a PDF or image, empty, or over 250 MB)" n={result.skipped} />}
            {result.sent > 0 && (
              <p style={sub}>
                We’re reading each file now — you’ll see its type in your list in a few seconds. Anything we can’t read,
                can’t classify, or already have will be marked <b>Needs attention</b> with what you can do about it.
              </p>
            )}
            <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
              <button className="btn-primary" style={{ flex: 1 }} onClick={() => onDone("all")}>{result.sent ? "Go to my reports" : "Close"}</button>
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
