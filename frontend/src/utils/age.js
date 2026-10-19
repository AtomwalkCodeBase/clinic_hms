/** utils/age.js */

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

/** Returns { years, months } elapsed since dob, or null if dob is */
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

/** "5y 2m" / "0y 3m" (or "" if dob is missing/invalid) — combined */
export function formatAgeYM(dob) {
  const a = calcAgeYM(dob);
  return a ? `${a.years}y ${a.months}m` : "";
}

/** "5y 2m" (or "" if either part is missing) — for backend responses that */
export function formatYearsMonths(years, months) {
  if (years == null || months == null) return "";
  return `${years}y ${months}m`;
}

export default calcAge;
