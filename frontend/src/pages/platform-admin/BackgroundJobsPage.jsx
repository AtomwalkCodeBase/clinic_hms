/**
 * pages/platform-admin/BackgroundJobsPage.jsx
 * -------------------------------------------
 * Platform admin → Background Jobs: run and watch Celery without a terminal.
 *
 *   Workers        start / stop / restart the worker and the Beat scheduler,
 *                  their live state, log, broker + queue depth, and the
 *                  settings they start with (broker URL, pool, concurrency…)
 *   Scheduled jobs periodic tasks (cron or every-N), optionally scoped to one
 *                  hospital — its DB key prefixes the job name
 *   History        every task run: status, duration, result / traceback
 *
 * Backend: apps/platform_admin/jobs_views.py, core/celery_runtime.py
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AppShell } from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import apiClient from "../../services/api.client";
import { useToast } from "../../hooks/useToast";
import API_ENDPOINTS from "../../config/api.config";

const J = API_ENDPOINTS.PLATFORM;
const inputStyle = {
  width: "100%", boxSizing: "border-box", border: "1.5px solid var(--color-border)", borderRadius: 8,
  padding: "7px 10px", fontSize: 13.5, background: "var(--color-surface)", color: "var(--color-text)", outline: "none",
};
const labelStyle = { display: "block", fontSize: 12.5, fontWeight: 600, marginBottom: 5 };
const th = { padding: "9px 12px", fontWeight: 600, textAlign: "left", whiteSpace: "nowrap" };
const td = { padding: "9px 12px", verticalAlign: "top" };
const unwrap = (res) => res?.data?.data ?? res?.data;

function ago(iso) {
  if (!iso) return "—";
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return `${Math.round(s)}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}
function until(iso) {
  if (!iso) return "—";
  const s = (new Date(iso).getTime() - Date.now()) / 1000;
  if (s <= 0) return "due now";
  if (s < 60) return `in ${Math.round(s)}s`;
  if (s < 3600) return `in ${Math.round(s / 60)}m`;
  if (s < 86400) return `in ${Math.round(s / 3600)}h`;
  return `in ${Math.round(s / 86400)}d`;
}
const fmtTime = (iso) => (iso ? new Date(iso).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "—");

function Pill({ tone, children }) {
  const c = {
    ok: ["#DCF3E8", "#166534"], warn: ["#FBF3E6", "#9A5B16"], bad: ["#FBEAE7", "#B23A2E"], mute: ["var(--color-border)", "var(--color-text-muted)"],
  }[tone] || ["var(--color-border)", "var(--color-text-muted)"];
  return <span style={{ fontSize: 11, fontWeight: 700, letterSpacing: ".03em", padding: "2px 8px", borderRadius: 999, background: c[0], color: c[1], whiteSpace: "nowrap" }}>{children}</span>;
}

export default function BackgroundJobsPage() {
  const [tab, setTab] = useState("workers");
  return (
    <AppShell>
      <PageShell title="Background Jobs">
        <div style={{ display: "inline-flex", border: "1px solid var(--color-border)", borderRadius: 9, overflow: "hidden", marginBottom: 16 }}>
          {[["workers", "Workers"], ["jobs", "Scheduled jobs"], ["history", "History"]].map(([id, l]) => (
            <button key={id} onClick={() => setTab(id)} style={{
              padding: "7px 14px", fontSize: 13, border: "none", cursor: "pointer",
              background: tab === id ? "var(--color-primary)" : "transparent",
              color: tab === id ? "#fff" : "var(--color-text-secondary)", fontWeight: tab === id ? 600 : 400,
            }}>{l}</button>
          ))}
        </div>
        {tab === "workers" ? <WorkersTab /> : tab === "jobs" ? <JobsTab /> : <HistoryTab />}
      </PageShell>
    </AppShell>
  );
}

/* ═════════════════════════════════════════════════════════ workers */
function WorkersTab() {
  const { toastSuccess, toastApiError } = useToast();
  const [st, setSt] = useState(null);
  const [busy, setBusy] = useState("");
  const [logFor, setLogFor] = useState("");

  const load = useCallback(async () => {
    try { setSt(unwrap(await apiClient.get(J.JOBS_RUNTIME))); }
    catch (err) { toastApiError(err, "Could not load status."); }
  }, [toastApiError]);
  useEffect(() => {
    load();
    const t = setInterval(load, 4000);
    return () => clearInterval(t);
  }, [load]);

  async function act(kind, action) {
    setBusy(`${kind}:${action}`);
    try {
      const res = await apiClient.post(J.JOBS_ACTION(kind, action));
      setSt(unwrap(res));
      toastSuccess(res?.data?.message || "Done.");
      if (action !== "stop") setLogFor(kind);
    } catch (err) { toastApiError(err, `Could not ${action} the ${kind}.`); } finally { setBusy(""); }
  }

  if (!st) return <div className="card" style={{ padding: 30, textAlign: "center", color: "var(--color-text-muted)" }}>Loading…</div>;

  return (
    <>
      {!st.process_control && (
        <div className="card" style={{ padding: "10px 14px", marginBottom: 12, borderLeft: "3px solid var(--color-warning)", fontSize: 13 }}>
          <b>Managed by systemd on this server.</b> The worker, Beat and Flower start with the server and restart
          themselves if they crash; this page shows their status. To restart by hand on the server:
          <code style={{ display: "block", marginTop: 6, fontSize: 12 }}>sudo systemctl restart hms-celery-worker hms-celery-beat hms-flower</code>
        </div>
      )}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))", gap: 12, marginBottom: 14 }}>
        <ProcessCard kind="worker" title="Worker"
          blurb={`Sorts documents and runs scheduled jobs — ${st.config.worker_concurrency || 1} at a time.`}
          p={st.worker} control={st.process_control} busy={busy} onAct={act} onLog={() => setLogFor(logFor === "worker" ? "" : "worker")} />
        <ProcessCard kind="beat" title="Beat scheduler" blurb="Queues scheduled jobs when they're due. Run exactly one."
          p={st.beat} control={st.process_control} busy={busy} onAct={act} onLog={() => setLogFor(logFor === "beat" ? "" : "beat")} />
        {st.flower && (
          <ProcessCard kind="flower" title="Flower dashboard" blurb="Celery's live monitor — workers, tasks, graphs."
            p={st.flower} control={st.process_control} busy={busy} onAct={act} onLog={() => setLogFor(logFor === "flower" ? "" : "flower")}
            note={st.flower.needs_broker ? "Needs a Redis broker — set the broker URL below, then restart the worker." : ""}
            link={st.flower.state === "running" ? st.flower.url : ""} />
        )}
      </div>

      <div className="card" style={{ padding: "12px 16px", marginBottom: 14, display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <div style={{ flex: 1, minWidth: 240 }}>
          <div style={{ fontWeight: 700, fontSize: 14 }}>Document pipeline log</div>
          <div style={{ fontSize: 12, color: "var(--color-text-muted)" }}>
            Every upload's journey, one line per step — uploaded → text read → rules → filed → AI queued → AI result.
            Written by the web server and the workers alike.
          </div>
        </div>
        <button className={logFor === "pipeline" ? "btn-primary" : "btn-outline"} onClick={() => setLogFor(logFor === "pipeline" ? "" : "pipeline")}>
          {logFor === "pipeline" ? "Hide pipeline log" : "Show pipeline log"}
        </button>
      </div>

      {logFor && <LogPanel kind={logFor} onClose={() => setLogFor("")} />}

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))", gap: 12, marginBottom: 14 }}>
        <div className="card" style={{ padding: 16 }}>
          <div style={{ fontWeight: 700, marginBottom: 10 }}>Broker & queues</div>
          <Row k="Broker" v={<code style={{ fontSize: 12, wordBreak: "break-all" }}>{st.broker.url}</code>} />
          <Row k="Live inspect" v={st.broker.broadcast ? "Yes (Redis/RabbitMQ)" : "No — Postgres broker; status comes from heartbeats"} />
          {st.queues?.error
            ? <Row k="Queues" v={<span style={{ color: "var(--color-error)" }}>{st.queues.error}</span>} />
            : Object.entries(st.queues || {}).map(([q, n]) => <Row key={q} k={`Queue “${q}”`} v={`${n} waiting`} />)}
        </div>
        <div className="card" style={{ padding: 16 }}>
          <div style={{ fontWeight: 700, marginBottom: 10 }}>Running now</div>
          {st.active?.length ? st.active.map(a => (
            <div key={a.task_id} style={{ fontSize: 12.5, padding: "6px 0", borderTop: "1px solid var(--color-border)" }}>
              <b>{a.task_name}</b> <span style={{ color: "var(--color-text-muted)" }}>· {a.worker || "worker"} · {ago(a.started)}</span>
            </div>
          )) : <div style={{ fontSize: 13, color: "var(--color-text-muted)" }}>Nothing running.</div>}
        </div>
      </div>

      <SettingsCard cfg={st.config} defaultBroker={st.broker.default_url} onSaved={setSt} managed={!st.process_control} />
    </>
  );
}

