/**
 * services/api.client.js
 * ----------------------
 * Axios instance with:
 *   - Base URL from VITE_API_BASE_URL
 *   - Automatic JWT attachment from localStorage
 *   - 401 → token refresh → retry once
 *   - 403 → dispatch forbidden event
 *   - Standardised error shape passed to callers
 *
 * Import `apiClient` (authenticated) or `publicClient` (no auth) in service files.
 */

import axios from "axios";
import APP_CONFIG from "../config/app.config";

const BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

// ─── Token storage helpers ────────────────────────────────────────────────────
const TOKEN_KEY   = "atomwalk_access";
const REFRESH_KEY = "atomwalk_refresh";

export const tokenStore = {
  getAccess:      ()      => localStorage.getItem(TOKEN_KEY),
  getRefresh:     ()      => localStorage.getItem(REFRESH_KEY),
  setAccess:      (token) => localStorage.setItem(TOKEN_KEY, token),
  setRefresh:     (token) => localStorage.setItem(REFRESH_KEY, token),
  clear:          ()      => {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(REFRESH_KEY);
  },
};

// Turns an axios error into { message, errors, status, data } using the
// backend's own response body when there is one, instead of axios's generic
// "Request failed with status code NNN". Shared by both clients so login
// failures are just as informative as authenticated-request failures.
//
// `data` carries the full, unmodified response body — callers that need
// endpoint-specific fields beyond message/errors (e.g. PortalBookView's 428
// consent_required/hospital_name/share_categories payload) must read them
// from `err.data`, not `err.response.data` — `.response` does not exist on
// the object this function returns, it's replaced entirely.
function normaliseError(error) {
  // When the backend didn't send a JSON `message` (network failure, CORS,
  // timeout, or a 500 with no body), fall back to a real sentence — not the
  // bare support email, which used to render as a lone, meaningless toast
  // like "support@atomwalk.com" with no indication anything went wrong.
  const fallback = error.response
    ? `Something went wrong. If this keeps happening, contact ${APP_CONFIG.SUPPORT_EMAIL}.`
    : `Could not reach the server. Check your connection, or contact ${APP_CONFIG.SUPPORT_EMAIL} if it persists.`;
  // Most views return the standard {message: ...} shape (core/response.py),
  // but a chunk of apps/patients/portal_views.py predates that helper and
  // hand-rolls Response({"error": "..."}, status=...) instead — same intent,
  // different key. Without this fallback every real, specific reason (hospital
  // not found, not enrolled for online booking, etc.) silently collapsed into
  // the generic "Something went wrong" toast.
  return {
    message: error.response?.data?.message || error.response?.data?.error || fallback,
    errors:  error.response?.data?.errors  || {},
    status:  error.response?.status,
    data:    error.response?.data || null,
  };
}

// ─── Public client (login, refresh) ──────────────────────────────────────────
export const publicClient = axios.create({
  baseURL: BASE_URL,
  timeout: 15_000,
  headers: { "Content-Type": "application/json" },
});

publicClient.interceptors.response.use(
  (response) => response,
  (error) => Promise.reject(normaliseError(error)),
);

// ─── Authenticated client ─────────────────────────────────────────────────────
export const apiClient = axios.create({
  baseURL: BASE_URL,
  timeout: 15_000,
  headers: { "Content-Type": "application/json" },
});

// Attach access token to every request
apiClient.interceptors.request.use(
  (config) => {
    const token = tokenStore.getAccess();
    if (token) {
      config.headers["Authorization"] = `Bearer ${token}`;
    }
    return config;
  },
  (error) => Promise.reject(error)
);

// ─── Response interceptor: handle 401 with token refresh ─────────────────────
let isRefreshing = false;
let refreshQueue = [];          // queued requests waiting for new token

const processQueue = (error, token = null) => {
  refreshQueue.forEach((prom) =>
    error ? prom.reject(error) : prom.resolve(token)
  );
  refreshQueue = [];
};

apiClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config;

    if (error.response?.status === 401 && !originalRequest._retry) {
      if (isRefreshing) {
        // Queue this request until refresh completes
        return new Promise((resolve, reject) => {
          refreshQueue.push({ resolve, reject });
        }).then((token) => {
          originalRequest.headers["Authorization"] = `Bearer ${token}`;
          return apiClient(originalRequest);
        });
      }

      originalRequest._retry = true;
      isRefreshing = true;

      try {
        const refreshToken = tokenStore.getRefresh();
        if (!refreshToken) throw new Error("No refresh token");

        const { data } = await publicClient.post("/api/v1/auth/token/refresh/", {
          refresh: refreshToken,
        });

        tokenStore.setAccess(data.access);
        processQueue(null, data.access);
        originalRequest.headers["Authorization"] = `Bearer ${data.access}`;
        return apiClient(originalRequest);
      } catch (refreshError) {
        processQueue(refreshError, null);
        tokenStore.clear();
        // Notify app to redirect to login
        window.dispatchEvent(new CustomEvent("atomwalk:session-expired"));
        return Promise.reject(refreshError);
      } finally {
        isRefreshing = false;
      }
    }

    if (error.response?.status === 403) {
      window.dispatchEvent(new CustomEvent("atomwalk:forbidden"));
    }

    // Normalise error so callers always get { message, errors }
    const normalised = normaliseError(error);
    return Promise.reject(normalised);
  }
);

export default apiClient;
