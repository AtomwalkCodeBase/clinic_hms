/**
 * pages/patient/DashboardPage.jsx
 * ---------------------------------
 * Patient portal home — search-first landing. One box to search hospitals,
 * doctors, or a reason for visit ("cardiologist", "eye doctor", "fever") —
 * results come back from every active hospital, not just one the patient
 * has to pick first. Quick-access tiles below cover the rest (browse all
 * hospitals, appointments, records). Bookings summary stays underneath when
 * the patient isn't actively searching.
 */
import { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { Building2, Calendar, ClipboardList, Pill, FlaskConical, Search } from "lucide-react";
import { AppShell }    from "../../components/layout/AppShell";
import { PageShell }   from "../../components/common/PageShell";
import DoctorCard      from "../../components/common/DoctorCard";
import { useApi }      from "../../hooks/useApi";
import { useAuth }     from "../../hooks/useAuth";
import apiClient       from "../../services/api.client";
import API_ENDPOINTS   from "../../config/api.config";
import ROUTES          from "../../config/routes.config";

const BADGE = {
  scheduled:   "badge--primary",
  waiting:     "badge--warning",
  vitals_done: "badge--success",
  in_progress: "badge--info",
  done:        "badge--success",
  cancelled:   "badge--error",
};

// Map chip class to accent colors for left border + tint
const CHIP_COLORS = {
  "icon-chip--green": { border: "var(--color-primary)", tint: "var(--color-primary-light)" },
  "icon-chip--blue":  { border: "#2C5D7C", tint: "#E5EEF3" },
  "icon-chip--gold":  { border: "var(--color-accent)", tint: "var(--color-accent-light)" },
  "icon-chip--rose":  { border: "#B3402E", tint: "#F9E7E3" },
};

const QUICK_LINKS = [
  { label: "Browse Hospitals",  icon: Building2,     chip: "icon-chip--green", to: ROUTES.PATIENT.HOSPITALS,     desc: "See every hospital on the platform" },
  { label: "My Appointments",   icon: Calendar,      chip: "icon-chip--blue",  to: ROUTES.PATIENT.APPOINTMENTS,  desc: "Upcoming and past visits" },
  { label: "My Health Journey", icon: ClipboardList, chip: "icon-chip--gold",  to: ROUTES.PATIENT.RECORDS,       desc: "Diagnoses, allergies, vitals" },
  { label: "Prescriptions",     icon: Pill,          chip: "icon-chip--rose",  to: ROUTES.PATIENT.PRESCRIPTIONS, desc: "Medicines prescribed to you" },
  { label: "Lab Reports",       icon: FlaskConical,  chip: "icon-chip--blue",  to: ROUTES.PATIENT.LAB_REPORTS,   desc: "Test results and reports" },
];

function HospitalResultCard({ h, onClick }) {
  return (
    <button onClick={onClick} className="card card--interactive" style={{
      textAlign: "left", padding: 0, cursor: "pointer", width: "100%", overflow: "hidden",
      display: "flex", flexDirection: "column",
    }}>
      <div style={{ display: "flex", gap: 12, alignItems: "center", padding: "16px 16px 12px" }}>
        <div className="icon-chip icon-chip--green" style={{ width: 44, height: 44 }}>
          <Building2 size={20} />
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 15 }}>{h.name}</div>
          <div style={{ fontSize: 12, color: "var(--color-text-muted)", marginTop: 2 }}>
            {[h.city, h.state].filter(Boolean).join(", ") || "Location not listed"}
          </div>
        </div>
      </div>

      {h.about && (
        <div style={{ fontSize: 12, color: "var(--color-text-secondary)", lineHeight: 1.4, padding: "0 16px 10px" }}>
          {h.about.length > 90 ? `${h.about.slice(0, 90)}…` : h.about}
        </div>
      )}

      {h.accreditations?.length > 0 && (
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", padding: "0 16px 14px" }}>
          {h.accreditations.map(a => (
            <span key={a} className="tag-pill" style={{ background: "var(--color-success-light)", color: "var(--color-success)" }}>{a}</span>
          ))}
        </div>
      )}

      <div style={{
        marginTop: "auto", padding: "10px 16px", borderTop: "1px solid var(--color-border)",
        fontSize: 12, fontWeight: 700,
        background: "linear-gradient(135deg, var(--color-accent) 0%, var(--color-warning) 100%)",
        color: "#fff",
      }}>
        View doctors →
      </div>
    </button>
  );
}

const SORT_OPTIONS = [
  { value: "",           label: "Best match" },
  { value: "experience",  label: "Experience (high to low)" },
  { value: "fee",         label: "Consultation fee (low to high)" },
  { value: "name",        label: "Name (A–Z)" },
];

