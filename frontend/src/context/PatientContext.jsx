/**
 * context/PatientContext.jsx
 * ---------------------------
 * Patient portal only. Tracks "which patient am I currently viewing" —
 * the logged-in account owner (self) or one of their linked family
 * members — as a single shared value across Dashboard/Records/
 * Prescriptions/Lab Reports, instead of each page re-deriving it from
 * its own URL query params.
 *
 * Convention: awpid === null means "self" (the account owner) — this
 * matches the backend's own convention (see _resolve_target_awpid_and_dob
 * in apps/patients/portal_views.py: an empty/missing patient_awpid
 * defaults to the account owner). Pages that call the my-records /
 * health-summary / growth / vaccinations endpoints should only send a
 * patient_awpid param when selectedPatient.awpid is set.
 *
 * Persisted in localStorage (same pattern as hooks/useActiveBranch.js's
 * "which branch am I viewing" switcher) so the selection survives a
 * page refresh/navigation, not just a single render — but keyed PER
 * ACCOUNT (see storageKeyFor below), not globally. Earlier revisions used
 * one global key, which meant a same-browser account switch (token just
 * expired, tab closed without logout, kiosk/shared device) could seed
 * `selectedPatient` from the PREVIOUS account's selection before an async
 * check could catch it — e.g. logging in as Meera but landing on "Viewing:
 * Ananya Krishnan" because Ananya was the last family member someone
 * viewed on this browser, with any component that fetches on mount
 * potentially firing against that wrong awpid before the correction ran.
 * Scoping the key by user_id removes the race at the root instead of
 * self-healing after the fact: a different account's PatientProvider reads
 * a DIFFERENT key from the start, so there is never a wrong value to seed
 * from in the first place. PatientProvider only ever mounts inside
 * ProtectedRoute (see App.jsx's PatientRoute), so `user` — and therefore
 * user.user_id — is always already populated by the time this runs.
 */

import { createContext, useState, useEffect, useContext, useCallback } from "react";
import { apiClient }   from "../services/api.client";
import API_ENDPOINTS   from "../config/api.config";
import { AuthContext } from "./AuthContext";

export const PatientContext = createContext(null);

const STORAGE_PREFIX = "atomwalk:portal_selected_patient";

function storageKeyFor(userId) {
  return userId ? `${STORAGE_PREFIX}:${userId}` : null;
}

/** Called from AuthContext on logout / detected session expiry — tidies up
 *  this account's stored selection so a shared device doesn't accumulate
 *  one leftover entry per patient who's ever used it. Not required for
 *  correctness (the per-account key already prevents any cross-account
 *  leak on its own), just housekeeping. */
export function clearStoredSelection(userId) {
  const key = storageKeyFor(userId);
  if (key) localStorage.removeItem(key);
}

function readStored(userId) {
  const key = storageKeyFor(userId);
  if (!key) return null;
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (parsed && parsed.awpid) return { awpid: parsed.awpid, name: parsed.name || "" };
  } catch {
    // ignore malformed storage
  }
  return null;
}

export function PatientProvider({ children }) {
  const { user } = useContext(AuthContext);
  const userId = user?.user_id ?? null;
  const [familyMembers, setFamilyMembers] = useState([]);
  const [isLoadingFamily, setIsLoadingFamily] = useState(false);

  const selfName = user?.full_name || user?.email?.split("@")[0] || "Me";

  const [selectedPatient, setSelectedPatient] = useState(() => {
    const stored = readStored(userId);
    return stored
      ? { awpid: stored.awpid, name: stored.name, isSelf: false }
      : { awpid: null, name: selfName, isSelf: true };
  });

  // Keep the "self" label in sync once the user's real name loads (the
  // initial render may only have an email-derived fallback).
  useEffect(() => {
    setSelectedPatient(prev => (prev.isSelf ? { ...prev, name: selfName } : prev));
  }, [selfName]);

  // Fetch the family list once on mount (patient portal only).
  useEffect(() => {
    if (!user) return;
    setIsLoadingFamily(true);
    apiClient.get(API_ENDPOINTS.PORTAL.FAMILY)
      .then(({ data: res }) => {
        const results = res?.data?.results || [];
        setFamilyMembers(results);
        // Belt-and-suspenders: the per-account key already means this
        // account can never have SEEDED from someone else's selection, but
        // still drop back to self if the stored awpid no longer resolves to
        // one of this account's own family members (e.g. removed since the
        // last visit).
        setSelectedPatient(prev => {
          if (prev.isSelf) return prev;
          const stillValid = results.some(m => m.awpid === prev.awpid);
          if (stillValid) return prev;
          clearStoredSelection(userId);
          return { awpid: null, name: selfName, isSelf: true };
        });
      })
      .catch(() => setFamilyMembers([]))
      .finally(() => setIsLoadingFamily(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user]);

  /** selectPatient(null, null) (or no args) resets the view back to self. */
  const selectPatient = useCallback((awpid, name) => {
    if (!awpid) {
      clearStoredSelection(userId);
      setSelectedPatient({ awpid: null, name: selfName, isSelf: true });
      return;
    }
    const key = storageKeyFor(userId);
    if (key) localStorage.setItem(key, JSON.stringify({ awpid, name }));
    setSelectedPatient({ awpid, name: name || "", isSelf: false });
  }, [selfName, userId]);

  return (
    <PatientContext.Provider value={{ familyMembers, isLoadingFamily, selectedPatient, selectPatient }}>
      {children}
    </PatientContext.Provider>
  );
}

export function usePatientContext() {
  const ctx = useContext(PatientContext);
  if (!ctx) {
    throw new Error("usePatientContext must be used within a PatientProvider");
  }
  return ctx;
}

export default PatientContext;
