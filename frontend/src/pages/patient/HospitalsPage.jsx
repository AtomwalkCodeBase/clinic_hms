/**
 * pages/patient/HospitalsPage.jsx
 * ---------------------------------
 * Step 1 of booking: browse hospitals as cards instead of a dropdown.
 * Also doubles as a cross-hospital search — a text box, a specialty
 * dropdown (built from every doctor's specialisation across every active
 * hospital, not a hardcoded list — see PortalSpecialtyListView), and a
 * city filter. Reuses the same /portal/search/ endpoint the dashboard's
 * search box already calls, so results stay consistent platform-wide.
 */
import { useState, useEffect, useMemo, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { Building2, MapPin, ShieldCheck, Search, SlidersHorizontal, X, LocateFixed, LoaderCircle } from "lucide-react";
import { AppShell }  from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import DoctorCard    from "../../components/common/DoctorCard";
import HospitalDirections from "../../components/common/HospitalDirections";
import { useApi }    from "../../hooks/useApi";
import { useGeolocation } from "../../hooks/useGeolocation";
import apiClient     from "../../services/api.client";
import API_ENDPOINTS from "../../config/api.config";
import ROUTES        from "../../config/routes.config";

function HospitalCard({ h, onClick }) {
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onClick}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") onClick?.(); }}
      className="card card--interactive hospital-card"
      style={{
        textAlign: "left", padding: 0, cursor: "pointer", overflow: "hidden",
        display: "flex", flexDirection: "column",
      }}
    >
      <div style={{
        background: "linear-gradient(135deg, var(--color-hero) 0%, var(--color-hero-2) 100%)",
        padding: "18px 20px",
        display: "flex", alignItems: "center", gap: 12,
        position: "relative", overflow: "hidden",
      }}>
        <div style={{
          width: 44, height: 44, borderRadius: 12, flexShrink: 0,
          background: h.logo ? "#fff" : "rgba(255,255,255,0.14)",
          display: "flex", alignItems: "center", justifyContent: "center", color: "#fff",
          border: "1px solid rgba(255,255,255,0.18)",
          position: "relative", overflow: "hidden",
        }}>
          {h.logo
            ? <img src={h.logo} alt={h.name} style={{ width: "84%", height: "84%", objectFit: "contain" }} />
            : <Building2 size={22} />}
        </div>
        <div style={{ position: "relative", flex: 1, minWidth: 0 }}>
          <div style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 16, color: "#fff", lineHeight: 1.25 }}>
            {h.name}
          </div>
          <div style={{ fontSize: 12, color: "var(--color-hero-muted)", marginTop: 3, display: "flex", alignItems: "center", gap: 4 }}>
            <MapPin size={11} style={{ flexShrink: 0 }} />
            {[h.city, h.state].filter(Boolean).join(", ") || "Location not listed"}
            {h.distance_km != null && (
              <span style={{ fontWeight: 700, color: "#fff" }}>· {h.distance_km} km away</span>
            )}
          </div>
        </div>
      </div>

      <div style={{ padding: "14px 20px 16px", display: "flex", flexDirection: "column", gap: 8, flex: 1, background: "#fff" }}>
        {h.about && (
          <div style={{ fontSize: 12, color: "var(--color-text-secondary)", lineHeight: 1.5 }}>
            {h.about.length > 110 ? `${h.about.slice(0, 110)}…` : h.about}
          </div>
        )}

        {h.accreditations?.length > 0 && (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 2 }}>
            {h.accreditations.map(a => (
              <span key={a} className="tag-pill" style={{
                background: "var(--color-success-light)", color: "var(--color-success)",
                display: "inline-flex", alignItems: "center", gap: 4,
              }}>
                <ShieldCheck size={11} />{a}
              </span>
            ))}
          </div>
        )}

        {(h.latitude != null && h.longitude != null) && (
          <HospitalDirections latitude={h.latitude} longitude={h.longitude} hospitalName={h.name} />
        )}

        <div style={{ marginTop: "auto" }}>
          <div style={{
            display: "inline-flex", alignItems: "center", gap: 6, marginTop: 8,
            padding: "7px 16px", borderRadius: 20, fontSize: 12, fontWeight: 700,
            background: "linear-gradient(135deg, var(--color-accent) 0%, var(--color-warning) 100%)",
            color: "#fff",
          }}>
            View doctors →
          </div>
        </div>
      </div>
    </div>
  );
}

