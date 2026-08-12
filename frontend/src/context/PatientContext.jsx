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
 * page refresh/navigation, not just a single render.
 */

import { createContext, useState, useEffect, useContext, useCallback } from "react";
import { apiClient }   from "../services/api.client";
import API_ENDPOINTS   from "../config/api.config";
import { AuthContext } from "./AuthContext";

export const PatientContext = createContext(null);

const STORAGE_KEY = "atomwalk:portal_selected_patient";

function readStored() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
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
  const [familyMembers, setFamilyMembers] = useState([]);
  const [isLoadingFamily, setIsLoadingFamily] = useState(false);

  const selfName = user?.full_name || user?.email?.split("@")[0] || "Me";

  const [selectedPatient, setSelectedPatient] = useState(() => {
    const stored = readStored();
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
        // Guards against the stale-localStorage case: the persisted
        // "viewing X" selection (see STORAGE_KEY below) is keyed globally in
        // this browser's localStorage, not per-account. If someone logs out
        // without it being cleared (token just expires, tab closed, etc.)
        // and a different patient logs in on the same browser, the selection
        // from the previous account would otherwise still be sitting there
        // and get applied to them — e.g. logging in as Meera but landing on
        // "Viewing: Ananya Krishnan" because Ananya was the last family
        // member someone viewed on this browser. Once the real family list
        // for the now-logged-in account is in, drop back to self if the
        // stored selection isn't actually one of their own family members.
        setSelectedPatient(prev => {
          if (prev.isSelf) return prev;
          const stillValid = results.some(m => m.awpid === prev.awpid);
          if (stillValid) return prev;
          localStorage.removeItem(STORAGE_KEY);
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
      localStorage.removeItem(STORAGE_KEY);
      setSelectedPatient({ awpid: null, name: selfName, isSelf: true });
      return;
    }
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ awpid, name }));
    setSelectedPatient({ awpid, name: name || "", isSelf: false });
  }, [selfName]);

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
