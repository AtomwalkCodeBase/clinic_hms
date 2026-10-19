/** context/AuthContext.jsx */

import { createContext, useState, useEffect, useCallback, useRef } from "react";
import { jwtDecode }      from "jwt-decode";
import { publicClient, tokenStore } from "../services/api.client";
import apiClient          from "../services/api.client";
import API_ENDPOINTS      from "../config/api.config";
import { clearStoredSelection } from "./PatientContext";

export const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user,      setUser]      = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  // logout()/the session-expired handler below are stable useCallbacks (empty
  const userRef = useRef(user);
  useEffect(() => { userRef.current = user; }, [user]);

  // The JWT never carries the profile photo (too large to put in a token),
  const hydrateFromMe = useCallback((decoded) => {
    return apiClient.get(API_ENDPOINTS.AUTH.ME)
      .then(r => {
        const extra = r.data?.data || {};
        setUser({
          ...decoded,
          full_name: decoded.full_name || extra.full_name || "",
          photo: extra.photo || "",
          // Hospital's own logo (Hospital.logo) — same reasoning as photo:
          logo: extra.logo || "",
        });
      })
      .catch(() => setUser(decoded));
  }, []);

  /** Re-pulls /me/ and merges the result onto the current user — call this */
  const refreshUser = useCallback(() => {
    return apiClient.get(API_ENDPOINTS.AUTH.ME)
      .then(r => {
        const extra = r.data?.data || {};
        setUser(prev => prev ? { ...prev, ...extra } : prev);
      })
      .catch(() => {});
  }, []);

  // ── Hydrate from stored token on mount ───────────────────────────────────
  useEffect(() => {
    const token = tokenStore.getAccess();
    if (token) {
      try {
        const decoded = jwtDecode(token);
        // Reject expired tokens
        if (decoded.exp * 1000 > Date.now()) {
          hydrateFromMe(decoded).finally(() => setIsLoading(false));
          return; // isLoading is set false in .finally()
        } else {
          tokenStore.clear();
        }
      } catch {
        tokenStore.clear();
      }
    }
    setIsLoading(false);
  }, [hydrateFromMe]);

  // ── Listen for session expiry fired by API client interceptor ────────────
  useEffect(() => {
    const onExpired = () => {
      clearStoredSelection(userRef.current?.user_id);
      setUser(null);
      tokenStore.clear();
    };
    window.addEventListener("atomwalk:session-expired", onExpired);
    return () => window.removeEventListener("atomwalk:session-expired", onExpired);
  }, []);

  // ── Login ─────────────────────────────────────────────────────────────────
  /** loginStaff / loginPatient — call the appropriate endpoint, */
  /** `credentials` is either a mobile number (string — the common case), or */
  const loginStaff = useCallback(async (credentials, password) => {
    const body = typeof credentials === "string"
      ? { mobile: credentials, password }
      : { hospital_code: credentials.hospital_code, employee_id: credentials.employeeId, password };
    const { data } = await publicClient.post(API_ENDPOINTS.AUTH.STAFF_LOGIN, body);
    tokenStore.setAccess(data.data.access);
    tokenStore.setRefresh(data.data.refresh);
    await hydrateFromMe(jwtDecode(data.data.access));
    return { success: true, must_change_password: data.data.must_change_password };
  }, [hydrateFromMe]);

  const loginPlatform = useCallback(async (username, password) => {
    const { data } = await publicClient.post(API_ENDPOINTS.AUTH.PLATFORM_LOGIN, {
      username,
      password,
    });
    tokenStore.setAccess(data.data.access);
    tokenStore.setRefresh(data.data.refresh);
    await hydrateFromMe(jwtDecode(data.data.access));
    return { success: true };
  }, [hydrateFromMe]);

  const loginPatient = useCallback(async (mobileOrAwpid, password) => {
    const { data } = await publicClient.post(API_ENDPOINTS.AUTH.PATIENT_LOGIN, {
      mobile: mobileOrAwpid,
      password,
    });
    tokenStore.setAccess(data.data.access);
    tokenStore.setRefresh(data.data.refresh);
    await hydrateFromMe(jwtDecode(data.data.access));
    return { success: true };
  }, [hydrateFromMe]);

  /** Day-to-day passwordless sign-in — consumes an action_token already */
  const loginPatientWithOTP = useCallback(async (actionToken) => {
    const { data } = await publicClient.post(API_ENDPOINTS.AUTH.PATIENT_LOGIN_OTP, {
      action_token: actionToken,
    });
    tokenStore.setAccess(data.data.access);
    tokenStore.setRefresh(data.data.refresh);
    await hydrateFromMe(jwtDecode(data.data.access));
    return { success: true };
  }, [hydrateFromMe]);

  // ── Logout ────────────────────────────────────────────────────────────────
  const logout = useCallback(() => {
    tokenStore.clear();
    // Tidy up this account's own stored "which family member am I viewing"
    clearStoredSelection(userRef.current?.user_id);
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider value={{ user, isLoading, loginStaff, loginPatient, loginPatientWithOTP, loginPlatform, logout, refreshUser }}>
      {children}
    </AuthContext.Provider>
  );
}