export default function PatientHospitalsPage() {
  const navigate = useNavigate();
  const geo = useGeolocation();
  const nearMeParams = geo.coords ? { lat: geo.coords.lat, lng: geo.coords.lng } : {};
  const { data, isLoading, error, refetch } = useApi(API_ENDPOINTS.PORTAL.HOSPITALS, { params: nearMeParams });
  const allHospitals = data?.results || [];

  const { data: specData } = useApi(API_ENDPOINTS.PORTAL.SPECIALTIES);
  const specialties = specData?.results || [];

  const cities = useMemo(() => {
    const set = new Set(allHospitals.map(h => h.city).filter(Boolean));
    return Array.from(set).sort();
  }, [allHospitals]);

  const [query, setQuery] = useState("");
  const [specialty, setSpecialty] = useState("");
  const [city, setCity] = useState("");
  const [showFilters, setShowFilters] = useState(false);
  const [searchResults, setSearchResults] = useState(null); // { hospitals, doctors }
  const [searching, setSearching] = useState(false);
  const debounceRef = useRef(null);

  const activeFilterCount = [specialty, city].filter(Boolean).length;
  const isFilterActive = query.trim().length >= 2 || specialty !== "" || city !== "";

  function clearFilters() {
    setQuery(""); setSpecialty(""); setCity("");
  }

  useEffect(() => {
    clearTimeout(debounceRef.current);
    if (!isFilterActive) {
      setSearchResults(null);
      setSearching(false);
      return;
    }
    setSearching(true);
    debounceRef.current = setTimeout(() => {
      const params = { ...nearMeParams };
      if (query.trim().length >= 2) params.q = query.trim();
      if (specialty) params.specialty = specialty;
      if (city) params.city = city;
      if (geo.coords) params.sort = "distance";
      apiClient.get(API_ENDPOINTS.PORTAL.SEARCH, { params })
        .then(({ data: d }) => setSearchResults(d))
        .catch(() => setSearchResults({ hospitals: [], doctors: [] }))
        .finally(() => setSearching(false));
    }, 350);
    return () => clearTimeout(debounceRef.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query, specialty, city, geo.coords]);

  const inputStyle = {
    width: "100%", boxSizing: "border-box", padding: "10px 12px", fontSize: 13,
    borderRadius: 8, border: "1.5px solid var(--color-border)", background: "var(--color-surface)",
    color: "var(--color-text)",
  };
  const labelStyle = { display: "block", fontSize: 11, fontWeight: 700, color: "var(--color-text-muted)", marginBottom: 4 };

  return (
    <AppShell>
      <PageShell title="Find a Hospital">
        <style>{`
          .hospital-card { transition: transform 160ms ease; }
          .hospital-card:hover { transform: translateY(-3px); }
          .spin { animation: hospitals-page-spin 1s linear infinite; }
          @keyframes hospitals-page-spin { to { transform: rotate(360deg); } }
        `}</style>
        <p style={{ color: "var(--color-text-secondary)", fontSize: 13, marginBottom: 16, marginTop: -8 }}>
          Choose a hospital to see its doctors and book an appointment — or search across every hospital.
        </p>

        {/* Search + filters */}
        <div style={{ marginBottom: 22 }}>
          <div style={{ position: "relative" }}>
            <Search size={16} style={{
              position: "absolute", left: 14, top: "50%", transform: "translateY(-50%)", color: "var(--color-text-muted)",
            }} />
            <input
              value={query}
              onChange={e => setQuery(e.target.value)}
              placeholder="Search hospitals, doctors, or a reason for visit — e.g. cardiologist, GreenLeaf Clinic"
              className="form-input"
              style={{ width: "100%", boxSizing: "border-box", padding: "12px 14px 12px 38px", fontSize: 13.5, borderRadius: 10 }}
            />
          </div>

          <div style={{ marginTop: 10, display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
            <button
              onClick={() => setShowFilters(s => !s)}
              className="btn-outline"
              style={{ display: "inline-flex", alignItems: "center", gap: 7, fontSize: 12.5, fontWeight: 700, padding: "7px 14px" }}
            >
              <SlidersHorizontal size={13} />
              {showFilters ? "Hide filters" : "Filters"}
              {!showFilters && activeFilterCount > 0 && (
                <span style={{
                  background: "var(--color-accent)", color: "#fff", borderRadius: 20, fontSize: 10.5,
                  fontWeight: 800, padding: "1px 7px", minWidth: 18, textAlign: "center",
                }}>
                  {activeFilterCount}
                </span>
              )}
            </button>

            {geo.status === "granted" ? (
              <button
                onClick={geo.clear}
                className="btn-outline"
                style={{ display: "inline-flex", alignItems: "center", gap: 7, fontSize: 12.5, fontWeight: 700, padding: "7px 14px", color: "var(--color-success)", borderColor: "var(--color-success)" }}
              >
                <LocateFixed size={13} /> Sorted by distance
              </button>
            ) : (
              <button
                onClick={geo.request}
                disabled={geo.status === "requesting"}
                className="btn-outline"
                style={{ display: "inline-flex", alignItems: "center", gap: 7, fontSize: 12.5, fontWeight: 700, padding: "7px 14px" }}
              >
                {geo.status === "requesting"
                  ? <LoaderCircle size={13} className="spin" />
                  : <LocateFixed size={13} />}
                {geo.status === "requesting" ? "Finding you…" : "Use my location"}
              </button>
            )}

            {(activeFilterCount > 0 || query) && (
              <button
                onClick={clearFilters}
                style={{
                  display: "inline-flex", alignItems: "center", gap: 5, fontSize: 12, fontWeight: 700,
                  color: "var(--color-text-muted)", background: "none", border: "none", cursor: "pointer", padding: "6px 4px",
                }}
              >
                <X size={13} /> Clear
              </button>
            )}
          </div>

          {(geo.status === "denied" || geo.status === "error" || geo.status === "unavailable") && (
            <div style={{ marginTop: 8, fontSize: 12, color: "var(--color-text-muted)" }}>
              {geo.errorMessage || "Couldn't use your location."} Showing hospitals alphabetically instead.
            </div>
          )}

          {showFilters && (
            <div className="card" style={{ marginTop: 10, padding: 14, display: "flex", gap: 12, flexWrap: "wrap" }}>
              <div style={{ flex: "1 1 220px" }}>
                <label style={labelStyle}>Kind of doctor / specialization</label>
                <select className="form-input" style={inputStyle} value={specialty} onChange={e => setSpecialty(e.target.value)}>
                  <option value="">All specialties</option>
                  {specialties.map(s => (
                    <option key={s.name} value={s.name}>{s.name} ({s.doctor_count})</option>
                  ))}
                </select>
              </div>
              <div style={{ flex: "1 1 180px" }}>
                <label style={labelStyle}>City</label>
                <select className="form-input" style={inputStyle} value={city} onChange={e => setCity(e.target.value)}>
                  <option value="">All cities</option>
                  {cities.map(c => <option key={c} value={c}>{c}</option>)}
                </select>
              </div>
            </div>
          )}
        </div>

        {isFilterActive ? (
          // ── Search results across every hospital ──────────────────────
          searching ? (
            <div style={{ padding: 40, textAlign: "center", color: "var(--color-text-muted)" }}>Searching…</div>
          ) : !searchResults || (searchResults.hospitals.length === 0 && searchResults.doctors.length === 0) ? (
            <div className="card" style={{ padding: 44, textAlign: "center" }}>
              <div style={{ fontFamily: "var(--font-display)", fontSize: 17, fontWeight: 600, marginBottom: 6 }}>
                No matches found
              </div>
              <div style={{ fontSize: 13, color: "var(--color-text-muted)" }}>
                Try a different specialization, city, or search term.
              </div>
            </div>
          ) : (
            <div style={{ display: "grid", gap: 24 }}>
              {searchResults.doctors.length > 0 && (
                <div>
                  <div className="dot-label dot-label--green" style={{ marginBottom: 10 }}>
                    Doctors ({searchResults.doctors.length})
                  </div>
                  <div style={{ display: "grid", gap: 14 }}>
                    {searchResults.doctors.map(d => (
                      <DoctorCard key={`${d.tenant_id}-${d.id}`} d={d}
                        onBook={() => navigate(ROUTES.PATIENT.DOCTOR_PROFILE(d.tenant_id, d.id))}
                        onViewProfile={() => navigate(ROUTES.PATIENT.DOCTOR_PROFILE(d.tenant_id, d.id))} />
                    ))}
                  </div>
                </div>
              )}
              {searchResults.hospitals.length > 0 && (
                <div>
                  <div className="dot-label dot-label--blue" style={{ marginBottom: 10 }}>
                    Hospitals ({searchResults.hospitals.length})
                  </div>
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: 18 }}>
                    {searchResults.hospitals.map(h => (
                      <HospitalCard key={h.tenant_id} h={h} onClick={() => navigate(ROUTES.PATIENT.HOSPITAL_DOCTORS(h.tenant_id))} />
                    ))}
                  </div>
                </div>
              )}
            </div>
          )
        ) : isLoading ? (
          <div style={{ padding: 40, textAlign: "center", color: "var(--color-text-muted)" }}>Loading hospitals…</div>
        ) : error ? (
          <div className="card" style={{ padding: 40, textAlign: "center" }}>
            <div style={{ color: "var(--color-error, #b91c1c)", fontWeight: 600, marginBottom: 6 }}>
              Couldn't load hospitals.
            </div>
            <div style={{ fontSize: 12, color: "var(--color-text-muted)", marginBottom: 14 }}>
              {error?.message || "Something went wrong talking to the server."}
            </div>
            <button className="btn btn--secondary" onClick={refetch}>Retry</button>
          </div>
        ) : allHospitals.length === 0 ? (
          <div className="card" style={{ padding: 40, textAlign: "center", color: "var(--color-text-muted)" }}>
            No hospitals available right now.
          </div>
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: 18 }}>
            {allHospitals.map(h => (
              <HospitalCard key={h.tenant_id} h={h} onClick={() => navigate(ROUTES.PATIENT.HOSPITAL_DOCTORS(h.tenant_id))} />
            ))}
          </div>
        )}
      </PageShell>
    </AppShell>
  );
}
