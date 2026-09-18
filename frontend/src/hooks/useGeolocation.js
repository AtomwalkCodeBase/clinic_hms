/**
 * hooks/useGeolocation.js
 * ------------------------
 * Thin wrapper around the browser's Geolocation API for the patient
 * portal's "hospitals near me". Deliberately consent-first: nothing here
 * calls getCurrentPosition on mount — a caller must invoke request() from
 * a real user action (a button click), so the permission prompt only
 * appears when the patient actually asked for it.
 *
 * Coordinates never get persisted anywhere (no localStorage, no backend
 * write) — they only ever travel as query params on the one request that
 * needs them, for the lifetime of this page.
 */
import { useState, useCallback } from "react";

// Geolocation only works in a "secure context" (HTTPS, or localhost for
// dev) — on plain HTTP, navigator.geolocation may be undefined, or
// getCurrentPosition may fail immediately. Either way this surfaces as
// "unavailable"/"error" below rather than throwing, so the page keeps
// working with the plain (non-sorted) hospital list.
export function useGeolocation() {
  const [status, setStatus] = useState("idle"); // idle | requesting | granted | denied | unavailable | error
  const [coords, setCoords] = useState(null);    // { lat, lng } | null
  const [errorMessage, setErrorMessage] = useState("");

  const request = useCallback(() => {
    if (!("geolocation" in navigator)) {
      setStatus("unavailable");
      setErrorMessage("This browser doesn't support location.");
      return;
    }
    setStatus("requesting");
    setErrorMessage("");
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setCoords({ lat: pos.coords.latitude, lng: pos.coords.longitude });
        setStatus("granted");
      },
      (err) => {
        // err.code: 1 = PERMISSION_DENIED, 2 = POSITION_UNAVAILABLE, 3 = TIMEOUT
        setStatus(err.code === 1 ? "denied" : "error");
        setErrorMessage(
          err.code === 1
            ? "Location permission denied."
            : "Couldn't determine your location. Try again."
        );
      },
      { enableHighAccuracy: false, timeout: 10000, maximumAge: 5 * 60 * 1000 }
    );
  }, []);

  const clear = useCallback(() => {
    setStatus("idle");
    setCoords(null);
    setErrorMessage("");
  }, []);

  return { status, coords, errorMessage, request, clear };
}

export default useGeolocation;
