/**
 * pages/front-desk/PatientsPage.jsx
 * ------------------------------------
 * Full, paginated list of every patient registered at this hospital —
 * distinct from AppointmentsPage's typeahead search box, which only ever
 * shows a capped 50 results and is meant for picking one patient to book
 * for, not browsing the whole roster. Front desk needed somewhere to just
 * see everyone, page through them, and jump straight into booking.
 */
import { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { AppShell }  from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import DependentBadge from "../../components/common/DependentBadge";
import PaginationControls from "../../components/common/PaginationControls";
import { useApi }    from "../../hooks/useApi";
import apiClient     from "../../services/api.client";
import API_ENDPOINTS from "../../config/api.config";
import { ROUTES }    from "../../config/routes.config";

export default function FrontDeskPatientsPage() {
  const navigate = useNavigate();
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const debounceRef = useRef(null);

  useEffect(() => {
    clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      setDebouncedQuery(query.trim());
      setPage(1);
    }, 300);
    return () => clearTimeout(debounceRef.current);
  }, [query]);

  const { data, isLoading } = useApi(API_ENDPOINTS.PATIENTS.SEARCH, {
    params: { page, page_size: pageSize, ...(debouncedQuery ? { q: debouncedQuery } : {}) },
  });
  const patients = data?.results || [];
  const pagination = data?.pagination || null;

  return (
    <AppShell>
      <PageShell title="All Patients">
        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          <div style={{
            display: "flex", alignItems: "center", justifyContent: "space-between",
            padding: "14px 20px", borderBottom: "1px solid var(--color-border)", gap: 12,
          }}>
            <span className="dot-label dot-label--green">
              Patients{pagination ? ` (${pagination.total_count})` : ""}
            </span>
            <input
              className="form-input" style={{ maxWidth: 280 }}
              placeholder="Search name / UHID / mobile…"
              value={query} onChange={e => setQuery(e.target.value)}
            />
          </div>

          {isLoading ? (
            <div style={{ padding: 40, textAlign: "center", color: "var(--color-text-muted)" }}>Loading…</div>
          ) : patients.length === 0 ? (
            <div style={{ padding: 48, textAlign: "center", color: "var(--color-text-muted)" }}>
              {debouncedQuery ? `No patients matched "${debouncedQuery}"` : "No patients registered here yet."}
            </div>
          ) : (
            <table className="data-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>UHID</th>
                  <th>Mobile</th>
                  <th>Branch</th>
                  <th style={{ width: 140 }}>Action</th>
                </tr>
              </thead>
              <tbody>
                {patients.map(p => (
                  <tr key={p.uuid || p.id}>
                    <td>
                      <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                        <span style={{ fontWeight: 600, fontSize: 13 }}>{p.full_name}</span>
                        <DependentBadge patient={p} />
                      </div>
                    </td>
                    <td style={{ fontSize: 12, color: "var(--color-text-muted)" }}>{p.uhid || "—"}</td>
                    <td style={{ fontSize: 12 }}>{p.mobile || (p.is_dependent ? "— (dependent)" : "—")}</td>
                    <td style={{ fontSize: 12 }}>{p.branch_name || "—"}</td>
                    <td>
                      <button className="btn-outline" style={{ fontSize: 11, padding: "4px 10px" }}
                        onClick={() => navigate(ROUTES.FRONT_DESK.APPOINTMENTS, { state: { patient: p } })}>
                        Book Appointment
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          <PaginationControls
            pagination={pagination}
            page={page} pageSize={pageSize}
            onPageChange={setPage} onPageSizeChange={setPageSize}
          />
        </div>
      </PageShell>
    </AppShell>
  );
}
