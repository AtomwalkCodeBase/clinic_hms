export const APPOINTMENT_STATUS_BADGE = {
  scheduled:   "badge--primary",
  waiting:     "badge--warning",
  vitals_done: "badge--success",
  in_progress: "badge--info",
  done:        "badge--success",
  cancelled:   "badge--error",
  no_show:     "badge--neutral",
};

export const PORTAL_APPOINTMENT_BADGE = {
  scheduled:   "badge--primary",
  waiting:     "badge--warning",
  vitals_done: "badge--success",
  in_progress: "badge--info",
  done:        "badge--success",
  cancelled:   "badge--error",
};

export const ADMISSION_STATUS_BADGE = {
  requested: "badge--neutral",
  admitted: "badge--warning",
  active: "badge--success",
  discharge_initiated: "badge--warning",
  discharged: "badge--neutral",
  cancelled: "badge--error",
};

export const INVOICE_STATUS_BADGE = {
  draft:          "badge--neutral",
  issued:         "badge--primary",
  paid:           "badge--success",
  partially_paid: "badge--warning",
  cancelled:      "badge--error",
};

export const LAB_STATUS_BADGE = {
  ordered:    { label: "Ordered",    bg: "var(--color-border)", color: "var(--color-text-muted)" },
  collected:  { label: "Collected",  bg: "#DBEAFE", color: "#1E40AF" },
  processing: { label: "Processing", bg: "#FEF3C7", color: "#92400E" },
  completed:  { label: "Completed",  bg: "#D1FAE5", color: "#065F46" },
  cancelled:  { label: "Cancelled",  bg: "#FEE2E2", color: "#991B1B" },
};

// Bed status -> the CSS class from intake-workspace.css that colors it, and
// the label the legend/details panel shows. "available" is styled as
// `.bed.free` (pre-existing class, kept as-is so nothing else regresses);
// the rest render distinctly instead of collapsing into one gray "taken".
export const BED_STATUS_META = {
  available:      { cls: "free",     label: "Available" },
  reserved:       { cls: "reserved", label: "Reserved" },
  occupied:       { cls: "occupied", label: "Occupied" },
  cleaning:       { cls: "cleaning", label: "Cleaning" },
  blocked:        { cls: "blocked",  label: "Blocked" },
  out_of_service: { cls: "blocked",  label: "Out of Service" },
};
