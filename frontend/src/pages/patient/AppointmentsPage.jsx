/**
 * pages/patient/AppointmentsPage.jsx
 * ------------------------------------
 * My Appointments — leads with the next upcoming visit (the thing the
 * patient actually came here to check), splits the rest into Upcoming /
 * Past, and shows real queue position (people ahead, who's currently being
 * seen) computed live from Appointment.status in the same tenant DB rather
 * than an invented "estimated wait" — we don't track per-consult timing,
 * so a minutes estimate would just be a guess dressed up as data.
 */
import { useMemo, useState, useEffect } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  Building2, Calendar, Clock, CircleCheck, ChevronRight, Stethoscope,
  XCircle, Users2, FileText, MapPin, Sparkles, CalendarClock,
} from "lucide-react";
import { AppShell }  from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import { usePaginatedList } from "../../hooks/usePaginatedList";
import { useApi } from "../../hooks/useApi";
import { useToast } from "../../hooks/useToast";
import apiClient     from "../../services/api.client";
import API_ENDPOINTS from "../../config/api.config";
import ROUTES        from "../../config/routes.config";

const TODAY = new Date().toISOString().split("T")[0];
// Mirrors the 2-month booking window enforced server-side (see
// AppointmentRescheduleView / PortalRescheduleBookingView) — a reschedule is
// just a move within the same booking rules as a fresh booking.
const MAX_RESCHEDULE_DATE = (() => {
  const d = new Date();
  d.setDate(d.getDate() + 62);
  return d.toISOString().split("T")[0];
})();
const CANCELLABLE_STATUSES = ["scheduled", "waiting", "vitals_done"];
const RESCHEDULABLE_STATUSES = ["scheduled", "waiting"];

const STATUS_META = {
  scheduled:   { label: "Confirmed",              color: "var(--color-primary)", bg: "var(--color-primary-light)", icon: CircleCheck },
  waiting:     { label: "Waiting",                color: "var(--color-info)",    bg: "var(--color-info-light)",    icon: Clock },
  vitals_done: { label: "Vitals Recorded",         color: "var(--color-info)",    bg: "var(--color-info-light)",    icon: CircleCheck },
  in_progress: { label: "Consultation in Progress",color: "var(--color-accent)",  bg: "var(--color-accent-light)",  icon: Stethoscope },
  done:        { label: "Completed",               color: "var(--color-success)", bg: "var(--color-success-light)", icon: CircleCheck },
  cancelled:   { label: "Cancelled",                color: "var(--color-error)",   bg: "var(--color-error-light)",   icon: XCircle },
  no_show:     { label: "No Show",                  color: "var(--color-error)",   bg: "var(--color-error-light)",   icon: XCircle },
  expired:     { label: "Not Completed",            color: "var(--color-text-muted)", bg: "var(--color-border)",     icon: XCircle },
};
const ACTIVE_STATUSES = ["scheduled", "waiting", "vitals_done", "in_progress"];

// An appointment that never got closed out (still scheduled/waiting/in_progress
// etc.) by the end of its own calendar day is stale, not upcoming — the hospital
// simply never marked it done. We don't mutate the real backend status for this
// (that's the hospital's record of what happened), we just stop presenting it as
// "upcoming" once its day has passed.
function isExpired(b) {
  const todayStr = new Date().toISOString().split("T")[0];
  return ACTIVE_STATUSES.includes(b.status) && b.date < todayStr;
}

function StatusBadge({ status }) {
  const meta = STATUS_META[status] || { label: status, color: "var(--color-text-muted)", bg: "var(--color-border)", icon: Clock };
  const Icon = meta.icon;
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 5, fontSize: 11, fontWeight: 700,
      padding: "4px 10px", borderRadius: 20, background: meta.bg, color: meta.color,
    }}>
      <Icon size={12} /> {meta.label}
    </span>
  );
}

function relativeDate(dateStr) {
  const today = new Date().toISOString().split("T")[0];
  const tomorrow = new Date(Date.now() + 86400000).toISOString().split("T")[0];
  if (dateStr === today) return "Today";
  if (dateStr === tomorrow) return "Tomorrow";
  try {
    return new Date(dateStr + "T00:00:00").toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
  } catch {
    return dateStr;
  }
}

