// Which roadmap bucket a vaccination item falls in ("Completed" / "Needs Review" / "Upcoming").
// Shared by the records timeline (RecordsPage) and the growth chart (GrowthVaccinationChart) so the
// marker colours on the chart always agree with the pill colours on the timeline.
export function vaxBucket(item) {
  const status = item.status;
  if (status === "completed" || status === "declined") return "Completed";
  if (status === "pending_review" || status === "rejected") return "Needs Review";
  if (status === "ordered") return "Needs Review";
  if (status === "unknown") {
    return item.timing === "due_now" || item.timing === "past_window" ? "Needs Review" : "Upcoming";
  }
  return "Upcoming";
}
