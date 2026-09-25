/**
 * pages/patient/reportMeta.js
 * ---------------------------
 * Shared labels for My Reports and its organize screen.
 */

// The medical type = the built-in folders. Order is the sidebar order.
export const TYPE_OPTIONS = [
  ["prescription", "Prescriptions"],
  ["lab_report", "Lab Reports"],
  ["scan", "Radiology"],
  ["discharge_summary", "Discharge Summaries"],
  ["other", "Other"],
];
export const TYPE_LABEL = Object.fromEntries(TYPE_OPTIONS);

// Lab-report panel slugs -> label. Mirrors core/report_types.py.
export const CATEGORY_LABELS = {
  cbc: "Complete Blood Count", lipid: "Lipid Profile", lft: "Liver Function Test",
  kft: "Kidney Function Test", thyroid: "Thyroid Profile", diabetes: "Blood Sugar & HbA1c",
  urine: "Urine Routine", electrolytes: "Serum Electrolytes", vitamin: "Vitamin & Mineral",
  inflammation: "Inflammatory Markers", cardiac: "Cardiac Markers", coagulation: "Coagulation Profile",
  hormone: "Hormone Panel", infection: "Infection Serology", culture: "Culture & Sensitivity",
};
export const CATEGORY_ORDER = Object.keys(CATEGORY_LABELS);
export const catLabel = (slug) => CATEGORY_LABELS[slug] || slug;

export const IN_FLIGHT = new Set(["queued", "extracting", "classifying"]);
export const inFlight = (d) => IN_FLIGHT.has(d?.processing_status);

/** The type the machine proposed for a document (unsorted rows are stored
 *  as "other", so fall back to the AI's / rules' guess). "" = no idea. */
export function suggestedType(doc) {
  // A confident "not a medical record" from the AI outranks a keyword hit —
  // brochures/flyers for hospital software are full of medical words.
  if (doc.llm_doc_type === "not_medical" && (doc.llm_confidence ?? 0) >= 0.8) return "other";
  if (doc.doc_type && doc.doc_type !== "other") return doc.doc_type;
  const guess = [doc.llm_doc_type, doc.rule_doc_type].find(t => TYPE_LABEL[t] && t !== "other");
  // Never leave the dropdown blank: unknown / not medical / unreadable → Other
  // (flagged for attention on the review screen).
  return guess || "other";
}

// Colour + icon identity per type (list rows, badges, stat cards, folders).
export const TYPE_TONE = {
  lab_report:        { fg: "#2563EB", bg: "rgba(37,99,235,.10)",  label: "Lab Report" },
  scan:              { fg: "#E11D48", bg: "rgba(225,29,72,.10)",  label: "Scan Report" },
  prescription:      { fg: "#0F766E", bg: "rgba(15,118,110,.11)", label: "Prescription" },
  discharge_summary: { fg: "#B45309", bg: "rgba(180,83,9,.11)",   label: "Discharge Summary" },
  other:             { fg: "#7C3AED", bg: "rgba(124,58,237,.10)", label: "Other" },
};

export const STAGE = {
  queued:      { label: "Waiting in queue", pct: 15 },
  bulk:        { label: "Scheduled for the next bulk run", pct: 8 },
  extracting:  { label: "Reading the page", pct: 45 },
  classifying: { label: "Identifying the type", pct: 80 },
  done:        { label: "Sorted", pct: 100 },
  failed:      { label: "Couldn't process", pct: 100 },
};

export const pct = (x) => (x == null ? "" : `${Math.round(x * 100)}%`);
