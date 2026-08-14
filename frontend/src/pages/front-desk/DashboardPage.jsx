/**
 * pages/front-desk/DashboardPage.jsx
 * ------------------------------------
 * Front desk home — premium theme.
 * Hero with today's flow + quick actions + live queue snapshot.
 */
import { useNavigate } from "react-router-dom";
import { AppShell }    from "../../components/layout/AppShell";
import { PageShell }   from "../../components/common/PageShell";
import { useApi }      from "../../hooks/useApi";
import { useAuth }     from "../../hooks/useAuth";
import API_ENDPOINTS   from "../../config/api.config";
import { ROUTES }      from "../../config/routes.config";

const TODAY = new Date().toISOString().split("T")[0];

function Sparkline({ points, width = 170, height = 44 }) {
  if (!points || points.length < 2) points = [0, 0];
  const max = Math.max(...points, 1);
  const step = width / (points.length - 1);
  const d = points
    .map((p, i) => `${i === 0 ? "M" : "L"}${(i * step).toFixed(1)},${(height - (p / max) * height + 2).toFixed(1)}`)
    .join(" ");
  return (
    <svg width={width} height={height + 4} style={{ overflow: "visible" }}>
      <path d={d} fill="none" stroke="var(--color-accent)" strokeWidth="2"
        strokeLinecap="round" strokeLinejoin="round" opacity="0.9" />
    </svg>
  );
}

export default function FrontDeskDashboardPage() {
  const navigate = useNavigate();
  const { user } = useAuth();

  const { data: meData } = useApi(API_ENDPOINTS.ORG.MY_PROFILE);
  const photo = meData?.photo;

  const { data: apptData, isLoading } = useApi(API_ENDPOINTS.OPD.APPOINTMENTS, {
    params: { date: TODAY },
  });
  const appointments = apptData?.results || apptData || [];

  const { data: statsData } = useApi(API_ENDPOINTS.OPD.STATS, { params: { days: 14 } });
  const weekStats = statsData?.results || [];

  const waiting    = appointments.filter(a => ["waiting", "scheduled"].includes(a.status)).length;
  const inProgress = appointments.filter(a => a.status === "in_progress").length;
  const done       = appointments.filter(a => a.status === "done").length;

  const greeting = () => {
    const h = new Date().getHours();
    if (h < 12) return "Good morning";
    if (h < 17) return "Good afternoon";
    return "Good evening";
  };
  const firstName = (user?.full_name || user?.email?.split("@")[0] || "there").split(" ")[0];
  const dateStr = new Date().toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long" });

  return (
    <AppShell>
      <PageShell title="">
        {/* Greeting */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 22 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
            <div
              onClick={() => navigate(ROUTES.FRONT_DESK.MY_PROFILE)}
              title="My Profile"
              style={{
                width: 48, height: 48, borderRadius: "50%", overflow: "hidden", cursor: "pointer",
                background: "var(--color-primary-light)", color: "var(--color-primary)",
                display: "flex", alignItems: "center", justifyContent: "center",
                fontSize: 16, fontWeight: 700, flexShrink: 0, border: "2px solid var(--color-border)",
              }}
            >
              {photo ? <img src={photo} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} /> : firstName?.charAt(0)}
            </div>
            <div>
              <div className="page-greeting-title">
                {greeting()}, <em style={{ fontStyle: "italic", color: "var(--color-primary)" }}>{firstName}</em>
              </div>
              <div className="page-greeting-sub">
                Front desk overview · {dateStr}
              </div>
            </div>
          </div>
          <div style={{ display: "flex", gap: 10 }}>
            <button className="btn-outline" style={{ fontSize: 12 }}
              onClick={() => navigate(ROUTES.FRONT_DESK.APPOINTMENTS)}>+ Appointment</button>
            <button className="btn-primary" style={{ fontSize: 12 }}
              onClick={() => navigate(ROUTES.FRONT_DESK.REGISTER_PATIENT)}>+ Patient</button>
          </div>
        </div>

        {/* Hero */}
        <div className="hero-card" style={{ marginBottom: 22 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
            <div>
              <div className="stat-label" style={{ marginBottom: 8 }}>Appointments today</div>
              <div className="hero-number">{isLoading ? "—" : appointments.length}</div>
              <div className="hero-sub" style={{ marginTop: 6 }}>
                {waiting} in queue · {done} completed
              </div>
            </div>
            <div style={{ textAlign: "right" }}>
              <div className="stat-label" style={{ marginBottom: 10 }}>14-day trend</div>
              <Sparkline points={weekStats.map(d => d.total)} />
            </div>
          </div>
          <hr className="hero-divider" />
          <div style={{ display: "flex", gap: 48 }}>
            {[
              { label: "In queue",     value: waiting },
              { label: "With doctor",  value: inProgress },
              { label: "Completed",    value: done },
            ].map(({ label, value }) => (
              <div key={label}>
                <div className="stat-label" style={{ marginBottom: 4 }}>{label}</div>
                <div style={{ fontFamily: "var(--font-display)", fontSize: 22, fontWeight: 600 }}>
                  {isLoading ? "—" : value}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Queue snapshot */}
        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          <div style={{
            display: "flex", justifyContent: "space-between", alignItems: "center",
            padding: "14px 20px", borderBottom: "1px solid var(--color-border)",
          }}>
            <span className="dot-label dot-label--green">Today's queue</span>
            <button className="btn-outline" style={{ fontSize: 12, padding: "5px 14px" }}
              onClick={() => navigate(ROUTES.FRONT_DESK.QUEUE)}>
              Open full queue →
            </button>
          </div>
          {isLoading ? (
            <div style={{ padding: 32, textAlign: "center", color: "var(--color-text-muted)" }}>Loading…</div>
          ) : appointments.length === 0 ? (
            <div style={{ padding: 40, textAlign: "center" }}>
              <div style={{ fontFamily: "var(--font-display)", fontSize: 18, fontWeight: 600, marginBottom: 6 }}>
                No appointments yet today
              </div>
              <div style={{ fontSize: 13, color: "var(--color-text-muted)" }}>
                Book an appointment or register a new patient to get started.
              </div>
            </div>
          ) : (
            <table className="data-table">
              <thead>
                <tr>
                  <th style={{ width: 60 }}>#</th>
                  <th>Patient</th>
                  <th>Doctor</th>
                  <th>Complaint</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {appointments.slice(0, 8).map(a => (
                  <tr key={a.id}>
                    <td style={{ fontWeight: 800, color: "var(--color-primary)" }}>{a.token_number}</td>
                    <td style={{ fontWeight: 600 }}>{a.patient_name || "—"}</td>
                    <td style={{ fontSize: 12, color: "var(--color-text-muted)" }}>{a.doctor_name || "—"}</td>
                    <td style={{ fontSize: 12 }}>{a.chief_complaint || "—"}</td>
                    <td>
                      <span className={`badge ${
                        a.status === "done" ? "badge--success"
                        : a.status === "in_progress" ? "badge--info"
                        : a.status === "cancelled" ? "badge--error"
                        : "badge--warning"}`}>
                        {a.status?.replace("_", " ")}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </PageShell>
    </AppShell>
  );
}
