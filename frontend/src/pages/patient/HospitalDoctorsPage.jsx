/**
 * pages/patient/HospitalDoctorsPage.jsx
 * ----------------------------------------
 * Step 2 of booking: doctors at the chosen hospital, as cards.
 */
import { useParams, useNavigate, Link } from "react-router-dom";
import { ShieldCheck } from "lucide-react";
import { AppShell }  from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import DoctorCard    from "../../components/common/DoctorCard";
import { useApi }    from "../../hooks/useApi";
import API_ENDPOINTS from "../../config/api.config";
import ROUTES        from "../../config/routes.config";

export default function PatientHospitalDoctorsPage() {
  const { tenantId } = useParams();
  const navigate = useNavigate();

  const { data: hospData } = useApi(API_ENDPOINTS.PORTAL.HOSPITALS);
  const hospital = (hospData?.results || []).find(h => String(h.tenant_id) === String(tenantId));

  const { data, isLoading, error, refetch } = useApi(API_ENDPOINTS.PORTAL.DOCTORS(tenantId));
  const doctors = data?.results || [];

  return (
    <AppShell>
      <PageShell title={hospital ? hospital.name : "Doctors"}>
        <Link to={ROUTES.PATIENT.HOSPITALS} style={{ fontSize: 12, color: "var(--color-text-muted)", display: "inline-block", marginBottom: 14 }}>
          ← All hospitals
        </Link>

        {hospital && (hospital.about || hospital.accreditations?.length > 0) && (
          <div className="card" style={{ padding: 16, marginBottom: 16 }}>
            {hospital.about && (
              <div style={{ fontSize: 13, color: "var(--color-text-secondary)", lineHeight: 1.5, marginBottom: hospital.accreditations?.length ? 10 : 0 }}>
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
        ) : doctors.length === 0 ? (
          <div className="card" style={{ padding: 40, textAlign: "center", color: "var(--color-text-muted)" }}>
            No doctors listed at this hospital yet.
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
