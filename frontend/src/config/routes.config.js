/**
 * config/routes.config.js
 * -----------------------
 * All application route paths defined in one place.
 * Import ROUTES wherever you need to navigate or check the current path.
 * Never hardcode route strings in components.
 */

export const ROUTES = {
  // Public
  LOGIN:                "/login",
  SETUP_PASSWORD:       "/setup-password",
  FORGOT_PASSWORD:      "/forgot-password",

  // Platform Admin
  PLATFORM: {
    DASHBOARD:          "/platform/dashboard",
    HOSPITALS:          "/platform/hospitals",
    HOSPITAL:    (id) => `/platform/hospitals/${id}`,
    SUBSCRIPTIONS:      "/platform/subscriptions",
    USERS:              "/platform/users",
    USAGE:              "/platform/usage",
    VACCINATION_TEMPLATES: "/platform/vaccination-templates",
  },

  // Hospital Admin
  ADMIN: {
    DASHBOARD:          "/admin/dashboard",
    STAFF:              "/admin/staff",
    BRANCHES:           "/admin/branches",
    DEPARTMENTS:        "/admin/departments",
    SERVICES:           "/admin/services",
    ROLES:              "/admin/roles",
    VACCINATION_SCHEDULE: "/admin/vaccination-schedule",
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
    REGISTER_PATIENT:   "/front-desk/register-patient",
    APPOINTMENTS:       "/front-desk/appointments",
    QUEUE:              "/front-desk/queue",
    BILLING:            "/front-desk/billing",
    HISTORY:            "/front-desk/history",
    MY_PROFILE:         "/front-desk/my-profile",
  },

  // Lab
  LAB: {
    DASHBOARD:          "/lab/dashboard",
    REQUESTS:           "/lab/requests",
    REPORTS:            "/lab/reports",
    REPORT:      (id) => `/lab/reports/${id}`,
    CATALOG:            "/lab/catalog",
    MY_PROFILE:         "/lab/my-profile",
  },

  // Pharmacist
  PHARMACIST: {
    DASHBOARD:          "/pharmacist/dashboard",
    PRESCRIPTIONS:      "/pharmacist/prescriptions",
    STOCK:              "/pharmacist/stock",
    TRANSACTIONS:       "/pharmacist/transactions",
    MY_PROFILE:         "/pharmacist/my-profile",
  },

  // Patient Portal
  PATIENT: {
    DASHBOARD:          "/patient/dashboard",
    APPOINTMENTS:       "/patient/appointments",
    HOSPITALS:          "/patient/hospitals",
    HOSPITAL_DOCTORS:   (tenantId) => `/patient/hospitals/${tenantId}/doctors`,
    DOCTOR_PROFILE:     (tenantId, doctorId) => `/patient/hospitals/${tenantId}/doctors/${doctorId}`,
    RECORDS:            "/patient/records",
    PRESCRIPTIONS:      "/patient/prescriptions",
    LAB_REPORTS:        "/patient/lab-reports",
    HEALTH_SUMMARY:     "/patient/health-summary",
    MY_PROFILE:         "/patient/my-profile",
  },
};

export default ROUTES;
