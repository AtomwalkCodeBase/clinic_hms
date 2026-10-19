// ─── Visit summary — auto-assembled from what the doctor has already typed
export function buildVisitSummary(form, diagnoses) {
  const parts = [];
  if (form.subjective?.trim()) parts.push(`Patient reports: ${form.subjective.trim()}.`);
  if (diagnoses.length > 0) {
    const primary = diagnoses.find(d => d.is_primary) || diagnoses[0];
    parts.push(`Working diagnosis: ${primary.description}${diagnoses.length > 1 ? ` (+${diagnoses.length - 1} more)` : ""}.`);
  } else if (form.assessment?.trim()) {
    parts.push(`Assessment: ${form.assessment.trim()}.`);
  }
  if (form.plan?.trim()) parts.push(`Plan: ${form.plan.trim()}.`);
  if (form.follow_up_in_days) parts.push(`Follow-up in ${form.follow_up_in_days} day(s).`);
  return parts.join(" ");
}
