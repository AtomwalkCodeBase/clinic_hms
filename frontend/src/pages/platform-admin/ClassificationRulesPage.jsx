/**
 * pages/platform-admin/ClassificationRulesPage.jsx
 * ------------------------------------------------
 * Platform admin: the keyword rules that classify uploaded documents
 * (apps/records). One rule per document type; keywords are pipe-separated,
 * e.g. laboratory|hemoglobin|glucose|reference range.
 *
 * The same rules drive the keyword score AND the Ollama prompt (used when the
 * score is under 75). Changes apply to the next document — no restart.
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

const inputStyle = {
  width: "100%", boxSizing: "border-box", border: "1.5px solid var(--color-border)", borderRadius: 8,
  padding: "8px 10px", fontSize: 13.5, background: "var(--color-surface)", color: "var(--color-text)", outline: "none",
};
const cellStyle = { padding: "6px 8px", textAlign: "left" };
const count = (keywords) => keywords.split("|").filter(k => k.trim()).length;

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

  return (
    <AppShell>
      <PageShell title="Classification rules">
        <p style={{ fontSize: 13, color: "var(--color-text-muted)", marginTop: 0 }}>
          Score = share of a type&rsquo;s keywords found on the page. 75 or more files it by these rules;
          under 75 the page and these same rules go to the AI (Ollama). Separate keywords with <code>|</code>.
        </p>

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
          <textarea rows={2} style={inputStyle} placeholder="Keywords, e.g. vaccine|dose|immunization"
            value={draft.keywords} onChange={e => setDraft(d => ({ ...d, keywords: e.target.value }))} />
          <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 8 }}>
            <button className="btn-primary" disabled={busy || !draft.doc_type.trim() || !draft.keywords.trim()} onClick={add}>Add rule</button>
          </div>
        </div>

        <div className="card" style={{ padding: 14, marginTop: 16 }}>
          <b style={{ display: "block", marginBottom: 8 }}>Upload sweep settings</b>
          {sweep && (
            <>
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
          <b style={{ display: "block", marginBottom: 8 }}>Classification results</b>
          <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
            <select style={inputStyle} value={reportFilters.method}
              onChange={e => setReportFilters(f => ({ ...f, method: e.target.value, page: 1 }))}>
              <option value="">All sources</option>
              <option value="rule">Rule</option>
              <option value="llm">LLM</option>
              <option value="staff">Staff (corrected)</option>
            </select>
            <select style={inputStyle} value={reportFilters.status}
              onChange={e => setReportFilters(f => ({ ...f, status: e.target.value, page: 1 }))}>
              <option value="">All statuses</option>
              <option value="completed">Completed</option>
              <option value="failed">Failed</option>
              <option value="queued">Queued</option>
              <option value="ocr">OCR</option>
              <option value="classifying">Classifying</option>
            </select>
          </div>
          {!report ? <p style={{ color: "var(--color-text-muted)" }}>Loading…</p> : (
            <>
              <table style={{ width: "100%", fontSize: 13, borderCollapse: "collapse" }}>
                <thead><tr style={{ color: "var(--color-text-muted)" }}>
                  <th style={cellStyle}>Title</th><th style={cellStyle}>Type</th><th style={cellStyle}>Source</th>
                  <th style={cellStyle}>Score</th><th style={cellStyle}>Status</th><th style={cellStyle}>Uploaded</th>
                </tr></thead>
                <tbody>
                  {report.results.map(d => (
                    <tr key={d.id} style={{ borderTop: "1px solid var(--color-border)" }}>
                      <td style={cellStyle}>{d.title}</td>
                      <td style={cellStyle}>
                        <select style={{ ...inputStyle, padding: "2px 4px" }} value={d.doc_type} disabled={busy}
                          onChange={e => correctDoc(d.id, e.target.value)}>
                          {report.doc_types.map(t => <option key={t} value={t}>{t}</option>)}
                        </select>
                      </td>
                      <td style={cellStyle}>{d.method || "—"}</td>
                      <td style={cellStyle}>{d.score ?? "—"}</td>
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
