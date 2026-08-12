/**
 * utils/validation.js
 * --------------------
 * Small shared input-validation helpers. Kept framework-free (plain
 * functions) so they can be used from any form's onChange handler or
 * validate() step without pulling in a form library.
 */

// India-style mobile numbers: exactly 10 digits, no country code, no
// leading zero requirement enforced here (backend is the source of truth
// for anything stricter) — this just stops the common "fat-fingered too
// few/too many digits" mistake at entry time.
const MOBILE_LENGTH = 10;

/** Strip everything but digits, and cap at `max` digits (default 10) — use
 * this directly in an onChange handler so the field can never *contain*
 * more than `max` digits in the first place, instead of only validating
 * after the fact. */
export function sanitizeMobileInput(value, max = MOBILE_LENGTH) {
  return (value || "").replace(/\D/g, "").slice(0, max);
}

/** True only for exactly 10 digits. */
export function isValidMobile(value) {
  return /^\d{10}$/.test(value || "");
}

/** Standard error message for a mobile field, or "" if valid/empty
 * (pair with a `required` check separately if the field is mandatory). */
export function mobileError(value) {
  if (!value) return "";
  return isValidMobile(value) ? "" : "Enter a valid 10-digit mobile number.";
}
