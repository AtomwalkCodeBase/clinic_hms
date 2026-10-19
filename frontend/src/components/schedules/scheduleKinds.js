/** Vaccination and milestone schedules are the same screens with different fields and wording, so the pages in this folder */
import API_ENDPOINTS from "../../config/api.config";

const newKey = () => `new-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
const missingAge = (r) => r.min_age_days === "" || r.min_age_days === null || r.min_age_days === undefined;

function payload(nameKey, extra) {
  return (r) => ({
    ...(r.id ? { id: r.id } : {}),
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

export const MILESTONE = {
  nameKey: "milestone",
  extraKey: "domain",
  endpoints: {
    schedules: API_ENDPOINTS.ORG.MILESTONE_SCHEDULES,
    schedule: API_ENDPOINTS.ORG.MILESTONE_SCHEDULE,
    activate: API_ENDPOINTS.ORG.MILESTONE_SCHEDULE_ACTIVATE,
    templates: API_ENDPOINTS.PLATFORM.MILESTONE_TEMPLATES,
    template: API_ENDPOINTS.PLATFORM.MILESTONE_TEMPLATE,
  },
  emptyRule: (sort) => ({
    _key: newKey(), domain: "gross_motor", milestone: "", scheduled_label: "", min_age_days: 0, max_age_days: "",
    mandatory: true, sort_order: sort,
  }),
  ruleError: (r) => (!r.domain || !r.milestone?.trim() || !r.scheduled_label?.trim() || missingAge(r)
    ? "Every milestone needs a domain, name, scheduled label, and min age." : null),
  rulePayload: payload("milestone", (r) => ({ domain: r.domain })),
  text: {
    scheduleTitle: "Developmental Milestone Schedule",
    templatesTitle: "Milestone Templates",
    rules: "Milestones", addRule: "+ Add Milestone", rule: "milestone",
    noRules: "No milestones yet. Add the first developmental checkpoint.",
    useDefault: "You're currently using the system Default Schedule for every pediatric patient. Clone it — or a different template below — to start customizing milestones for your hospital.",
    newTemplate: "New Milestone Template", templateExample: "e.g. Standard Developmental Checklist",
    createTemplate: "Create & Add Milestones",
    noTemplates: "No system milestone templates yet. Create one to give hospitals a starting checklist.",
    loadSchedules: "Failed to load milestone schedules.", loadTemplates: "Failed to load milestone templates.",
    nameLabel: "Milestone *", nameExample: "e.g. Sits without support",
    labelLabel: "Scheduled Label (age window) *", labelExample: "e.g. 6 months, 12 months",
    mandatory: "Mandatory (red-flag if missed)",
  },
};
