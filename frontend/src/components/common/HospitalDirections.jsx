/**
 * components/common/HospitalDirections.jsx
 * ------------------------------------------
 * "Get Directions" + an optional map preview for a hospital, given its
 * lat/lng (see Tenant.latitude/longitude, returned by _hospital_card /
 * PortalDoctorDetailView / PortalBookView / PortalMyBookingsView).
 *
 * Deliberately no maps SDK / API key: "Get Directions" opens Google Maps'
 * plain directions URL (works as a web page AND deep-links into the
 * Google/Apple Maps app on mobile, giving real turn-by-turn navigation for
 * free), and the preview is the keyless `output=embed` iframe. Renders
 * nothing if this hospital has no coordinates on file yet — that's a real,
 * expected state (platform admin hasn't set them), not an error.
 */
import { useEffect, useRef, useState } from "react";
import { MapPin, Navigation } from "lucide-react";
import { useGeolocation } from "../../hooks/useGeolocation";

export default function HospitalDirections({ latitude, longitude, hospitalName, defaultShowMap = false }) {
  const geo = useGeolocation();
  const [showMap, setShowMap] = useState(defaultShowMap);
  const [pendingDirections, setPendingDirections] = useState(false);
  // Holds the tab opened synchronously in the click handler while we wait
  // on the (async) geolocation callback — see handleGetDirections below.
  const pendingWinRef = useRef(null);

  const directionsUrl = (originLat, originLng) => {
    const params = new URLSearchParams({
      api: "1",
      destination: `${latitude},${longitude}`,
      travelmode: "driving",
    });
    if (originLat != null && originLng != null) {
      params.set("origin", `${originLat},${originLng}`);
    }
    return `https://www.google.com/maps/dir/?${params.toString()}`;
  };

  const handleGetDirections = () => {
    if (geo.status === "granted" && geo.coords) {
      window.open(directionsUrl(geo.coords.lat, geo.coords.lng), "_blank", "noopener,noreferrer");
      return;
    }
    // getCurrentPosition is async, so window.open() can't be called from
    // its callback — by then the browser no longer considers it a direct
    // result of this click and silently blocks it as a popup. Instead,
    // open the tab right now (still inside the click handler, so it's
    // allowed) and navigate that same tab once we know the real URL.
    pendingWinRef.current = window.open("", "_blank");
    setPendingDirections(true);
    geo.request();
  };

  useEffect(() => {
    if (!pendingDirections) return;
    const win = pendingWinRef.current;
    if (geo.status === "granted" && geo.coords) {
      if (win) win.location.href = directionsUrl(geo.coords.lat, geo.coords.lng);
      setPendingDirections(false);
      pendingWinRef.current = null;
    } else if (geo.status === "denied" || geo.status === "unavailable" || geo.status === "error") {
      // Fall back to a destination-only link — Google Maps will use its
      // own location detection (or ask the patient to search from wherever
      // they are) instead of the trip being blocked entirely.
      if (win) win.location.href = directionsUrl(null, null);
      setPendingDirections(false);
      pendingWinRef.current = null;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [geo.status, pendingDirections]);

  if (latitude == null || longitude == null) return null;

  return (
    <div style={{ display: "grid", gap: 8 }}>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <button
          onClick={(e) => { e.stopPropagation(); handleGetDirections(); }}
          disabled={geo.status === "requesting"}
          style={{
            display: "flex", alignItems: "center", gap: 6, padding: "8px 14px",
            borderRadius: "var(--radius-button)", border: "1.5px solid var(--color-primary)",
            background: "transparent", color: "var(--color-primary)", fontWeight: 700, fontSize: 12,
            cursor: geo.status === "requesting" ? "default" : "pointer", whiteSpace: "nowrap",
          }}
        >
          <Navigation size={13} />
          {geo.status === "requesting" ? "Locating you…" : "Get Directions"}
        </button>
        <button
          onClick={(e) => { e.stopPropagation(); setShowMap(v => !v); }}
          style={{
            display: "flex", alignItems: "center", gap: 6, padding: "8px 14px",
            borderRadius: "var(--radius-button)", border: "1.5px solid var(--color-border)",
            background: "transparent", color: "var(--color-text-secondary)", fontWeight: 700, fontSize: 12,
            cursor: "pointer", whiteSpace: "nowrap",
          }}
        >
          <MapPin size={13} />
          {showMap ? "Hide map" : "View on map"}
        </button>
      </div>
      {geo.status === "denied" && (
        <div style={{ fontSize: 11, color: "var(--color-text-muted)" }}>
          Location permission denied — opening directions without your starting point.
        </div>
      )}
      {showMap && (
        <iframe
          title={`Map location of ${hospitalName || "hospital"}`}
          src={`https://www.google.com/maps?q=${latitude},${longitude}&output=embed`}
          width="100%"
          height="220"
          style={{ border: 0, borderRadius: "var(--radius-card, 10px)" }}
          loading="lazy"
          referrerPolicy="no-referrer-when-downgrade"
        />
      )}
    </div>
  );
}
