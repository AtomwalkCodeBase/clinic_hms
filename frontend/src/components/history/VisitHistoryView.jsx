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
import apiClient      from "../../services/api.client";
import API_ENDPOINTS  from "../../config/api.config";
import { ROUTES }     from "../../config/routes.config";
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
      const { data } = await apiClient.get(API_ENDPOINTS.OPD.HISTORY, { params });
      setRows(data?.results || []);
      setPagination(data?.pagination || null);
    } catch {
      setRows([]);
      setPagination(null);
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [patient, dateFrom, dateTo]);

  // Reset to page 1 whenever a filter changes (debounced for the text search).
  useEffect(() => {
    const t = setTimeout(() => { setPage(1); fetchHistory(1); }, 350);
    return () => clearTimeout(t);
  }, [patient, dateFrom, dateTo, fetchHistory]);

  useEffect(() => {
    if (page !== 1) fetchHistory(page);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page]);

  function clearFilters() {
    setPatient(""); setDateFrom(""); setDateTo("");
  }

  const hasFilters = !!(patient || dateFrom || dateTo);

  return (
    <div>
      {/* Filters */}
      <div style={{ display: "flex", gap: 12, marginBottom: 20, flexWrap: "wrap", alignItems: "center" }}>
        <input
          value={patient}
          onChange={e => setPatient(e.target.value)}
          placeholder="Search by patient name, UHID, or AWPID…"
          style={{ flex: 1, minWidth: 240, padding: "9px 14px", borderRadius: 8, border: "1.5px solid var(--color-border)", background: "var(--color-surface)", fontSize: 14, outline: "none" }}
        />
        <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: "var(--color-text-muted)" }}>
          From
          <input type="date" value={dateFrom} onChange={e => setDateFrom(e.target.value)}
            style={{ padding: "8px 10px", borderRadius: 8, border: "1.5px solid var(--color-border)", background: "var(--color-surface)", fontSize: 13 }} />
        </label>
        <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: "var(--color-text-muted)" }}>
          To
          <input type="date" value={dateTo} onChange={e => setDateTo(e.target.value)}
            style={{ padding: "8px 10px", borderRadius: 8, border: "1.5px solid var(--color-border)", background: "var(--color-surface)", fontSize: 13 }} />
        </label>
        {hasFilters && (
          <button className="btn-outline" style={{ fontSize: 12, padding: "8px 14px" }} onClick={clearFilters}>
            Clear
          </button>
        )}
      </div>

      {loading ? (
        <div style={{ textAlign: "center", padding: 60, color: "var(--color-text-muted)" }}>Loading…</div>
      ) : rows.length === 0 ? (
        <div className="card" style={{ textAlign: "center", padding: 60 }}>
          <div style={{ fontSize: 40, marginBottom: 12 }}>🗂️</div>
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
