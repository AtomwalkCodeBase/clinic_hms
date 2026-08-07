/**
 * utils/age.js
 * ------------
 * Shared age-from-date-of-birth helpers — used wherever a DOB is shown
 * as read-only context (patients and, where tracked, staff) so age is
 * computed the same way everywhere instead of copy-pasted per page.
 */

/** Returns whole years as a number, or null if dob is missing/invalid. */
export function calcAge(dob) {
  if (!dob) return null;
  const d = new Date(dob);
  if (Number.isNaN(d.getTime())) return null;
  const today = new Date();
  let age = today.getFullYear() - d.getFullYear();
  if (today.getMonth() < d.getMonth() || (today.getMonth() === d.getMonth() && today.getDate() < d.getDate())) {
    age--;
  }
  return age;
}

/** "34y" (or "" if dob is missing) — for compact inline use next to a DOB. */
export function formatAge(dob) {
  const age = calcAge(dob);
  return age != null ? `${age}y` : "";
}

export default calcAge;
