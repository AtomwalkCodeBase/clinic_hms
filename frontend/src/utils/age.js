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

/**
 * Returns { years, months } elapsed since dob, or null if dob is
 * missing/invalid/in the future. Used wherever whole-year age is too
 * coarse — in particular infants under 1 year, where "0y" alone reads as
 * "unknown" rather than "newborn".
 */
export function calcAgeYM(dob) {
  if (!dob) return null;
  const d = new Date(dob);
  if (Number.isNaN(d.getTime())) return null;
  const today = new Date();
  let years = today.getFullYear() - d.getFullYear();
  let months = today.getMonth() - d.getMonth();
  if (today.getDate() < d.getDate()) months--;
  if (months < 0) { years--; months += 12; }
  if (years < 0) return null;
  return { years, months };
}

/**
 * "5y 2m" / "0y 3m" (or "" if dob is missing/invalid) — combined
 * years+months display so an infant's age reads as e.g. "0y 3m" instead
 * of being indistinguishable from "unknown".
 */
export function formatAgeYM(dob) {
  const a = calcAgeYM(dob);
  return a ? `${a.years}y ${a.months}m` : "";
}

/**
 * "5y 2m" (or "" if either part is missing) — for backend responses that
 * already computed years/months server-side (e.g. from a patient's linked
 * identity record where the raw DOB isn't sent to the client), so the
 * frontend doesn't need the DOB itself to render the same format.
 */
export function formatYearsMonths(years, months) {
  if (years == null || months == null) return "";
  return `${years}y ${months}m`;
}

export default calcAge;
