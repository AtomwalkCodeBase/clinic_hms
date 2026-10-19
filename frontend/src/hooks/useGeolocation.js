/** hooks/useGeolocation.js */
import { useState, useCallback } from "react";

// Geolocation only works in a "secure context" (HTTPS, or localhost for
export function useGeolocation() {
  const [status, setStatus] = useState("idle");
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
