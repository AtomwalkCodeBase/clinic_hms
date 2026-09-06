/**
 * components/history/VisitHistoryView.jsx
 * ------------------------------------------
 * Shared searchable visit-history table, used by the doctor, nurse, and
 * front-desk "History" pages. Not date-limited to today — search by patient
 * name / UHID / AWPID, optionally narrowed to a date range.
 *
 * Doctors see only their own past patients (same scoping as their live
 * queue); front desk and nurse see the whole hospital. That scoping is
 * enforced server-side in AppointmentHistoryView — this component just
 * renders whatever the backend returns.
 *
 * Props:
 *   role           — "doctor" | "nurse" | "front-desk" — controls the Action column.
 *   initialPatient — optional pre-fill for the patient search box (e.g. when
 *                    arriving here from "View" on the Patients page, jumping
 *                    straight to one patient's visit history).
 */
import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { FolderOpen, Filter, Search, X, FileText, Download } from "lucide-react";
import apiClient      from "../../services/api.client";
import API_ENDPOINTS  from "../../config/api.config";
import { ROUTES }     from "../../config/routes.config";
import { openDataUrlInNewTab, downloadFile } from "../../utils/fileViewer";
import DependentBadge from "../common/DependentBadge";

const BADGE = {
  scheduled:   "badge--primary",
  waiting:     "badge--warning",
  vitals_done: "badge--success",
  in_progress: "badge--info",
  done:        "badge--success",
  cancelled:   "badge--error",
  no_show:     "badge--neutral",
};

