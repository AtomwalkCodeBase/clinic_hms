/**
 * constants/messages.js
 * ---------------------
 * User-facing message strings. Centralised to make future i18n easy.
 * Never hardcode user-facing strings in components.
 */

export const MESSAGES = {
  // Generic
  SUCCESS:                "Operation successful.",
  SAVE_SUCCESS:           "Saved successfully.",
  DELETE_SUCCESS:         "Deleted successfully.",
  NETWORK_ERROR:          "Unable to connect. Please check your internet connection.",
  UNEXPECTED_ERROR:       "Something went wrong. Please try again.",
  UNAUTHORISED:           "You are not authorised to perform this action.",
  SESSION_EXPIRED:        "Your session has expired. Please log in again.",
  FORBIDDEN:              "Access denied.",
  NOT_FOUND:              "The requested resource was not found.",

  // Auth
  LOGIN_SUCCESS:          "Logged in successfully.",
  LOGOUT_SUCCESS:         "Logged out.",
  PASSWORD_SETUP_SUCCESS: "Password set successfully. You can now log in.",
  INVALID_CREDENTIALS:    "Invalid email or password.",

  // Patients
  PATIENT_REGISTERED:     "Patient registered successfully.",
  PATIENT_NOT_FOUND:      "No patient found with the given details.",
  AWPID_COPIED:           "AWPID copied to clipboard.",

  // Appointments
  APPOINTMENT_BOOKED:     "Appointment booked successfully.",
  APPOINTMENT_CANCELLED:  "Appointment cancelled.",

  // Encounters
  ENCOUNTER_OPENED:       "Encounter started.",
  ENCOUNTER_CLOSED:       "Encounter closed and records finalised.",

  // Lab
  LAB_REQUEST_CREATED:    "Lab test ordered.",
  REPORT_DELIVERED:       "Lab report delivered to patient.",

  // Prescriptions
  PRESCRIPTION_FINALISED: "Prescription finalised.",
  PRESCRIPTION_DISPENSED: "Prescription dispensed.",

  // Billing
  INVOICE_CREATED:        "Invoice created.",
  PAYMENT_RECORDED:       "Payment recorded.",

  // Tier gating
  UPGRADE_REQUIRED:       "This feature requires a higher subscription tier. Please contact your administrator.",

  // Validation
  REQUIRED_FIELD:         "This field is required.",
  INVALID_MOBILE:         "Enter a valid 10-digit Indian mobile number.",
  INVALID_EMAIL:          "Enter a valid email address.",
  PASSWORDS_MISMATCH:     "Passwords do not match.",
  MIN_LENGTH: (n) => `Must be at least ${n} characters.`,
  MAX_LENGTH: (n) => `Must be at most ${n} characters.`,
};

export default MESSAGES;
