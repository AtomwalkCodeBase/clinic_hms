/** constants/modules.js — what a module granted to a user group adds to a staff member's menu and routes (the API opens the same endpoints). */
import { ROLES } from "./roles";
import { ROUTES } from "../config/routes.config";

/** Modules that open some of the hospital admin's pages. */
export const MODULE_ADMIN_PAGES = {
  staff:      [ROUTES.ADMIN.STAFF, ROUTES.ADMIN.ROLES],
  facility:   [ROUTES.ADMIN.BRANCHES, ROUTES.ADMIN.DEPARTMENTS, ROUTES.ADMIN.ROOMS],
  billing:    [ROUTES.ADMIN.SERVICES, ROUTES.ADMIN.BILLING_REPORTS],
  compliance: [ROUTES.ADMIN.COMPLIANCE],
};

/** True if one of the user's granted modules opens a route guarded by `roles` at `pathname`. */
export function moduleAllows(user, roles, pathname) {
  const granted = user?.granted_modules || [];
  return roles.includes(ROLES.HOSPITAL_ADMIN)
    && granted.some(m => (MODULE_ADMIN_PAGES[m] || []).some(p => pathname.startsWith(p)));
}
