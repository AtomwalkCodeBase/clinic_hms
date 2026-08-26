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
import { useMemo, useState, useEffect, useCallback } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  Building2, Calendar, Clock, CircleCheck, ChevronRight, Stethoscope,
  XCircle, Users2, FileText, MapPin, CalendarClock, Receipt, Download,
  Search, Filter, X, Plus,
} from "lucide-react";
import { AppShell }  from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import { usePaginatedList } from "../../hooks/usePaginatedList";
import { useApi } from "../../hooks/useApi";
import { useToast } from "../../hooks/useToast";
import apiClient     from "../../services/api.client";
import API_ENDPOINTS from "../../config/api.config";
import ROUTES        from "../../config/routes.config";
import { openDataUrlInNewTab } from "../../utils/fileViewer";

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

const INVOICE_STATUS_META = {
  issued:         { label: "Issued",         color: "var(--color-info)",    bg: "var(--color-info-light)" },
  paid:           { label: "Paid",           color: "var(--color-success)", bg: "var(--color-success-light)" },
  partially_paid: { label: "Partially Paid", color: "var(--color-accent)",  bg: "var(--color-accent-light)" },
  cancelled:      { label: "Cancelled",      color: "var(--color-error)",   bg: "var(--color-error-light)" },
};

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

function getInitials(rawName) {
  const name = (rawName || "").replace(/^dr\.?\s+/i, "").trim();
  if (!name) return "Dr";
  const parts = name.split(/\s+/).filter(Boolean);
  return ((parts[0]?.[0] || "") + (parts[1]?.[0] || "")).toUpperCase() || "Dr";
}

