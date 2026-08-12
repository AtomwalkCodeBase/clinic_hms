/**
 * pages/patient/HospitalsPage.jsx
 * ---------------------------------
 * Step 1 of booking: browse hospitals as cards instead of a dropdown.
 */
import { useNavigate } from "react-router-dom";
import { Building2, MapPin, ShieldCheck } from "lucide-react";
import { AppShell }  from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import { useApi }    from "../../hooks/useApi";
import API_ENDPOINTS from "../../config/api.config";
import ROUTES        from "../../config/routes.config";

export default function PatientHospitalsPage() {
  const navigate = useNavigate();
  const { data, isLoading, error, refetch } = useApi(API_ENDPOINTS.PORTAL.HOSPITALS);
  const hospitals = data?.results || [];

  return (
    <AppShell>
      <PageShell title="Find a Hospital">
        <style>{`
          .hospital-card { transition: transform 160ms ease, box-shadow 160ms ease; }
          .hospital-card:hover { transform: translateY(-3px); box-shadow: 0 12px 32px rgba(0,0,0,0.12) !important; }
        `}</style>
        <p style={{ color: "var(--color-text-secondary)", fontSize: 13, marginBottom: 20, marginTop: -8 }}>
          Choose a hospital to see its doctors and book an appointment.
        </p>

        {isLoading ? (
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
        ) : hospitals.length === 0 ? (
          <div className="card" style={{ padding: 40, textAlign: "center", color: "var(--color-text-muted)" }}>
            No hospitals available right now.
          </div>
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: 18 }}>
            {hospitals.map(h => (
              <button
                key={h.tenant_id}
                onClick={() => navigate(ROUTES.PATIENT.HOSPITAL_DOCTORS(h.tenant_id))}
                className="card card--interactive hospital-card"
                style={{
                  textAlign: "left", padding: 0, cursor: "pointer", overflow: "hidden",
                  display: "flex", flexDirection: "column",
                }}
              >
                {/* Dark gradient header strip */}
                <div style={{
                  background: "linear-gradient(135deg, #1B5E43 0%, #123828 100%)",
                  padding: "18px 20px",
                  display: "flex", alignItems: "center", gap: 12,
                  position: "relative", overflow: "hidden",
                }}>
                  {/* Gold glow */}
                  <div style={{
                    position: "absolute", width: 160, height: 160, borderRadius: "50%",
                    background: "radial-gradient(circle, rgba(201,162,75,0.18) 0%, transparent 70%)",
                    top: -60, right: -40, pointerEvents: "none",
                  }} />
                  <div style={{
                    width: 44, height: 44, borderRadius: 12, flexShrink: 0,
                    background: "rgba(255,255,255,0.14)",
                    display: "flex", alignItems: "center", justifyContent: "center", color: "#fff",
                    border: "1px solid rgba(255,255,255,0.18)",
                    position: "relative",
                  }}>
                    <Building2 size={22} />
                  </div>
                  <div style={{ position: "relative", flex: 1, minWidth: 0 }}>
                    <div style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 16, color: "#fff", lineHeight: 1.25 }}>
                      {h.name}
                    </div>
                    <div style={{ fontSize: 12, color: "#8FA89A", marginTop: 3, display: "flex", alignItems: "center", gap: 4 }}>
                      <MapPin size={11} style={{ flexShrink: 0 }} />
                      {[h.city, h.state].filter(Boolean).join(", ") || "Location not listed"}
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

                  {/* Gold gradient CTA */}
                  <div style={{ marginTop: "auto" }}>
                    <div style={{
                      display: "inline-flex", alignItems: "center", gap: 6, marginTop: 8,
                      padding: "7px 16px", borderRadius: 20, fontSize: 12, fontWeight: 700,
                      background: "linear-gradient(135deg, #C9A24B 0%, #B07C24 100%)",
                      color: "#fff", boxShadow: "0 2px 8px rgba(201,162,75,0.30)",
                    }}>
                      View doctors →
                    </div>
                  </div>
                </div>
              </button>
            ))}
          </div>
        )}
      </PageShell>
    </AppShell>
  );
}
