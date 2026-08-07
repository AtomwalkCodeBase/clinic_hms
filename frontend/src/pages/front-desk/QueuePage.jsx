/**
 * pages/front-desk/QueuePage.jsx
 * --------------------------------
 * Front desk live OPD queue — all doctors, today.
 * Front desk can check patients in (scheduled → waiting) and cancel.
 */
import { useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { AppShell }  from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import DependentBadge from "../../components/common/DependentBadge";
import { useApi }    from "../../hooks/useApi";
import { useToast }  from "../../hooks/useToast";
import apiClient     from "../../services/api.client";
import API_ENDPOINTS from "../../config/api.config";
import { ROUTES }    from "../../config/routes.config";

const TODAY = new Date().toISOString().split("T")[0];

const BADGE = {
  scheduled:   "badge--primary",
  waiting:     "badge--warning",
  vitals_done: "badge--success",
  in_progress: "badge--info",
  done:        "badge--success",
  cancelled:   "badge--error",
  no_show:     "badge--neutral",
};

export default function FrontDeskQueuePage() {
  const { toastSuccess, toastApiError } = useToast();
  const navigate = useNavigate();
  const [busy, setBusy] = useState(null);
  const [page, setPage] = useState(1);

  const { data: apptData, isLoading, refetch } = useApi(API_ENDPOINTS.OPD.APPOINTMENTS, {
    params: { date: TODAY, page, page_size: 20 },
  });
  const appointments = apptData?.results || [];
  const pagination   = apptData?.pagination || null;

  const moveStatus = useCallback(async (id, status) => {
    setBusy(id);
    try {
      await apiClient.post(API_ENDPOINTS.OPD.APPT_STATUS(id), { status });
      toastSuccess(`Marked ${status.replace("_", " ")}.`);
      refetch();
    } catch (err) {
      toastApiError(err, "Could not update status.");
    } finally {
      setBusy(null);
    }
  }, [refetch, toastSuccess, toastApiError]);

  // Server-computed totals for the whole day (not just the current page),
  // so the stat strip stays accurate regardless of pagination.
  const serverCounts = apptData?.status_counts || {};
  const counts = {
    total: serverCounts.total ?? appointments.length,
    waiting: serverCounts.waiting ?? 0,
    inProgress: serverCounts.in_progress ?? 0,
    done: serverCounts.done ?? 0,
  };

  return (
    <AppShell>
      <PageShell title="OPD Queue">
        {/* Stat strip */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 14, marginBottom: 22 }}>
          {[
            { label: "Total today", value: counts.total,      dot: "dot-label--green" },
            { label: "In queue",    value: counts.waiting,    dot: "dot-label--gold" },
            { label: "With doctor", value: counts.inProgress, dot: "dot-label--blue" },
            { label: "Completed",   value: counts.done,       dot: "dot-label--green" },
          ].map(({ label, value, dot }) => (
            <div key={label} className="card" style={{ padding: "16px 20px" }}>
              <div className={`dot-label ${dot}`} style={{ marginBottom: 8 }}>{label}</div>
              <div style={{ fontFamily: "var(--font-display)", fontSize: 28, fontWeight: 600 }}>
                {isLoading ? "—" : value}
              </div>
            </div>
          ))}
        </div>

        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          <div style={{
            display: "flex", alignItems: "center", justifyContent: "space-between",
            padding: "14px 20px", borderBottom: "1px solid var(--color-border)",
          }}>
            <span className="dot-label dot-label--green">Queue — {TODAY}</span>
            <button className="btn-outline" style={{ fontSize: 12, padding: "5px 14px" }} onClick={refetch}>
              Refresh
            </button>
          </div>

          {isLoading ? (
            <div style={{ padding: 40, textAlign: "center", color: "var(--color-text-muted)" }}>Loading queue…</div>
          ) : appointments.length === 0 ? (
            <div style={{ padding: 48, textAlign: "center" }}>
              <div style={{ fontFamily: "var(--font-display)", fontSize: 18, fontWeight: 600, marginBottom: 6 }}>
                No patients in queue
              </div>
              <div style={{ fontSize: 13, color: "var(--color-text-muted)" }}>
                Booked appointments will appear here.
              </div>
            </div>
          ) : (
            <table className="data-table">
              <thead>
                <tr>
                  <th style={{ width: 70 }}>Token</th>
                  <th>Patient</th>
                  <th>UHID</th>
                  <th>Doctor</th>
                  <th>Time</th>
                  <th>Complaint</th>
                  <th>Status</th>
                  <th style={{ width: 170 }}>Action</th>
                </tr>
              </thead>
              <tbody>
                {appointments.map(a => (
                  <tr key={a.id}>
                    <td>
                      <span style={{
                        display: "inline-flex", alignItems: "center", justifyContent: "center",
                        width: 32, height: 32, borderRadius: 8,
                        background: "var(--color-primary-light)", color: "var(--color-primary)",
                        fontWeight: 800, fontSize: 14,
                      }}>{a.token_number}</span>
                    </td>
                    <td>
                      <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                        <div style={{ fontWeight: 600, fontSize: 13 }}>{a.patient_name || "—"}</div>
                        <DependentBadge patient={a} />
                      </div>
                      <div style={{ fontSize: 11, color: "var(--color-text-muted)" }}>{a.patient_awpid || ""}</div>
                    </td>
                    <td style={{ fontSize: 12, color: "var(--color-text-muted)" }}>{a.patient_uhid || "—"}</td>
                    <td style={{ fontSize: 12 }}>{a.doctor_name || "—"}</td>
                    <td style={{ fontSize: 12, fontWeight: 700 }}>{a.scheduled_time ? a.scheduled_time.slice(0, 5) : "—"}</td>
                    <td style={{ fontSize: 12, maxWidth: 180, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {a.chief_complaint || "—"}
                    </td>
                    <td>
                      <div style={{ display: "flex", flexDirection: "column", gap: 4, alignItems: "flex-start" }}>
                        <span className={`badge ${BADGE[a.status] || "badge--neutral"}`}>
                          {a.status?.replace("_", " ")}
                        </span>
                        {a.payment_preference === "pay_at_desk" && (
                          <span className="badge badge--warning" style={{ fontSize: 10 }}>Pay at desk</span>
                        )}
                      </div>
                    </td>
                    <td>
                      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                        {a.status === "scheduled" && (
                          <button className="btn-primary" style={{ fontSize: 11, padding: "5px 12px" }}
                            disabled={busy === a.id}
                            onClick={() => moveStatus(a.id, "waiting")}>
                            Check In
                          </button>
                        )}
                        {["scheduled", "waiting"].includes(a.status) && (
                          <button className="btn-outline" style={{
                            fontSize: 11, padding: "5px 12px",
                            color: "var(--color-error)", borderColor: "var(--color-error)",
                          }}
                            disabled={busy === a.id}
                            onClick={() => moveStatus(a.id, "cancelled")}>
                            Cancel
                          </button>
                        )}
                        {a.payment_preference === "pay_at_desk" && a.status !== "cancelled" && (
                          <button className="btn-outline" style={{ fontSize: 11, padding: "5px 12px" }}
                            onClick={() => navigate(ROUTES.FRONT_DESK.BILLING)}>
                            Bill
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
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