function Row({ k, v }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "120px 1fr", gap: 10, padding: "6px 0", borderTop: "1px solid var(--color-border)", fontSize: 12.5 }}>
      <span style={{ color: "var(--color-text-muted)" }}>{k}</span><span>{v}</span>
    </div>
  );
}

function ProcessCard({ kind, title, blurb, p, control, busy, onAct, onLog, note = "", link = "" }) {
  const tone = p.state === "running" ? "ok" : p.state === "starting" ? "warn" : "mute";
  const running = p.state !== "stopped";
  const b = (a) => busy === `${kind}:${a}`;
  return (
    <div className="card" style={{ padding: 16 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
        <span style={{ fontWeight: 700, fontSize: 15 }}>{title}</span>
        <Pill tone={tone}>{p.state.toUpperCase()}</Pill>
      </div>
      <div style={{ fontSize: 12, color: "var(--color-text-muted)", marginBottom: 10 }}>{blurb}</div>
      {note && <div style={{ fontSize: 12, color: "var(--color-warning)", marginBottom: 8 }}>{note}</div>}
      {kind === "flower"
        ? <Row k="Address" v={p.url || "—"} />
        : <Row k="Heartbeat" v={p.heartbeat_at ? ago(p.heartbeat_at) : "none"} />}
      <Row k="Started" v={p.started_at ? `${fmtTime(p.started_at)} (${ago(p.started_at)})` : "—"} />
      <Row k="Process" v={p.pid ? `PID ${p.pid}${p.process_running ? "" : " (not on this machine)"}` : "—"} />
      {p.memory_mb != null && <Row k="CPU / memory" v={`${p.cpu_percent ?? 0}% · ${p.memory_mb} MB`} />}
      {kind === "worker" && p.hostname && <Row k="Host" v={p.hostname} />}
      <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
        {!running ? (
          <button className="btn-primary" disabled={!control || !!busy || !!note} onClick={() => onAct(kind, "start")}>{b("start") ? "Starting…" : "Start"}</button>
        ) : (
          <>
            <button className="btn-outline" disabled={!control || !!busy} onClick={() => onAct(kind, "restart")}>{b("restart") ? "Restarting…" : "Restart"}</button>
            <button className="btn-outline" style={{ color: "var(--color-danger)" }} disabled={!control || !!busy} onClick={() => onAct(kind, "stop")}>{b("stop") ? "Stopping…" : "Stop"}</button>
          </>
        )}
        <button className="btn-outline" onClick={onLog}>Log</button>
        {link && <a className="btn-primary" href={link} target="_blank" rel="noreferrer" style={{ textDecoration: "none" }}>Open Flower ↗</a>}
      </div>
    </div>
  );
}

function LogPanel({ kind, onClose }) {
  const [text, setText] = useState("");
  const [follow, setFollow] = useState(true);
  const box = useRef(null);
  const load = useCallback(async () => {
    try { setText(unwrap(await apiClient.get(J.JOBS_LOG(kind), { params: { lines: 300 } }))?.log || ""); } catch { /* keep last */ }
  }, [kind]);
  useEffect(() => {
    load();
    if (!follow) return undefined;
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, [load, follow]);
  useEffect(() => { if (follow && box.current) box.current.scrollTop = box.current.scrollHeight; }, [text, follow]);
  return (
    <div className="card" style={{ padding: 14, marginBottom: 14 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
        <b style={{ fontSize: 13.5 }}>{{ worker: "Worker", beat: "Beat", flower: "Flower", pipeline: "Document pipeline" }[kind]} log</b>
        <label style={{ fontSize: 12, display: "flex", gap: 5, alignItems: "center" }}>
          <input type="checkbox" checked={follow} onChange={e => setFollow(e.target.checked)} /> Follow
        </label>
        <span style={{ flex: 1 }} />
        <button className="btn-outline" style={{ fontSize: 12, padding: "4px 10px" }} onClick={onClose}>Close</button>
      </div>
      <pre ref={box} style={{
        margin: 0, maxHeight: 340, overflow: "auto", fontSize: 11.5, lineHeight: 1.45, padding: 12, borderRadius: 8,
        background: "#0f1714", color: "#d6e4dc", whiteSpace: "pre-wrap", wordBreak: "break-all",
      }}>{text || "No log yet — start the process."}</pre>
    </div>
  );
}

function SettingsCard({ cfg, defaultBroker, onSaved, managed = false }) {
  const { toastSuccess, toastApiError } = useToast();
  const [f, setF] = useState(cfg);
  const [busy, setBusy] = useState(false);
  const [advanced, setAdvanced] = useState(false);
  const dirty = useMemo(() => JSON.stringify(f) !== JSON.stringify(cfg), [f, cfg]);
  useEffect(() => { if (!dirty) setF(cfg); }, [cfg]); // eslint-disable-line react-hooks/exhaustive-deps
  const set = (k) => (e) => setF(p => ({ ...p, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value }));
  const workers = Number(f.worker_concurrency) || 1;

  async function save() {
    setBusy(true);
    try {
      const res = await apiClient.patch(J.JOBS_RUNTIME, {
        worker_concurrency: workers,
        instant_max_files: Number(f.instant_max_files), bulk_batch_limit: Number(f.bulk_batch_limit),
        broker_url: f.broker_url, worker_queues: f.worker_queues, worker_loglevel: f.worker_loglevel,
        inline_fallback: f.inline_fallback,
      });
      onSaved(unwrap(res));
      toastSuccess(res?.data?.message || "Saved.");
    } catch (err) { toastApiError(err, "Could not save."); } finally { setBusy(false); }
  }

  return (
    <div className="card" style={{ padding: 16 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginBottom: 14 }}>
        <b>Settings</b>
        <span style={{ fontSize: 12, color: "var(--color-text-muted)" }}>
          {cfg.updated_by ? `last changed by ${cfg.updated_by}` : ""}
        </span>
      </div>

      {/* ── the one number most people need ── */}
      <label style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
        <span style={{ minWidth: 220 }}>
          <span style={{ display: "block", fontWeight: 700, fontSize: 14 }}>Workers</span>
          <span style={{ display: "block", fontSize: 12, color: "var(--color-text-muted)" }}>
            How many files are sorted at the same time. 1 is enough to start.
          </span>
        </span>
        <input style={{ ...inputStyle, width: 90, fontSize: 16, fontWeight: 600, textAlign: "center" }}
          type="number" min={1} max={8} value={f.worker_concurrency} onChange={set("worker_concurrency")} disabled={managed} />
        <span style={{ fontSize: 12, color: "var(--color-text-muted)", flex: 1, minWidth: 220 }}>
          {managed
            ? "On this server the number is set in /etc/hms/celery.env (CELERY_CONCURRENCY)."
            : `${workers === 1 ? "One file at a time." : `${workers} files at a time.`} AI checks always go one at a time. Restart the worker after saving.`}
        </span>
      </label>

      {/* ── upload routing ── */}
      <div style={{ fontWeight: 700, fontSize: 14, margin: "18px 0 8px" }}>Upload routing</div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 12 }}>
        <label><span style={labelStyle}>Sort instantly up to (files per upload)</span>
          <input style={inputStyle} type="number" min={0} max={50} value={f.instant_max_files ?? 3} onChange={set("instant_max_files")} />
        </label>
        <label><span style={labelStyle}>Bulk: files per scheduled run</span>
          <input style={inputStyle} type="number" min={1} max={500} value={f.bulk_batch_limit ?? 25} onChange={set("bulk_batch_limit")} />
        </label>
      </div>
      <div style={{ fontSize: 12, color: "var(--color-text-muted)", marginTop: 6 }}>
        Bigger uploads are sorted by the “Process bulk uploads” scheduled job (every 2 minutes — change it on the
        Scheduled jobs tab). Applies immediately, no restart.
      </div>

      {/* ── advanced (rarely needed) ── */}
      <button type="button" onClick={() => setAdvanced(a => !a)}
        style={{ marginTop: 16, background: "none", border: "none", padding: 0, cursor: "pointer", color: "var(--color-primary)", fontWeight: 600, fontSize: 13 }}>
        {advanced ? "▾ Hide advanced" : "▸ Advanced"}
      </button>
      {advanced && (
        <div style={{ marginTop: 10, padding: 12, borderRadius: 10, background: "var(--color-bg)" }}>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(190px, 1fr))", gap: 12 }}>
            <label style={{ gridColumn: "1 / -1" }}><span style={labelStyle}>Broker URL</span>
              <input style={inputStyle} value={f.broker_url} onChange={set("broker_url")}
                placeholder={managed ? `Set in .env: ${defaultBroker}` : `Default: ${defaultBroker}  —  e.g. redis://localhost:6379/0`}
                disabled={managed} title={managed ? "Set CELERY_BROKER_URL in the server's .env" : ""} />
            </label>
            <label><span style={labelStyle}>Queues (comma-separated)</span>
              <input style={inputStyle} value={f.worker_queues} onChange={set("worker_queues")} />
            </label>
            <label><span style={labelStyle}>Log level</span>
              <select style={inputStyle} value={f.worker_loglevel} onChange={set("worker_loglevel")}>
                {["DEBUG", "INFO", "WARNING", "ERROR"].map(l => <option key={l}>{l}</option>)}
              </select>
            </label>
          </div>
          <label style={{ display: "flex", gap: 8, alignItems: "flex-start", fontSize: 13, marginTop: 12 }}>
            <input type="checkbox" checked={!!f.inline_fallback} onChange={set("inline_fallback")} style={{ marginTop: 3 }} />
            <span>When the worker or Beat isn't running, sort bulk uploads inside the web server instead of leaving them queued.</span>
          </label>
        </div>
      )}

      <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 14 }}>
        {dirty && <button className="btn-outline" onClick={() => setF(cfg)}>Reset</button>}
        <button className="btn-primary" disabled={!dirty || busy} onClick={save}>{busy ? "Saving…" : "Save settings"}</button>
      </div>
    </div>
  );
}

