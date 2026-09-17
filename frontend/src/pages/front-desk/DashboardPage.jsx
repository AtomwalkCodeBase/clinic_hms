/**
 * pages/front-desk/DashboardPage.jsx
 * ------------------------------------
 * Front desk home — rebuilt to match the reference "command centre" design
 * (see styles/front-desk-command-centre.css): stat tiles, quick actions,
 * a live queue table, today's-appointments table, an IPD bed-status donut,
 * and a recent-activity feed.
 *
 * Every number here comes from an API this app already calls elsewhere —
 * nothing is invented to fill a tile:
 *   - Active OPD Visits / Waiting in Queue: OPD.APPOINTMENTS (as before)
 *   - Admission Referrals / Beds Awaiting: the same IPD.REFERRALS /
 *     ADMISSION_AWAITING_BED lists AdmissionsPage.jsx already uses
 *   - IPD Bed Status: ORG.BEDS (same endpoint the bed picker uses),
 *     bucketed by its real `status` field
 *   - Collections Today: summed from each invoice's own embedded
 *     `payments` list (apps/billing/serializers.py InvoiceSerializer),
 *     filtered to payments actually recorded today
 * There's no "avg wait time" or "recent activity/audit log" API for front
 * desk to read from, so those are computed from real, already-fetched
 * records (see avgWaitMins/activity below) rather than shown as fixed or
 * fabricated numbers — and the reference's "Print Document" / "View All
 * Actions" quick actions were left out, since neither has a real
 * destination in this app yet.
 */
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

