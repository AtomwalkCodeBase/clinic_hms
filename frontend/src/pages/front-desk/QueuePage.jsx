/**
 * pages/front-desk/QueuePage.jsx
 * --------------------------------
 * Front desk live OPD queue — all doctors, today.
 * Front desk can check patients in (scheduled → waiting) and cancel.
 */
import { useState, useCallback, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { AppShell }  from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import DependentBadge from "../../components/common/DependentBadge";
import PaginationControls from "../../components/common/PaginationControls";
import { useApi }    from "../../hooks/useApi";
import { useAuth }   from "../../hooks/useAuth";
import { useToast }  from "../../hooks/useToast";
import apiClient     from "../../services/api.client";
import API_ENDPOINTS from "../../config/api.config";
import { ROUTES }    from "../../config/routes.config";

const TODAY = new Date().toISOString().split("T")[0];
const MAX_RESCHEDULE_DATE = (() => {
  const d = new Date();
  d.setDate(d.getDate() + 62);
  return d.toISOString().split("T")[0];
})();

const BADGE = {
  scheduled:   "badge--primary",
  waiting:     "badge--warning",
  vitals_done: "badge--success",
  in_progress: "badge--info",
  done:        "badge--success",
  cancelled:   "badge--error",
  no_show:     "badge--neutral",
};

// Same slot grid as the booking form on AppointmentsPage — reused here so a
// reschedule shows real live availability instead of a freeform time field.
function RescheduleModal({ appt, onClose, onDone }) {
  const { toastSuccess, toastApiError } = useToast();
  const { user } = useAuth();
  const [date, setDate] = useState(appt.scheduled_date >= TODAY ? appt.scheduled_date : TODAY);
  const [slots, setSlots] = useState([]);
  const [slotsLoading, setSlotsLoading] = useState(false);
  const [slot, setSlot] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!date || !appt.doctor_user_id || !user?.tenant_id) return;
    setSlotsLoading(true);
    setSlot("");
    apiClient.get(API_ENDPOINTS.PORTAL.SLOTS(user.tenant_id, appt.doctor_user_id), { params: { date } })
      .then(({ data }) => setSlots((data?.results || []).filter(s => !s.past)))
      .catch(() => setSlots([]))
      .finally(() => setSlotsLoading(false));
  }, [date, appt.doctor_user_id, user]);

  async function confirm() {
    setSaving(true);
    try {
      await apiClient.post(API_ENDPOINTS.OPD.APPT_RESCHEDULE(appt.id), {
        scheduled_date: date, ...(slot ? { scheduled_time: slot } : {}),
      });
      toastSuccess("Appointment rescheduled.");
      onDone();
      onClose();
    } catch (err) {
      toastApiError(err, "Could not reschedule this appointment.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div style={{ position: "fixed", inset: 0, zIndex: 1000, background: "rgba(0,0,0,0.45)", display: "flex", alignItems: "center", justifyContent: "center", padding: 24 }}>
      <div style={{ background: "var(--color-surface)", borderRadius: 16, width: "100%", maxWidth: 440, padding: 26, boxShadow: "0 20px 60px rgba(0,0,0,0.3)" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
          <h2 style={{ margin: 0, fontSize: 16 }}>Reschedule appointment</h2>
          <button type="button" onClick={onClose} style={{ background: "none", border: "none", fontSize: 20, cursor: "pointer" }}>✕</button>
        </div>
        <div style={{ fontSize: 12, color: "var(--color-text-muted)", marginBottom: 18 }}>
          {appt.patient_name || "Patient"} · {appt.doctor_name || "Doctor"} · Token {appt.token_number}
        </div>

        <label className="stat-label" style={{ display: "block", marginBottom: 6 }}>New date</label>
        <input
          type="date" className="form-input" value={date} min={TODAY} max={MAX_RESCHEDULE_DATE}
          onChange={e => setDate(e.target.value)}
          style={{ width: "100%", boxSizing: "border-box", marginBottom: 16 }}
        />

        <label className="stat-label" style={{ display: "block", marginBottom: 8 }}>
          Slot {slot && <span style={{ color: "var(--color-primary)" }}>— {slot}</span>}
          <span style={{ fontWeight: 400, textTransform: "none", letterSpacing: 0 }}> (optional for walk-ins)</span>
        </label>
        {slotsLoading ? (
          <div style={{ fontSize: 13, color: "var(--color-text-muted)", marginBottom: 16 }}>Checking availability…</div>
        ) : slots.length === 0 ? (
          <div style={{ fontSize: 13, color: "var(--color-text-muted)", marginBottom: 16 }}>No slots configured for this date.</div>
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(72px, 1fr))", gap: 8, marginBottom: 16 }}>
            {slots.map(s => (
              <button key={s.time} type="button" disabled={!s.available}
                onClick={() => setSlot(slot === s.time ? "" : s.time)}
                style={{
                  padding: "6px 0", borderRadius: 8, fontSize: 12, fontWeight: 700,
                  border: slot === s.time ? "2px solid var(--color-primary)" : "1px solid var(--color-border)",
                  background: !s.available ? "var(--color-border)"
                    : slot === s.time ? "var(--color-primary)" : "var(--color-surface)",
                  color: !s.available ? "var(--color-text-disabled)"
                    : slot === s.time ? "#fff" : "var(--color-text-secondary)",
                  cursor: s.available ? "pointer" : "not-allowed",
                  textDecoration: !s.available ? "line-through" : "none",
                }}>
                {s.time}
              </button>
            ))}
          </div>
        )}

        <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
          <button type="button" className="btn-outline" disabled={saving} onClick={onClose} style={{ padding: "9px 16px" }}>Back</button>
          <button type="button" className="btn-primary" disabled={saving} onClick={confirm} style={{ padding: "9px 16px" }}>
            {saving ? "Saving…" : "Confirm new date/time"}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function FrontDeskQueuePage() {
  const { toastSuccess, toastApiError } = useToast();
  const navigate = useNavigate();
  const [busy, setBusy] = useState(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [rescheduleTarget, setRescheduleTarget] = useState(null);

  const { data: apptData, isLoading, refetch } = useApi(API_ENDPOINTS.OPD.APPOINTMENTS, {
    params: { date: TODAY, page, page_size: pageSize },
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
                  <th>Room</th>
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
                    <td style={{ fontSize: 12 }}>
                      {a.room_name
                        ? <>{a.room_name}{a.floor && <div style={{ fontSize: 10, color: "var(--color-text-muted)" }}>Floor {a.floor}</div>}</>
                        : <span style={{ color: "var(--color-text-muted)" }}>—</span>}
                    </td>
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
                            onClick={() => {
                              if (!window.confirm(`Check in ${a.patient_name || "this patient"} (Token ${a.token_number})?`)) return;
                              moveStatus(a.id, "waiting");
                            }}>
                            Check In
                          </button>
                        )}
                        {["scheduled", "waiting"].includes(a.status) && (
                          <button className="btn-outline" style={{ fontSize: 11, padding: "5px 12px" }}
                            disabled={busy === a.id}
                            onClick={() => setRescheduleTarget(a)}>
                            Reschedule
                          </button>
                        )}
                        {["scheduled", "waiting"].includes(a.status) && (
                          <button className="btn-outline" style={{
                            fontSize: 11, padding: "5px 12px",
                            color: "var(--color-error)", borderColor: "var(--color-error)",
                          }}
                            disabled={busy === a.id}
                            onClick={() => {
                              if (!window.confirm(`Cancel the appointment for ${a.patient_name || "this patient"} (Token ${a.token_number})? This cannot be undone.`)) return;
                              moveStatus(a.id, "cancelled");
                            }}>
                            Cancel
                          </button>
                        )}
                        {a.payment_preference === "pay_at_desk" && a.status !== "cancelled" && (
                          <button className="btn-outline" style={{ fontSize: 11, padding: "5px 12px" }}
                            onClick={() => navigate(ROUTES.FRONT_DESK.BILLING, { state: { appointment: a } })}>
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

          <PaginationControls
            pagination={pagination}
            page={page} pageSize={pageSize}
            onPageChange={setPage} onPageSizeChange={setPageSize}
          />
        </div>

        {rescheduleTarget && (
          <RescheduleModal
            appt={rescheduleTarget}
            onClose={() => setRescheduleTarget(null)}
            onDone={refetch}
          />
        )}
      </PageShell>
    </AppShell>
  );
}
