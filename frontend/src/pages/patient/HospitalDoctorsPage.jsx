/**
 * pages/patient/HospitalDoctorsPage.jsx
 * ----------------------------------------
 * Step 2 of booking: doctors at the chosen hospital, as cards. Same
 * search-box + specialty-dropdown pattern as HospitalsPage, but scoped to
 * this one hospital's already-fetched doctor list — filtered client-side
 * (no need to hit the cross-hospital /portal/search/ endpoint for a list
 * this small).
 */
import { useState, useMemo } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { Building2, MapPin, ShieldCheck, Search, SlidersHorizontal, X } from "lucide-react";
import { AppShell }  from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import DoctorCard    from "../../components/common/DoctorCard";
import HospitalDirections from "../../components/common/HospitalDirections";
import { useApi }    from "../../hooks/useApi";
import API_ENDPOINTS from "../../config/api.config";
import ROUTES        from "../../config/routes.config";

export default function PatientHospitalDoctorsPage() {
  const { tenantId } = useParams();
  const navigate = useNavigate();

  const { data: hospData } = useApi(API_ENDPOINTS.PORTAL.HOSPITALS);
  const hospital = (hospData?.results || []).find(h => String(h.tenant_id) === String(tenantId));

  const { data, isLoading, error, refetch } = useApi(API_ENDPOINTS.PORTAL.DOCTORS(tenantId));
  const allDoctors = data?.results || [];

  const specialties = useMemo(() => {
    const counts = new Map();
    for (const d of allDoctors) {
      const name = (d.specialisation || "").trim();
      if (!name) continue;
      counts.set(name, (counts.get(name) || 0) + 1);
    }
    return Array.from(counts.entries()).sort((a, b) => a[0].localeCompare(b[0]));
  }, [allDoctors]);

  const [query, setQuery] = useState("");
  const [specialty, setSpecialty] = useState("");
  const [showFilters, setShowFilters] = useState(false);

  const doctors = useMemo(() => {
    const q = query.trim().toLowerCase();
    return allDoctors.filter(d => {
      if (specialty && (d.specialisation || "").trim() !== specialty) return false;
      if (!q) return true;
      return [d.name, d.specialisation, d.qualification, d.known_for]
        .some(f => (f || "").toLowerCase().includes(q));
    });
  }, [allDoctors, query, specialty]);

  const activeFilterCount = specialty ? 1 : 0;
  function clearFilters() { setQuery(""); setSpecialty(""); }

  return (
    <AppShell>
      <PageShell title={hospital ? hospital.name : "Doctors"}>
        <Link to={ROUTES.PATIENT.HOSPITALS} style={{ fontSize: 12, color: "var(--color-text-muted)", display: "inline-block", marginBottom: 14 }}>
          ← All hospitals
        </Link>

        {/* Hospital info card with dark gradient header */}
        {hospital && (
          <div className="card" style={{ padding: 0, overflow: "hidden", marginBottom: 16 }}>
            <div style={{
              background: "linear-gradient(135deg, var(--color-hero) 0%, var(--color-hero-2) 100%)",
              padding: "16px 20px",
              display: "flex", alignItems: "center", gap: 14,
              position: "relative", overflow: "hidden",
            }}>
              <div style={{
                width: 48, height: 48, borderRadius: 12, flexShrink: 0,
                background: hospital.logo ? "#fff" : "rgba(255,255,255,0.14)",
                display: "flex", alignItems: "center", justifyContent: "center", color: "#fff",
                border: "1px solid rgba(255,255,255,0.2)",
                position: "relative", overflow: "hidden",
              }}>
                {hospital.logo
                  ? <img src={hospital.logo} alt={hospital.name} style={{ width: "84%", height: "84%", objectFit: "contain" }} />
                  : <Building2 size={24} />}
              </div>
              <div style={{ position: "relative", flex: 1, minWidth: 0 }}>
                <div style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 17, color: "#fff" }}>
                  {hospital.name}
                </div>
                {(hospital.city || hospital.state) && (
                  <div style={{ fontSize: 12, color: "var(--color-hero-muted)", marginTop: 3, display: "flex", alignItems: "center", gap: 4 }}>
                    <MapPin size={11} />
                    {[hospital.city, hospital.state].filter(Boolean).join(", ")}
                  </div>
                )}
              </div>
            </div>

            {(hospital.about || hospital.accreditations?.length > 0 || (hospital.latitude != null && hospital.longitude != null)) && (
              <div style={{ padding: "14px 20px", display: "grid", gap: 12 }}>
                {hospital.about && (
                  <div style={{ fontSize: 13, color: "var(--color-text-secondary)", lineHeight: 1.5 }}>
                    {hospital.about}
                  </div>
                )}
                {hospital.accreditations?.length > 0 && (
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                    {hospital.accreditations.map(a => (
                      <span key={a} className="tag-pill" style={{
                        background: "var(--color-success-light)", color: "var(--color-success)",
                        display: "inline-flex", alignItems: "center", gap: 4,
                      }}>
                        <ShieldCheck size={11} />{a}
                      </span>
                    ))}
                  </div>
                )}
                {(hospital.latitude != null && hospital.longitude != null) && (
                  <HospitalDirections latitude={hospital.latitude} longitude={hospital.longitude} hospitalName={hospital.name} />
                )}
              </div>
            )}
          </div>
        )}

        {!isLoading && !error && allDoctors.length > 0 && (
          <div style={{ marginBottom: 18 }}>
            <div style={{ position: "relative" }}>
              <Search size={16} style={{
                position: "absolute", left: 14, top: "50%", transform: "translateY(-50%)", color: "var(--color-text-muted)",
              }} />
              <input
                value={query}
                onChange={e => setQuery(e.target.value)}
                placeholder="Search doctors by name, specialization, or condition"
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

            {showFilters && (
              <div className="card" style={{ marginTop: 10, padding: 14 }}>
                <label style={{ display: "block", fontSize: 11, fontWeight: 700, color: "var(--color-text-muted)", marginBottom: 4 }}>
                  Kind of doctor / specialization
                </label>
                <select
                  className="form-input"
                  value={specialty}
                  onChange={e => setSpecialty(e.target.value)}
                  style={{
                    width: "100%", maxWidth: 320, boxSizing: "border-box", padding: "10px 12px", fontSize: 13,
                    borderRadius: 8, border: "1.5px solid var(--color-border)", background: "var(--color-surface)",
                    color: "var(--color-text)",
                  }}
                >
                  <option value="">All specialties</option>
                  {specialties.map(([name, count]) => (
                    <option key={name} value={name}>{name} ({count})</option>
                  ))}
                </select>
              </div>
            )}
          </div>
        )}

        {isLoading ? (
          <div style={{ padding: 40, textAlign: "center", color: "var(--color-text-muted)" }}>Loading doctors…</div>
        ) : error ? (
          <div className="card" style={{ padding: 40, textAlign: "center" }}>
            <div style={{ color: "var(--color-error, #b91c1c)", fontWeight: 600, marginBottom: 6 }}>
              Couldn't load doctors.
            </div>
            <div style={{ fontSize: 12, color: "var(--color-text-muted)", marginBottom: 14 }}>
              {error?.message || "Something went wrong talking to the server."}
            </div>
            <button className="btn btn--secondary" onClick={refetch}>Retry</button>
          </div>
        ) : allDoctors.length === 0 ? (
          <div className="card" style={{ padding: 40, textAlign: "center", color: "var(--color-text-muted)" }}>
            No doctors listed at this hospital yet.
          </div>
        ) : doctors.length === 0 ? (
          <div className="card" style={{ padding: 40, textAlign: "center", color: "var(--color-text-muted)" }}>
            No doctors match your search or filters.
          </div>
        ) : (
          <div style={{ display: "grid", gap: 14 }}>
            {doctors.map(d => (
              <DoctorCard
                key={d.id}
                d={d}
                hospitalName={hospital?.name}
                hospitalCity={hospital?.city}
                onBook={() => navigate(ROUTES.PATIENT.DOCTOR_PROFILE(tenantId, d.id))}
                onViewProfile={() => navigate(ROUTES.PATIENT.DOCTOR_PROFILE(tenantId, d.id))}
              />
            ))}
          </div>
        )}
      </PageShell>
    </AppShell>
  );
}
