/** utils/validation.js */

// India-style mobile numbers: exactly 10 digits, no country code, no
const MOBILE_LENGTH = 10;

/** Strip everything but digits, and cap at `max` digits (default 10) — use */
export function sanitizeMobileInput(value, max = MOBILE_LENGTH) {
  return (value || "").replace(/\D/g, "").slice(0, max);
}

/** True only for exactly 10 digits. */
export function isValidMobile(value) {
  return /^\d{10}$/.test(value || "");
}

/** Standard error message for a mobile field, or "" if valid/empty */
export function mobileError(value) {
  if (!value) return "";
  return isValidMobile(value) ? "" : "Enter a valid 10-digit mobile number.";
}