// Status color map for booking cards
const STATUS_COLORS = {
  scheduled:   { bg: "var(--color-primary-light)", border: "var(--color-primary)" },
  waiting:     { bg: "var(--color-warning-light)",  border: "var(--color-warning)" },
  vitals_done: { bg: "var(--color-success-light)",  border: "var(--color-success)" },
  in_progress: { bg: "var(--color-info-light)",     border: "var(--color-info)" },
  done:        { bg: "var(--color-success-light)",  border: "var(--color-success)" },
  cancelled:   { bg: "var(--color-error-light)",    border: "var(--color-error)" },
};

export default function PatientDashboardPage() {
  const { user } = useAuth();
  const navigate = useNavigate();

  const { data, isLoading } = useApi(API_ENDPOINTS.PORTAL.MY_BOOKINGS);
  const bookings = data?.results || [];
  // "Upcoming" = still active (not done/cancelled/no_show) AND its day hasn't
  // already passed — an appointment the hospital never closed out shouldn't
  // keep counting as upcoming forever once its date is in the past.
  const todayStr = new Date().toISOString().split("T")[0];
  const upcoming = bookings.filter(b =>
    !["done", "cancelled", "no_show"].includes(b.status) && b.date >= todayStr
  );

  const { data: stats } = useApi(API_ENDPOINTS.PORTAL.STATS);

  const [query, setQuery] = useState("");
  const [specialty, setSpecialty] = useState("");
  const [city, setCity] = useState("");
  const [sort, setSort] = useState("");
  const [showFilters, setShowFilters] = useState(false);
  const [results, setResults] = useState(null); // { hospitals, doctors } once searched
  const [searching, setSearching] = useState(false);
  const debounceRef = useRef(null);

  useEffect(() => {
    clearTimeout(debounceRef.current);
    const q = query.trim();
    const spec = specialty.trim();
    const cty = city.trim();
    if (q.length < 2 && !spec && !cty) {
      setResults(null);
      setSearching(false);
      return;
    }
    setSearching(true);
    debounceRef.current = setTimeout(() => {
      const params = {};
      if (q) params.q = q;
      if (spec) params.specialty = spec;
      if (cty) params.city = cty;
      if (sort) params.sort = sort;
      apiClient.get(API_ENDPOINTS.PORTAL.SEARCH, { params })
        .then(({ data: d }) => setResults(d))
        .catch(() => setResults({ hospitals: [], doctors: [] }))
        .finally(() => setSearching(false));
    }, 350);
    return () => clearTimeout(debounceRef.current);
  }, [query, specialty, city, sort]);

  const greeting = () => {
    const h = new Date().getHours();
    if (h < 12) return "Good morning";
    if (h < 17) return "Good afternoon";
    return "Good evening";
  };
  const firstName = (user?.full_name || user?.email?.split("@")[0] || "there").split(" ")[0];
  const isSearchActive = query.trim().length >= 2 || specialty.trim().length > 0 || city.trim().length > 0;

  return (
    <AppShell>
      <PageShell title="">
        {/* Hero — greeting, search, and live platform stats */}
        <div className="hero-card" style={{ marginBottom: 24, padding: "28px 28px 24px" }}>
          <div style={{ fontFamily: "var(--font-display)", fontSize: 26, fontWeight: 600, letterSpacing: "-0.01em", lineHeight: 1.25, color: "var(--color-hero-text)" }}>
            {greeting()}, <em style={{ fontStyle: "italic" }}>{firstName}</em>
          </div>
          <div style={{ fontSize: 13, fontWeight: 500, color: "var(--color-hero-muted)", marginTop: 4, marginBottom: 20 }}>
            Find the right doctor or hospital for your care.
          </div>

          {/* Search — white card-style with shadow, rounded */}
          <div style={{ position: "relative" }}>
            <Search size={16} style={{
              position: "absolute", left: 16, top: "50%", transform: "translateY(-50%)", color: "var(--color-text-muted)",
            }} />
            <input
              value={query}
              onChange={e => setQuery(e.target.value)}
              placeholder="Search hospitals, doctors, or a reason for visit — e.g. cardiologist, eye doctor, GreenLeaf Clinic"
              style={{
                width: "100%", boxSizing: "border-box", padding: "14px 16px 14px 42px", fontSize: 14,
                borderRadius: 50, border: "none", background: "#fff", color: "var(--color-text)",
              }}
            />
          </div>

          <div style={{ marginTop: 10 }}>
            <button
              onClick={() => setShowFilters(s => !s)}
              style={{ fontSize: 12, fontWeight: 600, color: "var(--color-hero-text)", background: "none", border: "none", cursor: "pointer", padding: 0, opacity: 0.85 }}
            >
              {showFilters ? "Hide filters ▲" : "Filter by specialty / city ▼"}
            </button>
            {showFilters && (
              <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginTop: 10 }}>
                <input
                  className="form-input"
                  value={specialty}
                  onChange={e => setSpecialty(e.target.value)}
                  placeholder="Specialty (e.g. cardiologist)"
                  style={{ flex: "1 1 200px", padding: "10px 12px", fontSize: 13, borderRadius: 8, border: "none" }}
                />
                <input
                  className="form-input"
                  value={city}
                  onChange={e => setCity(e.target.value)}
                  placeholder="City"
                  style={{ flex: "1 1 160px", padding: "10px 12px", fontSize: 13, borderRadius: 8, border: "none" }}
                />
                <select
                  className="form-input"
                  value={sort}
                  onChange={e => setSort(e.target.value)}
                  style={{ flex: "1 1 200px", padding: "10px 12px", fontSize: 13, borderRadius: 8, border: "none" }}
                >
                  {SORT_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                </select>
              </div>
            )}
          </div>

          {/* Hero stats — each in a tinted mini-card with accent color */}
          <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginTop: 24 }}>
            <div style={{
              background: "rgba(44,93,124,0.18)", borderRadius: 12, padding: "12px 20px", minWidth: 140,
              border: "1px solid rgba(44,93,124,0.25)",
            }}>
              <div className="hero-number" style={{ fontSize: 26, color: "#B9D3E0" }}>{stats ? stats.hospitals : "—"}</div>
              <div className="stat-label" style={{ marginTop: 2, color: "#C9D9E5" }}>Hospitals on the platform</div>
            </div>
            <div style={{
              background: "color-mix(in srgb, var(--color-primary) 18%, transparent)", borderRadius: 12, padding: "12px 20px", minWidth: 140,
              border: "1px solid color-mix(in srgb, var(--color-primary) 25%, transparent)",
            }}>
              <div className="hero-number" style={{ fontSize: 26, color: "color-mix(in srgb, var(--color-primary) 60%, white 40%)" }}>{stats ? stats.doctors : "—"}</div>
              <div className="stat-label" style={{ marginTop: 2, color: "color-mix(in srgb, var(--color-primary) 40%, white 60%)" }}>Doctors available</div>
            </div>
            <div style={{
              background: "color-mix(in srgb, var(--color-accent) 16%, transparent)", borderRadius: 12, padding: "12px 20px", minWidth: 140,
              border: "1px solid color-mix(in srgb, var(--color-accent) 28%, transparent)",
            }}>
              <div className="hero-number" style={{ fontSize: 26, color: "var(--color-accent)" }}>{isLoading ? "—" : upcoming.length}</div>
              <div className="stat-label" style={{ marginTop: 2, color: "color-mix(in srgb, var(--color-accent) 60%, white 40%)" }}>Upcoming visits</div>
            </div>
          </div>
        </div>

        {isSearchActive ? (
          // ── Search results ──────────────────────────────────────────────
          <div>
            {searching ? (
              <div className="card" style={{ padding: 40, textAlign: "center", color: "var(--color-text-muted)" }}>
                Searching…
              </div>
            ) : !results || (results.doctors.length === 0 && results.hospitals.length === 0) ? (
              <div className="card" style={{ padding: 44, textAlign: "center" }}>
                <div style={{ fontFamily: "var(--font-display)", fontSize: 17, fontWeight: 600, marginBottom: 6 }}>
                  {query.trim() ? `No matches for "${query.trim()}"` : "No matches for these filters"}
                </div>
                <div style={{ fontSize: 13, color: "var(--color-text-muted)" }}>
                  Try a specialisation (e.g. "dermatologist"), a doctor's name, or a hospital name.
                </div>
              </div>
            ) : (
              <div style={{ display: "grid", gap: 20 }}>
                {results.doctors.length > 0 && (
                  <div>
                    <div className="dot-label dot-label--green" style={{ marginBottom: 10 }}>
                      Doctors ({results.doctors.length})
                    </div>
                    <div style={{ display: "grid", gap: 14 }}>
                      {results.doctors.map(d => (
                        <DoctorCard key={`${d.tenant_id}-${d.id}`} d={d}
                          onBook={() => navigate(ROUTES.PATIENT.DOCTOR_PROFILE(d.tenant_id, d.id))}
                          onViewProfile={() => navigate(ROUTES.PATIENT.DOCTOR_PROFILE(d.tenant_id, d.id))} />
                      ))}
                    </div>
                  </div>
                )}
                {results.hospitals.length > 0 && (
                  <div>
                    <div className="dot-label dot-label--blue" style={{ marginBottom: 10 }}>
                      Hospitals ({results.hospitals.length})
                    </div>
                    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: 12 }}>
                      {results.hospitals.map(h => (
                        <HospitalResultCard key={h.tenant_id} h={h}
                          onClick={() => navigate(ROUTES.PATIENT.HOSPITAL_DOCTORS(h.tenant_id))} />
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        ) : (
          // ── Default landing — quick links + bookings summary ───────────
          <>
            <style>{`
              .ql-tile { transition: transform 160ms ease, box-shadow 160ms ease; }
              .ql-tile:hover { transform: translateY(-2px); box-shadow: 0 8px 24px rgba(0,0,0,0.10) !important; }
            `}</style>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(190px, 1fr))", gap: 14, marginBottom: 24 }}>
              {QUICK_LINKS.map(q => {
                const colors = CHIP_COLORS[q.chip] || CHIP_COLORS["icon-chip--green"];
                return (
                  <button key={q.label} onClick={() => navigate(q.to)}
                    className="card card--interactive ql-tile"
                    style={{
                      textAlign: "left", padding: 18, cursor: "pointer",
                      display: "flex", flexDirection: "column", gap: 6,
                      borderLeft: `4px solid ${colors.border}`,
                    }}>
                    <div className={`icon-chip ${q.chip}`} style={{ width: 40, height: 40 }}>
                      <q.icon size={19} />
                    </div>
                    <div style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 15, marginTop: 6 }}>{q.label}</div>
                    <div style={{ fontSize: 12, color: "var(--color-text-muted)", lineHeight: 1.4 }}>{q.desc}</div>
                  </button>
                );
              })}
            </div>

            <div>
              <div style={{ marginBottom: 12 }}>
                <span className="dot-label dot-label--green">Your bookings</span>
              </div>
              {isLoading ? (
                <div className="card" style={{ padding: 32, textAlign: "center", color: "var(--color-text-muted)" }}>Loading…</div>
              ) : bookings.length === 0 ? (
                <div className="card" style={{ padding: 44, textAlign: "center" }}>
                  <div style={{ fontFamily: "var(--font-display)", fontSize: 18, fontWeight: 600, marginBottom: 6 }}>
                    No bookings yet
                  </div>
                  <div style={{ fontSize: 13, color: "var(--color-text-muted)", marginBottom: 16 }}>
                    Search above for a doctor or hospital to book your first appointment.
                  </div>
                </div>
              ) : (
                <div style={{ display: "grid", gap: 12 }}>
                  {bookings.map((b) => {
                    const statusStyle = STATUS_COLORS[b.status] || { bg: "#F8F8F6", border: "var(--color-border)" };
                    return (
                      <div key={b.id} style={{
                        borderRadius: 14, overflow: "hidden",
                        border: `1.5px solid ${statusStyle.border}`,
                      }}>
                        {/* Header strip */}
                        <div style={{
                          background: "linear-gradient(135deg, var(--color-hero) 0%, var(--color-hero-2) 100%)",
                          padding: "12px 18px",
                          display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12,
                        }}>
                          <div style={{ minWidth: 0 }}>
                            <div style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 15, color: "#fff" }}>
                              {b.hospital}
                            </div>
                            <div style={{ fontSize: 12, color: "var(--color-hero-muted)", marginTop: 3 }}>
                              {b.doctor}{b.date ? ` · ${b.date}` : ""}{b.time ? ` · ${b.time}` : ""}
                            </div>
                          </div>
                          <span className={`badge ${BADGE[b.status] || "badge--neutral"}`} style={{ flexShrink: 0 }}>
                            {b.status?.replace(/_/g, " ")}
                          </span>
                        </div>

                        {/* Body */}
                        <div style={{
                          padding: "12px 18px", background: statusStyle.bg,
                          display: "flex", alignItems: "center", gap: 16,
                        }}>
                          {b.token_number != null && (
                            <div style={{
                              flexShrink: 0, textAlign: "center",
                              background: "#fff", border: "1px solid #EDD49A",
                              borderRadius: 10, padding: "6px 14px",
                            }}>
                              <div style={{ fontSize: 9, fontWeight: 700, color: "#9B7B40", textTransform: "uppercase", letterSpacing: "0.07em" }}>Token</div>
                              <div style={{ fontFamily: "var(--font-display)", fontWeight: 800, fontSize: 22, color: "var(--color-accent)", lineHeight: 1.1 }}>
                                #{b.token_number}
                              </div>
                            </div>
                          )}
                          {b.chief_complaint ? (
                            <div style={{
                              fontSize: 13, color: "var(--color-text-secondary)", fontStyle: "italic",
                              borderLeft: `3px solid ${statusStyle.border}`, paddingLeft: 12, lineHeight: 1.5,
                            }}>
                              "{b.chief_complaint}"
                            </div>
                          ) : (
                            <div style={{ fontSize: 12, color: "var(--color-text-muted)" }}>
                              No chief complaint recorded
                            </div>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </>
        )}
      </PageShell>
    </AppShell>
  );
}
