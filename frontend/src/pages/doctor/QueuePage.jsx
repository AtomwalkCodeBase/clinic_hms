/**
 * pages/doctor/QueuePage.jsx
 * ---------------------------
 * Doctor's live OPD queue for today.
 * Calls GET /api/v1/opd/appointments/?date=today
 * Status actions: waiting → in_progress → done
 * "Start" opens the encounter page.
 */

import { useState, useCallback } from "react";
import { useNavigate }      from "react-router-dom";
import { AppShell }         from "../../components/layout/AppShell";
import { PageShell }        from "../../components/common/PageShell";
import DependentBadge       from "../../components/common/DependentBadge";
import { useAuth }          from "../../hooks/useAuth";
import { useToast }         from "../../hooks/useToast";
import { useApi }           from "../../hooks/useApi";
import { useActiveBranch }  from "../../hooks/useActiveBranch";
import BranchSwitcher       from "../../components/common/BranchSwitcher";
import apiClient            from "../../services/api.client";
import API_ENDPOINTS        from "../../config/api.config";
import { Building2 }        from "lucide-react";
import { ROUTES }           from "../../config/routes.config";

const TODAY = new Date().toISOString().split("T")[0];

const STATUS_COLORS = {
  scheduled:   { bg: "#EDE9FF", color: "#5B52EE" },
  waiting:     { bg: "#FEF3C7", color: "#92400E" },
  vitals_done: { bg: "#DCFCE7", color: "#166534" },
  in_progress: { bg: "#DBEAFE", color: "#1E40AF" },
  done:        { bg: "#D1FAE5", color: "#065F46" },
  cancelled:   { bg: "#FEE2E2", color: "#991B1B" },
  no_show:     { bg: "#F3F4F6", color: "#6B7280" },
};

function StatusBadge({ status }) {
  const s = STATUS_COLORS[status] || { bg: "#F3F4F6", color: "#6B7280" };
  return (
    <span style={{
      display: "inline-block", padding: "3px 10px", borderRadius: 20,
      fontSize: 11, fontWeight: 700, background: s.bg, color: s.color,
      textTransform: "capitalize",
    }}>
      {status?.replace("_", " ")}
    </span>
  );
}

