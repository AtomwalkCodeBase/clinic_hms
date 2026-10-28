/** pages/front-desk/DashboardPage.jsx */
import { useState, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import {
  RefreshCw, Siren, UserRoundPlus, CalendarPlus, BedDouble, Wallet,
  Users, Clock, FileWarning, ArrowRight,
} from "lucide-react";
import { AppShell }    from "../../components/layout/AppShell";
import { PageShell }   from "../../components/common/PageShell";
import DependentBadge  from "../../components/common/DependentBadge";
import { useApi }      from "../../hooks/useApi";
import { useAuth }     from "../../hooks/useAuth";
import API_ENDPOINTS   from "../../config/api.config";
import { ROUTES }      from "../../config/routes.config";
import { todayLocal } from "../../utils/dates";

const TODAY = todayLocal();

function timeAgo(iso) {
  if (!iso) return "";
  const mins = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs} hr ago`;
  return new Date(iso).toLocaleDateString();
}

const QUEUE_TABS = [
  { key: "all",         label: "All" },
  { key: "waiting",     label: "Waiting" },
  { key: "in_progress", label: "With Doctor" },
  { key: "done",        label: "Completed" },
];
const APPT_TABS = [
  { key: "all",        label: "All" },
  { key: "checked_in", label: "Checked In" },
  { key: "pending",    label: "Pending" },
  { key: "cancelled",  label: "Cancelled" },
];
const STATUS_PILL = {
  waiting: "fdc-pill-waiting", scheduled: "fdc-pill-waiting",
  in_progress: "fdc-pill-progress",
  done: "fdc-pill-done",
  cancelled: "fdc-pill-cancelled", no_show: "fdc-pill-cancelled",
};

/** Pure-SVG donut ring — no charting library needed for 3 segments. */
function DonutChart({ segments, size = 132, stroke = 18 }) {
  const total = segments.reduce((s, x) => s + x.value, 0);
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  let offset = 0;
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} style={{ transform: "rotate(-90deg)" }}>
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--color-bg)" strokeWidth={stroke} />
      {total > 0 && segments.map((s, i) => {
        if (!s.value) return null;
        const frac = s.value / total;
        const dash = frac * c;
        const el = (
          <circle key={i} cx={size / 2} cy={size / 2} r={r} fill="none" stroke={s.color} strokeWidth={stroke}
            strokeDasharray={`${dash} ${c - dash}`} strokeDashoffset={-offset} strokeLinecap="butt" />
        );
        offset += dash;
        return el;
      })}
    </svg>
  );
}

function StatTile({ icon, tint, label, value, delta }) {
  return (
    <div className="fdc-stat-card">
      <div className={`fdc-stat-icon fdc-tint-${tint}`}>{icon}</div>
      <div className="fdc-stat-label">{label}</div>
      <div className="fdc-stat-value">{value}</div>
      {delta && <div className="fdc-stat-delta">{delta}</div>}
    </div>
  );
}

export default function FrontDeskDashboardPage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const branchId = user?.branch_id;

  const { data: apptData, isLoading, refetch: refetchAppts } = useApi(API_ENDPOINTS.OPD.APPOINTMENTS, {
    params: { date: TODAY }, pollMs: 15000,
  });
  const appointments = useMemo(() => apptData?.results || apptData || [], [apptData]);

  const { data: invData, refetch: refetchInvoices } = useApi(API_ENDPOINTS.BILLING.INVOICES, { params: { page_size: 100 } });

  function refreshAll() {
    refetchAppts(); refetchInvoices();
  }

  const waiting     = appointments.filter(a => ["waiting", "scheduled"].includes(a.status)).length;
  const activeToday = appointments.filter(a => a.status !== "cancelled" && a.status !== "no_show").length;

  // Real avg time-in-queue — minutes since each waiting patient's slot
  const avgWaitMins = useMemo(() => {
    const now = Date.now();
    const waits = appointments
      .filter(a => ["waiting", "scheduled"].includes(a.status) && a.scheduled_time)
      .map(a => {
        const [h, m] = a.scheduled_time.split(":").map(Number);
        const slot = new Date(); slot.setHours(h, m, 0, 0);
        return (now - slot.getTime()) / 60000;
      })
      .filter(m => m > 0);
    if (!waits.length) return null;
    return Math.round(waits.reduce((s, x) => s + x, 0) / waits.length);
  }, [appointments]);

  const collectionsToday = useMemo(() => {
    const invoices = invData?.results || [];
    let total = 0;
    for (const inv of invoices) {
      for (const p of inv.payments || []) {
        if (p.paid_at && p.paid_at.slice(0, 10) === TODAY) total += Number(p.amount) || 0;
      }
    }
    return total;
  }, [invData]);

  const [queueTab, setQueueTab] = useState("all");
  const [apptTab, setApptTab] = useState("all");

  const queueRows = appointments.filter(a => {
    if (queueTab === "all") return a.status !== "cancelled" && a.status !== "no_show";
    if (queueTab === "waiting") return ["waiting", "scheduled"].includes(a.status);
    return a.status === queueTab;
  });
  const apptRows = appointments.filter(a => {
    if (apptTab === "all") return true;
    if (apptTab === "checked_in") return ["waiting", "in_progress", "done"].includes(a.status);
    if (apptTab === "pending") return a.status === "scheduled";
    if (apptTab === "cancelled") return a.status === "cancelled" || a.status === "no_show";
    return true;
  });

  const greeting = () => {
    const h = new Date().getHours();
    if (h < 12) return "Good morning";
    if (h < 17) return "Good afternoon";
    return "Good evening";
  };
  const firstName = (user?.full_name || user?.email?.split("@")[0] || "there").split(" ")[0];
  const dateStr = new Date().toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long", year: "numeric" });

  return (
    <AppShell>
      <PageShell title="">
        <div className="fdc-header-row">
          <div>
            <div className="fdc-eyebrow">Front Desk</div>
            <div className="fdc-title">{greeting()}, {firstName}! 👋</div>
            <div className="fdc-subtitle">{dateStr} — here's what's happening at the front desk today.</div>
          </div>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            <button className="fdc-quick-action-btn" onClick={refreshAll}>
              <RefreshCw size={15} /> Refresh
            </button>
            <button className="fdc-quick-action-btn" style={{ background: "var(--color-primary)", color: "#fff", border: "none" }}
              onClick={() => navigate(ROUTES.FRONT_DESK.REGISTER_PATIENT)}>
              <UserRoundPlus size={15} /> Register Patient
            </button>
          </div>
        </div>

        <div className="fdc-stat-grid">
          <StatTile icon={<Users size={18} />} tint="green" label="Active OPD Visits" value={isLoading ? "—" : activeToday} />
          <StatTile icon={<Clock size={18} />} tint="amber" label="Waiting in Queue" value={isLoading ? "—" : waiting}
            delta={avgWaitMins != null ? `Avg wait: ${avgWaitMins} mins` : undefined} />
          <StatTile icon={<Wallet size={18} />} tint="gold" label="Collections Today" value={`₹${collectionsToday.toLocaleString("en-IN")}`} />
        </div>

        <div className="fdc-quick-actions-card">
          <div className="fdc-quick-actions-head">Quick Actions</div>
          <div className="fdc-quick-actions-sub">Common tasks to help you get started</div>
          <div className="fdc-quick-actions-row">
            <button className="fdc-quick-action-btn" onClick={() => navigate(ROUTES.FRONT_DESK.APPOINTMENTS)}>
              <CalendarPlus size={15} /> New Appointment
            </button>
            <button className="fdc-quick-action-btn" onClick={() => navigate(ROUTES.FRONT_DESK.REGISTER_PATIENT)}>
              <UserRoundPlus size={15} /> Walk-in Registration
            </button>
            <button className="fdc-quick-action-btn" onClick={() => navigate(ROUTES.FRONT_DESK.BILLING)}>
              <Wallet size={15} /> Collect Payment
            </button>
          </div>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, alignItems: "start" }}>
          {/* Live OPD Queue */}
          <div className="fdc-panel">
            <div className="fdc-panel-head">
              <div>
                <div className="fdc-panel-title">Live OPD Queue</div>
                <div className="fdc-panel-sub">Real-time patient queue for today</div>
              </div>
              <button className="fdc-panel-link" onClick={() => navigate(ROUTES.FRONT_DESK.QUEUE)}>
                View All <ArrowRight size={13} />
              </button>
            </div>
            <div style={{ padding: "10px 18px 0" }}>
              <div className="fdc-subtabs">
                {QUEUE_TABS.map(t => (
                  <button key={t.key} className={"fdc-subtab" + (queueTab === t.key ? " active" : "")} onClick={() => setQueueTab(t.key)}>
                    {t.label} ({t.key === "all"
                      ? appointments.filter(a => a.status !== "cancelled" && a.status !== "no_show").length
                      : t.key === "waiting" ? waiting
                      : appointments.filter(a => a.status === t.key).length})
                  </button>
                ))}
              </div>
            </div>
            <div style={{ overflowX: "auto" }}>
              <table className="fdc-table">
                <thead><tr><th>#</th><th>Patient</th><th>Department</th><th>Status</th></tr></thead>
                <tbody>
                  {queueRows.slice(0, 8).map(a => (
                    <tr key={a.appointment_id}>
                      <td style={{ fontWeight: 800, color: "var(--color-primary)" }}>{a.token_number}</td>
                      <td>
                        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                          {a.patient_name || "—"} <DependentBadge patient={a} />
                        </div>
                      </td>
                      <td>{a.department_name || a.doctor_name || "—"}</td>
                      <td><span className={`fdc-pill ${STATUS_PILL[a.status] || "fdc-pill-neutral"}`}>{(a.status || "").replace("_", " ")}</span></td>
                    </tr>
                  ))}
                  {!isLoading && queueRows.length === 0 && (
                    <tr><td colSpan={4} style={{ textAlign: "center", padding: 28, color: "var(--color-text-muted)" }}>Nothing here right now.</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {/* Today's Appointments */}
          <div className="fdc-panel">
            <div className="fdc-panel-head">
              <div>
                <div className="fdc-panel-title">Today's Appointments</div>
                <div className="fdc-panel-sub">Scheduled visits for today</div>
              </div>
              <button className="fdc-panel-link" onClick={() => navigate(ROUTES.FRONT_DESK.APPOINTMENTS)}>
                View All <ArrowRight size={13} />
              </button>
            </div>
            <div style={{ padding: "10px 18px 0" }}>
              <div className="fdc-subtabs">
                {APPT_TABS.map(t => (
                  <button key={t.key} className={"fdc-subtab" + (apptTab === t.key ? " active" : "")} onClick={() => setApptTab(t.key)}>
                    {t.label}
                  </button>
                ))}
              </div>
            </div>
            <div style={{ overflowX: "auto" }}>
              <table className="fdc-table">
                <thead><tr><th>Time</th><th>Patient</th><th>Department</th><th>Status</th></tr></thead>
                <tbody>
                  {apptRows.slice(0, 8).map(a => (
                    <tr key={a.appointment_id}>
                      <td style={{ fontWeight: 700 }}>{a.scheduled_time ? a.scheduled_time.slice(0, 5) : "—"}</td>
                      <td>{a.patient_name || "—"}</td>
                      <td>{a.department_name || a.doctor_name || "—"}</td>
                      <td><span className={`fdc-pill ${STATUS_PILL[a.status] || "fdc-pill-neutral"}`}>{(a.status || "").replace("_", " ")}</span></td>
                    </tr>
                  ))}
                  {!isLoading && apptRows.length === 0 && (
                    <tr><td colSpan={4} style={{ textAlign: "center", padding: 28, color: "var(--color-text-muted)" }}>Nothing here right now.</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

        </div>
      </PageShell>
    </AppShell>
  );
}
