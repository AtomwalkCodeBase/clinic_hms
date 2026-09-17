/**
 * pages/doctor/IpdPatientsPage.jsx
 * -------------------------------------
 * "My Inpatients" — every admission where this doctor is the ordering
 * doctor, so a doctor doing rounds has one place to see who's admitted
 * under their care, which bed/ward, and how long they've been in —
 * without that information only existing on front desk's own Admissions/
 * Bed Board screens. Read-only (bed assignment, transfer, and discharge
 * stay front-desk actions, same role boundary as everywhere else in this
 * app — see the Front Desk role-boundary notes).
 */
import { useState } from "react";
import { AppShell } from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import { useApi } from "../../hooks/useApi";
import API_ENDPOINTS from "../../config/api.config";

const STATUS_BADGE = {
  requested: "badge--neutral",
  admitted: "badge--warning",
  active: "badge--success",
  discharge_initiated: "badge--warning",
  discharged: "badge--neutral",
  cancelled: "badge--error",
};

function daysSince(iso) {
  if (!iso) return "—";
  const days = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 86400000));
  return days === 0 ? "Today" : `${days} day${days === 1 ? "" : "s"}`;
}

export default function IpdPatientsPage() {
  const [includeDischarged, setIncludeDischarged] = useState(false);
  const { data, isLoading, refetch } = useApi(API_ENDPOINTS.IPD.ADMISSIONS_MINE, {
    params: includeDischarged ? { include_discharged: 1 } : {},
    pollMs: 30000,
  });
  const admissions = data || [];

  return (
    <AppShell>
      <PageShell title="My Inpatients">
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
          <p style={{ fontSize: 13, color: "var(--color-text-muted)", margin: 0 }}>
            Patients admitted under you. Bed assignment, transfer, and discharge are handled by front desk.
          </p>
          <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12.5, whiteSpace: "nowrap" }}>
            <input type="checkbox" checked={includeDischarged} onChange={(e) => setIncludeDischarged(e.target.checked)} />
            Include discharged
          </label>
        </div>

        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          <table className="data-table">
            <thead>
              <tr>
                <th>Patient</th>
                <th>Admission #</th>
                <th>Department</th>
                <th>Bed / Ward</th>
                <th>Status</th>
                <th>Days Admitted</th>
              </tr>
            </thead>
            <tbody>
              {admissions.map((a) => (
                <tr key={a.id}>
                  <td>
                    <div style={{ fontWeight: 700, fontSize: 13.5 }}>{a.patient_name}</div>
                    <div style={{ fontSize: 12, color: "var(--color-text-muted)" }}>UHID {a.patient_uhid}</div>
                  </td>
                  <td>{a.admission_number}</td>
                  <td>{a.department_name}</td>
                  <td>
                    {a.bed_number
                      ? `${a.room_name ? a.room_name + " · " : ""}Bed ${a.bed_number}`
                      : <span style={{ color: "var(--color-text-muted)" }}>Awaiting bed</span>}
                  </td>
                  <td><span className={`badge ${STATUS_BADGE[a.status] || "badge--neutral"}`}>{a.status_display}</span></td>
                  <td style={{ fontSize: 12.5, color: "var(--color-text-muted)" }}>
                    {a.discharged_at ? `Discharged ${daysSince(a.created_at)}` : daysSince(a.created_at)}
                  </td>
                </tr>
              ))}
              {!isLoading && admissions.length === 0 && (
                <tr><td colSpan={6} style={{ textAlign: "center", padding: 28, color: "var(--color-text-muted)" }}>
                  {includeDischarged ? "No admissions found." : "No patients currently admitted under you."}
                </td></tr>
              )}
            </tbody>
          </table>
        </div>
      </PageShell>
    </AppShell>
  );
}
