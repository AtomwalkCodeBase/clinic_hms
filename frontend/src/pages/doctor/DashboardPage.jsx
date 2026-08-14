/**
 * pages/doctor/DashboardPage.jsx
 * --------------------------------
 * Doctor's home view — premium theme.
 * Serif greeting + dark hero card with queue stats + today's schedule.
 */
import { useState, useCallback } from "react";
import { useNavigate }   from "react-router-dom";
import { AppShell }      from "../../components/layout/AppShell";
import { PageShell }     from "../../components/common/PageShell";
import { useApi }        from "../../hooks/useApi";
import { useAuth }       from "../../hooks/useAuth";
import { useToast }      from "../../hooks/useToast";
import { useActiveBranch } from "../../hooks/useActiveBranch";
import BranchSwitcher    from "../../components/common/BranchSwitcher";
import apiClient         from "../../services/api.client";
import API_ENDPOINTS     from "../../config/api.config";

const TODAY = new Date().toISOString().split("T")[0];

const STATUS_COLORS = {
  waiting:     { bg: "var(--color-warning-light)", color: "var(--color-warning)" },
  vitals_done: { bg: "var(--color-success-light)", color: "var(--color-success)" },
  in_progress: { bg: "var(--color-info-light)",    color: "var(--color-info)" },
  done:        { bg: "var(--color-success-light)", color: "var(--color-success)" },
  cancelled:   { bg: "var(--color-error-light)",   color: "var(--color-error)" },
  scheduled:   { bg: "var(--color-primary-light)", color: "var(--color-primary)" },
};

function Badge({ status }) {
  const s = STATUS_COLORS[status] || { bg: "var(--color-border)", color: "var(--color-text-muted)" };
  return (
    <span style={{
      display: "inline-block", padding: "2px 10px", borderRadius: 12,
      fontSize: 11, fontWeight: 700, background: s.bg, color: s.color,
      textTransform: "capitalize",
    }}>
      {status?.replace("_", " ")}
    </span>
  );
}

