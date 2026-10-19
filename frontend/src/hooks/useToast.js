/** hooks/useToast.js */

import { useMemo } from "react";
import { toast } from "react-toastify";
import APP_CONFIG from "../config/app.config";

const DEFAULTS = {
  autoClose:   APP_CONFIG.TOAST_DURATION_MS,
  hideProgressBar: false,
  closeOnClick: true,
  pauseOnHover: true,
};

// These never depend on component state or props, so they're defined once
const toastApi = {
  toastSuccess: (message, options = {}) =>
    toast.success(message, { ...DEFAULTS, ...options }),

  toastError: (message, options = {}) =>
    toast.error(message, { ...DEFAULTS, ...options }),

  toastWarning: (message, options = {}) =>
    toast.warning(message, { ...DEFAULTS, ...options }),

  toastInfo: (message, options = {}) =>
    toast.info(message, { ...DEFAULTS, ...options }),

  /** Use for API errors — reads message from normalised error object */
  toastApiError: (err, fallback = "Something went wrong.") =>
    toast.error(err?.message || fallback, { ...DEFAULTS }),
};

export function useToast() {
  // useMemo isn't strictly needed since toastApi is already a stable module
  return useMemo(() => toastApi, []);
}

export default useToast;
