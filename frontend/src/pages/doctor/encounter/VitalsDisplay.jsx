import { classifyBP, classifyVital } from "./vitals";
import { VITAL_BADGE } from "./constants";

export function VitalsDisplay({ vitals }) {
  if (!vitals) {
    return (
      <p style={{ color: "var(--color-text-muted)", fontSize: 13, margin: 0 }}>
        No vitals recorded by nursing staff.
      </p>
    );
  }
  const items = [
    { label: "BP",       value: vitals.systolic_bp && vitals.diastolic_bp ? `${vitals.systolic_bp}/${vitals.diastolic_bp} mmHg` : null,
      status: classifyBP(vitals.systolic_bp, vitals.diastolic_bp) },
    { label: "Pulse",    value: vitals.pulse_rate   ? `${vitals.pulse_rate} bpm`   : null, status: classifyVital("pulse", vitals.pulse_rate) },
    { label: "SpO₂",     value: vitals.spo2         ? `${vitals.spo2}%`             : null, status: classifyVital("spo2", vitals.spo2) },
    { label: "Temp",     value: vitals.temperature  ? `${vitals.temperature}°F`    : null, status: classifyVital("temp", vitals.temperature) },
    { label: "Weight",   value: vitals.weight_kg    ? `${vitals.weight_kg} kg`     : null, status: null },
    { label: "RR",       value: vitals.respiratory_rate ? `${vitals.respiratory_rate}/min` : null, status: classifyVital("rr", vitals.respiratory_rate) },
  ].filter(i => i.value);

  return (
    <div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 10, marginBottom: vitals.nurse_notes ? 12 : 0 }}>
        {items.length === 0
          ? <p style={{ color: "var(--color-text-muted)", fontSize: 13, margin: 0 }}>All vitals not recorded.</p>
          : items.map(({ label, value, status }) => {
            const badge = status && VITAL_BADGE[status];
            return (
              <div key={label} style={{
                background: badge ? badge.bg : "#EFF6FF", borderRadius: 8, padding: "8px 14px",
                textAlign: "center", minWidth: 86,
              }}>
                <div style={{ fontSize: 15, fontWeight: 800, color: badge ? badge.color : "var(--color-primary)" }}>{value}</div>
                <div style={{ fontSize: 10, color: "var(--color-text-muted)", marginTop: 2 }}>{label}</div>
                {badge && (
                  <div style={{ fontSize: 9, fontWeight: 700, color: badge.color, marginTop: 3, letterSpacing: 0.3 }}>
                    {status === "normal" ? "✓ " : "⚠ "}{badge.label}
                  </div>
                )}
              </div>
            );
          })
        }
      </div>
      {vitals.nurse_notes && (
        <div style={{
          background: "#FFFBEB", border: "1px solid #FDE68A", borderRadius: 8,
          padding: "8px 12px", fontSize: 12, color: "#92400E",
        }}>
          <strong>Nurse note:</strong> {vitals.nurse_notes}
        </div>
      )}
    </div>
  );
}
