/** The icon and colour of each kind of report, so a prescription, a lab report, a vaccination card and a discharge summary are told apart at a glance. */
import { BadgeCheck, BedDouble, FileQuestion, FileText, FlaskConical, Pill, Receipt, ScanLine, Send, Stethoscope, Syringe } from "lucide-react";

export const TYPE_LOOK = {
  prescription:       { Icon: Pill,         background: "#e3f4f0", color: "#0f766e" },
  lab_report:         { Icon: FlaskConical, background: "#efe9fb", color: "#6d28d9" },
  discharge_summary:  { Icon: BedDouble,    background: "#e3effd", color: "#1d4ed8" },
  vaccination_record: { Icon: Syringe,      background: "#fdeaea", color: "#dc2626" },
  imaging_report:     { Icon: ScanLine,     background: "#e8ecfd", color: "#4338ca" },
  consultation_note:  { Icon: Stethoscope,  background: "#e0f4f8", color: "#0e7490" },
  medical_bill:       { Icon: Receipt,      background: "#fff4d6", color: "#b45309" },
  referral_letter:    { Icon: Send,         background: "#fce7f3", color: "#be185d" },
  medical_certificate: { Icon: BadgeCheck,  background: "#e5f5ea", color: "#15803d" },
  other:              { Icon: FileText,     background: "#eef2f6", color: "#475569" },
  not_classified:     { Icon: FileQuestion, background: "#fbf0dc", color: "#92400e" },
};

/** The look of a report's type, or null when the file has no type to show yet (still being read, failed, a duplicate). */
export const typeLook = (docType, state) => (state === "processing" || state === "failed" || state === "duplicate" ? null : TYPE_LOOK[docType] || TYPE_LOOK.other);
