/**
 * pages/platform-admin/ClassificationRulesPage.jsx
 * ------------------------------------------------
 * Platform admin: how uploaded documents were classified (apps/records) — every document with its type, who decided
 * it (the rule engine or a person), its score and its status; a person can correct a type here, and "Re-run" applies
 * today's rules to documents already read.
 *
 * The document types and their keywords are no longer edited on a screen: they are fixed in code
 * (apps/records/classification.py), so changing a keyword is a code change.
 *
 * Backend (apps/platform_admin/classification_rule_views.py):
 *   GET /platform/records/report/   PATCH /platform/records/report/<id>/   POST /platform/records/reclassify/
 */
import { useCallback, useEffect, useState } from "react";
import { AppShell } from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import apiClient from "../../services/api.client";
import { useToast } from "../../hooks/useToast";
import API_ENDPOINTS from "../../config/api.config";
import { adminInputStyle as inputStyle } from "../../styles/formStyles";


const cellStyle = { padding: "6px 8px", textAlign: "left" };
const NOT_CLASSIFIED = "not_classified";

export default function ClassificationRulesPage() {
  const { toastSuccess, toastApiError } = useToast();
  const [busy, setBusy] = useState(false);
  const [report, setReport] = useState(null);
  const [reportFilters, setReportFilters] = useState({ method: "", status: "", page: 1 });
  const [rerunSummary, setRerunSummary] = useState("");

  const loadReport = useCallback(async () => {
    try {
      const { method, status, page } = reportFilters;
      const res = await apiClient.get(API_ENDPOINTS.PLATFORM.RECORDS_REPORT, { params: { method, status, page } });
      setReport(res.data?.data || res.data);
    } catch (err) { toastApiError(err, "Could not load the report."); }
  }, [reportFilters, toastApiError]);
  useEffect(() => { loadReport(); }, [loadReport]);

  async function run(fn, done) {
    setBusy(true);
    try { await fn(); toastSuccess(done); }
    catch (err) { toastApiError(err, "Could not save."); }
    finally { setBusy(false); }
  }
  const correctDoc = (id, doc_type) => run(async () => {
    await apiClient.patch(API_ENDPOINTS.PLATFORM.RECORDS_REPORT_ITEM(id), { doc_type });
    await loadReport();
  }, "Corrected.");
  const rerun = () => run(async () => {
    const res = await apiClient.post(API_ENDPOINTS.PLATFORM.RECORDS_RECLASSIFY);
    const c = res.data?.data || res.data;
    setRerunSummary(`Checked ${c.checked}: ${c.changed} changed — ${c.classified} now have a type, ${c.unclassified} could not be classified.`);
    await loadReport();
  }, "Done.");

  return (
    <AppShell>
      <PageShell title="Document classification">
        <p style={{ fontSize: 13, color: "var(--color-text-muted)", marginTop: 0 }}>
          Each uploaded document is read and scored against the fixed document types. A clear winner is filed under its type;
          if none wins clearly the document is <b>not classified</b> and needs a person (it shows as &ldquo;review required&rdquo;).
          The types and keywords are set in code, not on this screen.
        </p>

        <div className="card" style={{ padding: 14, marginTop: 16 }}>
          <b style={{ display: "block", marginBottom: 4 }}>Apply to documents already read</b>
          <p style={{ fontSize: 12.5, color: "var(--color-text-muted)", margin: "0 0 8px" }}>
            After the rules change in a release, judge the documents again using the text already read (no re-reading of files).
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
              <option value="staff">Staff (corrected or issued)</option>
            </select>
            <select style={inputStyle} value={reportFilters.status}
              onChange={e => setReportFilters(f => ({ ...f, status: e.target.value, page: 1 }))}>
              <option value="">All statuses</option>
              <option value="completed">Completed</option>
              <option value="review_required">Review required</option>
              <option value="failed">Failed</option>
              <option value="queued">Queued</option>
              <option value="extracting">Extracting</option>
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
                          {d.doc_type === NOT_CLASSIFIED && (
                            <option value={NOT_CLASSIFIED} disabled>
                              Not classified{d.best_guess ? ` — closest: ${d.best_guess}` : ""}
                            </option>
                          )}
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