// Appointment.doctor_name is captured raw at booking time from whatever the
// hospital typed into the staff account's first/last name — some accounts
// already have "Dr." baked into the name, some don't (same root cause as
// the doctor-card display-name fix in portal_views.py, but that fix only
// covers newly-read doctor cards, not names already stored on past
// bookings). Strip any existing prefix before adding one, so it's always
// "Dr. X" exactly once regardless of how the underlying data looks.
function formatDoctorName(raw) {
  const stripped = (raw || "").replace(/^dr\.?\s+/i, "").trim();
  return stripped ? `Dr. ${stripped}` : raw;
}

function formatTime12h(t) {
  if (!t) return null;
  const [h, m] = t.split(":").map(Number);
  const period = h >= 12 ? "PM" : "AM";
  const h12 = h % 12 || 12;
  return `${h12}:${String(m).padStart(2, "0")} ${period}`;
}

function FamilyTag({ b, ownAwpid }) {
  if (!b.patient_name) return null;
  const isSelf = ownAwpid && b.patient_awpid === ownAwpid;
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 4, fontSize: 11, fontWeight: 700,
      padding: "3px 9px", borderRadius: 20,
      background: isSelf ? "var(--color-surface-secondary, #f6f4ee)" : "var(--color-accent-light)",
      color: isSelf ? "var(--color-text-muted)" : "var(--color-accent)",
    }}>
      <Users2 size={11} /> Patient: {isSelf ? `You (${b.patient_name})` : b.patient_name}
    </span>
  );
}

function AppointmentActions({ b, onCancel, onReschedule, size = 12 }) {
  const canCancel = CANCELLABLE_STATUSES.includes(b.status);
  const canReschedule = RESCHEDULABLE_STATUSES.includes(b.status);
  if (!canCancel && !canReschedule) return null;
  return (
    <div style={{ display: "flex", gap: 16 }}>
      {canReschedule && (
        <button
          onClick={() => onReschedule(b)}
          style={{
            display: "flex", alignItems: "center", gap: 4, background: "none", border: "none", cursor: "pointer",
            fontSize: size, fontWeight: 700, color: "var(--color-primary)", padding: 0,
          }}
        >
          <CalendarClock size={size + 1} /> Reschedule
        </button>
      )}
      {canCancel && (
        <button
          onClick={() => onCancel(b)}
          style={{
            display: "flex", alignItems: "center", gap: 4, background: "none", border: "none", cursor: "pointer",
            fontSize: size, fontWeight: 700, color: "var(--color-error)", padding: 0,
          }}
        >
          <XCircle size={size + 1} /> Cancel
        </button>
      )}
    </div>
  );
}

