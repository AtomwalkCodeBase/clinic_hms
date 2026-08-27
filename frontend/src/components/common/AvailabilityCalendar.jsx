/**
 * components/common/AvailabilityCalendar.jsx
 * --------------------------------------------
 * Date picker for the patient booking flow that replaces a plain
 * `<input type="date">`. A native date input has no way to disable
 * specific days of the week, so a patient could freely pick a Sunday for
 * a doctor who never works Sundays — the app already correctly refused to
 * let the booking complete (see PortalSlotListView / _slot_grid, which
 * return an empty slot grid for a day the doctor doesn't work), but the
 * calendar itself gave no visual sign of that until after picking the
 * date. This component greys out and disables non-working weekdays (and
 * out-of-range dates) up front, using the doctor's real weekly schedule
 * (`working_days`, 0=Monday..6=Sunday, from PortalDoctorDetailView).
 *
 * `workingDays === null` means "no schedule configured for this doctor
 * yet" — every day stays selectable, matching the backend's own fallback
 * (_slot_grid uses a generic all-week grid in that case too).
 */
import { useState, useRef, useEffect } from "react";
import { ChevronLeft, ChevronRight, CalendarDays } from "lucide-react";

const DAY_HEADERS = ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"];
const DAY_NAMES   = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

function toISO(d) {
  const y = d.getFullYear(), m = String(d.getMonth() + 1).padStart(2, "0"), day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}
function fromISO(s) {
  const [y, m, d] = s.split("-").map(Number);
  return new Date(y, m - 1, d);
}
// JS Date.getDay(): 0=Sunday..6=Saturday. Backend/DoctorAvailabilitySlot
// convention (Python's date.weekday()): 0=Monday..6=Sunday.
function jsToPyDow(jsDay) {
  return (jsDay + 6) % 7;
}
function formatDisplay(iso) {
  if (!iso) return "";
  const d = fromISO(iso);
  return `${DAY_NAMES[d.getDay()].slice(0, 3)}, ${d.getDate()} ${MONTH_NAMES[d.getMonth()].slice(0, 3)} ${d.getFullYear()}`;
}

