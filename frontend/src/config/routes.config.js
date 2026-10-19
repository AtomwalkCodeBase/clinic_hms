/** config/routes.config.js */

export const ROUTES = {
  // Public
  LOGIN:                "/login",
  SETUP_PASSWORD:       "/setup-password",
  // Separate flow/page per audience (not a shared tab-switcher) — see
  FORGOT_PASSWORD_STAFF:   "/forgot-password/staff",
  FORGOT_PASSWORD_PATIENT: "/forgot-password/patient",
  // Emergency QR scan target — deliberately outside every ProtectedRoute/
  EMERGENCY_VIEW: (token) => `/emergency/${token}`,
  // Consultation scratchpad — opened by scanning a patient's permanent
  CONSULT_PAD: (token) => `/consult-pad/${token}`,
  // What the QR printed on a prescription/lab report opens when scanned by
  VIEW_REPORT: (token) => `/view-report/${token}`,
  // "Share Records" break-glass — the doctor-has-a-laptop flow. The
  SHARE_RECORDS:          "/share-records",
  SHARE_RECORDS_TOKEN: (token) => `/share-records/${token}`,
  // Front door the patient reads out: the doctor opens this and types the
  SHARE_RECORDS_ENTRY:    "/share",
  SHARE_RECORDS_ENTRY_ALT: "/s",

  // Platform Admin
  PLATFORM: {
    DASHBOARD:          "/platform/dashboard",
    HOSPITALS:          "/platform/hospitals",
    HOSPITAL:    (id) => `/platform/hospitals/${id}`,
    SUBSCRIPTIONS:      "/platform/subscriptions",
    USERS:              "/platform/users",
    USAGE:              "/platform/usage",
    VACCINATION_TEMPLATES: "/platform/vaccination-templates",
    MILESTONE_TEMPLATES: "/platform/milestone-templates",
    CLASSIFICATION_RULES: "/platform/classification-rules",
  },

  // Hospital Admin
  ADMIN: {
    DASHBOARD:          "/admin/dashboard",
    STAFF:              "/admin/staff",
    BRANCHES:           "/admin/branches",
    DEPARTMENTS:        "/admin/departments",
    SERVICES:           "/admin/services",
    BILLING_REPORTS:    "/admin/billing-reports",
    COMPLIANCE:         "/admin/compliance",
    ROOMS:              "/admin/rooms",
    ROLES:              "/admin/roles",
    VACCINATION_SCHEDULE: "/admin/vaccination-schedule",
    MILESTONE_SCHEDULE: "/admin/milestone-schedule",
    SETTINGS:           "/admin/settings",
    MY_PROFILE:         "/admin/my-profile",
  },

  // Doctor
  DOCTOR: {
    DASHBOARD:          "/doctor/dashboard",
    QUEUE:              "/doctor/queue",
    ENCOUNTER:   (id) => `/doctor/encounter/${id}`,
    PATIENTS:           "/doctor/patients",
    PATIENT:     (id) => `/doctor/patients/${id}`,
    SCHEDULE:           "/doctor/schedule",
    HISTORY:            "/doctor/history",
    IPD_REFERRALS:      "/doctor/ipd-referrals",
    IPD_PATIENTS:       "/doctor/ipd-patients",
    MY_PROFILE:         "/doctor/my-profile",
  },

  // Nurse
  NURSE: {
    DASHBOARD:          "/nurse/dashboard",
    VITALS:             "/nurse/vitals",
    TASKS:              "/nurse/tasks",
    HISTORY:            "/nurse/history",
    MY_PROFILE:         "/nurse/my-profile",
  },

  // Front Desk
  FRONT_DESK: {
    DASHBOARD:          "/front-desk/dashboard",
    // Consolidated Patient Intake workspace — ONE sidebar item (an
    INTAKE:              "/front-desk/intake",
    INTAKE_REGISTER:     "/front-desk/intake/register",
    INTAKE_TRIAGE:       "/front-desk/intake/triage",
    INTAKE_EMERGENCY:    "/front-desk/intake/emergency",
    INTAKE_OPD:          "/front-desk/intake/opd",
    INTAKE_REFERRALS:    "/front-desk/intake/referrals",
    TRIAGE:             "/front-desk/triage",
    REGISTER_PATIENT:   "/front-desk/register-patient",
    REGISTER_EMERGENCY: "/front-desk/register-emergency",
    PATIENTS:           "/front-desk/patients",
    APPOINTMENTS:       "/front-desk/appointments",
    QUEUE:              "/front-desk/queue",
    BILLING:            "/front-desk/billing",
    HISTORY:            "/front-desk/history",
    ADMISSIONS:         "/front-desk/admissions",
    ADMISSION_DETAIL: (id) => `/front-desk/admissions/${id}`,
    IPD_PATIENTS:       "/front-desk/ipd-patients",
    BED_BOARD:          "/front-desk/bed-board",
    MY_PROFILE:         "/front-desk/my-profile",
  },

  // Lab
  LAB: {
    DASHBOARD:          "/lab/dashboard",
    REQUESTS:           "/lab/requests",
    REPORTS:            "/lab/reports",
    REPORT:      (id) => `/lab/reports/${id}`,
    CATALOG:            "/lab/catalog",
    SAMPLE_TYPE_SETUP:  "/lab/sample-type-setup",
    MY_PROFILE:         "/lab/my-profile",
  },

  // Pharmacist
  PHARMACIST: {
    DASHBOARD:          "/pharmacist/dashboard",
    PRESCRIPTIONS:      "/pharmacist/prescriptions",
    STOCK:              "/pharmacist/stock",
    TRANSACTIONS:       "/pharmacist/transactions",
    CATALOG:            "/pharmacist/catalog",
    DRUG_FORM_SETUP:    "/pharmacist/drug-form-setup",
    MY_PROFILE:         "/pharmacist/my-profile",
  },

  // Patient Portal
  PATIENT: {
    DASHBOARD:          "/patient/dashboard",
    APPOINTMENTS:       "/patient/appointments",
    HOSPITALS:          "/patient/hospitals",
    HOSPITAL_DOCTORS:   (hospitalId) => `/patient/hospitals/${hospitalId}/doctors`,
    DOCTOR_PROFILE:     (hospitalId, doctorId) => `/patient/hospitals/${hospitalId}/doctors/${doctorId}`,
    RECORDS:            "/patient/records",
    PRESCRIPTIONS:      "/patient/prescriptions",
    LAB_REPORTS:        "/patient/lab-reports",
    MY_REPORTS:         "/patient/my-reports",
    SHARED_RECORDS_PRIVACY: "/patient/shared-records-privacy",
    HEALTH_SUMMARY:     "/patient/health-summary",
    NOTIFICATIONS:      "/patient/notifications",
    MY_PROFILE:         "/patient/my-profile",
    CORRECTION_REQUESTS: "/patient/correction-requests",
    EMERGENCY_QR:       "/patient/emergency-qr",
  },
};

export default ROUTES;
