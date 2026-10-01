/**
 * pages/platform-admin/ClassificationRulesPage.jsx
 * ------------------------------------------------
 * Platform admin: the keyword rules that classify uploaded documents
 * (apps/records). One rule per document type; keywords are pipe-separated,
 * e.g. laboratory|hemoglobin|glucose|reference range.
 *
 * A document's confidence is how much of a type's keywords it contains AND how clearly that type beats the
 * others (apps/records/scoring.py). Changes apply to the next document — no restart; "Re-run" applies them to
 * documents already read.
 *
 * Backend (apps/platform_admin/classification_rule_views.py):
 *   GET/POST /platform/classification-rules/   PATCH/DELETE /platform/classification-rules/<id>/
 */
import { useCallback, useEffect, useState } from "react";
import { AppShell } from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import apiClient from "../../services/api.client";
import { useToast } from "../../hooks/useToast";
import API_ENDPOINTS from "../../config/api.config";
import { adminInputStyle as inputStyle } from "../../styles/formStyles";


const cellStyle = { padding: "6px 8px", textAlign: "left" };
const count = (keywords) => keywords.split("|").filter(k => k.trim() && !k.trim().startsWith("-")).length;

export default function ClassificationRulesPage() {
  const { toastSuccess, toastApiError } = useToast();
  const [rules, setRules] = useState(null);
  const [edits, setEdits] = useState({});                       // id -> {keywords?, is_active?}
  const [draft, setDraft] = useState({ doc_type: "", keywords: "" });
  const [busy, setBusy] = useState(false);

  const [sweep, setSweep] = useState(null);
  const [sweepEdits, setSweepEdits] = useState({});
  const [report, setReport] = useState(null);
  const [reportFilters, setReportFilters] = useState({ method: "", status: "", page: 1 });

  const load = useCallback(async () => {
    try {
      const res = await apiClient.get(API_ENDPOINTS.PLATFORM.CLASSIFICATION_RULES);
      setRules(res.data?.data || res.data || []);
      setEdits({});
    } catch (err) { toastApiError(err, "Could not load the rules."); setRules([]); }
  }, [toastApiError]);
  useEffect(() => { load(); }, [load]);

  const loadSweep = useCallback(async () => {
    try {
      const res = await apiClient.get(API_ENDPOINTS.PLATFORM.RECORDS_SWEEP_CONFIG);
      setSweep(res.data?.data || res.data);
      setSweepEdits({});
    } catch (err) { toastApiError(err, "Could not load the sweep settings."); }
  }, [toastApiError]);
  useEffect(() => { loadSweep(); }, [loadSweep]);

  const loadReport = useCallback(async () => {
    try {
      const { method, status, page } = reportFilters;
      const res = await apiClient.get(API_ENDPOINTS.PLATFORM.RECORDS_REPORT, { params: { method, status, page } });
      setReport(res.data?.data || res.data);
    } catch (err) { toastApiError(err, "Could not load the report."); }
  }, [reportFilters, toastApiError]);
  useEffect(() => { loadReport(); }, [loadReport]);

  const edit = (id, field, value) => setEdits(e => ({ ...e, [id]: { ...e[id], [field]: value } }));

  async function run(fn, done) {
    setBusy(true);
    try { await fn(); toastSuccess(done); await load(); }
    catch (err) { toastApiError(err, "Could not save."); }
    finally { setBusy(false); }
  }
  const save = (r) => run(() => apiClient.patch(API_ENDPOINTS.PLATFORM.CLASSIFICATION_RULE(r.id), edits[r.id]), "Saved — applies to the next upload.");
  const remove = (r) => window.confirm(`Delete the ${r.doc_type} rule?`)
    && run(() => apiClient.delete(API_ENDPOINTS.PLATFORM.CLASSIFICATION_RULE(r.id)), "Rule deleted.");
  const add = () => run(async () => {
    await apiClient.post(API_ENDPOINTS.PLATFORM.CLASSIFICATION_RULES, draft);
    setDraft({ doc_type: "", keywords: "" });
  }, "Rule added.");

  const saveSweep = () => run(async () => {
    await apiClient.patch(API_ENDPOINTS.PLATFORM.RECORDS_SWEEP_CONFIG, sweepEdits);
    await loadSweep();
  }, "Saved.");
  const correctDoc = (id, doc_type) => run(async () => {
    await apiClient.patch(API_ENDPOINTS.PLATFORM.RECORDS_REPORT_ITEM(id), { doc_type });
    await loadReport();
  }, "Corrected.");
  const [rerunSummary, setRerunSummary] = useState("");
  const rerun = () => run(async () => {
    const res = await apiClient.post(API_ENDPOINTS.PLATFORM.RECORDS_RECLASSIFY);
    const c = res.data?.data || res.data;
    setRerunSummary(`Checked ${c.checked}: ${c.changed} changed — ${c.classified} now have a type, ${c.unclassified} could not be classified.`);
    await loadReport();
  }, "Done.");

  return (
    <AppShell>
      <PageShell title="Classification rules">
        <p style={{ fontSize: 13, color: "var(--color-text-muted)", marginTop: 0 }}>
          Each document is compared with the types below and gets a <b>confidence</b> from 0 to 100: how many of a type&rsquo;s
          keywords it contains, and how clearly that type beats the next one. If the best type reaches the confidence
          bar (set further down) the document is filed under it; if none does it is left as <b>unable to classify</b>
          and the person can choose.
        </p>
        <div className="card" style={{ padding: "10px 13px", marginBottom: 12, fontSize: 12.5, lineHeight: 1.6 }}>
          <b>Writing keywords</b> — separate them with <code>|</code>, whole words and phrases, any case.
          Add <code>^3</code> to make a strong phrase count three times (<code>laboratory report^3</code>).
          Start a word with <code>-</code> to rule the type out when it appears (<code>-discharge summary</code>).
          A short, distinctive list of 10–30 works better than a long one.
        </div>

        {rules === null ? (
          <div className="card" style={{ padding: 24, textAlign: "center", color: "var(--color-text-muted)" }}>Loading…</div>
        ) : (
          rules.map(r => {
            const v = { ...r, ...edits[r.id] };
            return (
              <div key={r.id} className="card" style={{ padding: 14, marginBottom: 10, opacity: v.is_active ? 1 : 0.6 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
                  <b style={{ flex: 1, fontFamily: "var(--font-mono, monospace)" }}>{r.doc_type}</b>
                  <span style={{ fontSize: 12, color: "var(--color-text-muted)" }}>{count(v.keywords)} keywords</span>
                  <label style={{ fontSize: 13, display: "flex", alignItems: "center", gap: 5 }}>
                    <input type="checkbox" checked={v.is_active} onChange={e => edit(r.id, "is_active", e.target.checked)} /> Active
                  </label>
                </div>
                <textarea rows={2} style={inputStyle} value={v.keywords} onChange={e => edit(r.id, "keywords", e.target.value)} />
                <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 8 }}>
                  <button className="btn-outline" style={{ color: "var(--color-danger)" }} disabled={busy} onClick={() => remove(r)}>Delete</button>
                  <button className="btn-primary" disabled={busy || !edits[r.id]} onClick={() => save(r)}>Save</button>
                </div>
              </div>
            );
          })
        )}

        <div className="card" style={{ padding: 14, marginTop: 16 }}>
          <b style={{ display: "block", marginBottom: 8 }}>Add a document type</b>
          <input style={{ ...inputStyle, marginBottom: 8 }} placeholder="Type, e.g. vaccination_card"
            value={draft.doc_type} onChange={e => setDraft(d => ({ ...d, doc_type: e.target.value }))} />
          <textarea rows={2} style={inputStyle} placeholder="Keywords, e.g. vaccination card^3|vaccine|dose|-prescription"
            value={draft.keywords} onChange={e => setDraft(d => ({ ...d, keywords: e.target.value }))} />
          <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 8 }}>
            <button className="btn-primary" disabled={busy || !draft.doc_type.trim() || !draft.keywords.trim()} onClick={add}>Add rule</button>
          </div>
        </div>

        <div className="card" style={{ padding: 14, marginTop: 16 }}>
          <b style={{ display: "block", marginBottom: 8 }}>Settings</b>
          {sweep && (
            <>
              <label style={{ fontSize: 13, display: "block", marginBottom: 8 }}>
                Confidence bar (1–100) — the best type is filed only at or above this; below it the document is &ldquo;unable to classify&rdquo;
                <input type="number" min={1} max={100} style={inputStyle}
                  value={sweepEdits.min_confidence ?? sweep.min_confidence}
                  onChange={e => setSweepEdits(s => ({ ...s, min_confidence: e.target.value }))} />
              </label>
              <label style={{ fontSize: 13, display: "block", marginBottom: 8 }}>
                Evidence scale (1–100) — how many keyword hits count as plenty. Lower files more documents with fewer hits; higher is stricter
                <input type="number" min={1} max={100} style={inputStyle}
                  value={sweepEdits.evidence_scale ?? sweep.evidence_scale}
                  onChange={e => setSweepEdits(s => ({ ...s, evidence_scale: e.target.value }))} />
              </label>
              <label style={{ fontSize: 13, display: "block", marginBottom: 8 }}>
                Instant-upload limit (files sent right away; a larger batch is queued)
                <input type="number" min={1} style={inputStyle}
                  value={sweepEdits.instant_max_files ?? sweep.instant_max_files}
                  onChange={e => setSweepEdits(s => ({ ...s, instant_max_files: e.target.value }))} />
              </label>
              <label style={{ fontSize: 13, display: "block", marginBottom: 8 }}>
                Sweep dispatch limit (queued documents sent per run)
                <input type="number" min={1} style={inputStyle}
                  value={sweepEdits.sweep_dispatch_limit ?? sweep.sweep_dispatch_limit}
                  onChange={e => setSweepEdits(s => ({ ...s, sweep_dispatch_limit: e.target.value }))} />
              </label>
              <label style={{ fontSize: 13, display: "block" }}>
                Sweep interval (seconds between runs — takes effect immediately, no restart)
                <input type="number" min={1} style={inputStyle}
                  value={sweepEdits.sweep_interval_seconds ?? sweep.sweep_interval_seconds}
                  onChange={e => setSweepEdits(s => ({ ...s, sweep_interval_seconds: e.target.value }))} />
              </label>
              <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 8 }}>
                <button className="btn-primary" disabled={busy || !Object.keys(sweepEdits).length} onClick={saveSweep}>Save</button>
              </div>
            </>
          )}
        </div>

        <div className="card" style={{ padding: 14, marginTop: 16 }}>
          <b style={{ display: "block", marginBottom: 4 }}>Apply to documents already read</b>
          <p style={{ fontSize: 12.5, color: "var(--color-text-muted)", margin: "0 0 8px" }}>
            After changing keywords or settings, judge the documents again using the text already read (no re-reading of files).
            A type a person chose is never changed.
          </p>
          <button className="btn-outline" disabled={busy} onClick={rerun}>Re-run on existing documents</button>
          {rerunSummary && <span style={{ fontSize: 12.5, marginLeft: 10 }}>{rerunSummary}</span>}
        </div>

        <div className="card" style={{ padding: 14, marginTop: 16 }}>
          <b style={{ display: "block", marginBottom: 8 }}>Classification results</b>
          <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
            <select style={inputStyle} value={reportFilters.method}
              onChange={e => setReportFilters(f => ({ ...f, method: e.target.value, page: 1 }))}>
              <option value="">All sources</option>
              <option value="rule">Rule</option>
              <option value="staff">Staff (corrected)</option>
            </select>
            <select style={inputStyle} value={reportFilters.status}
              onChange={e => setReportFilters(f => ({ ...f, status: e.target.value, page: 1 }))}>
              <option value="">All statuses</option>
              <option value="completed">Completed</option>
              <option value="failed">Failed</option>
              <option value="queued">Queued</option>
              <option value="extracting">Extracting</option>
              <option value="rejected">Rejected (duplicate)</option>
              <option value="classifying">Classifying</option>
            </select>
          </div>
          {!report ? <p style={{ color: "var(--color-text-muted)" }}>Loading…</p> : (
            <>
              <table style={{ width: "100%", fontSize: 13, borderCollapse: "collapse" }}>
                <thead><tr style={{ color: "var(--color-text-muted)" }}>
                  <th style={cellStyle}>Title</th><th style={cellStyle}>Type</th><th style={cellStyle}>Source</th>
                  <th style={cellStyle}>Confidence</th><th style={cellStyle}>Status</th><th style={cellStyle}>Uploaded</th>
                </tr></thead>
                <tbody>
                  {report.results.map(d => (
                    <tr key={d.id} style={{ borderTop: "1px solid var(--color-border)" }}>
                      <td style={cellStyle}>{d.title}</td>
                      <td style={cellStyle}>
                        <select style={{ ...inputStyle, padding: "2px 4px" }} value={d.doc_type} disabled={busy}
                          onChange={e => correctDoc(d.id, e.target.value)}>
                          {!d.doc_type && <option value="">Unable to classify{d.best_guess ? ` — closest: ${d.best_guess}` : ""}</option>}
                          {report.doc_types.map(t => <option key={t} value={t}>{t}</option>)}
                        </select>
                      </td>
                      <td style={cellStyle}>{d.method || "—"}</td>
                      <td style={cellStyle}>{d.score != null ? Math.round(d.score) : "—"}</td>
                      <td style={cellStyle}>{d.processing_status}</td>
                      <td style={cellStyle}>{new Date(d.created_at).toLocaleString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div style={{ display: "flex", justifyContent: "space-between", marginTop: 8, fontSize: 12 }}>
                <span>{report.pagination.total_count} document(s)</span>
                <span style={{ display: "flex", gap: 8 }}>
                  <button className="btn-outline" disabled={!report.pagination.has_previous}
                    onClick={() => setReportFilters(f => ({ ...f, page: f.page - 1 }))}>Prev</button>
                  <button className="btn-outline" disabled={!report.pagination.has_next}
                    onClick={() => setReportFilters(f => ({ ...f, page: f.page + 1 }))}>Next</button>
                </span>
              </div>
            </>
          )}
        </div>
      </PageShell>
    </AppShell>
  );
}
