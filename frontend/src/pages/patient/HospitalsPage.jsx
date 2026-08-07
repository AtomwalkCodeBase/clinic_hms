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
                className="card card--interactive"
                style={{
                  textAlign: "left", padding: 0, cursor: "pointer", overflow: "hidden",
                  display: "flex", flexDirection: "column",
                }}
              >
                <div style={{
                  height: 64, background: "linear-gradient(135deg, var(--color-primary) 0%, var(--color-primary-dark) 100%)",
                  display: "flex", alignItems: "center", padding: "0 20px", gap: 12,
                }}>
                  <div style={{
                    width: 40, height: 40, borderRadius: 10, background: "rgba(255,255,255,0.16)",
                    display: "flex", alignItems: "center", justifyContent: "center", color: "#fff", flexShrink: 0,
                  }}>
                    <Building2 size={20} />
                  </div>
                  <div style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 16, color: "#fff", lineHeight: 1.25 }}>
                    {h.name}
                  </div>
                </div>

                <div style={{ padding: "14px 20px 18px", display: "flex", flexDirection: "column", gap: 8, flex: 1 }}>
                  <div style={{ fontSize: 12, color: "var(--color-text-muted)", display: "flex", alignItems: "center", gap: 5 }}>
                    <MapPin size={13} style={{ flexShrink: 0 }} />
                    {[h.city, h.state].filter(Boolean).join(", ") || "Location not listed"}
                  </div>

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

                  <div style={{
                    marginTop: "auto", paddingTop: 8, fontSize: 12, color: "var(--color-primary)", fontWeight: 700,
                  }}>
                    View doctors →
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
