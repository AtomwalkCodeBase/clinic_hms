import DependentBadge from "../../../components/common/DependentBadge";
import { User, Cake, CalendarClock, AlertTriangle, Stethoscope, Activity } from "lucide-react";
import { formatYearsMonths } from "../../../utils/age";

// ─── Compact clinical summary header ─────────────────────────────────────────
// A doctor with a full queue shouldn't have to scroll to understand who
// they're seeing. Everything here is real: age/gender/UHID/last-visit come
// from the encounter serializer, allergies and active problems come from
// the same cross-hospital history the sidebar shows, vitals are today's
// own recorded reading.
export function ClinicalSummaryHeader({ enc, history, allergies, activeProblems, vitals, isClosed }) {
  const genderLabel = { M: "Male", F: "Female", O: "Other" }[enc.patient_gender] || null;
  return (
    <div className="card" style={{ padding: "16px 20px", background: "var(--color-primary-light)", border: "1.5px solid var(--color-primary)" }}>
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", flexWrap: "wrap", gap: 14 }}>
        <div style={{ minWidth: 200 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <div style={{ fontFamily: "var(--font-display)", fontSize: 20, fontWeight: 600 }}>{enc.patient_name || "Patient"}</div>
            <DependentBadge patient={enc} />
          </div>
          <div style={{ fontSize: 12, color: "var(--color-text-muted)", marginTop: 3, display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center" }}>
            {(genderLabel || enc.patient_age != null) && (
              <span style={{ display: "flex", alignItems: "center", gap: 3 }}>
                {genderLabel && <><User size={12} /> {genderLabel}</>}
                {genderLabel && enc.patient_age != null && " · "}
                {enc.patient_age != null && <><Cake size={12} /> {formatYearsMonths(enc.patient_age, enc.patient_age_months) || `${enc.patient_age} yrs`}</>}
              </span>
            )}
            <span>· UHID: {enc.patient_uhid || "—"}</span>
            <span>· {enc.encounter_date}</span>
            {enc.patient_last_visit && (
              <span style={{ display: "flex", alignItems: "center", gap: 3 }}>
                <CalendarClock size={12} /> Last visit {new Date(enc.patient_last_visit).toLocaleDateString("en-IN")}
              </span>
            )}
            <span style={{ textTransform: "capitalize", fontWeight: 600, color: isClosed ? "#065F46" : "var(--color-primary)" }}>
              {enc.status}
            </span>
          </div>
        </div>

        {enc.chief_complaint && (
          <div style={{
            background: "#fff", borderRadius: 8, padding: "6px 14px",
            fontSize: 13, fontStyle: "italic", color: "var(--color-text-secondary)",
            border: "1px solid var(--color-border)", maxWidth: 360,
          }}>
            "{enc.chief_complaint}"
          </div>
        )}
      </div>

      <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 12 }}>
        {allergies.length > 0 && (
          <span style={{
            display: "flex", alignItems: "center", gap: 5, fontSize: 11, fontWeight: 700,
            background: "#FEE2E2", color: "#B91C1C", padding: "4px 10px", borderRadius: 20,
          }}>
            <AlertTriangle size={12} /> {allergies.map(a => a.substance).join(", ")}
          </span>
        )}
        {activeProblems.map((p, i) => (
          <span key={i} style={{
            display: "flex", alignItems: "center", gap: 5, fontSize: 11, fontWeight: 700,
            background: "#fff", border: "1px solid var(--color-primary)", color: "var(--color-primary)",
            padding: "4px 10px", borderRadius: 20,
          }}>
            <Stethoscope size={12} /> {p}
          </span>
        ))}
        {vitals && (vitals.systolic_bp || vitals.pulse_rate || vitals.spo2) && (
          <span style={{
            display: "flex", alignItems: "center", gap: 8, fontSize: 11, fontWeight: 600,
            background: "#fff", border: "1px solid var(--color-border)", color: "var(--color-text-secondary)",
            padding: "4px 10px", borderRadius: 20,
          }}>
            <Activity size={12} />
            {vitals.systolic_bp && vitals.diastolic_bp && `BP ${vitals.systolic_bp}/${vitals.diastolic_bp}`}
            {vitals.pulse_rate && `  HR ${vitals.pulse_rate}`}
            {vitals.spo2 && `  SpO₂ ${vitals.spo2}%`}
          </span>
        )}
        {allergies.length === 0 && activeProblems.length === 0 && !vitals && (
          <span style={{ fontSize: 11, color: "var(--color-text-muted)" }}>No known allergies or active problems on record.</span>
        )}
      </div>
    </div>
  );
}