// Real address text (hospital + city/state, whatever we actually have) piped
// into a Google Maps search link — not a fabricated pin/coordinate, just the
// standard "search this address" pattern, so "View on map" only appears when
// there's real location text to search for.
function mapsUrl(hospital, city, state) {
  const q = [hospital, city, state].filter(Boolean).join(", ");
  if (!q) return null;
  return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(q)}`;
}

function formatBookedOn(iso) {
  if (!iso) return null;
  try {
    return new Date(iso).toLocaleString("en-IN", {
      day: "2-digit", month: "short", year: "numeric", hour: "numeric", minute: "2-digit",
    });
  } catch {
    return null;
  }
}

// Doctor photo when the hospital uploaded one (same source as "Find
// Doctors"), otherwise a colored initials circle — never a fabricated stock
// photo or placeholder avatar.
function DoctorAvatar({ photo, name, size = 44 }) {
  if (photo) {
    return (
      <img
        src={photo} alt="" style={{ width: size, height: size, borderRadius: "50%", objectFit: "cover", flexShrink: 0 }}
      />
    );
  }
  return (
    <div style={{
      width: size, height: size, borderRadius: "50%", flexShrink: 0,
      display: "flex", alignItems: "center", justifyContent: "center",
      background: "linear-gradient(135deg, var(--color-hero) 0%, var(--color-hero-2) 100%)",
      color: "#fff", fontWeight: 800, fontSize: Math.round(size * 0.38), fontFamily: "var(--font-display)",
    }}>
      {getInitials(name)}
    </div>
  );
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

// `variant="buttons"` renders real outlined buttons (used in the hero
// card's "Appointment for" column, next to the reference layout's
// Reschedule/Cancel pair); the default `variant="links"` keeps the plain
// text-link treatment used inline in list rows.
function AppointmentActions({ b, onCancel, onReschedule, size = 12, direction = "row", variant = "links" }) {
  const canCancel = CANCELLABLE_STATUSES.includes(b.status);
  const canReschedule = RESCHEDULABLE_STATUSES.includes(b.status);
  if (!canCancel && !canReschedule) return null;
  if (variant === "buttons") {
    return (
      <div style={{ display: "flex", flexDirection: direction, gap: 8 }}>
        {canReschedule && (
          <button
            onClick={() => onReschedule(b)}
            className="btn-outline"
            style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 5, cursor: "pointer", fontSize: size, fontWeight: 700, padding: "7px 14px" }}
          >
            <CalendarClock size={size + 1} /> Reschedule
          </button>
        )}
        {canCancel && (
          <button
            onClick={() => onCancel(b)}
            style={{
              display: "flex", alignItems: "center", justifyContent: "center", gap: 5, cursor: "pointer",
              fontSize: size, fontWeight: 700, padding: "7px 14px", borderRadius: "var(--radius-button)",
              border: "1.5px solid var(--color-error)", background: "transparent", color: "var(--color-error)",
            }}
          >
            <XCircle size={size + 1} /> Cancel
          </button>
        )}
      </div>
    );
  }
  return (
    <div style={{ display: "flex", flexDirection: direction, gap: direction === "column" ? 10 : 16 }}>
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
  // Blank patient_name means "the account owner, booked before family
  // members existed" (see FamilyTag) — either way, resolve to a real label
  // so "who is this for" is never left to a small, easy-to-miss badge.
  const isSelf = !b.patient_name || (ownAwpid && b.patient_awpid === ownAwpid);
  const dateObj = new Date(b.date + "T00:00:00");
  const dateWord = relativeDate(b.date);
  return (
    <div className="card" style={{ padding: 0, overflow: "hidden", marginBottom: 22 }}>
      {/* Narrow-window/mobile tightening — the desktop padding/gaps below
          are sized for a wide card; at phone widths the same values leave
          large, empty-looking gaps between short wrapped lines. Scoped via
          classNames + !important since the rest of this card is inline-
          styled (same pattern as RecordsPage.jsx's vax-stats-grid). */}
      <style>{`
        @media (max-width: 640px) {
          .hero-top-grid  { flex-direction: column !important; }
          .hero-who-panel { width: 100% !important; margin-top: 10px !important; margin-left: 0 !important; border-left: none !important; padding-left: 0 !important; }
          .hero-doctor-panel, .hero-meta-panel { border-left: none !important; padding-left: 0 !important; }
        }
        @media (max-width: 520px) {
          .hero-content     { padding: 16px 16px !important; }
          .hero-top-grid    { gap: 12px !important; margin-bottom: 14px !important; }
          .hero-room-tag    { font-size: 11px !important; padding: 3px 8px !important; }
          .hero-token-badge { padding: 4px 10px !important; }
          .hero-token-number{ font-size: 16px !important; }
          .hero-complaint   { margin-bottom: 12px !important; }
          .hero-queue-box   { padding: 10px 12px !important; gap: 12px !important; margin-bottom: 12px !important; }
          .hero-timeline    { gap: 5px !important; margin-bottom: 4px !important; }
        }
      `}</style>
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

      <div className="hero-content" style={{ padding: "22px 24px" }}>
        {/* Horizontal layout: date box, doctor/hospital info, and "who this
            is for" all readable in one glance instead of stacked rows. */}
        <div className="hero-top-grid" style={{
          display: "flex", alignItems: "flex-start",
          flexWrap: "wrap", gap: 24, marginBottom: 18,
        }}>
          <div style={{
            display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
            width: 76, padding: "10px 6px", borderRadius: 12, flexShrink: 0, color: "#fff",
            background: "linear-gradient(135deg, var(--color-hero) 0%, var(--color-hero-2) 100%)",
          }}>
            <div style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.06em", opacity: 0.85 }}>
              {dateWord === "Today" || dateWord === "Tomorrow" ? dateWord : dateObj.toLocaleDateString("en-IN", { month: "short" })}
            </div>
            <div style={{ fontFamily: "var(--font-display)", fontWeight: 800, fontSize: 26, lineHeight: 1.1 }}>
              {dateObj.getDate()}
            </div>
            {b.time && <div style={{ fontSize: 10.5, fontWeight: 700, opacity: 0.9, marginTop: 2 }}>{formatTime12h(b.time)}</div>}
          </div>

          {/* Appointment meta — the time/status/booking-reference block,
              packed tight against the date box (not off in the middle of
              a stretchy gap). */}
          <div className="hero-meta-panel" style={{
            flexShrink: 0, borderLeft: "1px solid var(--color-border)", paddingLeft: 24, minWidth: 170,
          }}>
            <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: "0.06em", textTransform: "uppercase", color: "var(--color-text-muted)", marginBottom: 6 }}>
              Next Appointment
            </div>
            {b.time && (
              <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8, flexWrap: "wrap" }}>
                <span style={{ fontFamily: "var(--font-display)", fontWeight: 800, fontSize: 22 }}>{formatTime12h(b.time)}</span>
                <StatusBadge status={b.status} />
              </div>
            )}
            <div style={{ fontSize: 11.5, color: "var(--color-text-muted)", lineHeight: 1.8 }}>
              <div>Booking ID<br /><strong style={{ color: "var(--color-text-secondary)" }}>{b.id != null ? `#${b.id}` : "—"}</strong></div>
              {formatBookedOn(b.booked_at) && <div style={{ marginTop: 4 }}>Booked on<br />{formatBookedOn(b.booked_at)}</div>}
            </div>
          </div>

          {/* Doctor detail — photo/initials, specialisation, hospital +
              city/state, a real "View on map" link built from that address
              text. Everything here is a real field from PortalMyBookingsView;
              nothing invented (no rating, no fabricated address beyond
              city/state). */}
          <div className="hero-doctor-panel" style={{
            display: "flex", gap: 12, alignItems: "flex-start", minWidth: 0,
            borderLeft: "1px solid var(--color-border)", paddingLeft: 24,
          }}>
            <DoctorAvatar photo={b.doctor_photo} name={b.doctor} size={46} />
            <div style={{ minWidth: 0 }}>
              <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 2 }}>{formatDoctorName(b.doctor)}</div>
              {b.doctor_specialisation && (
                <div style={{ fontSize: 12.5, color: "var(--color-text-muted)", marginBottom: 4 }}>{b.doctor_specialisation}</div>
              )}
              <div className="hero-hospital-row" style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, color: "var(--color-text-secondary)", flexWrap: "wrap" }}>
                <Building2 size={13} />
                {b.hospital}{(b.hospital_city || b.hospital_state) ? `, ${[b.hospital_city, b.hospital_state].filter(Boolean).join(", ")}` : ""}
                {b.room_name && (
                  <span className="hero-room-tag" style={{
                    display: "inline-flex", alignItems: "center", gap: 4, fontSize: 11.5, fontWeight: 700,
                    color: "var(--color-primary)", padding: "3px 9px", borderRadius: 20, background: "var(--color-primary-light)",
                  }}>
                    <MapPin size={11} /> {b.room_name}{b.floor ? ` · Fl ${b.floor}` : ""}
                  </span>
                )}
              </div>
              {mapsUrl(b.hospital, b.hospital_city, b.hospital_state) && (
                <a
                  href={mapsUrl(b.hospital, b.hospital_city, b.hospital_state)} target="_blank" rel="noreferrer"
                  style={{ display: "inline-flex", alignItems: "center", gap: 3, marginTop: 6, fontSize: 11.5, fontWeight: 700, color: "var(--color-primary)", textDecoration: "none" }}
                >
                  <MapPin size={11} /> View on map
                </a>
              )}
            </div>
          </div>

          {/* "Who this is for" panel — pushed to the far right edge of the
              row (margin-left: auto) while the first three sections stay
              packed together on the left, instead of everything spreading
              out evenly with dead space in between. */}
          <div className="hero-who-panel" style={{
            flexShrink: 0, minWidth: 170, marginLeft: "auto",
            borderLeft: "1px solid var(--color-border)", paddingLeft: 24,
            display: "flex", flexDirection: "column", gap: 12,
          }}>
            <div>
              <div style={{ fontSize: 10, fontWeight: 700, color: "var(--color-text-muted)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 6 }}>
                Appointment for
              </div>
              <div style={{
                display: "flex", alignItems: "center", gap: 5, fontSize: 14, fontWeight: 800,
                color: isSelf ? "var(--color-text)" : "var(--color-accent)",
                marginBottom: b.token_number != null ? 10 : 0,
              }}>
                <Users2 size={13} style={{ flexShrink: 0 }} />
                {isSelf ? `You${b.patient_name ? ` (${b.patient_name})` : ""}` : b.patient_name}
              </div>
              {b.token_number != null && (
                <div className="hero-token-badge" style={{
                  display: "inline-flex", alignItems: "center", gap: 6, padding: "5px 14px", borderRadius: 12,
                  background: "#FFF8E1", border: "1.5px solid color-mix(in srgb, var(--color-accent) 40%, transparent)",
                }}>
                  <span style={{ fontSize: 10, fontWeight: 700, color: "var(--color-warning)", textTransform: "uppercase", letterSpacing: "0.06em" }}>Token</span>
                  <span className="hero-token-number" style={{ fontFamily: "var(--font-display)", fontWeight: 800, fontSize: 18, color: "var(--color-accent)", lineHeight: 1 }}>
                    #{b.token_number}
                  </span>
                </div>
              )}
            </div>
            {/* Reschedule/Cancel live right under "Appointment for" — same
                spot the reference layout puts them, instead of a separate
                action row at the bottom of the whole card. */}
            <AppointmentActions b={b} onCancel={onCancel} onReschedule={onReschedule} size={12} direction="column" variant="buttons" />
          </div>
        </div>

        {b.chief_complaint && (
          <div className="hero-complaint" style={{
            fontSize: 13, color: "var(--color-text-secondary)", marginBottom: 16, fontStyle: "italic",
            borderLeft: "3px solid var(--color-primary)", paddingLeft: 12,
          }}>
            "{b.chief_complaint}"
          </div>
        )}

        {(b.people_ahead != null || b.now_serving_token != null) && (
          <div className="hero-queue-box" style={{
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
        <div className="hero-timeline" style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 8 }}>
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
      </div>
    </div>
  );
}

// Table-row-style list item — a scannable strip (date, doctor/hospital,
// token, status, actions) rather than a tall card, so a list of many
// appointments reads like a list rather than a wall of tiles.
function AppointmentRow({ b, onOpenPrescriptions, ownAwpid, onCancel, onReschedule }) {
  const expired = isExpired(b);
  const displayStatus = expired ? "expired" : b.status;
  const isPast = b.status === "done" || b.status === "cancelled" || b.status === "no_show" || expired;
  const meta = STATUS_META[displayStatus] || STATUS_META.scheduled;
  const dateObj = new Date(b.date + "T00:00:00");

  return (
    <div className="appt-row card" style={{
      padding: "14px 16px", display: "flex", alignItems: "center", gap: 16, flexWrap: "wrap",
      borderLeft: `4px solid ${meta.color}`,
    }}>
      <div style={{
        display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
        width: 52, flexShrink: 0, padding: "6px 4px", borderRadius: 10, background: meta.bg,
      }}>
        <div style={{ fontSize: 9.5, fontWeight: 700, textTransform: "uppercase", color: meta.color }}>
          {dateObj.toLocaleDateString("en-IN", { month: "short" })}
        </div>
        <div style={{ fontFamily: "var(--font-display)", fontWeight: 800, fontSize: 18, color: meta.color, lineHeight: 1.1 }}>
          {dateObj.getDate()}
        </div>
      </div>

      <div className="appt-row-main" style={{ flex: "1 1 240px", minWidth: 0, display: "flex", gap: 10, alignItems: "flex-start" }}>
        <DoctorAvatar photo={b.doctor_photo} name={b.doctor} size={36} />
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <span style={{ fontWeight: 700, fontSize: 14 }}>{formatDoctorName(b.doctor)}</span>
            <FamilyTag b={b} ownAwpid={ownAwpid} />
          </div>
          {b.doctor_specialisation && (
            <div style={{ fontSize: 11.5, color: "var(--color-text-muted)" }}>{b.doctor_specialisation}</div>
          )}
          <div style={{ display: "flex", flexWrap: "wrap", gap: 10, fontSize: 12, color: "var(--color-text-muted)", marginTop: 3 }}>
            <span style={{ display: "flex", alignItems: "center", gap: 4 }}><Building2 size={11} /> {b.hospital}</span>
            {b.time && <span style={{ display: "flex", alignItems: "center", gap: 4 }}><Clock size={11} /> {formatTime12h(b.time)}</span>}
            {b.room_name && <span style={{ display: "flex", alignItems: "center", gap: 4 }}><MapPin size={11} /> {b.room_name}{b.floor ? ` · Fl ${b.floor}` : ""}</span>}
          </div>
          {b.chief_complaint && (
            <div style={{ fontSize: 12, color: "var(--color-text-secondary)", marginTop: 5, fontStyle: "italic" }}>
              "{b.chief_complaint}"
            </div>
          )}
          {b.status === "no_show" && (
            <div style={{ fontSize: 11.5, color: "var(--color-error)", marginTop: 5 }}>
              Missed check-in — marked as not completed.
            </div>
          )}
          {expired && (
            <div style={{ fontSize: 11.5, color: "var(--color-text-muted)", marginTop: 5 }}>
              Day passed without the hospital marking this complete.
            </div>
          )}
        </div>
      </div>

      {b.token_number != null && (
        <div style={{ textAlign: "center", flexShrink: 0 }}>
          <div style={{ fontSize: 9.5, fontWeight: 700, color: "var(--color-text-muted)", textTransform: "uppercase" }}>Token</div>
          <div style={{ fontFamily: "var(--font-display)", fontWeight: 800, fontSize: 15, color: "var(--color-accent)" }}>#{b.token_number}</div>
        </div>
      )}

      <div className="appt-row-actions" style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 8, flexShrink: 0, marginLeft: "auto" }}>
        <StatusBadge status={displayStatus} />
        {!isPast && <AppointmentActions b={b} onCancel={onCancel} onReschedule={onReschedule} size={11.5} />}
        {isPast && b.status === "done" && (
          <button
            onClick={onOpenPrescriptions}
            style={{
              display: "flex", alignItems: "center", gap: 4, background: "none", border: "none", cursor: "pointer",
              fontSize: 11.5, fontWeight: 700, color: "var(--color-primary)", padding: 0,
            }}
          >
            <FileText size={12} /> Prescription
          </button>
        )}
        {isPast && b.tenant_id && (
          <Link
            to={b.doctor_id
              ? ROUTES.PATIENT.DOCTOR_PROFILE(b.tenant_id, b.doctor_id)
              : ROUTES.PATIENT.HOSPITAL_DOCTORS(b.tenant_id)}
            style={{
              display: "flex", alignItems: "center", gap: 4,
              fontSize: 11.5, fontWeight: 700, color: "var(--color-primary)",
            }}
          >
            Book follow-up <ChevronRight size={12} />
          </Link>
        )}
      </div>
    </div>
  );
}