/* Tiny inline sparkline (SVG) */
function Sparkline({ points, width = 160, height = 44 }) {
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

export default function DoctorDashboardPage() {
  const { user }   = useAuth();
  const navigate   = useNavigate();
  const { toastApiError } = useToast();
  const [starting, setStarting] = useState(null);

  const { data: meData } = useApi(API_ENDPOINTS.ORG.MY_PROFILE);
  const photo = meData?.photo;
  const { branches, activeBranchId, setActiveBranchId, hasMultiple } = useActiveBranch();

  const startEncounter = useCallback(async (appt) => {
    setStarting(appt.id);
    try {
      const { data } = await apiClient.post(API_ENDPOINTS.OPD.ENCOUNTERS, {
        appointment_id: appt.id,
        patient_id:     appt.patient_id,
        doctor_user_id: user?.user_id,
      });
      const encId = data?.id || data?.data?.id;
      navigate(`/doctor/encounter/${encId}`);
    } catch (err) {
      toastApiError(err, "Could not start encounter.");
      setStarting(null);
    }
  }, [navigate, user, toastApiError]);

  // page_size: 100 — this dashboard only needs today's totals, not a paged
  // view, so request the max page size rather than paginating a stat card.
  const { data: apptData, isLoading } = useApi(API_ENDPOINTS.OPD.APPOINTMENTS, {
    params: { date: TODAY, page_size: 100, ...(hasMultiple && activeBranchId ? { branch_id: activeBranchId } : {}) },
  });
  const { data: statsData } = useApi(API_ENDPOINTS.OPD.STATS, {
    params: { days: 7 },
  });
  const weekStats = statsData?.results || [];

  const appointments = apptData?.results || [];
  // Prefer server-computed whole-day counts (accurate even beyond 100/day);
  // fall back to counting the fetched page if that key isn't present.
  const serverCounts = apptData?.status_counts;
  const waiting     = serverCounts ? serverCounts.waiting     : appointments.filter(a => ["waiting", "scheduled"].includes(a.status)).length;
  const vitalsReady = serverCounts ? serverCounts.vitals_done : appointments.filter(a => a.status === "vitals_done").length;
  const inProgress  = serverCounts ? serverCounts.in_progress : appointments.filter(a => a.status === "in_progress").length;
  const done        = serverCounts ? serverCounts.done        : appointments.filter(a => a.status === "done").length;

  const greeting = () => {
    const h = new Date().getHours();
    if (h < 12) return "Good morning";
    if (h < 17) return "Good afternoon";
    return "Good evening";
  };

  const lastName = user?.full_name?.split(" ").slice(-1)[0] || user?.email?.split("@")[0];
  const dateStr  = new Date().toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long" });

  return (
    <AppShell>
      <PageShell title="">
        {/* ── Serif greeting ─────────────────────────────────────────── */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 22 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
            <div
              onClick={() => navigate("/doctor/my-profile")}
              title="My Profile"
              style={{
                width: 48, height: 48, borderRadius: "50%", overflow: "hidden", cursor: "pointer",
                background: "var(--color-primary-light)", color: "var(--color-primary)",
                display: "flex", alignItems: "center", justifyContent: "center",
                fontSize: 18, fontWeight: 700, flexShrink: 0, border: "2px solid var(--color-border)",
              }}
            >
              {photo ? <img src={photo} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} /> : "Dr"}
            </div>
            <div>
              <div className="page-greeting-title">
                {greeting()}, <em style={{ fontStyle: "italic", color: "var(--color-primary)" }}>Dr. {lastName}</em>
              </div>
              <div className="page-greeting-sub">
                Your OPD summary · {dateStr}
              </div>
            </div>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <BranchSwitcher branches={branches} activeBranchId={activeBranchId} onChange={setActiveBranchId} />
            <button className="btn-primary" onClick={() => navigate("/doctor/queue")}>
              Open Queue →
            </button>
          </div>
        </div>

        {/* ── Dark hero card ─────────────────────────────────────────── */}
        <div className="hero-card" style={{ marginBottom: 22 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
            <div>
              <div className="stat-label" style={{ marginBottom: 8 }}>Patients today</div>
              <div className="hero-number">{isLoading ? "—" : appointments.length}</div>
              <div className="hero-sub" style={{ marginTop: 6 }}>
                {done} seen · {waiting + vitalsReady} in queue
              </div>
            </div>
            <div style={{ textAlign: "right" }}>
              <div className="stat-label" style={{ marginBottom: 10 }}>This week</div>
              <Sparkline points={weekStats.map(d => d.total)} />
            </div>
          </div>
          <hr className="hero-divider" />
          <div style={{ display: "flex", gap: 48 }}>
            {[
              { label: "Waiting",      value: waiting },
              { label: "Vitals ready", value: vitalsReady },
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

        {/* ── Today's patients ───────────────────────────────────────── */}
        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          <div style={{
            display: "flex", justifyContent: "space-between", alignItems: "center",
            padding: "14px 20px", borderBottom: "1px solid var(--color-border)",
          }}>
            <span className="dot-label dot-label--green">The schedule</span>
            <span style={{ fontSize: 12, color: "var(--color-text-muted)" }}>{dateStr}</span>
          </div>

          {isLoading ? (
            <div style={{ padding: 32, textAlign: "center", color: "var(--color-text-muted)" }}>Loading…</div>
          ) : appointments.length === 0 ? (
            <div style={{ padding: 40, textAlign: "center" }}>
              <div style={{ fontFamily: "var(--font-display)", fontSize: 18, fontWeight: 600, marginBottom: 6 }}>
                No appointments today
              </div>
              <div style={{ fontSize: 13, color: "var(--color-text-muted)" }}>
                Appointments booked by front desk will appear here.
              </div>
            </div>
          ) : (
            <table className="data-table">
              <thead>
                <tr>
                  <th style={{ width: 60 }}>#</th>
                  <th>Patient</th>
                  <th>UHID</th>
                  <th>Time</th>
                  <th>Chief Complaint</th>
                  <th>Status</th>
                  <th style={{ width: 100 }}>Action</th>
                </tr>
              </thead>
              <tbody>
                {appointments.map(a => (
                  <tr key={a.id}>
                    <td>
                      <span style={{
                        display: "inline-flex", alignItems: "center", justifyContent: "center",
                        width: 28, height: 28, borderRadius: 8,
                        background: "var(--color-primary-light)", color: "var(--color-primary)",
                        fontWeight: 800, fontSize: 13,
                      }}>
                        {a.token_number}
                      </span>
                    </td>
                    <td>
                      <div style={{ fontWeight: 600, fontSize: 13, color: "var(--color-text)" }}>{a.patient_name || "—"}</div>
                    </td>
                    <td style={{ fontSize: 12, color: "var(--color-text-muted)" }}>{a.patient_uhid || "—"}</td>
                    <td style={{ fontSize: 12, fontWeight: 700 }}>{a.scheduled_time ? a.scheduled_time.slice(0, 5) : "—"}</td>
                    <td style={{ fontSize: 12 }}>{a.chief_complaint || "—"}</td>
                    <td><Badge status={a.status} /></td>
                    <td>
                      {["waiting", "vitals_done"].includes(a.status) && (
                        <button
                          className="btn-primary"
                          style={{ fontSize: 11, padding: "4px 12px" }}
                          disabled={starting === a.id}
                          onClick={() => startEncounter(a)}
                        >
                          {starting === a.id ? "…" : "▶ Start"}
                        </button>
                      )}
                      {a.status === "in_progress" && a.encounter?.id && (
                        <button
                          className="btn-primary"
                          style={{ fontSize: 11, padding: "4px 12px", background: "var(--color-accent)" }}
                          onClick={() => navigate(`/doctor/encounter/${a.encounter.id}`)}
                        >
                          Open notes
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* ── Charts row ─────────────────────────────────────────────── */}
        <div style={{ display: "grid", gridTemplateColumns: "1.4fr 1fr", gap: 16, marginTop: 22 }}>

          {/* Weekly volume bar chart */}
          <div className="card" style={{ padding: "18px 22px" }}>
            <div className="dot-label dot-label--green" style={{ marginBottom: 16 }}>Consults · last 7 days</div>
            <WeekBars data={weekStats} />
          </div>

          {/* Today's status mix */}
          <div className="card" style={{ padding: "18px 22px" }}>
            <div className="dot-label dot-label--gold" style={{ marginBottom: 16 }}>Today's status mix</div>
            {[
              { label: "Waiting",      value: waiting,     color: "var(--color-warning)" },
              { label: "Vitals ready", value: vitalsReady, color: "var(--color-primary)" },
              { label: "In consult",   value: inProgress,  color: "var(--color-info)" },
              { label: "Completed",    value: done,        color: "var(--color-accent)" },
            ].map(({ label, value, color }) => {
              const total = Math.max(appointments.length, 1);
              return (
                <div key={label} style={{ marginBottom: 13 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 5 }}>
                    <span style={{ fontSize: 12, fontWeight: 600, color: "var(--color-text-secondary)" }}>{label}</span>
                    <span style={{ fontSize: 12, fontWeight: 700, color: "var(--color-text)" }}>{value}</span>
                  </div>
                  <div className="thin-bar">
                    <span style={{ width: `${(value / total) * 100}%`, background: color }} />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </PageShell>
    </AppShell>
  );
}

/* Simple bar chart — last 7 days, driven entirely by /opd/stats/ */
function WeekBars({ data = [] }) {
  const values = data.map(d => d.total);
  const labels = data.map(d => d.day);
  if (values.length === 0) {
    return (
      <div style={{ height: 120, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--color-text-muted)", fontSize: 13 }}>
        No activity yet
      </div>
    );
  }
  const max = Math.max(...values, 1);

  return (
    <div style={{ display: "flex", alignItems: "flex-end", gap: 10, height: 120 }}>
      {values.map((v, i) => (
        <div key={i} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", gap: 6, height: "100%", justifyContent: "flex-end" }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: "var(--color-text-secondary)" }}>{v}</div>
          <div style={{
            width: "70%", maxWidth: 34,
            height: `${Math.max((v / max) * 80, 4)}%`,
            borderRadius: "6px 6px 2px 2px",
            background: i === values.length - 1
              ? "linear-gradient(180deg, var(--color-accent), var(--color-warning))"
              : "linear-gradient(180deg, var(--color-primary), var(--color-primary-dark))",
            opacity: i === values.length - 1 ? 1 : 0.55,
            transition: "height 300ms ease",
          }} />
          <div style={{ fontSize: 10, color: "var(--color-text-muted)", fontWeight: 600 }}>{labels[i]}</div>
        </div>
      ))}
    </div>
  );
}
