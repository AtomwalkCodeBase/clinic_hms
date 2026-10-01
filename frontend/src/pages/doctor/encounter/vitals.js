// ─── Vitals display ───────────────────────────────────────────────────────────
// Standard adult clinical reference ranges (textbook values, not
// patient-specific data) — used only to badge a recorded vital as
// Normal/Watch/High so a doctor doesn't have to do the mental math on
// every patient. Never invents a reading; only classifies one already
// recorded by nursing staff.
export function classifyVital(key, val) {
  if (val == null || val === "") return null;
  const n = Number(val);
  if (Number.isNaN(n)) return null;
  switch (key) {
    // Pulse: 60-99 Green, 100-120 Amber, >120 Red (below 60 flagged Amber too — bradycardia).
    case "pulse":   return n > 120 ? "high" : n >= 100 ? "watch" : n < 60 ? "watch" : "normal";
    // SpO2: >=95 Green, 90-94 Amber, <90 Red.
    case "spo2":    return n < 90 ? "high" : n < 95 ? "watch" : "normal";
    // Temp: 97-99 Green, 99-101 Amber, >101 Red (below 97 flagged Amber too — hypothermia caution).
    case "temp":    return n > 101 ? "high" : n >= 99 ? "watch" : n < 97 ? "watch" : "normal";
    case "rr":      return n < 12 || n > 20 ? "watch" : "normal";
    default:        return null;
  }
}

export function classifyBP(sys, dia) {
  if (sys == null || dia == null) return null;
  if (sys >= 140 || dia >= 90) return "high";
  if (sys >= 120 || dia >= 80) return "watch";
  return "normal";
}