function StatCard({ icon: Icon, label, value, color, onClick, active }) {
  const Comp = onClick ? "button" : "div";
  return (
    <Comp
      onClick={onClick}
      className="card"
      style={{
        padding: "14px 16px", display: "flex", alignItems: "center", gap: 12,
        textAlign: "left", cursor: onClick ? "pointer" : "default", width: "100%",
        border: active ? `1.5px solid ${color}` : undefined,
        background: active ? `color-mix(in srgb, ${color} 8%, var(--color-surface))` : undefined,
        font: "inherit",
      }}
    >
      <span style={{
        width: 36, height: 36, borderRadius: 10, flexShrink: 0,
        display: "flex", alignItems: "center", justifyContent: "center",
        background: `color-mix(in srgb, ${color} 15%, transparent)`, color,
      }}>
        <Icon size={17} />
      </span>
      <div>
        <div style={{ fontFamily: "var(--font-display)", fontWeight: 800, fontSize: 20, lineHeight: 1.1 }}>{value}</div>
        <div style={{ fontSize: 11.5, color: "var(--color-text-muted)", fontWeight: 600 }}>{label}</div>
      </div>
    </Comp>
  );
}

// Quick-glance counts, doubling as tab shortcuts — clicking a card jumps
// straight to that tab. "Total" stays informational since there's no
// single "everything" tab to jump to.
function StatsRow({ stats, activeTab, onSetTab }) {
  const cards = [
    { key: "upcoming",  label: "Upcoming",           value: stats.upcomingCount,  color: "var(--color-primary)", icon: CalendarClock, tab: "upcoming" },
    { key: "past",      label: "Past Visits",        value: stats.pastCount,      color: "var(--color-success)", icon: CircleCheck,   tab: "past" },
    { key: "cancelled", label: "Cancelled",          value: stats.cancelledCount, color: "var(--color-error)",   icon: XCircle,        tab: "cancelled" },
    { key: "total",     label: "Total Appointments", value: stats.totalCount,     color: "var(--color-accent)",  icon: Calendar },
  ];
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 12, marginBottom: 18 }}>
      {cards.map(c => (
        <StatCard
          key={c.key} icon={c.icon} label={c.label} value={c.value} color={c.color}
          active={c.tab ? activeTab === c.tab : false}
          onClick={c.tab ? () => onSetTab(c.tab) : undefined}
        />
      ))}
    </div>
  );
}