/* ═════════════════════════════════════════════════════════ scheduled jobs */
function describeSchedule(j) {
  if (j.schedule_type === "interval") return `Every ${j.interval.every} ${j.interval.every === 1 ? j.interval.period.replace(/s$/, "") : j.interval.period}`;
  if (j.schedule_type !== "crontab") return "—";
  const { minute: m, hour: h, day_of_week: dw, day_of_month: dm, month_of_year: my } = j.crontab;
  const rest = dw === "*" && dm === "*" && my === "*";
  if (rest && h === "*" && /^\*\/\d+$/.test(m)) return `Every ${m.slice(2)} minutes`;
  if (rest && h === "*" && /^\d+$/.test(m)) return `Hourly at :${m.padStart(2, "0")}`;
  if (rest && /^\d+$/.test(h) && /^\d+$/.test(m)) return `Daily at ${h.padStart(2, "0")}:${m.padStart(2, "0")}`;
  return `cron ${m} ${h} ${dm} ${my} ${dw}`;
}

function JobsTab() {
  const { toastSuccess, toastApiError } = useToast();
  const [jobs, setJobs] = useState(null);
  const [cat, setCat] = useState({ tasks: [], tenants: [], timezone: "" });
  const [editing, setEditing] = useState(null);

  const load = useCallback(async () => {
    try {
      const [a, b] = await Promise.all([apiClient.get(J.JOBS_SCHEDULES), apiClient.get(J.JOBS_TASKS)]);
      setJobs(unwrap(a) || []);
      setCat(unwrap(b));
    } catch (err) { toastApiError(err, "Could not load jobs."); }
  }, [toastApiError]);
  useEffect(() => { load(); }, [load]);

  const taskLabel = (n) => cat.tasks.find(t => t.name === n)?.label || n;
  const tenantName = (db) => cat.tenants.find(t => t.db_name === db)?.name || db;

  async function toggle(j) {
    try { await apiClient.patch(J.JOBS_SCHEDULE(j.id), { enabled: !j.enabled }); load(); }
    catch (err) { toastApiError(err, "Could not update."); }
  }
  async function runNow(j) {
    try { const res = await apiClient.post(J.JOBS_SCHEDULE_RUN(j.id)); toastSuccess(res?.data?.message || "Queued."); }
    catch (err) { toastApiError(err, "Could not run."); }
  }
  async function remove(j) {
    if (!window.confirm(`Delete the job “${j.name}”?`)) return;
    try { await apiClient.delete(J.JOBS_SCHEDULE(j.id)); toastSuccess("Job deleted."); load(); }
    catch (err) { toastApiError(err, "Could not delete."); }
  }

  return (
    <>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12, flexWrap: "wrap" }}>
        <p style={{ margin: 0, fontSize: 13, color: "var(--color-text-muted)", flex: 1, minWidth: 260 }}>
          Beat queues each enabled job when it's due (times in {cat.timezone || "local time"}); the worker runs it.
          Changes are picked up within a few seconds — no restart.
        </p>
        <button className="btn-primary" onClick={() => setEditing({})}>+ New job</button>
      </div>

      {editing && <JobEditor job={editing} cat={cat} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); load(); }} />}

      {!jobs ? (
        <div className="card" style={{ padding: 30, textAlign: "center", color: "var(--color-text-muted)" }}>Loading…</div>
      ) : (
        <div className="card" style={{ padding: 0, overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead><tr style={{ color: "var(--color-text-muted)", fontSize: 12 }}>
              <th style={th}>Job</th><th style={th}>Schedule</th><th style={th}>Next run</th><th style={th}>Last run</th>
              <th style={th}>Runs</th><th style={th}>On</th><th style={th} />
            </tr></thead>
            <tbody>
              {jobs.map(j => (
                <tr key={j.id} style={{ borderTop: "1px solid var(--color-border)", opacity: j.enabled ? 1 : 0.6 }}>
                  <td style={td}>
                    <div style={{ fontWeight: 600 }}>
                      {j.tenant_db && <span style={{ fontFamily: "monospace", fontSize: 11, background: "var(--color-bg)", border: "1px solid var(--color-border)", borderRadius: 5, padding: "1px 5px", marginRight: 6 }} title={tenantName(j.tenant_db)}>{j.tenant_db}</span>}
                      {j.label}
                    </div>
                    <div style={{ fontSize: 11.5, color: "var(--color-text-muted)" }}>{taskLabel(j.task)}{j.one_off ? " · once" : ""}</div>
                  </td>
                  <td style={td}>{describeSchedule(j)}</td>
                  <td style={td}>{j.enabled ? until(j.next_run_at) : "—"}</td>
                  <td style={td}>{j.last_run_at ? ago(j.last_run_at) : "never"}</td>
                  <td style={{ ...td, fontVariantNumeric: "tabular-nums" }}>{j.total_run_count}</td>
                  <td style={td}><input type="checkbox" checked={j.enabled} onChange={() => toggle(j)} aria-label="Enabled" /></td>
                  <td style={{ ...td, whiteSpace: "nowrap" }}>
                    <button className="btn-outline" style={{ fontSize: 12, padding: "4px 10px" }} onClick={() => runNow(j)}>Run now</button>{" "}
                    <button className="btn-outline" style={{ fontSize: 12, padding: "4px 10px" }} onClick={() => setEditing(j)}>Edit</button>{" "}
                    <button className="btn-outline" style={{ fontSize: 12, padding: "4px 10px", color: "var(--color-danger)" }} onClick={() => remove(j)}>Delete</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

const CRON_PRESETS = [
  ["Every 5 minutes", { minute: "*/5", hour: "*", day_of_month: "*", month_of_year: "*", day_of_week: "*" }],
  ["Hourly", { minute: "0", hour: "*", day_of_month: "*", month_of_year: "*", day_of_week: "*" }],
  ["Daily 07:00", { minute: "0", hour: "7", day_of_month: "*", month_of_year: "*", day_of_week: "*" }],
  ["Weekdays 09:00", { minute: "0", hour: "9", day_of_month: "*", month_of_year: "*", day_of_week: "1-5" }],
  ["1st of month 02:00", { minute: "0", hour: "2", day_of_month: "1", month_of_year: "*", day_of_week: "*" }],
];

function JobEditor({ job, cat, onClose, onSaved }) {
  const { toastSuccess, toastApiError } = useToast();
  const isNew = !job.id;
  const schedulable = cat.tasks.filter(t => t.schedulable);
  const [f, setF] = useState(() => ({
    label: job.label || "",
    task: job.task || schedulable[0]?.name || "",
    tenant_db: job.tenant_db || "",
    schedule_type: job.schedule_type || "crontab",
    crontab: job.crontab || CRON_PRESETS[2][1],
    interval: job.interval || { every: 15, period: "minutes" },
    kwargs: JSON.stringify(job.kwargs ?? (schedulable[0]?.kwargs || {}), null, 2),
    enabled: job.enabled ?? true,
    one_off: job.one_off ?? false,
    description: job.description || "",
  }));
  const [busy, setBusy] = useState(false);
  const meta = cat.tasks.find(t => t.name === f.task) || {};
  const set = (k, v) => setF(p => ({ ...p, [k]: v }));

  function pickTask(name) {
    const m = cat.tasks.find(t => t.name === name) || {};
    setF(p => ({ ...p, task: name, kwargs: JSON.stringify(m.kwargs || {}, null, 2), tenant_db: m.tenant_aware ? p.tenant_db : "",
      label: p.label || m.label || "" }));
  }

  async function save() {
    let kwargs;
    try { kwargs = JSON.parse(f.kwargs || "{}"); } catch { toastApiError(null, "Arguments must be valid JSON."); return; }
    setBusy(true);
    const body = {
      label: f.label, task: f.task, tenant_db: f.tenant_db, schedule_type: f.schedule_type,
      crontab: f.crontab, interval: { every: Number(f.interval.every), period: f.interval.period },
      kwargs, enabled: f.enabled, one_off: f.one_off, description: f.description,
    };
    try {
      if (isNew) await apiClient.post(J.JOBS_SCHEDULES, body);
      else await apiClient.patch(J.JOBS_SCHEDULE(job.id), body);
      toastSuccess(isNew ? "Job scheduled." : "Job saved.");
      onSaved();
    } catch (err) { toastApiError(err, "Could not save the job."); } finally { setBusy(false); }
  }

  const cronField = (k, l, ph) => (
    <label key={k}><span style={labelStyle}>{l}</span>
      <input style={{ ...inputStyle, fontFamily: "monospace" }} value={f.crontab[k]} placeholder={ph}
        onChange={e => set("crontab", { ...f.crontab, [k]: e.target.value })} />
    </label>
  );

  return (
    <div className="card" style={{ padding: 16, marginBottom: 16, display: "grid", gap: 14 }}>
      <b>{isNew ? "New scheduled job" : `Edit “${job.name}”`}</b>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 12 }}>
        <label><span style={labelStyle}>Task</span>
          <select style={inputStyle} value={f.task} onChange={e => pickTask(e.target.value)}>
            {schedulable.map(t => <option key={t.name} value={t.name}>{t.label}</option>)}
          </select>
        </label>
        <label><span style={labelStyle}>Job name</span>
          <input style={inputStyle} value={f.label} onChange={e => set("label", e.target.value)} placeholder="e.g. Daily reminders" />
        </label>
        <label><span style={labelStyle}>Hospital</span>
          <select style={inputStyle} value={f.tenant_db} disabled={!meta.tenant_aware} onChange={e => set("tenant_db", e.target.value)}>
            <option value="">{meta.tenant_aware ? "All hospitals" : "Platform-wide task"}</option>
            {meta.tenant_aware && cat.tenants.map(t => <option key={t.db_name} value={t.db_name}>{t.name} ({t.db_name})</option>)}
          </select>
        </label>
      </div>
      {meta.description && <div style={{ fontSize: 12, color: "var(--color-text-muted)", marginTop: -6 }}>{meta.description}</div>}
      {f.tenant_db && (
        <div style={{ fontSize: 12, color: "var(--color-text-muted)", marginTop: -6 }}>
          Saved as <code>{f.tenant_db}: {f.label || "…"}</code> and runs against that hospital's database only.
        </div>
      )}

      <div>
        <span style={labelStyle}>Schedule</span>
        <div style={{ display: "flex", gap: 14, fontSize: 13, marginBottom: 10 }}>
          {[["crontab", "At set times (cron)"], ["interval", "Every N minutes/hours"]].map(([v, l]) => (
            <label key={v} style={{ display: "flex", gap: 6, alignItems: "center" }}>
              <input type="radio" checked={f.schedule_type === v} onChange={() => set("schedule_type", v)} /> {l}
            </label>
          ))}
        </div>
        {f.schedule_type === "crontab" ? (
          <>
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 10 }}>
              {CRON_PRESETS.map(([l, c]) => (
                <button key={l} type="button" className="btn-outline" style={{ fontSize: 11.5, padding: "3px 9px" }} onClick={() => set("crontab", c)}>{l}</button>
              ))}
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))", gap: 10 }}>
              {cronField("minute", "Minute", "0-59, */5")}
              {cronField("hour", "Hour", "0-23, *")}
              {cronField("day_of_month", "Day of month", "1-31, *")}
              {cronField("month_of_year", "Month", "1-12, *")}
              {cronField("day_of_week", "Day of week", "0-6 (0=Sun), 1-5")}
            </div>
          </>
        ) : (
          <div style={{ display: "flex", gap: 10, maxWidth: 360 }}>
            <input style={inputStyle} type="number" min={1} value={f.interval.every} onChange={e => set("interval", { ...f.interval, every: e.target.value })} />
            <select style={inputStyle} value={f.interval.period} onChange={e => set("interval", { ...f.interval, period: e.target.value })}>
              {["seconds", "minutes", "hours", "days"].map(p => <option key={p}>{p}</option>)}
            </select>
          </div>
        )}
      </div>

      <label><span style={labelStyle}>Arguments (JSON)</span>
        <textarea style={{ ...inputStyle, minHeight: 80, fontFamily: "monospace", fontSize: 12.5 }} value={f.kwargs} onChange={e => set("kwargs", e.target.value)} />
      </label>
      <label><span style={labelStyle}>Description</span>
        <input style={inputStyle} value={f.description} onChange={e => set("description", e.target.value)} />
      </label>
      <div style={{ display: "flex", gap: 16, fontSize: 13 }}>
        <label style={{ display: "flex", gap: 6, alignItems: "center" }}><input type="checkbox" checked={f.enabled} onChange={e => set("enabled", e.target.checked)} /> Enabled</label>
        <label style={{ display: "flex", gap: 6, alignItems: "center" }}><input type="checkbox" checked={f.one_off} onChange={e => set("one_off", e.target.checked)} /> Run once, then disable</label>
      </div>
      <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
        <button className="btn-outline" onClick={onClose}>Cancel</button>
        <button className="btn-primary" disabled={busy || !f.label.trim() || !f.task} onClick={save}>{busy ? "Saving…" : "Save job"}</button>
      </div>
    </div>
  );
}

/* ═════════════════════════════════════════════════════════ history */
const STATUS_TONE = { SUCCESS: "ok", FAILURE: "bad", STARTED: "warn", RETRY: "warn", PENDING: "mute", REVOKED: "mute" };

function HistoryTab() {
  const { toastApiError } = useToast();
  const [data, setData] = useState(null);
  const [status, setStatus] = useState("");
  const [open, setOpen] = useState("");
  const [live, setLive] = useState(true);

  const load = useCallback(async () => {
    try { setData(unwrap(await apiClient.get(J.JOBS_HISTORY, { params: { status, limit: 150 } }))); }
    catch (err) { toastApiError(err, "Could not load history."); }
  }, [status, toastApiError]);
  useEffect(() => {
    load();
    if (!live) return undefined;
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, [load, live]);

  if (!data) return <div className="card" style={{ padding: 30, textAlign: "center", color: "var(--color-text-muted)" }}>Loading…</div>;
  const counts = data.last_24h || {};

  return (
    <>
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginBottom: 12 }}>
        <span style={{ fontSize: 12.5, color: "var(--color-text-muted)" }}>Last 24h:</span>
        {["", "SUCCESS", "FAILURE", "STARTED"].map(s => (
          <button key={s || "all"} className={status === s ? "btn-primary" : "btn-outline"} style={{ fontSize: 12, padding: "4px 10px" }} onClick={() => setStatus(s)}>
            {s ? `${s.toLowerCase()} ${counts[s] || 0}` : `all ${Object.values(counts).reduce((a, b) => a + b, 0)}`}
          </button>
        ))}
        <span style={{ flex: 1 }} />
        <label style={{ fontSize: 12.5, display: "flex", gap: 5, alignItems: "center" }}>
          <input type="checkbox" checked={live} onChange={e => setLive(e.target.checked)} /> Auto-refresh
        </label>
      </div>
      <div className="card" style={{ padding: 0, overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12.5 }}>
          <thead><tr style={{ color: "var(--color-text-muted)", fontSize: 12 }}>
            <th style={th}>When</th><th style={th}>Task</th><th style={th}>Job</th><th style={th}>Status</th><th style={th}>Took</th><th style={th}>Worker</th>
          </tr></thead>
          <tbody>
            {data.results.length === 0 && (
              <tr><td style={{ ...td, color: "var(--color-text-muted)" }} colSpan={6}>No runs yet.</td></tr>
            )}
            {data.results.map(r => (
              <FragmentRow key={r.task_id} r={r} open={open === r.task_id} onToggle={() => setOpen(open === r.task_id ? "" : r.task_id)} />
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function FragmentRow({ r, open, onToggle }) {
  return (
    <>
      <tr style={{ borderTop: "1px solid var(--color-border)", cursor: "pointer" }} onClick={onToggle}>
        <td style={{ ...td, whiteSpace: "nowrap" }}>{fmtTime(r.date_created)}</td>
        <td style={td}><code style={{ fontSize: 12 }}>{r.task_name || "—"}</code></td>
        <td style={td}>{r.periodic_task_name || <span style={{ color: "var(--color-text-muted)" }}>manual / upload</span>}</td>
        <td style={td}><Pill tone={STATUS_TONE[r.status]}>{r.status}</Pill></td>
        <td style={{ ...td, fontVariantNumeric: "tabular-nums" }}>{r.duration_s != null ? `${r.duration_s}s` : "—"}</td>
        <td style={{ ...td, color: "var(--color-text-muted)" }}>{r.worker || "—"}</td>
      </tr>
      {open && (
        <tr><td colSpan={6} style={{ padding: "0 12px 12px" }}>
          <div style={{ fontSize: 12, color: "var(--color-text-muted)", margin: "4px 0" }}>Arguments: <code>{r.task_kwargs || "{}"}</code> · id {r.task_id}</div>
          <pre style={{ margin: 0, maxHeight: 260, overflow: "auto", fontSize: 11.5, padding: 10, borderRadius: 8, background: "#0f1714", color: r.traceback ? "#f3b4ab" : "#d6e4dc", whiteSpace: "pre-wrap" }}>
            {r.traceback || r.result || "(no output)"}
          </pre>
        </td></tr>
      )}
    </>
  );
}
