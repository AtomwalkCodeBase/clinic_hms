export function emptyMilestoneRule(sortOrder) {
  return {
    _key: `new-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
    domain: "gross_motor",
    milestone: "",
    scheduled_label: "",
    min_age_days: 0,
    max_age_days: "",
    mandatory: true,
    sort_order: sortOrder,
  };
}

export function emptyVaccinationRule(sortOrder) {
  return {
    _key: `new-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
    vaccine_name: "",
    dose_number: 1,
    scheduled_label: "",
    min_age_days: 0,
    max_age_days: "",
    mandatory: true,
    sort_order: sortOrder,
  };
}
