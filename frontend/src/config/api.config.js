/**
 * config/api.config.js
 * --------------------
 * Central registry of ALL API endpoints used by Atomwalk HMS frontend.
 *
 * Rules:
 *   - Never hardcode any URL in a component or service file.
 *   - All URLs must be defined here and imported where needed.
 *   - Dynamic segments use arrow functions: (id) => `${BASE}/resource/${id}/`
 *   - Base URL comes from VITE_API_BASE_URL environment variable.
 */

const BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";
const API_V1 = `${BASE_URL}/api/v1`;

export const API_ENDPOINTS = {
  AUTH: {
    STAFF_LOGIN:      `${API_V1}/auth/login/staff/`,
    PLATFORM_LOGIN:   `${API_V1}/auth/login/platform/`,
    PATIENT_LOGIN:    `${API_V1}/auth/login/patient/`,
    PATIENT_LOGIN_OTP: `${API_V1}/auth/login/patient/otp/`,
    REFRESH:          `${API_V1}/auth/token/refresh/`,
    ME:               `${API_V1}/auth/me/`,
    PERMISSIONS:      `${API_V1}/auth/me/permissions/`,
    CHANGE_PASSWORD:  `${API_V1}/auth/change-password/`,
    SETUP_PASSWORD:   `${API_V1}/auth/setup-password/`,
    STAFF_INVITE:     `${API_V1}/auth/staff/invite/`,
    // OTP — shared by staff/patient forgot-password, patient registration,
    // and day-to-day patient OTP login (see apps/auth_app/otp_views.py).
    OTP_REQUEST:      `${API_V1}/auth/otp/request/`,
    OTP_VERIFY:       `${API_V1}/auth/otp/verify/`,
    STAFF_FORGOT_PASSWORD_RESET:   `${API_V1}/auth/forgot-password/staff/reset/`,
    PATIENT_FORGOT_PASSWORD_RESET: `${API_V1}/auth/forgot-password/patient/reset/`,
  },

  PLATFORM: {
    TENANTS:          `${API_V1}/platform/tenants/`,
    TENANT:     (id) => `${API_V1}/platform/tenants/${id}/`,
    TENANT_AUDIT_LOG: (id) => `${API_V1}/platform/tenants/${id}/audit-log/`,
    TENANT_OVERVIEW:  (id) => `${API_V1}/platform/tenants/${id}/overview/`,
    TENANT_STAFF:     (id) => `${API_V1}/platform/tenants/${id}/staff/`,
    TENANT_STAFF_DETAIL: (id, staffId) => `${API_V1}/platform/tenants/${id}/staff/${staffId}/`,
    TENANT_STAFF_RESET_PASSWORD: (id, staffId) => `${API_V1}/platform/tenants/${id}/staff/${staffId}/reset-password/`,
    STATS:            `${API_V1}/platform/stats/`,
    PLANS:            `${API_V1}/platform/plans/`,
    USERS:            `${API_V1}/platform/users/`,
    SUBSCRIPTIONS:    `${API_V1}/platform/subscriptions/`,
    USAGE:            `${API_V1}/platform/usage/`,
    VACCINATION_TEMPLATES:      `${API_V1}/platform/vaccination-templates/`,
    VACCINATION_TEMPLATE: (id) => `${API_V1}/platform/vaccination-templates/${id}/`,
  },

  ORG: {
    BRANCHES:         `${API_V1}/org/branches/`,
    BRANCH:     (id) => `${API_V1}/org/branches/${id}/`,
    DEPARTMENTS:      `${API_V1}/org/departments/`,
    STAFF:            `${API_V1}/org/staff/`,
    STAFF_MEMBER:(id) => `${API_V1}/org/staff/${id}/`,
    DOCTORS:          `${API_V1}/org/doctors/`,
    DOCTOR:     (id) => `${API_V1}/org/doctors/${id}/`,
    MY_DOCTOR_PROFILE: `${API_V1}/org/me/doctor-profile/`,
    MY_STAFF_PROFILE:  `${API_V1}/org/me/staff-profile/`,
    MY_PROFILE:        `${API_V1}/org/me/profile/`,
    STAFF_BRANCHES: (id) => `${API_V1}/org/staff/${id}/branches/`,
    MY_BRANCHES:       `${API_V1}/org/me/branches/`,
    PERMISSIONS:       `${API_V1}/org/permissions/`,
    ROLES:             `${API_V1}/org/roles/`,
    ROLE:       (id) => `${API_V1}/org/roles/${id}/`,
    STAFF_ROLES:(id) => `${API_V1}/org/staff/${id}/roles/`,
    VACCINATION_SCHEDULES:        `${API_V1}/org/vaccination-schedules/`,
    VACCINATION_SCHEDULE:  (id) => `${API_V1}/org/vaccination-schedules/${id}/`,
    VACCINATION_SCHEDULE_ACTIVATE: (id) => `${API_V1}/org/vaccination-schedules/${id}/activate/`,
    ROOMS:             `${API_V1}/org/rooms/`,
    ROOM:       (id) => `${API_V1}/org/rooms/${id}/`,
    ROOM_ASSIGNMENTS:  `${API_V1}/org/room-assignments/`,
    ROOM_ASSIGNMENT: (id) => `${API_V1}/org/room-assignments/${id}/`,
  },

  PATIENTS: {
    LIST:             `${API_V1}/patients/`,
    REGISTER:         `${API_V1}/patients/register/`,
    LOOKUP:           `${API_V1}/patients/lookup/`,
    SEARCH:           `${API_V1}/patients/search/`,
    DETAIL:     (id) => `${API_V1}/patients/${id}/`,
    HISTORY:    (id) => `${API_V1}/patients/${id}/history/`,
    ALLERGIES:  (id) => `${API_V1}/patients/${id}/allergies/`,
    DOCUMENT:   (id) => `${API_V1}/patients/documents/${id}/`,
    LAB_RESULT: (id) => `${API_V1}/patients/lab-results/${id}/`,
    GROWTH:            (id) => `${API_V1}/patients/${id}/growth/`,
    VACCINATIONS:      (id) => `${API_V1}/patients/${id}/vaccinations/`,
    VACCINATION_VERIFY:(id) => `${API_V1}/patients/vaccinations/${id}/verify/`,
    VACCINATION_ORDER:     (id) => `${API_V1}/patients/${id}/vaccinations/order/`,
    VACCINATION_DECLINE:   (id) => `${API_V1}/patients/${id}/vaccinations/decline/`,
    VACCINATION_ADMINISTER:(id) => `${API_V1}/patients/${id}/vaccinations/administer/`,
  },

  SCHEDULING: {
    APPOINTMENTS:     `${API_V1}/scheduling/appointments/`,
    APPOINTMENT:(id) => `${API_V1}/scheduling/appointments/${id}/`,
    QUEUE:            `${API_V1}/scheduling/queue/`,
    QUEUE_NEXT:       `${API_V1}/scheduling/queue/next/`,
    TEMPLATES:        `${API_V1}/scheduling/templates/`,
  },

  // OPD module — appointment queue, encounters, prescriptions
  OPD: {
    STATS:            `${API_V1}/opd/stats/`,
    TRANSCRIBE:       `${API_V1}/opd/transcribe/`,
    MONITORING:       `${API_V1}/opd/monitoring/`,
    HISTORY:          `${API_V1}/opd/history/`,
    APPOINTMENTS:     `${API_V1}/opd/appointments/`,
    APPOINTMENT:(id) => `${API_V1}/opd/appointments/${id}/`,
    APPT_STATUS:(id) => `${API_V1}/opd/appointments/${id}/status/`,
    APPT_RESCHEDULE:(id) => `${API_V1}/opd/appointments/${id}/reschedule/`,
    APPT_VITALS:(id) => `${API_V1}/opd/appointments/${id}/vitals/`,
    ENCOUNTERS:       `${API_V1}/opd/encounters/`,
    ENCOUNTER:  (id) => `${API_V1}/opd/encounters/${id}/`,
    ENCOUNTER_SIGN:(id) => `${API_V1}/opd/encounters/${id}/sign/`,
    PRESCRIPTIONS:              `${API_V1}/opd/prescriptions/`,
    PRESCRIPTION:        (id) => `${API_V1}/opd/prescriptions/${id}/`,
    PRESCRIPTION_ITEMS:  (id) => `${API_V1}/opd/prescriptions/${id}/items/`,
    PRESCRIPTION_ITEM: (rxId, itemId) => `${API_V1}/opd/prescriptions/${rxId}/items/${itemId}/`,
    RX_ITEMS:            (id) => `${API_V1}/opd/prescriptions/${id}/items/`,
    FAVOURITES:                `${API_V1}/opd/favourites/`,
  },

  // Patient portal (patient JWT)
  PORTAL: {
    REGISTER:              `${API_V1}/portal/register/`,
    HOSPITALS:             `${API_V1}/portal/hospitals/`,
    STATS:                 `${API_V1}/portal/stats/`,
    SEARCH:                `${API_V1}/portal/search/`,
    DOCTORS:   (tenantId) => `${API_V1}/portal/hospitals/${tenantId}/doctors/`,
    DOCTOR_DETAIL: (tenantId, doctorId) => `${API_V1}/portal/hospitals/${tenantId}/doctors/${doctorId}/`,
    SLOTS: (tenantId, doctorId) => `${API_V1}/portal/hospitals/${tenantId}/doctors/${doctorId}/slots/`,
    NEXT_TOKEN: (tenantId, doctorId) => `${API_V1}/portal/hospitals/${tenantId}/doctors/${doctorId}/next-token/`,
    BOOK:                  `${API_V1}/portal/book/`,
    MY_BOOKINGS:           `${API_V1}/portal/my-bookings/`,
    CANCEL_BOOKING:  (id) => `${API_V1}/portal/my-bookings/${id}/cancel/`,
    RESCHEDULE_BOOKING:(id) => `${API_V1}/portal/my-bookings/${id}/reschedule/`,
    MY_RECORDS:            `${API_V1}/portal/my-records/`,
    DOCUMENTS:             `${API_V1}/portal/documents/`,
    LAB_ORDERS:            `${API_V1}/portal/lab-orders/`,
    LAB_ORDER_CHOICE:      `${API_V1}/portal/lab-orders/choice/`,
    LAB_REPORT_FILE: (tenantDb, requestId) => `${API_V1}/portal/lab-orders/${tenantDb}/${requestId}/report/`,
    PRESCRIPTIONS:         `${API_V1}/portal/prescriptions/`,
    PRESCRIPTION_CHOICE:   `${API_V1}/portal/prescriptions/choice/`,
    PROFILE:                `${API_V1}/portal/profile/`,
    CHANGE_PASSWORD:        `${API_V1}/portal/profile/change-password/`,
    // Forgot-password is now OTP-based — see AUTH.OTP_REQUEST / AUTH.OTP_VERIFY
    // / AUTH.PATIENT_FORGOT_PASSWORD_RESET (apps/auth_app/otp_views.py).
    MOBILE_CHANGE_REQUEST_OTP: `${API_V1}/portal/profile/mobile-change/request-otp/`,
    FAMILY:                 `${API_V1}/portal/family/`,
    HEALTH_SUMMARY:         `${API_V1}/portal/health-summary/`,
    VACCINATIONS:           `${API_V1}/portal/vaccinations/`,
    VACCINATION_UPLOAD:     `${API_V1}/portal/vaccinations/upload/`,
    VACCINATION_FILE: (recordId) => `${API_V1}/portal/vaccinations/${recordId}/file/`,
    GROWTH:                 `${API_V1}/portal/growth/`,
    TIMELINE:               `${API_V1}/portal/timeline/`,
    NOTIFICATIONS:          `${API_V1}/portal/notifications/`,
    NOTIFICATION_READ: (tenantDb, id) => `${API_V1}/portal/notifications/${tenantDb}/${id}/read/`,
  },

  // apps.clinical was retired (HMS-07c-1) — live consultation flow is
  // apps.opd (see OPD.ENCOUNTER* / OPD.PRESCRIPTIONS above).

  PRESCRIPTIONS: {
    // LIST/DETAIL/FINALIZE (apps.prescriptions.Prescription) were retired
    // (HMS-07c-1) — live prescriptions are OPD.PRESCRIPTIONS above. Only the
    // drug catalog endpoints below are still live.
    DRUGS:            `${API_V1}/prescriptions/drugs/`,
    DRUG_ITEM:  (id) => `${API_V1}/prescriptions/drugs/${id}/`,
    DRUG_SEARCH:      `${API_V1}/prescriptions/drugs/search/`,
    DRUG_FORMS:       `${API_V1}/prescriptions/drug-forms/`,
    DRUG_FORM_ITEM: (id) => `${API_V1}/prescriptions/drug-forms/${id}/`,
  },

  LAB: {
    CATALOG:              `${API_V1}/lab/catalog/`,
    CATALOG_ITEM:  (id) => `${API_V1}/lab/catalog/${id}/`,
    REQUESTS:             `${API_V1}/lab/requests/`,
    REQUEST_LOOKUP:       `${API_V1}/lab/requests/lookup/`,
    REQUEST_CHOICE: (id) => `${API_V1}/lab/requests/${id}/choice/`,
    REQUEST_STATUS: (id) => `${API_V1}/lab/requests/${id}/status/`,
    REQUEST_REPORT: (id) => `${API_V1}/lab/requests/${id}/report/`,
    DELIVER:        (id) => `${API_V1}/lab/reports/${id}/deliver/`,
  },

  BILLING: {
    SERVICES:         `${API_V1}/billing/services/`,
    SERVICE:    (id) => `${API_V1}/billing/services/${id}/`,
    SERVICE_CATEGORIES:      `${API_V1}/billing/service-categories/`,
    SERVICE_CATEGORY: (id) => `${API_V1}/billing/service-categories/${id}/`,
    PAYMENT_MODES:      `${API_V1}/billing/payment-modes/`,
    PAYMENT_MODE: (id) => `${API_V1}/billing/payment-modes/${id}/`,
    INVOICE_STATUSES:      `${API_V1}/billing/invoice-statuses/`,
    INVOICE_STATUS: (id) => `${API_V1}/billing/invoice-statuses/${id}/`,
    INVOICES:         `${API_V1}/billing/invoices/`,
    INVOICE:    (id) => `${API_V1}/billing/invoices/${id}/`,
    INVOICE_ITEMS: (id) => `${API_V1}/billing/invoices/${id}/items/`,
    INVOICE_PDF: (id) => `${API_V1}/billing/invoices/${id}/pdf/`,
    PAYMENTS:         `${API_V1}/billing/payments/`,
    SUMMARY:          `${API_V1}/billing/summary/`,
    REVENUE_REPORT:   `${API_V1}/billing/reports/revenue/`,
  },

  PHARMACY: {
    STOCK:            `${API_V1}/pharmacy/stock/`,
    TRANSACTIONS:     `${API_V1}/pharmacy/transactions/`,
    DISPENSE:         `${API_V1}/pharmacy/dispense/`,
    PRESCRIPTIONS:    `${API_V1}/pharmacy/prescriptions/`,
    PRESCRIPTION_LOOKUP: `${API_V1}/pharmacy/prescriptions/lookup/`,
  },

  // apps.ai_pipeline was retired (HMS-07c-1) — its urls.py was never
  // mounted even before that, so this AI.JOBS/JOB block was already dead
  // (confirmed unreferenced anywhere in frontend/src).

  TASKS: {
    LIST:             `${API_V1}/tasks/`,
    DETAIL:     (id) => `${API_V1}/tasks/${id}/`,
    ASSIGN:     (id) => `${API_V1}/tasks/${id}/assign/`,
    COMPLETE:   (id) => `${API_V1}/tasks/${id}/complete/`,
  },

  COMPLIANCE: {
    AUDIT_LOG:            `${API_V1}/compliance/audit-log/`,
    AMENDMENTS:           `${API_V1}/compliance/amendments/`,
    AMENDMENT_RESOLVE: (id) => `${API_V1}/compliance/amendments/${id}/resolve/`,
    CONSENTS:             `${API_V1}/compliance/consents/`,
    PORTAL_AMENDMENTS:    `${API_V1}/compliance/portal/amendments/`,
  },
};

export default API_ENDPOINTS;
