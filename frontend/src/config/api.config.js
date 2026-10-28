/** config/api.config.js */

const BASE_URL = import.meta.env.VITE_API_BASE_URL || (import.meta.env.DEV ? "http://localhost:8000" : "");
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
    // OTP — shared by staff/patient forgot-password, patient registration,
    OTP_REQUEST:      `${API_V1}/auth/otp/request/`,
    OTP_VERIFY:       `${API_V1}/auth/otp/verify/`,
    STAFF_FORGOT_PASSWORD_RESET:   `${API_V1}/auth/forgot-password/staff/reset/`,
    PATIENT_FORGOT_PASSWORD_RESET: `${API_V1}/auth/forgot-password/patient/reset/`,
  },

  RECORDS: {
    UPLOAD: `${API_V1}/records/upload/`,   // multipart, apps/records
    SUBMIT: `${API_V1}/records/submit/`,   // the patient confirms the type of each new upload
    HEALTH_TIMELINE:  (awpid) => `${API_V1}/peds/patients/${awpid}/health-timeline/`,
    GROWTH:           (awpid) => `${API_V1}/peds/patients/${awpid}/growth/`,
    IMMUNIZATION:     (awpid) => `${API_V1}/peds/patients/${awpid}/immunization/`,
    REBUILD_TIMELINE: (awpid) => `${API_V1}/peds/patients/${awpid}/rebuild/`,
    CLINICAL_SUMMARY: (awpid) => `${API_V1}/peds/patients/${awpid}/clinical-summary/`,   // doctors: lab trends, medicines, data gaps
    REVIEW_EVENT:     (eventId)   => `${API_V1}/peds/events/${eventId}/`,
    ACKNOWLEDGE_RECURRENCE: (flagId) => `${API_V1}/peds/recurrence/${flagId}/acknowledge/`,
  },
  PLATFORM: {
    HOSPITALS:          `${API_V1}/platform/hospitals/`,
    HOSPITAL:     (id) => `${API_V1}/platform/hospitals/${id}/`,
    HOSPITAL_AUDIT_LOG: (id) => `${API_V1}/platform/hospitals/${id}/audit-log/`,
    HOSPITAL_OVERVIEW:  (id) => `${API_V1}/platform/hospitals/${id}/overview/`,
    HOSPITAL_STAFF:     (id) => `${API_V1}/platform/hospitals/${id}/staff/`,
    HOSPITAL_STAFF_DETAIL: (id, staffId) => `${API_V1}/platform/hospitals/${id}/staff/${staffId}/`,
    HOSPITAL_STAFF_RESET_PASSWORD: (id, staffId) => `${API_V1}/platform/hospitals/${id}/staff/${staffId}/reset-password/`,
    STATS:            `${API_V1}/platform/stats/`,
    PLANS:            `${API_V1}/platform/plans/`,
    USERS:            `${API_V1}/platform/users/`,
    VACCINATION_TEMPLATES:      `${API_V1}/platform/vaccination-templates/`,
    VACCINATION_TEMPLATE: (id) => `${API_V1}/platform/vaccination-templates/${id}/`,
    RECORDS_REPORT:       `${API_V1}/platform/records/report/`,
    RECORDS_REPORT_ITEM: (id) => `${API_V1}/platform/records/report/${id}/`,
    RECORDS_RECLASSIFY:   `${API_V1}/platform/records/reclassify/`,
  },

  ORG: {
    BRANCHES:         `${API_V1}/org/branches/`,
    BRANCH:     (id) => `${API_V1}/org/branches/${id}/`,
    DEPARTMENTS:      `${API_V1}/org/departments/`,
    STAFF:            `${API_V1}/org/staff/`,
    STAFF_MEMBER:(id) => `${API_V1}/org/staff/${id}/`,
    DOCTORS:          `${API_V1}/org/doctors/`,
    DOCTOR_SPECIALISATIONS: `${API_V1}/org/doctors/specialisations/`,
    MY_DOCTOR_PROFILE: `${API_V1}/org/me/doctor-profile/`,
    MY_STAFF_PROFILE:  `${API_V1}/org/me/staff-profile/`,
    MY_PROFILE:        `${API_V1}/org/me/profile/`,
    STAFF_BRANCHES: (id) => `${API_V1}/org/staff/${id}/branches/`,
    MY_BRANCHES:       `${API_V1}/org/me/branches/`,
    SETTINGS:          `${API_V1}/org/settings/`,
    PERMISSIONS:       `${API_V1}/org/permissions/`,
    ROLES:             `${API_V1}/org/roles/`,
    ROLE:       (id) => `${API_V1}/org/roles/${id}/`,
    VACCINATION_SCHEDULES:        `${API_V1}/org/vaccination-schedules/`,
    VACCINATION_SCHEDULE:  (id) => `${API_V1}/org/vaccination-schedules/${id}/`,
    VACCINATION_SCHEDULE_ACTIVATE: (id) => `${API_V1}/org/vaccination-schedules/${id}/activate/`,
    FLOORS:            `${API_V1}/org/floors/`,
    FLOOR:      (id) => `${API_V1}/org/floors/${id}/`,
    ROOMS:             `${API_V1}/org/rooms/`,
    ROOM:       (id) => `${API_V1}/org/rooms/${id}/`,
    ROOM_ASSIGNMENTS:  `${API_V1}/org/room-assignments/`,
    ROOM_ASSIGNMENT: (id) => `${API_V1}/org/room-assignments/${id}/`,
    // Beds (IPD bed assignment) + front-desk triage availability — see
    DEPARTMENTS_AVAILABILITY: `${API_V1}/org/departments/availability/`,
  },

  PATIENTS: {
    REGISTER:         `${API_V1}/patients/register/`,
    // Provisional/unidentified-patient registration (Emergency path) — no
    LOOKUP:           `${API_V1}/patients/lookup/`,
    ATTACH_NETWORK:   `${API_V1}/patients/attach-network/`,
    SEARCH:           `${API_V1}/patients/search/`,
    FAMILY_TREE:      `${API_V1}/patients/family-tree/`,
    HISTORY:    (id) => `${API_V1}/patients/${id}/history/`,
    DOCUMENT:   (id) => `${API_V1}/patients/documents/${id}/`,
    LAB_RESULT: (id) => `${API_V1}/patients/lab-results/${id}/`,
    VACCINATIONS:      (id) => `${API_V1}/patients/${id}/vaccinations/`,
    VACCINATION_VERIFY:(id) => `${API_V1}/patients/vaccinations/${id}/verify/`,
    VACCINATION_ORDER:     (id) => `${API_V1}/patients/${id}/vaccinations/order/`,
    VACCINATION_DECLINE:   (id) => `${API_V1}/patients/${id}/vaccinations/decline/`,
    VACCINATION_ADMINISTER:(id) => `${API_V1}/patients/${id}/vaccinations/administer/`,
    // ── Pediatric-only additions ────────────────────────────────────────
    BIRTH_HISTORY:     (id) => `${API_V1}/patients/${id}/birth-history/`,
  },

  // OPD module — appointment queue, encounters, prescriptions
  OPD: {
    STATS:            `${API_V1}/opd/stats/`,
    TRANSCRIBE:       `${API_V1}/opd/transcribe/`,
    MONITORING:       `${API_V1}/opd/monitoring/`,
    HISTORY:          `${API_V1}/opd/history/`,
    APPOINTMENTS:     `${API_V1}/opd/appointments/`,
    APPOINTMENTS_UPCOMING: `${API_V1}/opd/appointments/upcoming/`,
    APPT_STATUS:(id) => `${API_V1}/opd/appointments/${id}/status/`,
    APPT_RESCHEDULE:(id) => `${API_V1}/opd/appointments/${id}/reschedule/`,
    APPT_VITALS:(id) => `${API_V1}/opd/appointments/${id}/vitals/`,
    ENCOUNTERS:       `${API_V1}/opd/encounters/`,
    ENCOUNTER:  (id) => `${API_V1}/opd/encounters/${id}/`,
    ENCOUNTER_SIGN:(id) => `${API_V1}/opd/encounters/${id}/sign/`,
    ENCOUNTER_PDF:(id) => `${API_V1}/opd/encounters/${id}/pdf/`,
    ENCOUNTER_FOLLOWUP:(id) => `${API_V1}/opd/encounters/${id}/follow-up/`,
    ENCOUNTER_PREVIOUS:(id) => `${API_V1}/opd/encounters/${id}/previous/`,
    FOLLOWUP_NURSE_WORKLIST: `${API_V1}/opd/followups/nurse-worklist/`,
    FOLLOWUP_MARK_BOOKED:(id) => `${API_V1}/opd/followups/${id}/mark-booked/`,
    ENCOUNTER_CONSULT_SESSION:(id) => `${API_V1}/opd/encounters/${id}/consult-session/`,
    ENCOUNTER_INTERNAL_NOTE:(id) => `${API_V1}/opd/encounters/${id}/internal-note/`,   // the doctor's handwritten note PDF (doctor only)
    PRESCRIPTIONS:              `${API_V1}/opd/prescriptions/`,
    PRESCRIPTION_ITEMS:  (id) => `${API_V1}/opd/prescriptions/${id}/items/`,
    PRESCRIPTION_ITEM: (rxId, itemId) => `${API_V1}/opd/prescriptions/${rxId}/items/${itemId}/`,
    FAVOURITES:                `${API_V1}/opd/favourites/`,
    FAVOURITE_ITEM:      (id) => `${API_V1}/opd/favourites/${id}/`,
    APPOINTMENT_TYPES:         `${API_V1}/opd/appointment-types/`,
    APPOINTMENT_TYPE_ITEM: (id) => `${API_V1}/opd/appointment-types/${id}/`,
  },

  // Patient portal (patient JWT)
  PORTAL: {
    REGISTER:              `${API_V1}/portal/register/`,
    HOSPITALS:             `${API_V1}/portal/hospitals/`,
    STATS:                 `${API_V1}/portal/stats/`,
    SEARCH:                `${API_V1}/portal/search/`,
    SPECIALTIES:           `${API_V1}/portal/specialties/`,
    DOCTORS:   (hospitalId) => `${API_V1}/portal/hospitals/${hospitalId}/doctors/`,
    DOCTOR_DETAIL: (hospitalId, doctorId) => `${API_V1}/portal/hospitals/${hospitalId}/doctors/${doctorId}/`,
    SLOTS: (hospitalId, doctorId) => `${API_V1}/portal/hospitals/${hospitalId}/doctors/${doctorId}/slots/`,
    BOOK:                  `${API_V1}/portal/book/`,
    MY_BOOKINGS:           `${API_V1}/portal/my-bookings/`,
    CANCEL_BOOKING:  (id) => `${API_V1}/portal/my-bookings/${id}/cancel/`,
    RESCHEDULE_BOOKING:(id) => `${API_V1}/portal/my-bookings/${id}/reschedule/`,
    MY_RECORDS:            `${API_V1}/portal/my-records/`,
    INVOICES:              `${API_V1}/portal/invoices/`,
    INVOICE_RECEIPT: (hospitalDb, id) => `${API_V1}/portal/invoices/${hospitalDb}/${id}/receipt/`,
    DOCUMENTS:             `${API_V1}/portal/documents/`,
    DOCUMENT: (id) =>       `${API_V1}/portal/documents/${id}/`,
    DOCUMENTS_ZIP:         `${API_V1}/portal/documents/zip/`,
    PRESCRIPTIONS:         `${API_V1}/portal/prescriptions/`,
    PRESCRIPTION_RECEIPT: (hospitalDb, id) => `${API_V1}/portal/prescriptions/${hospitalDb}/${id}/receipt/`,
    PROFILE:                `${API_V1}/portal/profile/`,
    CHANGE_PASSWORD:        `${API_V1}/portal/profile/change-password/`,
    // Forgot-password is now OTP-based — see AUTH.OTP_REQUEST / AUTH.OTP_VERIFY
    MOBILE_CHANGE_REQUEST_OTP: `${API_V1}/portal/profile/mobile-change/request-otp/`,
    FAMILY:                 `${API_V1}/portal/family/`,
    FAMILY_DETAIL:  (awpid) => `${API_V1}/portal/family/${awpid}/`,
    HEALTH_SUMMARY:         `${API_V1}/portal/health-summary/`,
    VACCINATIONS:           `${API_V1}/portal/vaccinations/`,
    VACCINATION_UPLOAD:     `${API_V1}/portal/vaccinations/upload/`,
    VACCINATION_FILE: (recordId) => `${API_V1}/portal/vaccinations/${recordId}/file/`,
    GROWTH:                 `${API_V1}/portal/growth/`,
    TIMELINE:               `${API_V1}/portal/timeline/`,
    NOTIFICATIONS:          `${API_V1}/portal/notifications/`,
    NOTIFICATION_READ: (hospitalDb, id) => `${API_V1}/portal/notifications/${hospitalDb}/${id}/read/`,
    EMERGENCY_TOKEN:        `${API_V1}/portal/emergency/token/`,
    // "Share Records" — patient-authenticated half: the patient CREATES the
    RECORDS_SHARE_CREATE:           `${API_V1}/portal/records-share/`,
    RECORDS_SHARE_MINE:             `${API_V1}/portal/records-share/mine/`,
    RECORDS_SHARE_DECISION: (token) => `${API_V1}/portal/records-share/${token}/decision/`,
    RECORDS_SHARE_END:      (token) => `${API_V1}/portal/records-share/${token}/end/`,
    RECORDS_SHARE_DOWNLOAD_DECISION: (token) => `${API_V1}/portal/records-share/${token}/downloads/decision/`,
    // Shared-records privacy — the standing "what a doctor sees" config, the
    RECORDS_PRIVACY:                `${API_V1}/portal/records-privacy/`,
    RECORDS_PRIVACY_TOGGLE:         `${API_V1}/portal/records-privacy/toggle/`,
    RECORDS_SHARE_REVEAL:  (token) => `${API_V1}/portal/records-share/${token}/reveal/`,
  },

  // "Share Records" — public, token-gated half the doctor's laptop reads
  RECORDS_SHARE: {
    // The doctor's laptop binds itself to a session — by the patient's
    CLAIM:   `${API_V1}/records-share/claim/`,
    STATUS:  (token) => `${API_V1}/records-share/${token}/`,
    RECORDS: (token) => `${API_V1}/records-share/${token}/records/`,
    DOC_VIEW: (token, docId) => `${API_V1}/records-share/${token}/documents/${docId}/view/`,
    DOWNLOADS: (token) => `${API_V1}/records-share/${token}/downloads/`,
    CLOSE:   (token) => `${API_V1}/records-share/${token}/close/`,
  },

  // Emergency QR summary — public, no auth (see apps/hospital_patients/emergency_views.py).
  EMERGENCY: {
    SUMMARY: (token) => `${API_V1}/emergency/${token}/`,
  },

  // Public document-view page — what a printed prescription/lab-report QR
  VIEW_REPORT: {
    RESOLVE: (token) => `${API_V1}/view-report/${token}/`,
  },

  // Consultation handwriting pad — public, no auth (see
  CONSULT_PAD: {
    BASE: (token) => `${API_V1}/consult-pad/${token}/`,
  },

  // apps.clinical was retired (HMS-07c-1) — live consultation flow is



  BILLING: {
    SERVICES:         `${API_V1}/billing/services/`,
    SERVICE:    (id) => `${API_V1}/billing/services/${id}/`,
    SERVICE_CATEGORIES:      `${API_V1}/billing/service-categories/`,
    SERVICE_CATEGORY: (id) => `${API_V1}/billing/service-categories/${id}/`,
    PAYMENT_MODES:      `${API_V1}/billing/payment-modes/`,
    PAYMENT_MODE: (id) => `${API_V1}/billing/payment-modes/${id}/`,
    INVOICE_STATUSES:      `${API_V1}/billing/invoice-statuses/`,
    INVOICE_STATUS: (id) => `${API_V1}/billing/invoice-statuses/${id}/`,
    // Also carries what used to be the separate ward-types/ catalog
    ROOM_TYPES:      `${API_V1}/billing/room-types/`,
    ROOM_TYPE: (id) => `${API_V1}/billing/room-types/${id}/`,
    INVOICES:         `${API_V1}/billing/invoices/`,
    INVOICE:    (id) => `${API_V1}/billing/invoices/${id}/`,
    INVOICE_ITEMS: (id) => `${API_V1}/billing/invoices/${id}/items/`,
    INVOICE_PDF: (id) => `${API_V1}/billing/invoices/${id}/pdf/`,
    PAYMENTS:         `${API_V1}/billing/payments/`,
    SUMMARY:          `${API_V1}/billing/summary/`,
    REVENUE_REPORT:   `${API_V1}/billing/reports/revenue/`,
  },


  // apps.ai_pipeline was retired (HMS-07c-1) — its urls.py was never

  // apps.tasks (Task/TaskAssignment) was retired (v7 table-count redesign)

  COMPLIANCE: {
    AUDIT_LOG:            `${API_V1}/compliance/audit-log/`,
    AMENDMENTS:           `${API_V1}/compliance/amendments/`,
    AMENDMENT_RESOLVE: (id) => `${API_V1}/compliance/amendments/${id}/resolve/`,
    PORTAL_AMENDMENTS:    `${API_V1}/compliance/portal/amendments/`,
  },

  // IPD module — admission intake + bed assignment (immediate or
};

export default API_ENDPOINTS;