// Same slot grid used at booking time (PortalSlotListView), reused here so
// rescheduling shows real live availability rather than a freeform time
// field — a freeform field could collide with another booked slot the
// patient can't see, or with the doctor's actual working hours.
function RescheduleModal({ booking, onClose, onDone }) {
  const { toastSuccess, toastApiError } = useToast();
  const [date, setDate] = useState(booking.date >= TODAY ? booking.date : TODAY);
  const [slots, setSlots] = useState([]);
  const [slotsLoading, setSlotsLoading] = useState(false);
  const [selectedSlot, setSelectedSlot] = useState(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!date || !booking.tenant_id || !booking.doctor_id) return;
    setSlotsLoading(true);
    setSelectedSlot(null);
    apiClient.get(API_ENDPOINTS.PORTAL.SLOTS(booking.tenant_id, booking.doctor_id), { params: { date } })
      .then(res => setSlots(res.data?.results || []))
      .catch(() => setSlots([]))
      .finally(() => setSlotsLoading(false));
  }, [date, booking.tenant_id, booking.doctor_id]);

  async function confirm() {
    if (!selectedSlot) return;
    setSaving(true);
    try {
      await apiClient.post(API_ENDPOINTS.PORTAL.RESCHEDULE_BOOKING(booking.id), {
        scheduled_date: date, scheduled_time: selectedSlot,
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

  const canPickHospitalDoctor = booking.tenant_id && booking.doctor_id;

  return (
    <div style={{ position: "fixed", inset: 0, zIndex: 1000, background: "rgba(0,0,0,0.45)", display: "flex", alignItems: "center", justifyContent: "center", padding: 24 }}>
      <div style={{ background: "var(--color-surface)", borderRadius: 16, width: "100%", maxWidth: 440, padding: 26, boxShadow: "0 20px 60px rgba(0,0,0,0.3)" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
          <h2 style={{ margin: 0, fontSize: 16 }}>Reschedule appointment</h2>
          <button type="button" onClick={onClose} style={{ background: "none", border: "none", fontSize: 20, cursor: "pointer" }}>✕</button>
        </div>
        <div style={{ fontSize: 12, color: "var(--color-text-muted)", marginBottom: 18 }}>
          {formatDoctorName(booking.doctor)} · {booking.hospital}
        </div>

        {!canPickHospitalDoctor ? (
          <div style={{ fontSize: 13, color: "var(--color-error)", marginBottom: 16 }}>
            Can't reschedule this booking online right now — please contact the hospital directly.
          </div>
        ) : (
          <>
            <label className="stat-label" style={{ display: "block", marginBottom: 6 }}>New date</label>
            <input
              type="date" className="form-input" value={date} min={TODAY} max={MAX_RESCHEDULE_DATE}
              onChange={e => setDate(e.target.value)}
              style={{ width: "100%", boxSizing: "border-box", marginBottom: 16 }}
            />

            <label className="stat-label" style={{ display: "block", marginBottom: 8 }}>Available slots</label>
            {slotsLoading ? (
              <div style={{ fontSize: 13, color: "var(--color-text-muted)", marginBottom: 16 }}>Checking availability…</div>
            ) : slots.length === 0 ? (
              <div style={{ fontSize: 13, color: "var(--color-text-muted)", marginBottom: 16 }}>No slots configured for this date.</div>
            ) : (
              <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 16 }}>
                {slots.map(s => {
                  const isSelected = selectedSlot === s.time;
                  return (
                    <button
                      key={s.time} type="button" disabled={!s.available}
                      onClick={() => setSelectedSlot(s.time)}
                      style={{
                        padding: "7px 12px", borderRadius: 8, fontSize: 12.5, fontWeight: 700,
                        cursor: s.available ? "pointer" : "not-allowed",
                        border: `1.5px solid ${isSelected ? "var(--color-primary)" : s.available ? "var(--color-success)" : "var(--color-border)"}`,
                        background: isSelected
                          ? "linear-gradient(135deg, var(--color-hero) 0%, var(--color-hero-2) 100%)"
                          : s.available ? "var(--color-success-light)" : "var(--color-surface-secondary, #f6f4ee)",
                        color: isSelected ? "#fff" : s.available ? "var(--color-success)" : "var(--color-text-muted)",
                        textDecoration: s.available ? "none" : "line-through",
                      }}
                    >
                      {formatTime12h(s.time)}
                    </button>
                  );
                })}
              </div>
            )}
          </>
        )}

        <div style={{ display: "flex", gap: 10, justifyContent: "flex-end", marginTop: 6 }}>
          <button type="button" className="btn-outline" disabled={saving} onClick={onClose} style={{ padding: "9px 16px" }}>Back</button>
          <button type="button" className="btn-primary" disabled={saving || !selectedSlot} onClick={confirm} style={{ padding: "9px 16px" }}>
            {saving ? "Saving…" : "Confirm new time"}
          </button>
        </div>
      </div>
    </div>
  );
}

function HeroAppointment({ b, ownAwpid, onCancel, onReschedule }) {
  const meta = STATUS_META[b.status] || STATUS_META.scheduled;
  return (
    <div className="card" style={{ padding: 0, overflow: "hidden", marginBottom: 22 }}>
      {/* Dark hero gradient header */}
      <div style={{
        background: "linear-gradient(135deg, var(--color-hero) 0%, var(--color-hero-2) 100%)",
        padding: "18px 24px",
        display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 10,
        position: "relative", overflow: "hidden",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, color: "#fff", position: "relative" }}>
          <span style={{ width: 8, height: 8, borderRadius: "50%", background: "#7EE0A8" }} />
          <span style={{ fontSize: 12, fontWeight: 700, letterSpacing: 0.5, textTransform: "uppercase" }}>
            Upcoming Appointment
          </span>
        </div>
        <div style={{ position: "relative" }}>
          <StatusBadge status={b.status} />
        </div>
      </div>

      <div style={{ padding: "22px 24px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", marginBottom: 2 }}>
          <div style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 24 }}>
            {relativeDate(b.date)}{b.time ? `, ${formatTime12h(b.time)}` : ""}
          </div>
          <FamilyTag b={b} ownAwpid={ownAwpid} />
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 14, color: "var(--color-text-secondary)", marginBottom: 14 }}>
          <Building2 size={14} /> {b.hospital}
        </div>

        {b.room_name && (
          <div style={{
            display: "flex", alignItems: "center", gap: 6, fontSize: 13.5, fontWeight: 600,
            color: "var(--color-primary)", marginBottom: 14, padding: "8px 12px", borderRadius: 8,
            background: "var(--color-primary-light)", width: "fit-content",
          }}>
            <MapPin size={14} /> {b.room_name}{b.floor ? ` · Floor ${b.floor}` : ""}
          </div>
        )}

        <div style={{ display: "flex", flexWrap: "wrap", gap: 16, alignItems: "center", marginBottom: 16 }}>
          <div style={{ fontSize: 15, fontWeight: 700 }}>{formatDoctorName(b.doctor)}</div>
          {b.token_number != null && (
            <div style={{
              display: "flex", alignItems: "center", gap: 8, padding: "6px 16px", borderRadius: 12,
              background: "#FFF8E1", border: "1.5px solid color-mix(in srgb, var(--color-accent) 40%, transparent)",
            }}>
              <span style={{ fontSize: 11, fontWeight: 700, color: "var(--color-warning)", textTransform: "uppercase", letterSpacing: "0.06em" }}>Token</span>
              <span style={{ fontFamily: "var(--font-display)", fontWeight: 800, fontSize: 22, color: "var(--color-accent)", lineHeight: 1 }}>
                #{b.token_number}
              </span>
            </div>
          )}
        </div>

        {b.chief_complaint && (
          <div style={{
            fontSize: 13, color: "var(--color-text-secondary)", marginBottom: 16, fontStyle: "italic",
            borderLeft: "3px solid var(--color-primary)", paddingLeft: 12,
          }}>
            "{b.chief_complaint}"
          </div>
        )}

        {(b.people_ahead != null || b.now_serving_token != null) && (
          <div style={{
            display: "flex", flexWrap: "wrap", gap: 20, padding: "12px 16px", borderRadius: 10,
            background: "var(--color-info-light)", marginBottom: 16,
          }}>
            {b.now_serving_token != null && (
              <div>
                <div className="stat-label" style={{ color: "var(--color-info)" }}>Currently serving</div>
                <div style={{ fontWeight: 700, fontSize: 15, color: "var(--color-info)" }}>Token #{b.now_serving_token}</div>
              </div>
            )}
            {b.people_ahead != null && (
              <div>
                <div className="stat-label" style={{ color: "var(--color-info)" }}>Patients ahead of you</div>
                <div style={{ fontWeight: 700, fontSize: 15, color: "var(--color-info)" }}>
                  {b.people_ahead === 0 ? "You're next" : b.people_ahead}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Timeline — purely derived from the real status field */}
        <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 8 }}>
          {[
            { key: "booked",  label: "Booking confirmed",            done: true },
            { key: "token",   label: `Token generated${b.token_number != null ? ` (#${b.token_number})` : ""}`, done: b.token_number != null },
            { key: "consult", label: "Doctor consultation",           done: ["in_progress", "done"].includes(b.status), active: b.status === "in_progress" },
            { key: "rx",      label: "Prescription available",        done: b.status === "done" },
          ].map(step => (
            <div key={step.key} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12.5 }}>
              <span style={{
                width: 18, height: 18, borderRadius: "50%", flexShrink: 0,
                display: "flex", alignItems: "center", justifyContent: "center", fontSize: 10,
                background: step.done
                  ? "linear-gradient(135deg, var(--color-hero) 0%, var(--color-hero-2) 100%)"
                  : step.active
                  ? "linear-gradient(135deg, var(--color-accent) 0%, var(--color-warning) 100%)"
                  : "var(--color-border)",
                color: step.done || step.active ? "#fff" : "var(--color-text-muted)",
                fontWeight: 700,
              }}>
                {step.done ? "✓" : step.active ? "•" : ""}
              </span>
              <span style={{ color: step.done ? "var(--color-text)" : "var(--color-text-muted)", fontWeight: step.active ? 700 : 400 }}>
                {step.label}
              </span>
            </div>
          ))}
        </div>

        <AppointmentActions b={b} onCancel={onCancel} onReschedule={onReschedule} size={13} />
      </div>
    </div>
  );
}

