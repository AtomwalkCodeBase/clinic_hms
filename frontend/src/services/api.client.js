/** services/api.client.js */

import axios from "axios";
import APP_CONFIG from "../config/app.config";
import API_ENDPOINTS from "../config/api.config";

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
function normaliseError(error) {
  // When the backend didn't send a JSON `message` (network failure, CORS,
  const fallback = error.response
    ? `Something went wrong. If this keeps happening, contact ${APP_CONFIG.SUPPORT_EMAIL}.`
    : `Could not reach the server. Check your connection, or contact ${APP_CONFIG.SUPPORT_EMAIL} if it persists.`;
  // Most views return the standard {message: ...} shape (core/response.py),
  return {
    message: error.response?.data?.message
      || error.response?.data?.error
      // Bare DRF errors ({"detail": "..."}) — normally reshaped server-side by
      || (typeof error.response?.data?.detail === "string" ? error.response.data.detail : "")
      || fallback,
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

        const { data } = await publicClient.post(API_ENDPOINTS.AUTH.REFRESH, {
          refresh: refreshToken,
        });

        // The server wraps every reply as { success, message, data: {...} } (see
        const tokens = data?.data ?? data;
        if (!tokens?.access) throw new Error("Token refresh returned no access token");

        tokenStore.setAccess(tokens.access);
        if (tokens.refresh) tokenStore.setRefresh(tokens.refresh);
        processQueue(null, tokens.access);
        originalRequest.headers["Authorization"] = `Bearer ${tokens.access}`;
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
