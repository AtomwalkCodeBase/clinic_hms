/** Vaccination and milestone schedules are the same screens with different fields and wording, so the pages in this folder */
import API_ENDPOINTS from "../../config/api.config";

const newKey = () => `new-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
const missingAge = (r) => r.min_age_days === "" || r.min_age_days === null || r.min_age_days === undefined;

function payload(nameKey, extra) {
  return (r) => ({
    ...(r.immunization_schedule_rule_id ? { id: r.immunization_schedule_rule_id } : {}),
    [nameKey]: r[nameKey].trim(),
    ...extra(r),
    scheduled_label: r.scheduled_label.trim(),
    min_age_days: r.min_age_days,
    max_age_days: r.max_age_days === "" ? null : r.max_age_days,
    mandatory: !!r.mandatory,
    sort_order: r.sort_order ?? 0,
  });
}

export const VACCINATION = {
  nameKey: "vaccine_name",
  extraKey: "dose_number",
  endpoints: {
    schedules: API_ENDPOINTS.ORG.VACCINATION_SCHEDULES,
    schedule: API_ENDPOINTS.ORG.VACCINATION_SCHEDULE,
    activate: API_ENDPOINTS.ORG.VACCINATION_SCHEDULE_ACTIVATE,
    templates: API_ENDPOINTS.PLATFORM.VACCINATION_TEMPLATES,
    template: API_ENDPOINTS.PLATFORM.VACCINATION_TEMPLATE,
  },
  emptyRule: (sort) => ({
    _key: newKey(), vaccine_name: "", dose_number: 1, scheduled_label: "", min_age_days: 0, max_age_days: "",
    mandatory: true, sort_order: sort,
  }),
  ruleError: (r) => (!r.vaccine_name?.trim() || !r.scheduled_label?.trim() || missingAge(r)
    ? "Every rule needs a vaccine name, scheduled label, and min age." : null),
  rulePayload: payload("vaccine_name", (r) => ({ dose_number: r.dose_number || 1 })),
  text: {
    scheduleTitle: "Vaccination Schedule",
    templatesTitle: "Vaccination Templates",
    rules: "Rules", addRule: "+ Add Rule", rule: "rule",
    noRules: "No rules yet. Add the first vaccine milestone.",
    useDefault: "You're currently using the system Default Schedule for every patient. Clone it — or a different template below — to start customizing vaccine milestones for your hospital.",
    newTemplate: "New Vaccination Template", templateExample: "e.g. National Immunization Schedule",
    createTemplate: "Create & Add Rules",
    noTemplates: "No system vaccination templates yet. Create one to give hospitals a starting roadmap.",
    loadSchedules: "Failed to load vaccination schedules.", loadTemplates: "Failed to load vaccination templates.",
    nameLabel: "Vaccine Name *", nameExample: "e.g. BCG",
    labelLabel: "Scheduled Label (milestone) *", labelExample: "e.g. Birth, 6 weeks, 9 months",
    mandatory: "Mandatory",
  },
};
