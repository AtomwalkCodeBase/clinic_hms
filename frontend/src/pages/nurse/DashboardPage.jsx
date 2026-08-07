/**
 * pages/nurse/DashboardPage.jsx
 * --------------------------------
 * Nurse dashboard — shows today's queue with a focus on vitals pending.
 * Quick-action: click any waiting patient to go to VitalsPage.
 */

import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { AppShell }   from "../../components/layout/AppShell";
import { PageShell }  from "../../components/common/PageShell";
import { useToast }   from "../../hooks/useToast";
import apiClient      from "../../services/api.client";
import API_ENDPOINTS  from "../../config/api.config";

const TODAY = new Date().toISOString().slice(0, 10);

const STATUS_CONFIG = {
  scheduled:    { label: "Scheduled",    color: "#64748b", bg: "#f1f5f9" },
  waiting:      { label: "Waiting",      color: "#d97706", bg: "#fef3c7" },
  vitals_done:  { label: "Vitals Done",  color: "#0891b2", bg: "#e0f2fe" },
  in_progress:  { label: "With Doctor",  color: "#7c3aed", bg: "#ede9fe" },
  done:         { label: "Done",         color: "#16a34a", bg: "#dcfce7" },
  cancelled:    { label: "Cancelled",    color: "#dc2626", bg: "#fee2e2" },
};

function StatusBadge({ status }) {
  const c = STATUS_CONFIG[status] || { label: status, color: "#64748b", bg: "#f1f5f9" };
  return (
    <span style={{
      display: "inline-block", padding: "2px 9px", borderRadius: 20,
      fontSize: 11, fontWeight: 600, background: c.bg, color: c.color,
    }}>{c.label}</span>
  );
}

export default function NurseDashboardPage() {
  const navigate = useNavigate();
  const { toastApiError } = useToast();

  const [appointments, setAppointments] = useState([]);
  const [loading,      setLoading]      = useState(true);

  useEffect(() => {
    setLoading(true);
    apiClient.get(`${API_ENDPOINTS.OPD.APPOINTMENTS}?date=${TODAY}`)
      .then(r => setAppointments(r.data?.results || r.data?.data || []))
      .catch(() => toastApiError(null, "Failed to load today's queue."))
      .finally(() => setLoading(false));
  }, []);

  const waiting     = appointments.filter(a => a.status === "waiting" || a.status === "scheduled");
  const vitalsDone  = appointments.filter(a => a.status === "vitals_done");
  const withDoctor  = appointments.filter(a => a.status === "in_progress");
  const done        = appointments.filter(a => a.status === "done");

  const stats = [
    { label: "Total",        value: appointments.length, color: "#5B52EE" },
    { label: "Needs Vitals", value: waiting.length,      color: "#d97706" },
    { label: "Vitals Done",  value: vitalsDone.length,   color: "#0891b2" },
    { label: "With Doctor",  value: withDoctor.length,   color: "#7c3aed" },
    { label: "Completed",    value: done.length,         color: "#16a34a" },
  ];

  return (
    <AppShell>
      <PageShell title="Nurse Dashboard">

        {/* Stats row */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 12, marginBottom: 24 }}>
          {stats.map(s => (
            <div key={s.label} className="card" style={{ padding: "16px 20px", textAlign: "center" }}>
              <div style={{ fontSize: 28, fontWeight: 800, color: s.color }}>{s.value}</div>
              <div style={{ fontSize: 12, color: "var(--color-text-muted)", marginTop: 4 }}>{s.label}</div>
            </div>
          ))}
        </div>

        {/* Needs Vitals — primary action area */}
        {waiting.length > 0 && (
          <div style={{ marginBottom: 24 }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
              <div style={{ fontWeight: 700, fontSize: 15 }}>
                🚨 Needs Vitals ({waiting.length})
              </div>
              <button className="btn-primary" onClick={() => navigate("/nurse/vitals")}
                style={{ fontSize: 13, padding: "7px 16px" }}>
                Open Vitals Entry →
              </button>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {waiting.map(appt => (
                <div key={appt.id} className="card"
                  onClick={() => navigate("/nurse/vitals")}
                  style={{ padding: "12px 20px", cursor: "pointer", display: "flex", alignItems: "center", gap: 14,
                    border: "1.5px solid #fde68a", background: "#fffbeb" }}>
                  <div style={{
                    width: 36, height: 36, borderRadius: "50%",
                    background: "#d97706", color: "#fff",
                    display: "flex", alignItems: "center", justifyContent: "center",
                    fontWeight: 700, fontSize: 14, flexShrink: 0,
                  }}>
                    {appt.token_number || "?"}
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontWeight: 600 }}>{appt.patient_name}</div>
                    <div style={{ fontSize: 12, color: "var(--color-text-muted)" }}>
                      {appt.patient_uhid}
                      {appt.chief_complaint && ` · ${appt.chief_complaint}`}
                    </div>
                  </div>
                  <StatusBadge status={appt.status} />
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Full queue */}
        <div>
          <div style={{ fontWeight: 700, fontSize: 15, marginBottom: 10 }}>
            Today's Queue
          </div>
          {loading ? (
            <div className="card" style={{ padding: 40, textAlign: "center", color: "var(--color-text-muted)" }}>
              Loading…
            </div>
          ) : appointments.length === 0 ? (
            <div className="card" style={{ padding: 60, textAlign: "center" }}>
              <div style={{ fontSize: 40, marginBottom: 12 }}>📋</div>
              <div style={{ fontWeight: 600, marginBottom: 6 }}>No appointments today</div>
              <div style={{ color: "var(--color-text-muted)", fontSize: 14 }}>
                Patients will appear here once appointments are booked.
              </div>
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {appointments.map(appt => (
                <div key={appt.id} className="card" style={{ padding: "12px 20px", display: "flex", alignItems: "center", gap: 14 }}>
                  <div style={{
                    width: 36, height: 36, borderRadius: "50%",
                    background: "var(--color-primary-light)", color: "var(--color-primary)",
                    display: "flex", alignItems: "center", justifyContent: "center",
                    fontWeight: 700, fontSize: 14, flexShrink: 0,
                  }}>
                    {appt.token_number || "?"}
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontWeight: 600 }}>{appt.patient_name}</div>
                    <div style={{ fontSize: 12, color: "var(--color-text-muted)" }}>
                      {appt.patient_uhid}
                      {appt.chief_complaint && ` · ${appt.chief_complaint}`}
                    </div>
                  </div>
                  <StatusBadge status={appt.status} />
                  {(appt.status === "waiting" || appt.status === "scheduled") && (
                    <button onClick={() => navigate("/nurse/vitals")}
                      className="btn-primary"
                      style={{ fontSize: 12, padding: "5px 12px" }}>
                      Enter Vitals
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>

      </PageShell>
    </AppShell>
  );
}