function AppointmentCard({ b, onOpenPrescriptions, ownAwpid, onCancel, onReschedule }) {
  const expired = isExpired(b);
  const displayStatus = expired ? "expired" : b.status;
  const isPast = b.status === "done" || b.status === "cancelled" || b.status === "no_show" || expired;
  const meta = STATUS_META[displayStatus] || STATUS_META.scheduled;

  return (
    <div className="card" style={{
      padding: 0, overflow: "hidden",
      borderLeft: `4px solid ${meta.color}`,
      background: meta.bg,
    }}>
      {/* Card header */}
      <div style={{ padding: "12px 16px 10px", display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 8 }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 12, color: "var(--color-text-muted)" }}>
            <Building2 size={12} />
            <span style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 13 }}>{b.hospital}</span>
          </div>
          <div style={{ fontWeight: 700, fontSize: 14, marginTop: 3, color: "var(--color-text)" }}>
            {formatDoctorName(b.doctor)}
          </div>
          <div style={{ marginTop: 4 }}><FamilyTag b={b} ownAwpid={ownAwpid} /></div>
        </div>
        <StatusBadge status={displayStatus} />
      </div>

      <div style={{ padding: "0 16px 10px" }}>
        <div style={{ display: "flex", gap: 14, fontSize: 12.5, color: "var(--color-text-secondary)" }}>
          <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
            <Calendar size={12} /> {relativeDate(b.date)}
          </span>
          {b.time && (
            <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
              <Clock size={12} /> {formatTime12h(b.time)}
            </span>
          )}
          {b.room_name && (
            <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
              <MapPin size={12} /> {b.room_name}{b.floor ? ` · Fl ${b.floor}` : ""}
            </span>
          )}
        </div>

        {b.chief_complaint && (
          <div style={{
            fontSize: 12, color: "var(--color-text-muted)", marginTop: 6,
            borderLeft: "2px solid var(--color-border)", paddingLeft: 8, fontStyle: "italic",
          }}>
            {b.chief_complaint}
          </div>
        )}

        {b.status === "no_show" && (
          <div style={{ fontSize: 12, color: "var(--color-error)", marginTop: 6 }}>
            This appointment window passed without a check-in — marked as not completed.
          </div>
        )}

        {expired && (
          <div style={{ fontSize: 12, color: "var(--color-text-muted)", marginTop: 6 }}>
            This appointment's day has passed and it was never marked complete by the hospital.
          </div>
        )}

        {!isPast && (
          <div style={{ marginTop: 8 }}>
            <AppointmentActions b={b} onCancel={onCancel} onReschedule={onReschedule} />
          </div>
        )}

        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: 8 }}>
          {b.token_number != null ? (
            <div style={{ fontSize: 12, fontWeight: 800, color: "var(--color-accent)", fontFamily: "var(--font-display)" }}>
              Token #{b.token_number}
            </div>
          ) : <span />}
          <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
            {isPast && b.status === "done" && (
              <button
                onClick={onOpenPrescriptions}
                style={{
                  display: "flex", alignItems: "center", gap: 4, background: "none", border: "none", cursor: "pointer",
                  fontSize: 12, fontWeight: 700, color: "var(--color-primary)", padding: 0,
                }}
              >
                <FileText size={13} /> View prescription
              </button>
            )}
            {isPast && b.tenant_id && (
              <Link
                to={b.doctor_id
                  ? ROUTES.PATIENT.DOCTOR_PROFILE(b.tenant_id, b.doctor_id)
                  : ROUTES.PATIENT.HOSPITAL_DOCTORS(b.tenant_id)}
                style={{
                  display: "flex", alignItems: "center", gap: 4,
                  fontSize: 12, fontWeight: 700, color: "var(--color-primary)",
                }}
              >
                Book follow-up <ChevronRight size={13} />
              </Link>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export default function PatientAppointmentsPage() {
  const navigate = useNavigate();
  const { toastSuccess, toastApiError } = useToast();
  const {
    items: bookings, isLoading: bookingsLoading, pagination: bookingsPagination,
    loadMore: loadMoreBookings, isLoadingMore: bookingsLoadingMore, hasMore: hasMoreBookings,
    refetch,
  } = usePaginatedList(API_ENDPOINTS.PORTAL.MY_BOOKINGS, { pageSize: 20 });

  const { data: stats } = useApi(API_ENDPOINTS.PORTAL.STATS);
  const { data: profile } = useApi(API_ENDPOINTS.PORTAL.PROFILE);
  const ownAwpid = profile?.awpid;

  const [rescheduleTarget, setRescheduleTarget] = useState(null);

  async function handleCancel(b) {
    const when = `${relativeDate(b.date)}${b.time ? ` at ${formatTime12h(b.time)}` : ""}`;
    if (!window.confirm(`Cancel your appointment with ${formatDoctorName(b.doctor)} on ${when}? This cannot be undone.`)) return;
    try {
      await apiClient.post(API_ENDPOINTS.PORTAL.CANCEL_BOOKING(b.id));
      toastSuccess("Appointment cancelled.");
      refetch();
    } catch (err) {
      toastApiError(err, "Could not cancel this appointment.");
    }
  }

  const { hero, upcoming, past } = useMemo(() => {
    const active = bookings.filter(b => ACTIVE_STATUSES.includes(b.status) && !isExpired(b));
    const closed = bookings.filter(b => !ACTIVE_STATUSES.includes(b.status) || isExpired(b));
    active.sort((a, b) => `${a.date}${a.time || "00:00"}`.localeCompare(`${b.date}${b.time || "00:00"}`));
    closed.sort((a, b) => `${b.date}${b.time || "00:00"}`.localeCompare(`${a.date}${a.time || "00:00"}`));
    return { hero: active[0] || null, upcoming: active.slice(1), past: closed };
  }, [bookings]);

  return (
    <AppShell>
      <PageShell title="My Appointments">

        {bookingsLoading ? (
          <div className="card" style={{ padding: 40, textAlign: "center", color: "var(--color-text-muted)" }}>Loading…</div>
        ) : (
          <>
            {hero && <HeroAppointment b={hero} ownAwpid={ownAwpid} onCancel={handleCancel} onReschedule={setRescheduleTarget} />}

            {/* CTA into the browse flow — proper hero card gradient */}
            <div style={{
              marginBottom: 22, borderRadius: "var(--radius-card)", overflow: "hidden",
              background: "linear-gradient(135deg, var(--color-hero) 0%, var(--color-hero-2) 100%)",
              display: "flex", alignItems: "center", justifyContent: "space-between",
              gap: 16, flexWrap: "wrap", position: "relative",
            }}>
              <div style={{ padding: "20px 24px", position: "relative" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 6, fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 17, marginBottom: 4, color: "var(--color-accent)" }}>
                  <Sparkles size={16} style={{ color: "var(--color-accent)" }} /> Find a doctor
                </div>
                <div style={{ fontSize: 13, color: "var(--color-hero-muted)", marginBottom: 10 }}>
                  Find a doctor near you and book your consultation in a couple of taps.
                </div>
                <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
                  {stats?.doctors > 0 && (
                    <span style={{ fontSize: 12, fontWeight: 600, color: "var(--color-hero-muted)", display: "flex", alignItems: "center", gap: 5 }}>
                      <Users2 size={13} style={{ color: "var(--color-hero-muted)" }} /> {stats.doctors} doctors available
                    </span>
                  )}
                  {stats?.hospitals > 0 && (
                    <span style={{ fontSize: 12, fontWeight: 600, color: "var(--color-hero-muted)", display: "flex", alignItems: "center", gap: 5 }}>
                      <Building2 size={13} style={{ color: "var(--color-hero-muted)" }} /> {stats.hospitals} hospitals on the platform
                    </span>
                  )}
                  <span style={{ fontSize: 12, fontWeight: 600, color: "var(--color-hero-muted)", display: "flex", alignItems: "center", gap: 5 }}>
                    <CircleCheck size={13} style={{ color: "var(--color-hero-muted)" }} /> Instant confirmation
                  </span>
                </div>
              </div>
              <div style={{ padding: "20px 24px", position: "relative", flexShrink: 0 }}>
                <Link
                  to={ROUTES.PATIENT.HOSPITALS}
                  style={{
                    display: "inline-flex", alignItems: "center", gap: 6, padding: "10px 24px",
                    background: "linear-gradient(135deg, var(--color-accent) 0%, var(--color-warning) 100%)",
                    color: "#fff", fontWeight: 700, fontSize: 13, borderRadius: "var(--radius-button)",
                    textDecoration: "none", whiteSpace: "nowrap",
                  }}
                >
                  Find a doctor <ChevronRight size={15} />
                </Link>
              </div>
            </div>

            {hero && (
              <div style={{
                display: "flex", gap: 10, alignItems: "flex-start", padding: "12px 16px",
                borderRadius: 10, background: "var(--color-surface)", border: "1px solid var(--color-border)", marginBottom: 22,
                fontSize: 12, color: "var(--color-text-secondary)", lineHeight: 1.7,
              }}>
                <MapPin size={14} style={{ flexShrink: 0, marginTop: 1, color: "var(--color-text-muted)" }} />
                <div>
                  <strong style={{ color: "var(--color-text)" }}>Before your visit:</strong> carry any previous
                  medical reports, bring a valid ID, and try to arrive about 10 minutes before your slot.
                  Clinic hours are typically 9:00 AM – 1:00 PM and 2:00 PM – 6:00 PM.
                  {" "}Need to cancel or reschedule? Use the options on your appointment card below.
                </div>
              </div>
            )}

            {bookings.length === 0 ? (
              <div className="card" style={{ padding: 44, textAlign: "center" }}>
                <div style={{ fontFamily: "var(--font-display)", fontSize: 18, fontWeight: 600, marginBottom: 6 }}>
                  No appointments yet
                </div>
                <div style={{ fontSize: 13, color: "var(--color-text-muted)" }}>
                  Book your first appointment above to see it here.
                </div>
              </div>
            ) : (
              <>
                {upcoming.length > 0 && (
                  <div style={{ marginBottom: 24 }}>
                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
                      <span className="dot-label dot-label--green" style={{ fontSize: 11, letterSpacing: "0.08em" }}>
                        Upcoming Appointments ({upcoming.length})
                      </span>
                      <button className="btn-outline" style={{ fontSize: 12, padding: "5px 14px" }} onClick={refetch}>
                        Refresh
                      </button>
                    </div>
                    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: 14 }}>
                      {upcoming.map(b => (
                        <AppointmentCard key={b.id} b={b} ownAwpid={ownAwpid}
                          onCancel={handleCancel} onReschedule={setRescheduleTarget} />
                      ))}
                    </div>
                  </div>
                )}

                {past.length > 0 && (
                  <div>
                    <span className="dot-label dot-label--gold" style={{ marginBottom: 10, display: "inline-block", fontSize: 11, letterSpacing: "0.08em" }}>
                      Past Visits ({past.length})
                    </span>
                    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: 14 }}>
                      {past.map(b => (
                        <AppointmentCard key={b.id} b={b} ownAwpid={ownAwpid} onOpenPrescriptions={() => navigate(ROUTES.PATIENT.PRESCRIPTIONS)} />
                      ))}
                    </div>
                  </div>
                )}

                {!hero && upcoming.length === 0 && past.length === 0 && bookings.length > 0 && (
                  // Shouldn't normally happen (every booking falls into one bucket),
                  // but keep a fallback rather than silently showing nothing.
                  <div className="card" style={{ padding: 32, textAlign: "center", color: "var(--color-text-muted)" }}>
                    No appointments to show.
                  </div>
                )}

                {hasMoreBookings && (
                  <div style={{ padding: 16, textAlign: "center" }}>
                    <button
                      onClick={loadMoreBookings}
                      disabled={bookingsLoadingMore}
                      className="btn-outline"
                      style={{ padding: "8px 20px", fontSize: 12 }}>
                      {bookingsLoadingMore ? "Loading…" : `Load more (${bookingsPagination?.total_count - bookings.length} more)`}
                    </button>
                  </div>
                )}
              </>
            )}
          </>
        )}

        {rescheduleTarget && (
          <RescheduleModal
            booking={rescheduleTarget}
            onClose={() => setRescheduleTarget(null)}
            onDone={refetch}
          />
        )}
      </PageShell>
    </AppShell>
  );
}
