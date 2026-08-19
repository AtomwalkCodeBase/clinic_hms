/**
 * constants/roles.js
 * ------------------
 * All user roles in the system.
 * These must match the role strings in backend JWT claims exactly.
 */

export const ROLES = {
  PLATFORM_ADMIN:   "platform_admin",
  HOSPITAL_ADMIN:   "hospital_admin",
  DOCTOR:           "doctor",
  NURSE:            "nurse",
  FRONT_DESK:       "front_desk",
  LAB_TECH:         "lab_tech",
  PHARMACIST:       "pharmacist",
  PATIENT:          "patient",
};

/**
 * Role display labels for UI rendering.
 */
export const ROLE_LABELS = {
  [ROLES.PLATFORM_ADMIN]: "Platform Admin",
  [ROLES.HOSPITAL_ADMIN]: "Hospital Admin",
  [ROLES.DOCTOR]:         "Doctor",
  [ROLES.NURSE]:          "Nurse",
  [ROLES.FRONT_DESK]:     "Front Desk",
  [ROLES.LAB_TECH]:       "Lab Technician",
  [ROLES.PHARMACIST]:     "Pharmacist",
  [ROLES.PATIENT]:        "Patient",
};

/**
 * Roles that are considered hospital staff (non-patient, non-platform).
 */
export const STAFF_ROLES = [
  ROLES.HOSPITAL_ADMIN,
  ROLES.DOCTOR,
  ROLES.NURSE,
  ROLES.FRONT_DESK,
  ROLES.LAB_TECH,
  ROLES.PHARMACIST,
];

/**
 * Priority order used to derive a single "primary" identity for a
 * role="custom" staff member (their acts_as claim can hold several roles at
 * once — e.g. a solo-clinic login that is doctor+nurse+front_desk). Used to
 * pick their default landing route (App.jsx) and to order their merged
 * sidebar nav (AppShell.jsx) so both agree on which hat comes first.
 * Matches apps.org.rbac.ACTS_AS_CHOICES on the backend.
 */
export const ACTS_AS_PRIORITY = [
  ROLES.HOSPITAL_ADMIN,
  ROLES.DOCTOR,
  ROLES.NURSE,
  ROLES.FRONT_DESK,
  ROLES.LAB_TECH,
  ROLES.PHARMACIST,
];

export default ROLES;
