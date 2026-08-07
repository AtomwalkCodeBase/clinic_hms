/**
 * hooks/useToast.js
 * -----------------
 * Thin wrapper around react-toastify so components
 * import one hook instead of the library directly.
 *
 * Usage:
 *   const { toastSuccess, toastError, toastInfo } = useToast();
 *   toastSuccess("Patient registered!");
 */

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
// at module scope and the hook just hands back the same object every call.
// Returning a fresh object/functions on every render (as this used to do)
// breaks any caller that puts toastApiError etc. in a useCallback/useEffect
// dependency array — the changed identity re-triggers the effect on every
// render, and if that effect fetches data and the fetch fails, it retoasts
// and re-renders forever (seen on the hospital-admin dashboard: a single
// failed request turned into an endless stream of duplicate error toasts).
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
  // singleton, but keeping the hook shape means callers don't need to change.
  return useMemo(() => toastApi, []);
}

export default useToast;