const TABS = [
  { key: "upcoming",  label: "Upcoming" },
  { key: "past",      label: "Past" },
  { key: "cancelled", label: "Cancelled" },
];

function BillRow({ inv }) {
  const { toastApiError } = useToast();
  const [downloading, setDownloading] = useState(false);
  const meta = INVOICE_STATUS_META[inv.status] || { label: inv.status, color: "var(--color-text-muted)", bg: "var(--color-border)" };

  async function downloadReceipt() {
    const win = window.open("", "_blank");
    setDownloading(true);
    try {
      const res = await apiClient.get(API_ENDPOINTS.PORTAL.INVOICE_RECEIPT(inv.tenant_db, inv.id));
      const data = res.data?.data || res.data;
      if (data?.file_data) {
        openDataUrlInNewTab(win, data.file_data);
      } else if (win) {
        win.close();
      }
    } catch (err) {
      toastApiError(err, "Could not generate the receipt.");
      if (win) win.close();
    } finally {
      setDownloading(false);
    }
  }

  return (
    <div className="card" style={{
      padding: "14px 16px", display: "flex", alignItems: "center", justifyContent: "space-between",
      gap: 12, flexWrap: "wrap",
    }}>
      <div style={{ minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <span style={{ fontWeight: 700, fontSize: 13.5 }}>{inv.invoice_number}</span>
          <span style={{
            fontSize: 10.5, fontWeight: 700, padding: "3px 9px", borderRadius: 20,
            background: meta.bg, color: meta.color,
          }}>
            {meta.label}
          </span>
        </div>
        <div style={{ fontSize: 12, color: "var(--color-text-muted)", marginTop: 3, display: "flex", alignItems: "center", gap: 4 }}>
          <Building2 size={11} /> {inv.hospital}
        </div>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 18 }}>
        <div style={{ textAlign: "right" }}>
          <div style={{ fontWeight: 700, fontSize: 14, fontFamily: "var(--font-display)" }}>₹{inv.total_amount}</div>
          {inv.status === "partially_paid" && (
            <div style={{ fontSize: 11, color: "var(--color-text-muted)" }}>₹{inv.paid_amount} paid</div>
          )}
        </div>
        <button
          onClick={downloadReceipt}
          disabled={downloading}
          style={{
            display: "flex", alignItems: "center", gap: 5, background: "none", border: "none", cursor: "pointer",
            fontSize: 12, fontWeight: 700, color: "var(--color-primary)", padding: 0,
          }}
        >
          <Download size={13} /> {downloading ? "Preparing…" : "Receipt"}
        </button>
      </div>
    </div>
  );
}

