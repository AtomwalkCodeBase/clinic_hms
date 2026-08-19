/**
 * context/AuthContext.jsx
 * -----------------------
 * Provides the authenticated user object, login/logout actions,
 * and the loading state across the entire app.
 *
 * What it stores:
 *   user      — decoded JWT payload (id, email, role, db_name, tenant_id, license_tier)
 *   isLoading — true while verifying token on first mount
 *
 * It does NOT store permissions — see PermissionContext.jsx.
 */

import { createContext, useState, useEffect, useCallback } from "react";
import { jwtDecode }      from "jwt-decode";
import { publicClient, tokenStore } from "../services/api.client";
import apiClient          from "../services/api.client";
import API_ENDPOINTS      from "../config/api.config";

export const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user,      setUser]      = useState(null);
  const [isLoading, setIsLoading] = useState(true);

  // The JWT never carries the profile photo (too large to put in a token),
  // so it's fetched separately from /me/ and merged onto the decoded-JWT
  // user object. Also backfills full_name for older tokens that predate it.
  const hydrateFromMe = useCallback((decoded) => {
    return apiClient.get(API_ENDPOINTS.AUTH.ME)
      .then(r => {
        const extra = r.data?.data || {};
        setUser({
          ...decoded,
          full_name: decoded.full_name || extra.full_name || "",
          photo: extra.photo || "",
          // Hospital's own logo (Tenant.logo) — same reasoning as photo:
          // too big for the JWT, fetched fresh so AppShell's topbar picks
          // up a newly-uploaded logo without needing a fresh login.
          logo: extra.logo || "",
        });
      })
      .catch(() => setUser(decoded));
  }, []);

  /** Re-pulls /me/ and merges the result onto the current user — call this
   *  after a profile photo (or other /me-visible field) changes, so the
   *  sidebar/topbar update immediately without requiring a fresh login. */
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
      setUser(null);
      tokenStore.clear();
      localStorage.removeItem("atomwalk:portal_selected_patient");
    };
    window.addEventListener("atomwalk:session-expired", onExpired);
    return () => window.removeEventListener("atomwalk:session-expired", onExpired);
  }, []);

  // ── Login ─────────────────────────────────────────────────────────────────
  /**
   * loginStaff / loginPatient — call the appropriate endpoint,
   * store tokens, decode and set user.
   * Returns { success: true } or throws with { message, errors }.
   */
  /**
   * `credentials` is either a mobile number (string — the common case), or
   * {subdomain, employeeId} for hospitals using employee-ID login (see
   * docs/onboarding_auth_rbac_architecture.md 3.1.2 — employee IDs aren't
   * globally unique, so that path needs the hospital's subdomain too).
   */
  const loginStaff = useCallback(async (credentials, password) => {
    const body = typeof credentials === "string"
      ? { mobile: credentials, password }
      : { subdomain: credentials.subdomain, employee_id: credentials.employeeId, password };
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

  /**
   * Day-to-day passwordless sign-in — consumes an action_token already
   * obtained from POST /auth/otp/verify/ (purpose="login_patient"). See
   * components/auth/PatientOTPLoginPanel.jsx for the request/verify UI.
   */
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
    // "Which family member am I viewing" (patient portal) is stored in
    // localStorage keyed globally, not per-account — clear it here so the
    // next login on this browser (a different patient, or the same one)
    // doesn't inherit a stranger's family-member selection. See also the
    // ownership check in PatientContext, which catches the case where this
    // didn't run (token just expired, no explicit logout).
    localStorage.removeItem("atomwalk:portal_selected_patient");
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider value={{ user, isLoading, loginStaff, loginPatient, loginPatientWithOTP, loginPlatform, logout, refreshUser }}>
      {children}
    </AuthContext.Provider>
  );
}
