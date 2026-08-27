/**
 * pages/lab/ReportsPage.jsx
 * ---------------------------
 * Read-only list of delivered in-house reports — a record of what's already
 * gone out. Upload/deliver happens on the Requests page; this is just the
 * "released" view.
 */
import { useState, useMemo } from "react";
import { AppShell }  from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import { useApi }    from "../../hooks/useApi";
import API_ENDPOINTS from "../../config/api.config";
import { dataUrlToBlob } from "../../utils/fileViewer";

export default function ReportsPage() {
  const { data, isLoading } = useApi(API_ENDPOINTS.LAB.REQUESTS, { params: { status: "completed", page_size: 100 } });
  const reports = (data?.results || []).filter(o => o.report?.status === "delivered");

  const [search, setSearch] = useState("");
  const filteredReports = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return reports;
    return reports.filter(o =>
      o.patient_name?.toLowerCase().includes(q) ||
      o.patient_uhid?.toLowerCase().includes(q) ||
      o.test_name?.toLowerCase().includes(q)
    );
  }, [reports, search]);

  return (
    <AppShell>
      <PageShell title="Released Results">
        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "14px 20px", borderBottom: "1px solid var(--color-border)" }}>
            <span className="dot-label dot-label--green">Delivered reports</span>
            <input className="form-input" placeholder="Search patient, UHID, or test…"
              value={search} onChange={e => setSearch(e.target.value)} style={{ maxWidth: 260 }} />
          </div>
          {isLoading ? (
            <div style={{ padding: 40, textAlign: "center", color: "var(--color-text-muted)" }}>Loading…</div>
          ) : filteredReports.length === 0 ? (
            <div style={{ padding: 48, textAlign: "center", color: "var(--color-text-muted)" }}>
              {reports.length === 0 ? "No reports delivered yet." : "No reports match your search."}
            </div>
          ) : (
            <table className="data-table">
              <thead>
                <tr>
                  <th>Patient</th>
                  <th>Test</th>
                  <th>Summary</th>
                  <th>Delivered</th>
                  <th style={{ width: 100 }}>File</th>
                </tr>
              </thead>
              <tbody>
                {filteredReports.map(o => (
                  <tr key={o.id}>
                    <td>
                      <div style={{ fontWeight: 600, fontSize: 13 }}>{o.patient_name}</div>
                      <div style={{ fontSize: 11, color: "var(--color-text-muted)" }}>{o.patient_uhid}</div>
                    </td>
                    <td style={{ fontSize: 13 }}>{o.test_name}</td>
                    <td style={{ fontSize: 12, color: "var(--color-text-secondary)", maxWidth: 320 }}>
                      {o.report?.result_summary || "—"}
                    </td>
                    <td style={{ fontSize: 12 }}>
                      {o.report?.delivered_at ? new Date(o.report.delivered_at).toLocaleDateString("en-IN") : "—"}
                    </td>
                    <td>
                      {o.report?.file_data ? (
                        <button type="button"
                          onClick={() => {
                            const url = URL.createObjectURL(dataUrlToBlob(o.report.file_data));
                            window.open(url, "_blank");
                            setTimeout(() => URL.revokeObjectURL(url), 60000);
                          }}
                          className="btn-outline" style={{ fontSize: 11, padding: "4px 10px" }}>
                          View
                        </button>
                      ) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </PageShell>
    </AppShell>
  );
}