function BillsSection() {
  const {
    items: invoices, isLoading, pagination, loadMore, isLoadingMore, hasMore,
  } = usePaginatedList(API_ENDPOINTS.PORTAL.INVOICES, { pageSize: 10 });

  if (isLoading || invoices.length === 0) return null;

  return (
    <div style={{ marginTop: 24 }}>
      <span className="dot-label dot-label--gold" style={{ marginBottom: 10, display: "inline-block", fontSize: 11, letterSpacing: "0.08em" }}>
        <Receipt size={12} style={{ verticalAlign: -2, marginRight: 4 }} />
        My Bills ({invoices.length})
      </span>
      <div style={{ display: "grid", gap: 10 }}>
        {invoices.map(inv => <BillRow key={`${inv.tenant_db}-${inv.id}`} inv={inv} />)}
      </div>
      {hasMore && (
        <div style={{ padding: 16, textAlign: "center" }}>
          <button
            onClick={loadMore}
            disabled={isLoadingMore}
            className="btn-outline"
            style={{ padding: "8px 20px", fontSize: 12 }}>
            {isLoadingMore ? "Loading…" : `Load more (${pagination?.total_count - invoices.length} more)`}
          </button>
        </div>
      )}
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
  } = usePaginatedList(API_ENDPOINTS.PORTAL.MY_BOOKINGS, { pageSize: 20, pollMs: 20000 });

  const { data: profile } = useApi(API_ENDPOINTS.PORTAL.PROFILE);
  const ownAwpid = profile?.awpid;

  const [rescheduleTarget, setRescheduleTarget] = useState(null);
  const [activeTab, setActiveTab] = useState("upcoming");

  // Search + filter — applied within whichever tab is active. The hero
  // card always shows the true next active appointment regardless of
  // filters (it's a status callout, not a list item).
  const [search, setSearch] = useState("");
  const [showFilters, setShowFilters] = useState(false);
  const [familyFilter, setFamilyFilter] = useState(""); // patient_awpid, "" = everyone
  const [doctorFilter, setDoctorFilter] = useState("");
  const [hospitalFilter, setHospitalFilter] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  const familyOptions = useMemo(() => {
    const seen = new Map();
    bookings.forEach(b => {
      if (b.patient_awpid && !seen.has(b.patient_awpid)) {
        seen.set(b.patient_awpid, b.patient_name || b.patient_awpid);
      }
    });
    return [...seen.entries()].sort((a, b) => a[1].localeCompare(b[1]));
  }, [bookings]);

  const doctorOptions = useMemo(
    () => [...new Set(bookings.map(b => b.doctor).filter(Boolean))].sort(),
    [bookings]
  );
  const hospitalOptions = useMemo(
    () => [...new Set(bookings.map(b => b.hospital).filter(Boolean))].sort(),
    [bookings]
  );

  const hasActiveFilters = !!(search || familyFilter || doctorFilter || hospitalFilter || dateFrom || dateTo);

  const matchesFilters = useCallback((b) => {
    if (familyFilter && b.patient_awpid !== familyFilter) return false;
    if (doctorFilter && b.doctor !== doctorFilter) return false;
    if (hospitalFilter && b.hospital !== hospitalFilter) return false;
    if (dateFrom && b.date < dateFrom) return false;
    if (dateTo && b.date > dateTo) return false;
    if (search) {
      const q = search.toLowerCase();
      const haystack = [
        b.doctor, b.hospital, b.chief_complaint, b.patient_name, b.doctor_specialisation,
        b.status, b.room_name, b.token_number != null ? `#${b.token_number}` : "",
      ].filter(Boolean).join(" ").toLowerCase();
      if (!haystack.includes(q)) return false;
    }
    return true;
  }, [familyFilter, doctorFilter, hospitalFilter, dateFrom, dateTo, search]);

  function clearFilters() {
    setSearch(""); setFamilyFilter("");
    setDoctorFilter(""); setHospitalFilter(""); setDateFrom(""); setDateTo("");
  }

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

  // Three real buckets, straight off the same status field the rest of the
  // app trusts: active-and-not-expired ("upcoming"), cancelled/no_show
  // ("cancelled"), and everything else closed out ("past" — done, or
  // expired without ever being closed by the hospital).
  const { hero, upcoming, past, cancelled } = useMemo(() => {
    const active = bookings.filter(b => ACTIVE_STATUSES.includes(b.status) && !isExpired(b));
    const closed = bookings.filter(b => !ACTIVE_STATUSES.includes(b.status) || isExpired(b));
    const cancelledList = closed.filter(b => b.status === "cancelled" || b.status === "no_show");
    const pastList = closed.filter(b => b.status !== "cancelled" && b.status !== "no_show");
    active.sort((a, b) => `${a.date}${a.time || "00:00"}`.localeCompare(`${b.date}${b.time || "00:00"}`));
    pastList.sort((a, b) => `${b.date}${b.time || "00:00"}`.localeCompare(`${a.date}${a.time || "00:00"}`));
    cancelledList.sort((a, b) => `${b.date}${b.time || "00:00"}`.localeCompare(`${a.date}${a.time || "00:00"}`));
    return { hero: active[0] || null, upcoming: active.slice(1), past: pastList, cancelled: cancelledList };
  }, [bookings]);

  // Quick-glance counts for the stat-card row — derived client-side from
  // the same bookings list already loaded for the page (no separate
  // aggregate endpoint exists, and doesn't need to: this page only ever
  // loads a patient's own bookings, a small list). Total uses the API's
  // real total_count so it stays correct even before every page is loaded.
  const listStats = useMemo(() => ({
    upcomingCount: upcoming.length + (hero ? 1 : 0),
    pastCount: past.length,
    cancelledCount: cancelled.length,
    totalCount: bookingsPagination?.total_count ?? bookings.length,
  }), [upcoming, past, cancelled, hero, bookings, bookingsPagination]);

  // The hero card is a spotlight on "your next visit," not a list item —
  // pulled out of the Upcoming list while unfiltered. With only one active
  // booking, that spotlight IS the whole Upcoming tab, and searching would
  // silently show nothing — so once a filter is active the hero folds back
  // into the searched pool.
  const filteredUpcoming = useMemo(() => {
    const pool = hasActiveFilters && hero ? [hero, ...upcoming] : upcoming;
    return pool.filter(matchesFilters);
  }, [hasActiveFilters, hero, upcoming, matchesFilters]);
  const filteredPast = useMemo(() => past.filter(matchesFilters), [past, matchesFilters]);
  const filteredCancelled = useMemo(() => cancelled.filter(matchesFilters), [cancelled, matchesFilters]);
  const showHeroCard = hero && activeTab === "upcoming" && !hasActiveFilters;

  const activeList = activeTab === "upcoming" ? filteredUpcoming : activeTab === "past" ? filteredPast : filteredCancelled;
  const activeListLabel = activeTab === "upcoming" ? "Upcoming Appointments" : activeTab === "past" ? "Past Appointments" : "Cancelled Appointments";

  return (
    <AppShell>
      <PageShell
        title="My Appointments"
        action={
          <Link
            to={ROUTES.PATIENT.HOSPITALS}
            className="btn-primary"
            style={{ display: "inline-flex", alignItems: "center", gap: 6, textDecoration: "none", padding: "10px 18px" }}
          >
            <Plus size={15} /> Book New Appointment
          </Link>
        }
      >

        {bookingsLoading ? (
          <div className="card" style={{ padding: 40, textAlign: "center", color: "var(--color-text-muted)" }}>Loading…</div>
        ) : bookings.length === 0 ? (
          <div className="card" style={{ padding: 44, textAlign: "center" }}>
            <div style={{ fontFamily: "var(--font-display)", fontSize: 18, fontWeight: 600, marginBottom: 6 }}>
              No appointments yet
            </div>
            <div style={{ fontSize: 13, color: "var(--color-text-muted)", marginBottom: 16 }}>
              Book your first appointment to see it here.
            </div>
            <Link to={ROUTES.PATIENT.HOSPITALS} className="btn-primary" style={{ display: "inline-flex", alignItems: "center", gap: 6, textDecoration: "none", padding: "10px 20px" }}>
              <Plus size={14} /> Book New Appointment
            </Link>
          </div>
        ) : (
          <>
            {/* Tab bar — Upcoming / Past / Cancelled, each backed by a real
                status bucket (see the hero/upcoming/past/cancelled useMemo
                above), with counts straight off the same data. */}
            <div style={{ display: "flex", gap: 4, borderBottom: "1px solid var(--color-border)", marginBottom: 20 }}>
              {TABS.map(t => {
                const count = t.key === "upcoming" ? listStats.upcomingCount : t.key === "past" ? listStats.pastCount : listStats.cancelledCount;
                const isActive = activeTab === t.key;
                return (
                  <button
                    key={t.key}
                    onClick={() => setActiveTab(t.key)}
                    style={{
                      background: "none", border: "none", cursor: "pointer", padding: "10px 6px", marginRight: 18,
                      fontSize: 13.5, fontWeight: 700, color: isActive ? "var(--color-primary)" : "var(--color-text-muted)",
                      borderBottom: isActive ? "2.5px solid var(--color-primary)" : "2.5px solid transparent",
                    }}
                  >
                    {t.label} {count > 0 && <span style={{ opacity: 0.7, fontWeight: 600 }}>({count})</span>}
                  </button>
                );
              })}
            </div>

            {showHeroCard && <HeroAppointment b={hero} ownAwpid={ownAwpid} onCancel={handleCancel} onReschedule={setRescheduleTarget} />}

            <StatsRow stats={listStats} activeTab={activeTab} onSetTab={setActiveTab} />

            {showHeroCard && (
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

            {/* Search + filter bar — hospital is the dimension patients
                reach for most, so it sits inline (always visible) rather
                than behind a toggle; the rest (family member, doctor, date
                range) stay in "More filters" since most patients never need
                them. Status isn't filterable here — the active tab is
                already the status bucket. */}
            <div className="card" style={{ padding: 14, marginBottom: 18 }}>
              <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
                <div style={{ position: "relative", flex: "1 1 220px", minWidth: 200 }}>
                  <Search size={14} style={{ position: "absolute", left: 10, top: "50%", transform: "translateY(-50%)", color: "var(--color-text-muted)" }} />
                  <input
                    type="text" className="form-input" placeholder="Search by doctor, hospital or reason…"
                    value={search} onChange={e => setSearch(e.target.value)}
                    style={{ width: "100%", boxSizing: "border-box", paddingLeft: 32 }}
                  />
                </div>
                {hospitalOptions.length > 1 && (
                  <select
                    className="form-input" value={hospitalFilter} onChange={e => setHospitalFilter(e.target.value)}
                    style={{ flex: "0 1 170px", minWidth: 140 }}
                  >
                    <option value="">All Hospitals</option>
                    {hospitalOptions.map(h => <option key={h} value={h}>{h}</option>)}
                  </select>
                )}
                <button
                  className="btn-outline" onClick={() => setShowFilters(v => !v)}
                  style={{ fontSize: 12, padding: "8px 14px", display: "flex", alignItems: "center", gap: 6 }}
                >
                  <Filter size={13} /> Filter {(familyFilter || doctorFilter || dateFrom || dateTo) && <span style={{ color: "var(--color-accent)" }}>•</span>}
                </button>
                <button className="btn-outline" style={{ fontSize: 12, padding: "8px 14px" }} onClick={refetch}>
                  Refresh
                </button>
              </div>

              {showFilters && (
                <div style={{
                  marginTop: 12, paddingTop: 12, borderTop: "1px solid var(--color-border)",
                  display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))", gap: 10,
                }}>
                  {familyOptions.length > 1 && (
                    <div>
                      <label className="stat-label" style={{ display: "block", marginBottom: 4 }}>Family member</label>
                      <select className="form-input" value={familyFilter} onChange={e => setFamilyFilter(e.target.value)} style={{ width: "100%" }}>
                        <option value="">Everyone</option>
                        {familyOptions.map(([awpid, name]) => (
                          <option key={awpid} value={awpid}>{awpid === ownAwpid ? `You (${name})` : name}</option>
                        ))}
                      </select>
                    </div>
                  )}
                  {doctorOptions.length > 1 && (
                    <div>
                      <label className="stat-label" style={{ display: "block", marginBottom: 4 }}>Doctor</label>
                      <select className="form-input" value={doctorFilter} onChange={e => setDoctorFilter(e.target.value)} style={{ width: "100%" }}>
                        <option value="">Any doctor</option>
                        {doctorOptions.map(d => <option key={d} value={d}>{formatDoctorName(d)}</option>)}
                      </select>
                    </div>
                  )}
                  <div>
                    <label className="stat-label" style={{ display: "block", marginBottom: 4 }}>From date</label>
                    <input type="date" className="form-input" value={dateFrom} onChange={e => setDateFrom(e.target.value)} style={{ width: "100%" }} />
                  </div>
                  <div>
                    <label className="stat-label" style={{ display: "block", marginBottom: 4 }}>To date</label>
                    <input type="date" className="form-input" value={dateTo} onChange={e => setDateTo(e.target.value)} style={{ width: "100%" }} />
                  </div>
                  {hasActiveFilters && (
                    <div style={{ display: "flex", alignItems: "flex-end" }}>
                      <button className="btn-outline" onClick={clearFilters} style={{ fontSize: 12, padding: "8px 14px", display: "flex", alignItems: "center", gap: 5 }}>
                        <X size={13} /> Clear
                      </button>
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* Row-list responsive tightening — kept as one shared block
                rather than per-row so it's not duplicated across every
                AppointmentRow instance. */}
            <style>{`
              @media (max-width: 560px) {
                .appt-row-actions { flex-direction: row !important; align-items: center !important; justify-content: space-between !important; width: 100% !important; margin-left: 0 !important; }
              }
            `}</style>

            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
              <span className={`dot-label ${activeTab === "cancelled" ? "dot-label--gold" : "dot-label--green"}`} style={{ fontSize: 11, letterSpacing: "0.08em" }}>
                {activeListLabel.toUpperCase()} ({activeList.length})
              </span>
            </div>

            {activeList.length > 0 ? (
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                {activeList.map(b => (
                  <AppointmentRow
                    key={b.id} b={b} ownAwpid={ownAwpid}
                    onCancel={handleCancel}
                    onReschedule={setRescheduleTarget}
                    onOpenPrescriptions={() => navigate(ROUTES.PATIENT.PRESCRIPTIONS)}
                  />
                ))}
              </div>
            ) : (
              <div className="card" style={{ padding: 32, textAlign: "center", color: "var(--color-text-muted)" }}>
                {hasActiveFilters ? (
                  <>Nothing matches these filters. <button onClick={clearFilters} className="btn-outline" style={{ fontSize: 12, padding: "5px 12px", marginLeft: 8 }}>Clear filters</button></>
                ) : (
                  <>No {activeTab} appointments{activeTab === "upcoming" && !hero ? " — book one to see it here." : "."}</>
                )}
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

            <BillsSection />
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