export default function VisitHistoryView({ role, initialPatient = "" }) {
  const navigate = useNavigate();
  const [patient,   setPatient]   = useState(initialPatient);
  const [dateFrom,  setDateFrom]  = useState("");
  const [dateTo,    setDateTo]    = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [showFilters,  setShowFilters]  = useState(!!(initialPatient));
  const [page,      setPage]      = useState(1);
  const [rows,       setRows]       = useState([]);
  const [pagination, setPagination] = useState(null);
  const [loading,    setLoading]    = useState(true);

  const fetchHistory = useCallback(async (targetPage) => {
    setLoading(true);
    try {
      const params = { page: targetPage, page_size: 20 };
      if (patient)  params.patient   = patient;
      if (dateFrom) params.date_from = dateFrom;
      if (dateTo)   params.date_to   = dateTo;
      if (statusFilter) params.status = statusFilter;
      const { data } = await apiClient.get(API_ENDPOINTS.OPD.HISTORY, { params });
      setRows(data?.results || []);
      setPagination(data?.pagination || null);
    } catch {
      setRows([]);
      setPagination(null);
    } finally {
      setLoading(false);
    }
  }, [patient, dateFrom, dateTo, statusFilter]);

  // Reset to page 1 whenever a filter changes (debounced for the text search).
  useEffect(() => {
    const t = setTimeout(() => { setPage(1); fetchHistory(1); }, 350);
    return () => clearTimeout(t);
  }, [patient, dateFrom, dateTo, statusFilter, fetchHistory]);

  useEffect(() => {
    if (page !== 1) fetchHistory(page);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page]);

  function clearFilters() {
    setPatient(""); setDateFrom(""); setDateTo(""); setStatusFilter("");
  }

  // Open a stored PDF SharedDocument in a new tab.
  // window.open() must be synchronous in the click handler or the popup is
  // blocked; the tab is pointed at the file once it loads. Responses are
  // enveloped { success, data: {...} } — unwrap one level.
  async function openDoc(docId) {
    const win = window.open("", "_blank");
    try {
      const res = await apiClient.get(API_ENDPOINTS.PATIENTS.DOCUMENT(docId));
      const doc = res.data?.data || res.data;
      if (doc?.file_data) openDataUrlInNewTab(win, doc.file_data);
      else if (win) win.close();
    } catch (err) {
      if (win) win.close();
      window.alert(err?.message || err?.data?.message || "Could not open the document.");
    }
  }

  // Save a stored PDF to disk (browser "Save As"). ?download=1 makes the
  // backend hand back an attachment-disposition URL / data URI.
  async function downloadDoc(docId) {
    try {
      const res = await apiClient.get(API_ENDPOINTS.PATIENTS.DOCUMENT(docId), { params: { download: 1 } });
      const doc = res.data?.data || res.data;
      if (doc?.file_data) downloadFile(doc.file_data, doc.file_name || "document.pdf");
      else window.alert("Could not download the document.");
    } catch (err) {
      window.alert(err?.message || err?.data?.message || "Could not download the document.");
    }
  }

  // label + [View] [Save] for one stored PDF.
  const miniBtn = {
    display: "inline-flex", alignItems: "center", gap: 3, fontWeight: 700,
    padding: "2px 6px", borderRadius: 5, cursor: "pointer", fontSize: 10,
    border: "1px solid var(--color-primary)", color: "var(--color-primary)",
    background: "var(--color-primary-light)",
  };
  const docActions = (docId, tag) => (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
      {tag && <span style={{ color: "var(--color-text-muted)" }}>({tag})</span>}
      <button type="button" style={miniBtn} onClick={() => openDoc(docId)}>
        <FileText size={9} /> View
      </button>
      <button type="button" style={miniBtn} onClick={() => downloadDoc(docId)}>
        <Download size={9} /> Save
      </button>
    </span>
  );

  const hasFilters = !!(patient || dateFrom || dateTo || statusFilter);

  return (
    <div>
      {/* Search + filters */}
      <div className="card" style={{ padding: 14, marginBottom: 20 }}>
        <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
          <div style={{ position: "relative", flex: "1 1 260px" }}>
            <Search size={15} style={{ position: "absolute", left: 11, top: "50%", transform: "translateY(-50%)", color: "var(--color-text-muted)" }} />
            <input
              value={patient}
              onChange={e => setPatient(e.target.value)}
              placeholder="Search by patient name, UHID, or AWPID…"
              style={{
                width: "100%", boxSizing: "border-box", padding: "10px 14px 10px 34px", borderRadius: 8,
                border: "1.5px solid var(--color-border)", background: "var(--color-surface)", fontSize: 14, outline: "none",
              }}
            />
          </div>
          <button
            type="button"
            className={hasFilters ? "btn-primary" : "btn-outline"}
            style={{ padding: "9px 18px", display: "flex", alignItems: "center", gap: 7, fontWeight: 700 }}
            onClick={() => setShowFilters(v => !v)}
          >
            <Filter size={14} /> Filters{hasFilters ? " •" : ""}
          </button>
        </div>

        {showFilters && (
          <div style={{
            marginTop: 12, paddingTop: 12, borderTop: "1px solid var(--color-border)",
            display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))", gap: 10,
          }}>
            <div>
              <label className="stat-label" style={{ display: "block", marginBottom: 5 }}>From date</label>
              <input type="date" className="form-input" value={dateFrom} onChange={e => setDateFrom(e.target.value)} />
            </div>
            <div>
              <label className="stat-label" style={{ display: "block", marginBottom: 5 }}>To date</label>
              <input type="date" className="form-input" value={dateTo} min={dateFrom} onChange={e => setDateTo(e.target.value)} />
            </div>
            <div>
              <label className="stat-label" style={{ display: "block", marginBottom: 5 }}>Status</label>
              <select className="form-input" style={{ appearance: "auto" }} value={statusFilter} onChange={e => setStatusFilter(e.target.value)}>
                <option value="">Any status</option>
                <option value="scheduled">Scheduled</option>
                <option value="waiting">Waiting</option>
                <option value="vitals_done">Vitals Done</option>
                <option value="in_progress">In Progress</option>
                <option value="done">Done</option>
                <option value="cancelled">Cancelled</option>
                <option value="no_show">No Show</option>
              </select>
            </div>
            {hasFilters && (
              <div style={{ display: "flex", alignItems: "flex-end" }}>
                <button className="btn-outline" style={{ fontSize: 12, padding: "8px 14px", display: "flex", alignItems: "center", gap: 5 }} onClick={clearFilters}>
                  <X size={13} /> Clear
                </button>
              </div>
            )}
          </div>
        )}
      </div>

      {loading ? (
        <div style={{ textAlign: "center", padding: 60, color: "var(--color-text-muted)" }}>Loading…</div>
      ) : rows.length === 0 ? (
        <div className="card" style={{ textAlign: "center", padding: 60 }}>
          <FolderOpen size={40} style={{ color: "var(--color-text-muted)", marginBottom: 12 }} />
          <div style={{ fontWeight: 600, marginBottom: 8 }}>
            {hasFilters ? "No visits match your search" : "No visit history yet"}
          </div>
          <div style={{ color: "var(--color-text-muted)" }}>
            {hasFilters ? "Try a different name, UHID, or date range." : "Past visits will appear here once patients are seen."}
          </div>
        </div>
      ) : (
        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          <table className="data-table">
            <thead>
              <tr>
                <th style={{ width: 70 }}>Token</th>
                <th>Patient</th>
                <th>Date</th>
                <th>Time</th>
                {role !== "doctor" && <th>Doctor</th>}
                <th>Complaint</th>
                <th>Status</th>
                {role === "doctor" && <th style={{ width: 110 }}>Action</th>}
              </tr>
            </thead>
            <tbody>
              {rows.map(r => (
                <tr key={r.id}>
                  <td>
                    <span style={{
                      display: "inline-flex", alignItems: "center", justifyContent: "center",
                      width: 30, height: 30, borderRadius: 8,
                      background: "var(--color-primary-light)", color: "var(--color-primary)",
                      fontWeight: 800, fontSize: 12,
                    }}>{r.token_number ?? "—"}</span>
                  </td>
                  <td>
                    <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                      <div style={{ fontWeight: 600, fontSize: 13 }}>{r.patient_name || "—"}</div>
                      <DependentBadge patient={r} />
                    </div>
                    <div style={{ fontSize: 11, color: "var(--color-text-muted)" }}>{r.patient_uhid || ""}</div>
                    {r.has_encounter && (
                      <div style={{ marginTop: 4, display: "flex", flexDirection: "column", gap: 4, fontSize: 10 }}>
                        {(r.prescription_doc_id || r.handwritten_prescription_doc_id) ? (
                          <div style={{ display: "flex", alignItems: "center", gap: 5, flexWrap: "wrap" }}>
                            <span style={{ fontWeight: 700, color: "var(--color-text-secondary)" }}>Prescription:</span>
                            {r.prescription_doc_id && docActions(r.prescription_doc_id)}
                            {r.handwritten_prescription_doc_id && docActions(r.handwritten_prescription_doc_id, "handwritten")}
                          </div>
                        ) : (
                          <span style={{ color: "var(--color-text-muted)" }}>
                            {r.has_prescription ? "Prescription (no PDF)" : "No prescription issued"}
                          </span>
                        )}
                        {r.internal_note_doc_id ? (
                          <div style={{ display: "flex", alignItems: "center", gap: 5, flexWrap: "wrap" }}>
                            <span style={{ fontWeight: 700, color: "var(--color-text-secondary)" }}>Internal note:</span>
                            {docActions(r.internal_note_doc_id)}
                          </div>
                        ) : (
                          <span style={{ color: r.has_internal_note ? "var(--color-text-secondary)" : "var(--color-text-muted)" }}>
                            {r.has_internal_note ? "Internal note recorded" : "No internal note recorded"}
                          </span>
                        )}
                      </div>
                    )}
                  </td>
                  <td style={{ fontSize: 12 }}>{r.scheduled_date}</td>
                  <td style={{ fontSize: 12 }}>{r.scheduled_time ? r.scheduled_time.slice(0, 5) : "—"}</td>
                  {role !== "doctor" && <td style={{ fontSize: 12 }}>{r.doctor_name || "—"}</td>}
                  <td style={{ fontSize: 12, maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {r.chief_complaint || <span style={{ color: "var(--color-text-muted)" }}>—</span>}
                  </td>
                  <td>
                    <span className={`badge ${BADGE[r.status] || "badge--neutral"}`}>
                      {r.status?.replace("_", " ")}
                    </span>
                  </td>
                  {role === "doctor" && (
                    <td>
                      {r.has_encounter ? (
                        <button className="btn-outline" style={{ fontSize: 11, padding: "5px 12px" }}
                          onClick={() => navigate(ROUTES.DOCTOR.ENCOUNTER(r.encounter.id))}>
                          View notes
                        </button>
                      ) : (
                        <span style={{ fontSize: 11, color: "var(--color-text-muted)" }}>—</span>
                      )}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>

          {pagination && pagination.total_pages > 1 && (
            <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 16, padding: "16px 20px", borderTop: "1px solid var(--color-border)" }}>
              <button className="btn-outline" style={{ fontSize: 12, padding: "6px 14px" }}
                disabled={!pagination.has_previous}
                onClick={() => setPage(p => Math.max(1, p - 1))}>
                ← Previous
              </button>
              <span style={{ fontSize: 12, color: "var(--color-text-muted)" }}>
                Page {pagination.page} of {pagination.total_pages} · {pagination.total_count} visits
              </span>
              <button className="btn-outline" style={{ fontSize: 12, padding: "6px 14px" }}
                disabled={!pagination.has_next}
                onClick={() => setPage(p => Math.min(pagination.total_pages, p + 1))}>
                Next →
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
