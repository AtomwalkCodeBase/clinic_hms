/**
 * pages/public/ConsultPadPage.jsx
 * --------------------------------
 * The phone side of the consultation handwriting pad.
 *
 * The doctor starts a ConsultSession from an encounter, shows the patient's
 * permanent QR, and the phone lands here: a two-tab writing pad —
 * **Prescription** and **Internal Note** — each a multi-page canvas. Every
 * stroke autosaves to the session (PUT one tab at a time); nothing is
 * "submitted". The session stays live, surviving this tab being closed and
 * re-scanned, until the doctor signs the encounter on the web.
 *
 * Outside AppShell/ProtectedRoute — the phone has no Atomwalk session.
 * Fetched with publicClient. Backend: apps/patients/consult_pad_views.py.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { publicClient } from "../../services/api.client";
import API_ENDPOINTS from "../../config/api.config";

const PAPER = "#ffffff";
const RULE_COLOR = "#eef1f5";
const PEN_SIZES = [
  { key: "s", label: "S", width: 2 },
  { key: "m", label: "M", width: 3.5 },
  { key: "l", label: "L", width: 6 },
];
// Pen colours the doctor can pick on the phone. First is the default. The
// colour bakes into the saved PNG, so no backend change is needed — a page
// reloads/restores exactly as it was drawn.
const PEN_COLORS = [
  { key: "ink",   value: "#1f2937" },
  { key: "blue",  value: "#1d4ed8" },
  { key: "red",   value: "#dc2626" },
  { key: "green", value: "#15803d" },
];
const PEN_COLOR = PEN_COLORS[0].value;

// Zoom range for the pad. Applied as CSS display size (not a transform) so
// scrolling/panning to any corner keeps working and pointer-to-canvas
// mapping stays exact — see pointFrom().
const ZOOM_MIN = 0.5;
const ZOOM_MAX = 3;
const ZOOM_STEP = 0.25;
const clampZoom = (z) => Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, Math.round(z * 100) / 100));
const UNDO_LIMIT = 25;
const AUTOSAVE_MS = 1500;
// Background sync: while a tab has unsaved strokes, retry the PUT on this
// cadence and the instant the browser reports the connection is back — no
// stroke or tap needed.
const RETRY_MS = 4000;

const TABS = [
  { key: "rx", label: "Prescription", hint: "Drug · dose · frequency · duration" },
  { key: "note", label: "Internal Note", hint: "S — Subjective   O — Objective   A — Assessment   P — Plan" },
];

let _pid = 0;
const nextPageId = () => `p${++_pid}`;

// Per-device crash safety net. Every stroke also writes the tab images here
// synchronously, so a power cut / tab kill between autosaves loses nothing —
// on the next open we offer to restore anything not yet acknowledged by the
// server. Keyed by the pad token; cleared once everything is saved.
const LS_KEY = (t) => `consultpad:v1:${t}`;

function pageDims(containerW) {
  const vw = typeof window !== "undefined" ? window.innerWidth : 800;
  // Base the A4-ish portrait page on the ACTUAL width the pad column has to
  // work with (measured from the live container), not a guess off
  // window.innerWidth — that's what made it mis-fit on some phones. Height
  // just follows the 1.414 aspect; the column scrolls, and the doctor can
  // zoom out if a page is too tall for their screen.
  const avail = Math.max(240, (containerW || vw) - 20);
  const w = Math.round(Math.max(280, Math.min(avail, 860)));
  return { w, h: Math.round(w * 1.414), dpr: (typeof window !== "undefined" && window.devicePixelRatio) || 1 };
}

function paintPaper(ctx, w, h) {
  ctx.save();
  ctx.fillStyle = PAPER;
  ctx.fillRect(0, 0, w, h);
  ctx.strokeStyle = RULE_COLOR;
  ctx.lineWidth = 1;
  for (let y = 56; y < h - 8; y += 38) {
    ctx.beginPath();
    ctx.moveTo(10, y);
    ctx.lineTo(w - 10, y);
    ctx.stroke();
  }
  ctx.restore();
}

const blankPages = () => [{ id: nextPageId(), src: null }];
const pagesFrom = (arr) =>
  arr && arr.length ? arr.map((src) => ({ id: nextPageId(), src })) : blankPages();

export default function ConsultPadPage() {
  const { token } = useParams();

  const [status, setStatus] = useState("loading"); // loading | invalid | inactive | ready
  const [patient, setPatient] = useState(null);
  const [errorMsg, setErrorMsg] = useState("");

  const [activeTab, setActiveTab] = useState("rx");
  const [tabsPages, setTabsPages] = useState({ rx: blankPages(), note: blankPages() });
  const [tool, setTool] = useState("pen"); // pen | eraser
  const [sizeKey, setSizeKey] = useState("m");
  const [penColor, setPenColor] = useState(PEN_COLOR);
  const [zoom, setZoom] = useState(1);
  const [mode, setMode] = useState("draw"); // draw | scroll
  const [saveState, setSaveState] = useState("idle"); // idle | unsaved | saving | saved | error
  const [online, setOnline] = useState(typeof navigator === "undefined" ? true : navigator.onLine !== false);
  const [doneSheet, setDoneSheet] = useState(false); // "Done" confirmation sheet open
  const [handedBack, setHandedBack] = useState(false); // terminal "all saved, hand it back" screen
  const [recovery, setRecovery] = useState(null); // { tabs } found in localStorage from a prior crash
  const [notice, setNotice] = useState("");       // transient status line (auto-restore, rotate…)
  const [geom, setGeom] = useState(0);            // bump to re-lay-out canvases after a rotate/resize

  const dims = useRef(pageDims());
  const rootRef = useRef(null);       // stable shell element — measured for responsive page width
  const padScrollRef = useRef(null);  // the scrolling pad column (pinch surface)
  const pinch = useRef(null);         // { id1, id2, startDist, startZoom } while a 2-finger pinch is active
  const pointers = useRef(new Map()); // live pointerId -> {x,y} on the pad column
  const sessionIdRef = useRef(null); // id of the consultation this pad is bound to
  const canvases = useRef(new Map()); // pageId -> { el, ctx }
  const undo = useRef(new Map());     // pageId -> [dataURL, ...]
  const lastPage = useRef(null);
  const drawingId = useRef(null);
  const lastPt = useRef({ x: 0, y: 0 });
  const autosaveTimer = useRef(null);
  const dirtyTabs = useRef(new Set()); // tabs with strokes newer than their last successful save
  const savingRef = useRef(false);     // a PUT is in flight — don't stack retries on top

  const toolRef = useRef(tool);        toolRef.current = tool;
  const sizeRef = useRef(sizeKey);     sizeRef.current = sizeKey;
  const colorRef = useRef(penColor);  colorRef.current = penColor;
  const modeRef = useRef(mode);        modeRef.current = mode;
  const activeTabRef = useRef(activeTab); activeTabRef.current = activeTab;
  const tabsPagesRef = useRef(tabsPages); tabsPagesRef.current = tabsPages;

  const pages = tabsPages[activeTab];

  // ── Load the session ─────────────────────────────────────────────────
  useEffect(() => {
    let alive = true;
    let tries = 0;
    const attempt = () => {
      publicClient
        .get(API_ENDPOINTS.CONSULT_PAD.BASE(token))
        .then(({ data }) => {
          if (!alive) return;
          const d = data?.data || data;
          setPatient(d);
          if (!d.active) { setStatus("inactive"); return; }
          sessionIdRef.current = d.session_id ?? null;
          setTabsPages({
            rx: pagesFrom(d.tabs?.rx?.pages),
            note: pagesFrom(d.tabs?.note?.pages),
          });
          // Anything this device saved locally but never got acknowledged?
          let auto = null;
          try {
            const local = JSON.parse(localStorage.getItem(LS_KEY(token)) || "null");
            const n = local ? (local.tabs?.rx?.length || 0) + (local.tabs?.note?.length || 0) : 0;
            if (local && n > 0) {
              const sid = d.session_id ?? null;
              if (local.sid != null && sid != null && local.sid !== sid) {
                // Crash-saved writing from a PREVIOUS consultation on this
                // reused QR token — not ours. Drop it silently.
                clearLocal();
              } else if (local.synced === false) {
                const serverAt = d.updated_at ? Date.parse(d.updated_at) : 0;
                const localFresher = !serverAt || (local.at && local.at >= serverAt - 2000);
                if (local.sid != null && local.sid === sid && localFresher) {
                  // Same consultation, and this phone holds the freshest copy —
                  // just put it back, no decision to make.
                  auto = local;
                } else {
                  setRecovery(local); // ambiguous — let a human confirm
                }
              }
            }
          } catch { /* private mode / bad JSON — ignore */ }
          setStatus("ready");
          if (auto) { restoreLocal(auto); flash("Restored your unsaved writing from this phone."); }
        })
        .catch((err) => {
          if (!alive) return;
          // No HTTP status = network/timeout (e.g. power just came back and
          // the server isn't reachable yet). Retry a few times with backoff
          // before showing the dead-end "code not valid" screen.
          if (!err?.status && tries < 4) { tries += 1; setTimeout(attempt, 1500 * tries); return; }
          setErrorMsg(err?.message || "This code is not valid. Ask the front desk for a fresh QR.");
          setStatus("invalid");
        });
    };
    attempt();
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  // Auto-clear the transient status line.
  useEffect(() => {
    if (!notice) return;
    const t = setTimeout(() => setNotice(""), 4000);
    return () => clearTimeout(t);
  }, [notice]);
  const flash = (m) => setNotice(m);

  // Flush on background/close, and warn before an accidental navigation away
  // while a stroke hasn't been saved yet. `pagehide` is the reliable one on
  // iOS (visibilitychange and beforeunload are both flaky there when the tab
  // is discarded or the user swipes to the home screen).
  useEffect(() => {
    const stash = () => {
      persistLocal();                                    // synchronous — always lands
      if (dirtyTabs.current.size) flushTab(activeTabRef.current, snapshotActive());
    };
    const onHide = () => { if (document.visibilityState === "hidden") stash(); };
    const onPageHide = () => stash();
    const onBeforeUnload = (e) => {
      persistLocal();
      if (dirtyTabs.current.size) { e.preventDefault(); e.returnValue = ""; }
    };
    document.addEventListener("visibilitychange", onHide);
    window.addEventListener("pagehide", onPageHide);
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => {
      document.removeEventListener("visibilitychange", onHide);
      window.removeEventListener("pagehide", onPageHide);
      window.removeEventListener("beforeunload", onBeforeUnload);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Responsive geometry ────────────────────────────────────────────────
  // Canvas geometry is fixed at mount. When the space the pad has to work
  // with changes — a rotate, the on-screen keyboard, browser chrome showing
  // / hiding, split-screen — re-lay-out every page at the new size, carrying
  // the drawing across: snapshot each canvas, drop the old-sized contexts +
  // undo stacks, bump `geom` so the pad remounts and repaints from those
  // snapshots. Width is measured off the live container (rootRef), not
  // window.innerWidth, so it fits every device.
  const relayout = useCallback(() => {
    const next = pageDims(rootRef.current?.clientWidth);
    const cur = dims.current;
    if (Math.abs(next.w - cur.w) < 2 && Math.abs(next.h - cur.h) < 2 && next.dpr === cur.dpr) return;
    drawingId.current = null; // a stroke can't survive the remount
    const active = activeTabRef.current;
    const snap = (tabsPagesRef.current[active] || []).map((p) => ({
      id: p.id,
      src: canvases.current.get(p.id)?.el?.toDataURL("image/png") || p.src || null,
    }));
    canvases.current.clear();
    undo.current = new Map();       // stacks hold old-size bitmaps — not reusable
    dims.current = next;
    setTabsPages((prev) => ({ ...prev, [active]: snap }));
    setGeom((g) => g + 1);
    persistLocal();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    let t;
    const onResize = () => { clearTimeout(t); t = setTimeout(relayout, 180); };
    window.addEventListener("resize", onResize);
    window.addEventListener("orientationchange", onResize);
    window.visualViewport?.addEventListener("resize", onResize);
    let ro;
    if (rootRef.current && typeof ResizeObserver !== "undefined") {
      ro = new ResizeObserver(onResize);
      ro.observe(rootRef.current);
    }
    // One pass after first paint, once the real container width is known.
    onResize();
    return () => {
      clearTimeout(t);
      window.removeEventListener("resize", onResize);
      window.removeEventListener("orientationchange", onResize);
      window.visualViewport?.removeEventListener("resize", onResize);
      ro?.disconnect();
    };
  }, [relayout]);

  // Background sync — the moment the connection is back (or every few seconds
  // while offline), push any unsaved strokes on their own. No stroke, no tap.
  useEffect(() => {
    const drain = () => {
      if (dirtyTabs.current.size && !savingRef.current && navigator.onLine !== false) {
        saveAll();
      }
    };
    const goOnline = () => { setOnline(true); drain(); };
    const goOffline = () => setOnline(false);
    window.addEventListener("online", goOnline);
    window.addEventListener("offline", goOffline);
    // The `online` event is unreliable on some mobile browsers, so also poll
    // while there's unsaved work — a cheap no-op when everything's saved.
    const ticker = setInterval(drain, RETRY_MS);
    return () => {
      window.removeEventListener("online", goOnline);
      window.removeEventListener("offline", goOffline);
      clearInterval(ticker);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Canvas ───────────────────────────────────────────────────────────
  const registerCanvas = useCallback((id, el, src) => {
    if (!el) return;
    if (canvases.current.get(id)?.el === el) return;
    const { w, h, dpr } = dims.current;
    el.width = Math.round(w * dpr);
    el.height = Math.round(h * dpr);
    const ctx = el.getContext("2d");
    ctx.scale(dpr, dpr);
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    paintPaper(ctx, w, h);
    if (src) {
      const img = new Image();
      img.onload = () => ctx.drawImage(img, 0, 0, w, h);
      img.src = src;
    }
    canvases.current.set(id, { el, ctx });
    if (!undo.current.has(id)) undo.current.set(id, []);
  }, []);

  const snapshotActive = () =>
    (tabsPagesRef.current[activeTabRef.current] || []).map((p) => ({
      id: p.id,
      src: canvases.current.get(p.id)?.el?.toDataURL("image/png") || p.src || null,
    }));

  // Mirror both tabs to localStorage. Synchronous, so it survives an
  // instant power loss the way an in-flight PUT does not. `synced` records
  // whether the server has everything — recovery only offers itself when
  // it's false.
  const persistLocal = () => {
    try {
      const active = activeTabRef.current;
      const activeSnap = snapshotActive();
      const grab = (t) =>
        (t === active ? activeSnap : tabsPagesRef.current[t] || [])
          .map((p) => p.src).filter(Boolean);
      const tabs = { rx: grab("rx"), note: grab("note") };
      if (!tabs.rx.length && !tabs.note.length) return;
      localStorage.setItem(LS_KEY(token), JSON.stringify({
        at: Date.now(), synced: dirtyTabs.current.size === 0, sid: sessionIdRef.current, tabs,
      }));
    } catch { /* private mode / quota — best-effort only */ }
  };
  const clearLocal = () => { try { localStorage.removeItem(LS_KEY(token)); } catch { /* ignore */ } };

  // A tab has unsaved work the moment a stroke lands; cleared when its PUT
  // succeeds. Drives the save pill and the "Done" sheet's copy.
  const markDirty = () => {
    dirtyTabs.current.add(activeTabRef.current);
    setSaveState((s) => (s === "saving" ? s : "unsaved"));
  };
  const hasUnsaved = () =>
    dirtyTabs.current.size > 0 || saveState === "saving" || saveState === "error";

  async function flushTab(tab, snap) {
    const srcs = snap.map((s) => s.src).filter(Boolean);
    if (!srcs.length) return;
    savingRef.current = true;
    setSaveState("saving");
    try {
      await publicClient.put(API_ENDPOINTS.CONSULT_PAD.BASE(token), { tab, pages: srcs });
      dirtyTabs.current.delete(tab);
      setSaveState(dirtyTabs.current.size ? "unsaved" : "saved");
      if (dirtyTabs.current.size) persistLocal();
      else clearLocal();
    } catch {
      setSaveState("error");
      persistLocal(); // keep the unsent work on this device — the
      // background-sync effect will re-send it once the connection is back
    } finally {
      savingRef.current = false;
    }
  }

  // Force-save the active tab plus any other tab still marked dirty. Returns
  // true when everything is saved.
  async function saveAll() {
    if (autosaveTimer.current) clearTimeout(autosaveTimer.current);
    const active = activeTabRef.current;
    const snap = snapshotActive();
    setTabsPages((p) => ({ ...p, [active]: snap }));
    await flushTab(active, snap);
    for (const t of Array.from(dirtyTabs.current)) {
      if (t === active) continue;
      const stored = (tabsPagesRef.current[t] || []).map((pg) => ({ src: pg.src }));
      await flushTab(t, stored);
    }
    return dirtyTabs.current.size === 0;
  }

  const scheduleAutosave = () => {
    if (autosaveTimer.current) clearTimeout(autosaveTimer.current);
    autosaveTimer.current = setTimeout(() => {
      const snap = snapshotActive();
      setTabsPages((p) => ({ ...p, [activeTabRef.current]: snap }));
      flushTab(activeTabRef.current, snap);
    }, AUTOSAVE_MS);
  };

  const switchTab = (next) => {
    if (next === activeTab) return;
    if (autosaveTimer.current) clearTimeout(autosaveTimer.current);
    const snap = snapshotActive();
    setTabsPages((p) => ({ ...p, [activeTab]: snap }));
    flushTab(activeTab, snap);
    lastPage.current = null;
    setActiveTab(next);
  };

  // "Done" — save straight away, then show the confirmation sheet so the
  // patient can either hand the phone back or keep writing.
  const openDoneSheet = async () => {
    setDoneSheet(true);
    if (dirtyTabs.current.size) await saveAll();
  };

  const exitPad = () => {
    dirtyTabs.current.clear(); // they've chosen to leave — no beforeunload nag
    clearLocal();
    setDoneSheet(false);
    setHandedBack(true);
    try { window.close(); } catch { /* scanned-QR tabs usually can't self-close */ }
  };

  const saveAndExit = async () => {
    const ok = await saveAll();
    if (ok) exitPad();
    // else: sheet stays open, now showing the "not saved — retry" state
  };

  // Recovery — pull the crash-saved images straight to the server (not via
  // the canvases, which haven't repainted yet). Called from the banner
  // (no arg → uses `recovery` state) or auto on load with an explicit record.
  const restoreLocal = async (rec) => {
    rec = rec || recovery;
    setRecovery(null);
    if (!rec) return;
    setTabsPages({ rx: pagesFrom(rec.tabs?.rx || []), note: pagesFrom(rec.tabs?.note || []) });
    for (const t of ["rx", "note"]) {
      const srcs = (rec.tabs?.[t] || []).filter(Boolean);
      if (!srcs.length) continue;
      dirtyTabs.current.add(t);
      await flushTab(t, srcs.map((src) => ({ src })));
    }
  };
  const dismissRecovery = () => { setRecovery(null); clearLocal(); };

  // drawing — map a screen point to canvas coordinates. getBoundingClientRect
  // already reflects the element's rendered (zoomed) size, so dividing by it
  // gives exact canvas-space coords at any zoom level.
  const pointFrom = (el, e) => {
    const r = el.getBoundingClientRect();
    const sx = r.width ? dims.current.w / r.width : 1;
    const sy = r.height ? dims.current.h / r.height : 1;
    return { x: (e.clientX - r.left) * sx, y: (e.clientY - r.top) * sy };
  };
  const onDown = (id) => (e) => {
    if (modeRef.current !== "draw") return;
    if (pinch.current || pointers.current.size >= 2 || drawingId.current != null) return; // pinch, or already drawing
    e.preventDefault();
    const rec = canvases.current.get(id);
    if (!rec) return;
    e.currentTarget.setPointerCapture?.(e.pointerId);
    pushUndo(id);
    lastPage.current = id;
    drawingId.current = id;
    lastPt.current = pointFrom(rec.el, e);
  };
  const onMove = (id) => (e) => {
    if (drawingId.current !== id) return;
    if (pinch.current) { drawingId.current = null; return; } // second finger landed
    e.preventDefault();
    const rec = canvases.current.get(id);
    if (!rec) return;
    const p = pointFrom(rec.el, e);
    const { ctx } = rec;
    const w = PEN_SIZES.find((s) => s.key === sizeRef.current)?.width || 3.5;
    ctx.strokeStyle = toolRef.current === "eraser" ? PAPER : colorRef.current;
    ctx.lineWidth = toolRef.current === "eraser" ? w * 5 : w;
    ctx.beginPath();
    ctx.moveTo(lastPt.current.x, lastPt.current.y);
    ctx.lineTo(p.x, p.y);
    ctx.stroke();
    lastPt.current = p;
  };
  const onUp = () => {
    if (drawingId.current == null) return;
    drawingId.current = null;
    markDirty();
    persistLocal(); // synchronous crash safety before the debounced PUT
    scheduleAutosave();
  };

  // ── Pinch-to-zoom ─────────────────────────────────────────────────────
  // Two pointers on the pad column drive `zoom`; a third+ is ignored. While a
  // pinch is live the draw handlers bail (see onDown/onMove), so a stray
  // stroke can't be drawn mid-gesture.
  const pinchDist = () => {
    const pts = Array.from(pointers.current.values());
    if (pts.length < 2) return 0;
    return Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y);
  };
  const onPadPointerDown = (e) => {
    pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pointers.current.size === 2) {
      drawingId.current = null; // abandon any half-drawn stroke
      pinch.current = { startDist: pinchDist() || 1, startZoom: zoom };
    }
  };
  const onPadPointerMove = (e) => {
    if (!pointers.current.has(e.pointerId)) return;
    pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pinch.current && pointers.current.size >= 2) {
      const ratio = (pinchDist() || pinch.current.startDist) / pinch.current.startDist;
      setZoom(clampZoom(pinch.current.startZoom * ratio));
    }
  };
  const onPadPointerUp = (e) => {
    pointers.current.delete(e.pointerId);
    if (pointers.current.size < 2) pinch.current = null;
  };
  const setZoomTo = (z) => setZoom(clampZoom(z));

  const pushUndo = (id) => {
    const rec = canvases.current.get(id);
    if (!rec) return;
    const stack = undo.current.get(id) || [];
    stack.push(rec.el.toDataURL("image/png"));
    if (stack.length > UNDO_LIMIT) stack.shift();
    undo.current.set(id, stack);
  };
  const activePageId = () => {
    const ids = new Set(pages.map((p) => p.id));
    return ids.has(lastPage.current) ? lastPage.current : pages[0]?.id;
  };
  const doUndo = () => {
    const id = activePageId();
    const rec = canvases.current.get(id);
    const stack = undo.current.get(id);
    if (!rec || !stack || !stack.length) return;
    const prev = stack.pop();
    const img = new Image();
    img.onload = () => {
      const { w, h } = dims.current;
      rec.ctx.clearRect(0, 0, w, h);
      rec.ctx.drawImage(img, 0, 0, w, h);
      markDirty();
      scheduleAutosave();
    };
    img.src = prev;
  };
  const clearPage = () => {
    const id = activePageId();
    const rec = canvases.current.get(id);
    if (!rec) return;
    pushUndo(id);
    paintPaper(rec.ctx, dims.current.w, dims.current.h);
    markDirty();
    scheduleAutosave();
  };
  const addPage = () => {
    const id = nextPageId();
    setTabsPages((p) => ({ ...p, [activeTab]: [...p[activeTab], { id, src: null }] }));
    setTimeout(() => canvases.current.get(id)?.el?.scrollIntoView({ behavior: "smooth", block: "start" }), 60);
  };

  // Does this page carry any pen? Compares the live canvas against a fresh
  // paint of the ruled paper — so a page that was written on then erased, or
  // one restored from `src`, is both handled. Errs towards "yes" (→ prompt)
  // on any failure.
  const pageHasInk = (id) => {
    try {
      const rec = canvases.current.get(id);
      if (!rec) return !!pages.find((p) => p.id === id)?.src;
      const probe = document.createElement("canvas");
      probe.width = rec.el.width;
      probe.height = rec.el.height;
      const pctx = probe.getContext("2d");
      pctx.scale(dims.current.dpr, dims.current.dpr);
      paintPaper(pctx, dims.current.w, dims.current.h);
      return probe.toDataURL("image/png") !== rec.el.toDataURL("image/png");
    } catch {
      return true;
    }
  };

  const deletePage = (id) => {
    if (pages.length <= 1) return; // never remove the last page
    if (pageHasInk(id) && !window.confirm("Delete this page? Anything written on it will be removed.")) return;
    canvases.current.delete(id);
    undo.current.delete(id);
    if (lastPage.current === id) lastPage.current = null;
    setTabsPages((p) => ({ ...p, [activeTab]: p[activeTab].filter((pg) => pg.id !== id) }));
    markDirty();
    scheduleAutosave();
  };

  // ── Chrome ───────────────────────────────────────────────────────────
  const shell = (children) => (
    <div ref={rootRef} style={{ position: "fixed", inset: 0, background: "#eef2f7", display: "flex", flexDirection: "column",
      fontFamily: "system-ui, -apple-system, sans-serif", color: "#0f172a", overflow: "hidden",
      paddingLeft: "env(safe-area-inset-left)", paddingRight: "env(safe-area-inset-right)" }}>
      {children}
    </div>
  );

  if (status === "loading") return shell(<div style={{ margin: "auto", padding: 24, color: "#64748b" }}>Loading…</div>);
  if (status === "invalid")
    return shell(
      <div style={{ margin: "auto", padding: 24, maxWidth: 360, textAlign: "center" }}>
        <div style={{ fontSize: 40, marginBottom: 8 }}>⚠️</div>
        <h1 style={{ fontSize: 18, margin: "0 0 8px" }}>Code not valid</h1>
        <p style={{ color: "#64748b", fontSize: 14 }}>{errorMsg}</p>
      </div>
    );
  if (status === "inactive")
    return shell(
      <div style={{ margin: "auto", padding: 24, maxWidth: 360, textAlign: "center" }}>
        <div style={{ fontSize: 40, marginBottom: 8 }}>🩺</div>
        <h1 style={{ fontSize: 18, margin: "0 0 8px" }}>No active consultation</h1>
        <p style={{ color: "#64748b", fontSize: 14 }}>
          The doctor hasn't started {patient?.patient_name ? `${patient.patient_name}'s` : "this"} consultation yet.
          Re-open this after they tap "Handwrite (QR)".
        </p>
      </div>
    );

  // Terminal screen after "Exit" — the patient can hand the phone back.
  if (handedBack)
    return shell(
      <div style={{ margin: "auto", padding: 24, maxWidth: 360, textAlign: "center" }}>
        <div style={{ fontSize: 46, marginBottom: 10 }}>✅</div>
        <h1 style={{ fontSize: 19, margin: "0 0 8px" }}>All saved</h1>
        <p style={{ color: "#64748b", fontSize: 14, lineHeight: 1.55 }}>
          Your prescription and note are on the doctor's screen. You can hand the phone back.
        </p>
        <button type="button" onClick={() => setHandedBack(false)}
          style={{ ...btn("#fff", "#2563eb", "#93c5fd"), marginTop: 18 }}>
          Open the pad again
        </button>
      </div>
    );

  const { w: PW, h: PH } = dims.current;
  const PWz = Math.round(PW * zoom);
  const PHz = Math.round(PH * zoom);
  const tabMeta = TABS.find((t) => t.key === activeTab);

  return shell(
    <>
      {/* Header */}
      <div style={{ padding: "9px 12px", background: "#fff", borderBottom: "1px solid #e2e8f0",
        display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
        <strong style={{ fontSize: 15 }}>{patient?.patient_name || "Patient"}</strong>
        <span style={{ fontSize: 12, color: "#64748b" }}>
          {patient?.patient_awpid}
          {patient?.age_years != null ? ` · ${patient.age_years} yrs` : ""}
          {patient?.gender ? ` · ${patient.gender}` : ""}
        </span>
      </div>

      {/* Crash recovery */}
      {recovery && (
        <div style={{ padding: "9px 12px", background: "#fffbeb", borderBottom: "1px solid #fde68a",
          display: "flex", alignItems: "center", gap: 8, fontSize: 12.5, color: "#92400e" }}>
          <span style={{ flex: 1 }}>Unsent writing from this phone was found. Restore it?</span>
          <button type="button" onClick={() => restoreLocal()} style={{ ...seg(true), padding: "6px 10px" }}>Restore</button>
          <button type="button" onClick={dismissRecovery} style={{ ...seg(false), padding: "6px 10px" }}>Discard</button>
        </div>
      )}

      {/* Transient status (auto-restore, rotate…) */}
      {notice && (
        <div style={{ padding: "7px 12px", background: "#eff6ff", borderBottom: "1px solid #bfdbfe",
          fontSize: 12, color: "#1e40af" }}>{notice}</div>
      )}

      {/* Tabs */}
      <div style={{ display: "flex", background: "#fff", borderBottom: "1px solid #e2e8f0" }}>
        {TABS.map((t) => (
          <button key={t.key} type="button" onClick={() => switchTab(t.key)}
            style={{
              flex: 1, padding: "10px 8px", fontSize: 13, fontWeight: 700, border: "none",
              borderBottom: `3px solid ${activeTab === t.key ? "#2563eb" : "transparent"}`,
              background: "none", color: activeTab === t.key ? "#2563eb" : "#64748b", cursor: "pointer",
            }}>
            {t.label}
          </button>
        ))}
      </div>

      {/* Toolbar */}
      <div style={{ display: "flex", alignItems: "center", gap: 6, padding: "8px 10px",
        background: "#fff", borderBottom: "1px solid #e2e8f0", flexWrap: "wrap" }}>
        <div style={{ display: "flex", border: "1px solid #cbd5e1", borderRadius: 8, overflow: "hidden" }}>
          {PEN_SIZES.map((s) => (
            <button key={s.key} type="button" onClick={() => { setSizeKey(s.key); setTool("pen"); }}
              style={{ ...seg(tool === "pen" && sizeKey === s.key), width: 34 }}>{s.label}</button>
          ))}
        </div>
        {/* Pen colour */}
        <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
          {PEN_COLORS.map((c) => {
            const on = tool === "pen" && penColor === c.value;
            return (
              <button key={c.key} type="button" aria-label={`Pen colour ${c.key}`}
                onClick={() => { setPenColor(c.value); setTool("pen"); }}
                style={{
                  width: 24, height: 24, borderRadius: 999, cursor: "pointer", padding: 0,
                  background: c.value, boxShadow: on ? "0 0 0 2px #fff, 0 0 0 4px #2563eb" : "none",
                  border: on ? "none" : "2px solid #fff", outline: "1px solid #cbd5e1",
                }} />
            );
          })}
        </div>
        <button type="button" onClick={() => setTool("eraser")} style={seg(tool === "eraser")}>Eraser</button>
        <button type="button" onClick={doUndo} style={seg(false)}>Undo</button>
        <button type="button" onClick={clearPage} style={seg(false)}>Clear page</button>
        {/* Zoom */}
        <div style={{ display: "flex", alignItems: "center", border: "1px solid #cbd5e1", borderRadius: 8, overflow: "hidden" }}>
          <button type="button" aria-label="Zoom out" onClick={() => setZoomTo(zoom - ZOOM_STEP)}
            disabled={zoom <= ZOOM_MIN} style={{ ...seg(false), borderRadius: 0, border: "none", width: 34, opacity: zoom <= ZOOM_MIN ? 0.4 : 1 }}>−</button>
          <button type="button" onClick={() => setZoomTo(1)} title="Reset zoom"
            style={{ ...seg(zoom !== 1), borderRadius: 0, border: "none", borderLeft: "1px solid #cbd5e1", borderRight: "1px solid #cbd5e1", minWidth: 46 }}>
            {Math.round(zoom * 100)}%
          </button>
          <button type="button" aria-label="Zoom in" onClick={() => setZoomTo(zoom + ZOOM_STEP)}
            disabled={zoom >= ZOOM_MAX} style={{ ...seg(false), borderRadius: 0, border: "none", width: 34, opacity: zoom >= ZOOM_MAX ? 0.4 : 1 }}>+</button>
        </div>
        <div style={{ flex: 1 }} />
        <button type="button" onClick={() => setMode((m) => (m === "draw" ? "scroll" : "draw"))} style={seg(mode === "scroll")}
          title="Switch between writing and scrolling">
          {mode === "draw" ? "✎ Pen" : "✋ Scroll"}
        </button>
      </div>

      {/* Pad — remounts per tab; each canvas restores from its page.src.
          Zoom is applied as CSS display size on the page + canvas, so the
          column simply scrolls to reach any corner. */}
      <div key={`${activeTab}:${geom}`} ref={padScrollRef}
        onPointerDown={onPadPointerDown} onPointerMove={onPadPointerMove}
        onPointerUp={onPadPointerUp} onPointerCancel={onPadPointerUp}
        style={{ flex: 1, overflow: "auto", padding: "14px 0 4px",
          display: "flex", flexDirection: "column", alignItems: "safe center", gap: 14 * zoom,
          touchAction: mode === "draw" ? (zoom > 1 ? "pan-x pan-y" : "pan-y") : "auto" }}>
        {pages.map((p, i) => (
          <div key={p.id} style={{ position: "relative", width: PWz, flexShrink: 0,
            boxShadow: "0 1px 6px rgba(15,23,42,0.14)", borderRadius: 4 }}>
            <div style={{ position: "absolute", top: 6, left: 10, right: 10, fontSize: 10, color: "#cbd5e1",
              pointerEvents: "none", userSelect: "none" }}>
              {i === 0 ? tabMeta.hint : `Page ${i + 1}`}
            </div>
            {pages.length > 1 && (
              <button
                type="button"
                aria-label={`Delete page ${i + 1}`}
                onPointerDown={(e) => e.stopPropagation()}
                onClick={(e) => { e.stopPropagation(); deletePage(p.id); }}
                style={{
                  position: "absolute", top: 4, right: 4, zIndex: 3,
                  display: "inline-flex", alignItems: "center", gap: 4,
                  padding: "4px 9px", fontSize: 11, fontWeight: 700, lineHeight: 1,
                  color: "#b91c1c", background: "rgba(255,255,255,0.94)",
                  border: "1px solid #fecaca", borderRadius: 7, cursor: "pointer",
                }}
              >
                ✕ Delete page
              </button>
            )}
            <canvas
              ref={(el) => registerCanvas(p.id, el, p.src)}
              onPointerDown={onDown(p.id)}
              onPointerMove={onMove(p.id)}
              onPointerUp={onUp}
              onPointerCancel={onUp}
              style={{ width: PWz, height: PHz, display: "block", borderRadius: 4,
                touchAction: mode === "draw" ? "none" : "auto", cursor: mode === "draw" ? "crosshair" : "grab" }}
            />
          </div>
        ))}
        <button type="button" onClick={addPage} style={{ ...btn("#fff", "#2563eb", "#93c5fd"), width: PWz, flexShrink: 0, marginBottom: 6 }}>
          + Add page
        </button>
      </div>

      {/* Bottom bar — a live save pill (nothing is ever "submitted"; every
          stroke autosaves) plus the Done affordance. */}
      <div style={{ padding: 12, display: "flex", gap: 10, alignItems: "center",
        borderTop: "1px solid #e2e8f0", background: "#fff" }}>
        <SavePill saveState={saveState} pageCount={pages.length} online={online} />
        <div style={{ flex: 1 }} />
        <button type="button" onClick={openDoneSheet} style={btn("#2563eb", "#fff", "#2563eb")}>Done</button>
      </div>

      {/* Done confirmation sheet */}
      {doneSheet && (
        <div style={sheetBackdrop} onClick={() => setDoneSheet(false)}>
          <div style={sheetCard} onClick={(e) => e.stopPropagation()}>
            {hasUnsaved() ? (
              <>
                <div style={{ fontSize: 34, textAlign: "center" }}>
                  {saveState === "saving" ? "⏳" : saveState === "error" ? "⚠️" : "📝"}
                </div>
                <h2 style={sheetTitle}>
                  {saveState === "saving" ? "Saving your writing…"
                    : saveState === "error" ? "Couldn't save yet"
                    : "Save your writing?"}
                </h2>
                <p style={sheetText}>
                  {saveState === "error"
                    ? "The last save didn't go through. Try again, or exit without saving."
                    : "You have changes that aren't on the doctor's screen yet."}
                </p>
                <button type="button" onClick={saveAndExit} disabled={saveState === "saving"}
                  style={{ ...btn("#2563eb", "#fff", "#2563eb"), width: "100%", opacity: saveState === "saving" ? 0.6 : 1 }}>
                  {saveState === "error" ? "Retry save & exit" : "Save & exit"}
                </button>
                <button type="button" onClick={exitPad}
                  style={{ ...btn("#fff", "#b91c1c", "#fecaca"), width: "100%", marginTop: 8 }}>
                  Exit without saving
                </button>
                <button type="button" onClick={() => setDoneSheet(false)}
                  style={{ ...btn("#fff", "#475569", "#cbd5e1"), width: "100%", marginTop: 8 }}>
                  Keep writing
                </button>
              </>
            ) : (
              <>
                <div style={{ fontSize: 34, textAlign: "center" }}>✅</div>
                <h2 style={sheetTitle}>Everything's saved</h2>
                <p style={sheetText}>
                  Your prescription and note are on the doctor's screen. Hand the phone back, or keep writing.
                </p>
                <button type="button" onClick={exitPad}
                  style={{ ...btn("#2563eb", "#fff", "#2563eb"), width: "100%" }}>
                  Exit
                </button>
                <button type="button" onClick={() => setDoneSheet(false)}
                  style={{ ...btn("#fff", "#475569", "#cbd5e1"), width: "100%", marginTop: 8 }}>
                  Keep writing
                </button>
              </>
            )}
          </div>
        </div>
      )}
    </>
  );
}

// Always-visible save indicator. The pad has no "submit" — every stroke
// autosaves — so this pill is how the patient knows their work is safe.
const PILL = {
  idle:    { bg: "#f1f5f9", fg: "#64748b", dot: "#94a3b8" },
  unsaved: { bg: "#fffbeb", fg: "#b45309", dot: "#f59e0b" },
  saving:  { bg: "#f1f5f9", fg: "#475569", dot: "#64748b" },
  saved:   { bg: "#ecfdf5", fg: "#047857", dot: "#10b981" },
  error:   { bg: "#fef2f2", fg: "#b91c1c", dot: "#ef4444" },
};
function SavePill({ saveState, pageCount, online }) {
  // Offline with unsaved work isn't a failure — the strokes are safe on the
  // phone and will sync themselves. Say so, in amber, not alarming red.
  const offlinePending = !online && (saveState === "error" || saveState === "unsaved" || saveState === "saving");
  const key = offlinePending ? "unsaved" : saveState;
  const s = PILL[key] || PILL.idle;
  const text = offlinePending
    ? "Offline — will save when reconnected"
    : ({
        idle: `${pageCount} page${pageCount > 1 ? "s" : ""}`,
        unsaved: "Unsaved changes",
        saving: "Saving…",
        saved: "Saved — safe to hand back",
        error: "Reconnecting — will save automatically",
      }[saveState] || `${pageCount} page${pageCount > 1 ? "s" : ""}`);
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "6px 10px",
      borderRadius: 999, background: s.bg, color: s.fg, fontSize: 12, fontWeight: 700, whiteSpace: "nowrap" }}>
      <span style={{ width: 8, height: 8, borderRadius: 999, background: s.dot }} />
      {saveState === "saved" && !offlinePending ? "✓ " : ""}{text}
    </span>
  );
}

const sheetBackdrop = {
  position: "fixed", inset: 0, background: "rgba(15,23,42,0.45)",
  display: "flex", alignItems: "flex-end", justifyContent: "center", zIndex: 50,
};
const sheetCard = {
  width: "100%", maxWidth: 480, background: "#fff", borderRadius: "16px 16px 0 0",
  padding: "20px 18px calc(20px + env(safe-area-inset-bottom))",
  boxShadow: "0 -8px 30px rgba(15,23,42,0.25)",
};
const sheetTitle = { fontSize: 18, fontWeight: 800, margin: "10px 0 6px", textAlign: "center" };
const sheetText = { fontSize: 13.5, color: "#64748b", lineHeight: 1.5, textAlign: "center", margin: "0 0 16px" };

function btn(bg, fg, border) {
  return {
    padding: "12px 18px", fontSize: 15, fontWeight: 600, borderRadius: 8,
    border: `1px solid ${border}`, background: bg, color: fg, cursor: "pointer",
  };
}
function seg(active) {
  return {
    padding: "7px 10px", fontSize: 12, fontWeight: 600, border: "1px solid #cbd5e1",
    borderRadius: 8, background: active ? "#2563eb" : "#fff", color: active ? "#fff" : "#0f172a",
    cursor: "pointer", whiteSpace: "nowrap",
  };
}