export default function DoctorQueuePage() {
  const { user }   = useAuth();
  const navigate   = useNavigate();
  const { toastSuccess, toastApiError } = useToast();
  const [actionLoading, setActionLoading] = useState(null);
  const [page, setPage] = useState(1);
  const { branches, activeBranchId, setActiveBranchId, hasMultiple } = useActiveBranch();

  const { data: apptData, isLoading, refetch } = useApi(
    API_ENDPOINTS.OPD.APPOINTMENTS,
    { params: { date: TODAY, page, page_size: 20, ...(hasMultiple && activeBranchId ? { branch_id: activeBranchId } : {}) } }
  );

  const appointments = apptData?.results || [];
  const pagination   = apptData?.pagination || null;
  // Stat cards use server-computed totals for the whole day, not just the
  // current page, so they stay accurate regardless of how many pages there are.
  const counts = apptData?.status_counts || {};
  const waiting     = counts.waiting ?? 0;
  const vitalsReady = counts.vitals_done ?? 0;
  const inProgress  = counts.in_progress ?? 0;
  const done        = counts.done ?? 0;
  const total       = counts.total ?? appointments.length;

  const moveStatus = useCallback(async (apptId, newStatus) => {
    setActionLoading(apptId + newStatus);
    try {
      await apiClient.post(API_ENDPOINTS.OPD.APPT_STATUS(apptId), { status: newStatus });
      toastSuccess(`Status updated to ${newStatus.replace("_", " ")}.`);
      refetch();
    } catch (err) {
      toastApiError(err, "Could not update status.");
    } finally {
      setActionLoading(null);
    }
  }, [refetch, toastSuccess, toastApiError]);

  const startEncounter = useCallback(async (appt) => {
    setActionLoading(appt.id + "start");
    try {
      // Create encounter — the backend moves status to in_progress automatically
      const { data } = await apiClient.post(API_ENDPOINTS.OPD.ENCOUNTERS, {
        appointment_id: appt.id,
        patient_id:     appt.patient_id,
        doctor_user_id: user?.user_id,
      });
      const encId = data?.id || data?.data?.id;
      navigate(`/doctor/encounter/${encId}`);
    } catch (err) {
      toastApiError(err, "Could not start encounter.");
      setActionLoading(null);
    }
  }, [navigate, user, toastApiError]);

  return (
    <AppShell>
      <PageShell title="Today's OPD Queue">

        {/* Stats row */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(5,1fr)", gap: 14, marginBottom: 24 }}>
          {[
            { label: "Total Today",  value: total,               dot: "dot-label--green" },
            { label: "Waiting",      value: waiting,             dot: "dot-label--gold" },
            { label: "Vitals Ready", value: vitalsReady,         dot: "dot-label--green" },
            { label: "In Progress",  value: inProgress,          dot: "dot-label--blue" },
            { label: "Done",         value: done,                dot: "dot-label--green" },
          ].map(({ label, value, dot }) => (
            <div key={label} className="card" style={{ padding: "16px 18px" }}>
              <div className={`dot-label ${dot}`} style={{ marginBottom: 8 }}>{label}</div>
              <div style={{ fontFamily: "var(--font-display)", fontSize: 28, fontWeight: 600 }}>
                {isLoading ? "—" : value}
              </div>
            </div>
          ))}
        </div>

        {/* Queue table */}
        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          <div style={{
            display: "flex", alignItems: "center", justifyContent: "space-between",
            padding: "14px 20px", borderBottom: "1px solid var(--color-border)",
          }}>
            <span style={{ fontWeight: 700, fontSize: 14 }}>Queue — {TODAY}</span>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <BranchSwitcher branches={branches} activeBranchId={activeBranchId} onChange={setActiveBranchId} />
              <button className="btn-outline" style={{ fontSize: 12, padding: "5px 14px" }}
                onClick={refetch}>Refresh</button>
            </div>
          </div>

          {isLoading ? (
            <div style={{ padding: 40, textAlign: "center", color: "var(--color-text-muted)" }}>
              Loading queue…
            </div>
          ) : appointments.length === 0 ? (
            <div style={{ padding: 48, textAlign: "center" }}>
              <Building2 size={36} style={{ color: "var(--color-text-muted)", marginBottom: 12 }} />
              <div style={{ fontWeight: 600, marginBottom: 6 }}>No patients in queue today</div>
              <div style={{ fontSize: 13, color: "var(--color-text-muted)" }}>
                Appointments booked by front desk will appear here.
              </div>
            </div>
          ) : (
            <table className="data-table">
              <thead>
                <tr>
                  <th style={{ width: 70 }}>Token</th>
                  <th>Patient</th>
                  <th>UHID</th>
                  <th>Time</th>
                  <th>Chief Complaint</th>
                  <th>Type</th>
                  <th>Status</th>
                  <th style={{ width: 160 }}>Action</th>
                </tr>
              </thead>
              <tbody>
                {appointments.map(appt => {
                  const busy = actionLoading?.startsWith(appt.id);
                  return (
                    <tr key={appt.id}>
                      <td>
                        <span style={{
                          display: "inline-flex", alignItems: "center", justifyContent: "center",
                          width: 32, height: 32, borderRadius: 8,
                          background: "var(--color-primary-light)", color: "var(--color-primary)",
                          fontWeight: 800, fontSize: 14,
                        }}>
                          {appt.token_number}
                        </span>
                      </td>
                      <td>
                        <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                          <div style={{ fontWeight: 600, fontSize: 13 }}>{appt.patient_name || "—"}</div>
                          <DependentBadge patient={appt} />
                        </div>
                        <div style={{ fontSize: 11, color: "var(--color-text-muted)" }}>{appt.patient_awpid || ""}</div>
                      </td>
                      <td style={{ fontSize: 12, color: "var(--color-text-muted)" }}>
                        {appt.patient_uhid || "—"}
                      </td>
                      <td style={{ fontSize: 12, fontWeight: 700 }}>
                        {appt.scheduled_time ? appt.scheduled_time.slice(0, 5) : "—"}
                      </td>
                      <td style={{ fontSize: 12, maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {appt.chief_complaint || <span style={{ color: "var(--color-text-muted)" }}>—</span>}
                      </td>
                      <td>
                        <span style={{ fontSize: 11, textTransform: "capitalize" }}>
                          {appt.appointment_type || "opd"}
                        </span>
                      </td>
                      <td><StatusBadge status={appt.status} /></td>
                      <td>
                        <div style={{ display: "flex", gap: 6 }}>
                          {(appt.status === "waiting" || appt.status === "vitals_done") && (
                            <button
                              className="btn-primary"
                              style={{ fontSize: 11, padding: "5px 12px", background: appt.status === "vitals_done" ? "#16A34A" : undefined }}
                              disabled={busy}
                              onClick={() => startEncounter(appt)}
                            >
                              {busy ? "…" : "▶ Start"}
                            </button>
                          )}
                          {appt.status === "in_progress" && (
                            <button
                              className="btn-primary"
                              style={{ fontSize: 11, padding: "5px 12px", background: "#10B981" }}
                              disabled={busy}
                              onClick={() => navigate(`/doctor/encounter/${appt.encounter?.id || appt.id}`)}
                            >
                              Open Notes
                            </button>
                          )}
                          {appt.status === "scheduled" && (
                            <button
                              className="btn-outline"
                              style={{ fontSize: 11, padding: "5px 12px" }}
                              disabled={busy}
                              onClick={() => moveStatus(appt.id, "waiting")}
                            >
                              Check In
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}

          {pagination && pagination.total_pages > 1 && (
            <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 16, padding: "16px 20px", borderTop: "1px solid var(--color-border)" }}>
              <button
                className="btn-outline"
                style={{ fontSize: 12, padding: "6px 14px" }}
                disabled={!pagination.has_previous}
                onClick={() => setPage(p => Math.max(1, p - 1))}
              >
                ← Previous
              </button>
              <span style={{ fontSize: 12, color: "var(--color-text-muted)" }}>
                Page {pagination.page} of {pagination.total_pages}
              </span>
              <button
                className="btn-outline"
                style={{ fontSize: 12, padding: "6px 14px" }}
                disabled={!pagination.has_next}
                onClick={() => setPage(p => Math.min(pagination.total_pages, p + 1))}
              >
                Next →
              </button>
            </div>
          )}
        </div>
      </PageShell>
    </AppShell>
  );
}