export default function AvailabilityCalendar({ value, onChange, min, max, workingDays, doctorLabel }) {
  const [open, setOpen] = useState(false);
  const [viewMonth, setViewMonth] = useState(() => {
    const base = value ? fromISO(value) : (min ? fromISO(min) : new Date());
    return new Date(base.getFullYear(), base.getMonth(), 1);
  });
  const boxRef = useRef(null);

  useEffect(() => {
    function onDocClick(e) {
      if (boxRef.current && !boxRef.current.contains(e.target)) setOpen(false);
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, []);

  const minD = min ? fromISO(min) : null;
  const maxD = max ? fromISO(max) : null;

  function isDisabled(d) {
    if (minD && d < minD) return true;
    if (maxD && d > maxD) return true;
    if (workingDays != null && !workingDays.includes(jsToPyDow(d.getDay()))) return true;
    return false;
  }

  function pick(d) {
    if (isDisabled(d)) return;
    onChange(toISO(d));
    setOpen(false);
  }

  const year = viewMonth.getFullYear(), month = viewMonth.getMonth();
  const firstOfMonth = new Date(year, month, 1);
  const startOffset = firstOfMonth.getDay(); // days to back up to Sunday
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const today = new Date(); today.setHours(0, 0, 0, 0);

  const cells = [];
  for (let i = 0; i < startOffset; i++) cells.push(null);
  for (let day = 1; day <= daysInMonth; day++) cells.push(new Date(year, month, day));

  const canGoPrev = !minD || new Date(year, month, 0) >= new Date(minD.getFullYear(), minD.getMonth(), 1);
  const canGoNext = !maxD || new Date(year, month + 1, 1) <= new Date(maxD.getFullYear(), maxD.getMonth() + 1, 0);

  const unavailableLabel = workingDays != null
    ? `Not available: ${DAY_NAMES.filter((_, i) => !workingDays.includes(jsToPyDow(i))).map(n => n.slice(0, 3)).join(", ") || "none — every day open"}`
    : null;

  return (
    <div ref={boxRef} style={{ position: "relative" }}>
      <button
        type="button"
        className="form-input"
        onClick={() => setOpen(o => !o)}
        style={{
          width: "100%", display: "flex", alignItems: "center", justifyContent: "space-between",
          textAlign: "left", cursor: "pointer", background: "var(--color-surface)",
        }}
      >
        <span>{value ? formatDisplay(value) : "Select a date"}</span>
        <CalendarDays size={15} style={{ color: "var(--color-text-muted)", flexShrink: 0 }} />
      </button>

      {open && (
        <div
          style={{
            position: "absolute", top: "calc(100% + 6px)", left: 0, zIndex: 50,
            background: "var(--color-surface)", border: "1.5px solid var(--color-border)",
            borderRadius: 12, boxShadow: "0 8px 24px rgba(0,0,0,0.12)", padding: 14, width: 280,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
            <button
              type="button" disabled={!canGoPrev}
              onClick={() => setViewMonth(new Date(year, month - 1, 1))}
              style={{
                border: "none", background: "none", padding: 4, borderRadius: 6,
                cursor: canGoPrev ? "pointer" : "not-allowed", color: canGoPrev ? "var(--color-text)" : "var(--color-border)",
              }}
            >
              <ChevronLeft size={16} />
            </button>
            <div style={{ fontSize: 13, fontWeight: 700 }}>{MONTH_NAMES[month]} {year}</div>
            <button
              type="button" disabled={!canGoNext}
              onClick={() => setViewMonth(new Date(year, month + 1, 1))}
              style={{
                border: "none", background: "none", padding: 4, borderRadius: 6,
                cursor: canGoNext ? "pointer" : "not-allowed", color: canGoNext ? "var(--color-text)" : "var(--color-border)",
              }}
            >
              <ChevronRight size={16} />
            </button>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "repeat(7, 1fr)", gap: 2, marginBottom: 2 }}>
            {DAY_HEADERS.map(h => (
              <div key={h} style={{ fontSize: 10, fontWeight: 700, textAlign: "center", color: "var(--color-text-muted)", padding: "4px 0" }}>
                {h}
              </div>
            ))}
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(7, 1fr)", gap: 2 }}>
            {cells.map((d, i) => {
              if (!d) return <div key={`blank-${i}`} />;
              const disabled = isDisabled(d);
              const isSelected = value === toISO(d);
              const isToday = d.getTime() === today.getTime();
              const unavailableDay = workingDays != null && !workingDays.includes(jsToPyDow(d.getDay()));
              return (
                <button
                  key={toISO(d)}
                  type="button"
                  disabled={disabled}
                  title={disabled && unavailableDay ? `${doctorLabel || "Doctor"} isn't available on ${DAY_NAMES[d.getDay()]}s` : undefined}
                  onClick={() => pick(d)}
                  style={{
                    aspectRatio: "1", border: isToday && !isSelected ? "1.5px solid var(--color-primary)" : "1.5px solid transparent",
                    borderRadius: 8, fontSize: 12, fontWeight: isSelected ? 700 : 500,
                    cursor: disabled ? "not-allowed" : "pointer",
                    background: isSelected ? "var(--color-primary)" : "transparent",
                    color: isSelected ? "#fff" : disabled ? "var(--color-text-muted)" : "var(--color-text)",
                    opacity: disabled ? 0.4 : 1,
                    textDecoration: unavailableDay && !isSelected ? "line-through" : "none",
                  }}
                >
                  {d.getDate()}
                </button>
              );
            })}
          </div>

          {unavailableLabel && (
            <div style={{ fontSize: 11, color: "var(--color-text-muted)", marginTop: 10, paddingTop: 10, borderTop: "1px solid var(--color-border)" }}>
              {unavailableLabel}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
