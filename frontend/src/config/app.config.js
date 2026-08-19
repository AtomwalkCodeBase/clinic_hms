/**
 * config/app.config.js
 * --------------------
 * Application-level configuration constants.
 * Update this file to rebrand or change global app settings.
 */

export const APP_CONFIG = {
  /** Application display name */
  APP_NAME: "AW360™ Clinical HMS",

  /** Shown in browser tab and meta tags */
  SITE_TITLE: "AW360™ HMS — Hospital Management System",

  /** Version string for display/debugging */
  VERSION: "1.0.0",

  /** Company name for footers and legal text */
  COMPANY_NAME: "Atomwalk Technologies Pvt. Ltd.",

  /** Support email shown in error pages */
  SUPPORT_EMAIL: "support@atomwalk.com",

  /** Support phone number */
  SUPPORT_PHONE: "+91 80 1234 5678",

  /** Default locale for date/number formatting */
  DEFAULT_LOCALE: "en-IN",

  /** Default currency for billing display */
  DEFAULT_CURRENCY: "INR",

  /** Number of results per page for list views */
  DEFAULT_PAGE_SIZE: 20,

  /** Session timeout in minutes (JWT refresh interval) */
  SESSION_TIMEOUT_MINUTES: 60,

  /** Toast notification auto-dismiss duration (ms) */
  TOAST_DURATION_MS: 4000,

  /** Debounce delay for search inputs (ms) */
  SEARCH_DEBOUNCE_MS: 300,
};

export default APP_CONFIG;