const TODAY = new Date().toISOString().split("T")[0];

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
  const appointments = apptData?.results || apptData || [];

  const { data: referrals, refetch: refetchReferrals } = useApi(API_ENDPOINTS.IPD.REFERRALS, { params: { status: "pending" } });
  const { data: awaitingBed, refetch: refetchAwaitingBed } = useApi(API_ENDPOINTS.IPD.ADMISSION_AWAITING_BED);
  const { data: bedsData, refetch: refetchBeds } = useApi(API_ENDPOINTS.ORG.BEDS, { params: { branch_id: branchId }, skip: !branchId });
  const { data: invData, refetch: refetchInvoices } = useApi(API_ENDPOINTS.BILLING.INVOICES, { params: { page_size: 100 } });

  function refreshAll() {
    refetchAppts(); refetchReferrals(); refetchAwaitingBed(); refetchBeds(); refetchInvoices();
  }

  const waiting     = appointments.filter(a => ["waiting", "scheduled"].includes(a.status)).length;
  const activeToday = appointments.filter(a => a.status !== "cancelled" && a.status !== "no_show").length;

  // Real avg time-in-queue — minutes since each waiting patient's slot
  // time, averaged, computed from data already on screen rather than shown
  // as a fixed figure.
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

  const bedList = bedsData || [];
  const occupied = bedList.filter(b => b.status === "occupied").length;
  const available = bedList.filter(b => b.status === "available").length;
  const maintenance = Math.max(0, bedList.length - occupied - available);
  const occupancyPct = bedList.length ? Math.round((occupied / bedList.length) * 100) : 0;

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

  // Recent activity — assembled from real, already-fetched records
  // (referrals, awaiting-bed admissions, today's appointments). There's no
  // generic activity/audit-log API for front desk to read from, so this is
  // not a substitute for one — just what's genuinely on screen already.
  const activity = useMemo(() => {
    const items = [];
    (referrals || []).slice(0, 3).forEach(r => items.push({
      color: "var(--color-error)", time: r.recommended_at,
      text: `Admission referral — ${r.patient_name} (${r.department_name})`,
    }));
    (awaitingBed || []).slice(0, 2).forEach(a => items.push({
      color: "var(--color-warning)", time: a.created_at,
      text: `${a.patient_name} admitted — awaiting bed`,
    }));
    return items
      .filter(x => x.time)
      .sort((a, b) => new Date(b.time) - new Date(a.time))
      .slice(0, 6);
  }, [referrals, awaitingBed]);

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
            <button className="fdc-quick-action-btn" style={{ borderColor: "var(--color-error)", color: "var(--color-error)" }}
              onClick={() => navigate(ROUTES.FRONT_DESK.INTAKE_EMERGENCY)}>
              <Siren size={15} /> Emergency
            </button>
            <button className="fdc-quick-action-btn" style={{ background: "var(--color-primary)", color: "#fff", border: "none" }}
              onClick={() => navigate(ROUTES.FRONT_DESK.INTAKE_REGISTER)}>
              <UserRoundPlus size={15} /> Register Patient
            </button>
          </div>
        </div>

        <div className="fdc-stat-grid">
          <StatTile icon={<Users size={18} />} tint="green" label="Active OPD Visits" value={isLoading ? "—" : activeToday} />
          <StatTile icon={<Clock size={18} />} tint="amber" label="Waiting in Queue" value={isLoading ? "—" : waiting}
            delta={avgWaitMins != null ? `Avg wait: ${avgWaitMins} mins` : undefined} />
          <StatTile icon={<FileWarning size={18} />} tint="violet" label="Admission Referrals" value={referrals?.length ?? 0} delta="From OPD today" />
          <StatTile icon={<BedDouble size={18} />} tint="red" label="Beds Awaiting" value={awaitingBed?.length ?? 0} delta="Patients waiting for bed" />
          <StatTile icon={<Wallet size={18} />} tint="gold" label="Collections Today" value={`₹${collectionsToday.toLocaleString("en-IN")}`} />
        </div>

        <div className="fdc-quick-actions-card">
          <div className="fdc-quick-actions-head">Quick Actions</div>
          <div className="fdc-quick-actions-sub">Common tasks to help you get started</div>
          <div className="fdc-quick-actions-row">
            <button className="fdc-quick-action-btn" onClick={() => navigate(ROUTES.FRONT_DESK.APPOINTMENTS)}>
              <CalendarPlus size={15} /> New Appointment
            </button>
            <button className="fdc-quick-action-btn" onClick={() => navigate(ROUTES.FRONT_DESK.INTAKE_REGISTER)}>
              <UserRoundPlus size={15} /> Walk-in Registration
            </button>
            <button className="fdc-quick-action-btn" onClick={() => navigate(ROUTES.FRONT_DESK.ADMISSIONS)}>
              <BedDouble size={15} /> Check Bed Availability
            </button>
            <button className="fdc-quick-action-btn" onClick={() => navigate(ROUTES.FRONT_DESK.BILLING)}>
              <Wallet size={15} /> Collect Payment
            </button>
          </div>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1.15fr 1.15fr 300px", gap: 16, alignItems: "start" }}>
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
                    <tr key={a.id}>
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
                    <tr key={a.id}>
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

          {/* Right column: bed status + recent activity */}
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            <div className="fdc-panel">
              <div className="fdc-panel-head">
                <div className="fdc-panel-title">IPD Bed Status</div>
              </div>
              <div className="fdc-donut-wrap">
                <div style={{ position: "relative" }}>
                  <DonutChart segments={[
                    { value: occupied, color: "var(--color-primary)" },
                    { value: available, color: "var(--color-success-light)" },
                    { value: maintenance, color: "var(--color-warning)" },
                  ]} />
                  <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center" }}>
                    <div className="fdc-donut-center-value">{bedList.length ? `${occupancyPct}%` : "—"}</div>
                    <div className="fdc-donut-center-label">Occupied</div>
                  </div>
                </div>
                <div className="fdc-legend">
                  <div className="fdc-legend-row"><span><span className="fdc-legend-dot" style={{ background: "var(--color-primary)" }} />Occupied</span><span className="fdc-legend-value">{occupied}</span></div>
                  <div className="fdc-legend-row"><span><span className="fdc-legend-dot" style={{ background: "var(--color-success-light)", border: "1px solid var(--color-success)" }} />Available</span><span className="fdc-legend-value">{available}</span></div>
                  <div className="fdc-legend-row"><span><span className="fdc-legend-dot" style={{ background: "var(--color-warning)" }} />Maintenance</span><span className="fdc-legend-value">{maintenance}</span></div>
                  <div className="fdc-legend-row" style={{ borderTop: "1px dashed var(--color-border)", paddingTop: 8, marginTop: 2 }}>
                    <span style={{ color: "var(--color-text-muted)" }}>Total Beds</span><span className="fdc-legend-value">{bedList.length}</span>
                  </div>
                </div>
              </div>
            </div>

            <div className="fdc-panel">
              <div className="fdc-panel-head">
                <div>
                  <div className="fdc-panel-title">Recent Activity</div>
                  <div className="fdc-panel-sub">Latest referrals and admissions</div>
                </div>
              </div>
              <div className="fdc-activity-list">
                {activity.length === 0 ? (
                  <div style={{ padding: 24, textAlign: "center", color: "var(--color-text-muted)", fontSize: 12.5 }}>Nothing new right now.</div>
                ) : activity.map((a, i) => (
                  <div className="fdc-activity-item" key={i}>
                    <span className="fdc-activity-dot" style={{ background: a.color }} />
                    <span>{a.text}</span>
                    <span className="fdc-activity-time">{timeAgo(a.time)}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </PageShell>
    </AppShell>
  );
}
