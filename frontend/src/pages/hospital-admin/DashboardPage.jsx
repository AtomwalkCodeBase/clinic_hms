/**
 * pages/hospital-admin/DashboardPage.jsx
 * ----------------------------------------
 * Hospital admin home — premium theme.
 * Serif greeting + dark revenue-style hero + schedule / action center + KPI grid.
 */

import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { AppShell }    from "../../components/layout/AppShell";
import { PageShell }   from "../../components/common/PageShell";
import { useAuth }     from "../../hooks/useAuth";
import { useApi }      from "../../hooks/useApi";
import { useToast }    from "../../hooks/useToast";
import { usePermissions } from "../../hooks/usePermissions";
import apiClient       from "../../services/api.client";
import API_ENDPOINTS   from "../../config/api.config";
import { ROUTES }      from "../../config/routes.config";
import { Users, Building2, Settings } from "lucide-react";

const TODAY = new Date().toISOString().slice(0, 10);

/* Tiny inline sparkline */
function Sparkline({ points, width = 180, height = 46 }) {
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

function KpiCard({ label, value, sub, loading, dotClass = "dot-label--green" }) {
  return (
    <div className="card" style={{ padding: "18px 22px" }}>
      <div className={`dot-label ${dotClass}`} style={{ marginBottom: 10 }}>{label}</div>
      <div style={{ fontFamily: "var(--font-display)", fontSize: 30, fontWeight: 600, lineHeight: 1, color: "var(--color-text)" }}>
        {loading ? "—" : value}
      </div>
      {sub && <div style={{ fontSize: 12, color: "var(--color-text-muted)", marginTop: 6 }}>{sub}</div>}
    </div>
  );
}

function ActionRow({ icon: Icon, label, count, onClick }) {
  return (
    <button onClick={onClick} style={{
      display: "flex", alignItems: "center", gap: 12, width: "100%",
      padding: "11px 14px", border: "none", background: "transparent",
      borderBottom: "1px solid var(--color-border)", cursor: "pointer",
      fontSize: 13, color: "var(--color-text-secondary)", textAlign: "left",
    }}>
      <span style={{ display: "flex", width: 22, justifyContent: "center" }}><Icon size={15} /></span>
      <span style={{ flex: 1, fontWeight: 500 }}>{label}</span>
      {count !== undefined && (
        <span style={{
          fontSize: 11, fontWeight: 700, color: "var(--color-text)",
          background: "var(--color-table-header)", borderRadius: 10, padding: "1px 9px",
        }}>{count}</span>
      )}
      <span style={{ color: "var(--color-text-muted)" }}>→</span>
    </button>
  );
}

function SetupStep({ number, title, description, done, onClick, disabled }) {
  return (
    <div
      onClick={!done && !disabled ? onClick : undefined}
      style={{
        display: "flex", alignItems: "flex-start", gap: 16,
        padding: "20px 24px", borderRadius: "var(--radius-card)",
        border: `1.5px solid ${done ? "var(--color-primary)" : "var(--color-border)"}`,
        background: done ? "var(--color-primary-light)" : disabled ? "var(--color-bg)" : "var(--color-surface)",
        cursor: !done && !disabled ? "pointer" : "default",
        opacity: disabled ? 0.5 : 1,
      }}
    >
      <div style={{
        width: 36, height: 36, borderRadius: "50%", flexShrink: 0,
        display: "flex", alignItems: "center", justifyContent: "center",
        background: done ? "var(--color-primary)" : "var(--color-hero)",
        color: "#fff", fontWeight: 700, fontSize: 15,
      }}>
        {done ? "✓" : number}
      </div>
      <div style={{ flex: 1 }}>
        <div style={{ fontFamily: "var(--font-display)", fontWeight: 600, fontSize: 16, color: "var(--color-text)" }}>
          {title}
        </div>
        <div style={{ fontSize: 13, color: "var(--color-text-muted)", marginTop: 4 }}>
          {description}
        </div>
        {!done && !disabled && (
          <div style={{ marginTop: 10 }}>
            <span className="btn-primary" style={{ fontSize: 12, padding: "5px 14px" }}>
              Set up now →
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

export default function DashboardPage() {
  const navigate     = useNavigate();
  const { user }     = useAuth();
  const { toastApiError } = useToast();

  const { data: meData } = useApi(API_ENDPOINTS.ORG.MY_PROFILE);
  const photo = meData?.photo;

  // Live branch/doctor/staff counts + tier limits — same source of truth as
  // the capacity banners on StaffPage/BranchesPage/RolesPage (backend
  // computes these from a live DB count each time, see
  // apps.tenants.limits.get_usage_counts). Previously this page re-fetched
  // /org/branches/ + /org/staff/ itself and hand-rolled the counts, but
  // /org/staff/ returns a *paginated* {results, pagination} object (not a
  // flat array) — the old code did staff.filter(...) directly on that
  // object, which throws, gets swallowed by an empty catch, and silently
  // leaves every count at 0 forever. Reusing usePermissions() sidesteps
  // that entirely and keeps this page in sync with every other admin page.
  const { permissions, isLoading: permsLoading, refresh: refreshPermissions } = usePermissions();
  const orgStats = {
    branches: permissions?.usage?.branches ?? 0,
    doctors:  permissions?.usage?.doctors  ?? 0,
    staff:    permissions?.usage?.staff    ?? 0,
  };
  const orgStatsFailed = !permsLoading && !permissions?.usage;

  const [weekStats, setWeekStats] = useState([]);
  const [opdStats, setOpdStats] = useState({
    total: 0, waiting: 0, vitals_done: 0, in_progress: 0, done: 0,
  });
  const [loading, setLoading] = useState(true);

  const fetchStats = useCallback(async () => {
    setLoading(true);
    try {
      const [opdRes, statsRes] = await Promise.allSettled([
        apiClient.get(`${API_ENDPOINTS.OPD.APPOINTMENTS}?date=${TODAY}`),
        apiClient.get(`${API_ENDPOINTS.OPD.STATS}?days=14`),
      ]);

      if (statsRes.status === "fulfilled") {
        setWeekStats(statsRes.value.data?.results || []);
      }

      if (opdRes.status === "fulfilled") {
        const body  = opdRes.value.data;
        const appts = body?.results || body?.data?.results || [];
        setOpdStats({
          total:       appts.length,
          waiting:     appts.filter(a => a.status === "waiting" || a.status === "scheduled").length,
          vitals_done: appts.filter(a => a.status === "vitals_done").length,
          in_progress: appts.filter(a => a.status === "in_progress").length,
          done:        appts.filter(a => a.status === "done").length,
        });
      }
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, [toastApiError]);

  useEffect(() => { fetchStats(); }, [fetchStats]);

  const setupDone = orgStats.branches > 0 && (orgStats.staff > 0 || orgStats.doctors > 0);
  const tier = user?.license_tier || "starter";

  const greeting = () => {
    const h = new Date().getHours();
    if (h < 12) return "Good morning";
    if (h < 17) return "Good afternoon";
    return "Good evening";
  };
  const firstName = (user?.full_name || user?.email?.split("@")[0] || "Admin").split(" ")[0];
  const dateStr = new Date().toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long" });

  return (
    <AppShell>
      <PageShell title="">

        {/* ── Serif greeting row ─────────────────────────────────────── */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 22 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
            <div
              onClick={() => navigate(ROUTES.ADMIN.MY_PROFILE)}
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
                {dateStr} · <span style={{ textTransform: "capitalize", fontWeight: 600, color: "var(--color-accent)" }}>{tier} plan</span>
              </div>
            </div>
          </div>
          <div style={{ display: "flex", gap: 10 }}>
            <button className="btn-outline" style={{ fontSize: 12 }} onClick={() => navigate(ROUTES.ADMIN.STAFF)}>+ Staff</button>
            <button className="btn-primary" style={{ fontSize: 12 }} onClick={() => navigate(ROUTES.ADMIN.BRANCHES)}>+ Branch</button>
          </div>
        </div>

        {/* ── Dark hero card ─────────────────────────────────────────── */}
        <div className="hero-card" style={{ marginBottom: 22 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
            <div>
              <div className="stat-label" style={{ marginBottom: 8 }}>Patients today</div>
              <div className="hero-number">{loading ? "—" : opdStats.total}</div>
              <div className="hero-sub" style={{ marginTop: 6 }}>
                {opdStats.done} completed · {opdStats.waiting + opdStats.vitals_done} in queue
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
              { label: "Waiting",      value: opdStats.waiting },
              { label: "Vitals done",  value: opdStats.vitals_done },
              { label: "With doctor",  value: opdStats.in_progress },
              { label: "Completed",    value: opdStats.done },
            ].map(({ label, value }) => (
              <div key={label}>
                <div className="stat-label" style={{ marginBottom: 4 }}>{label}</div>
                <div style={{ fontFamily: "var(--font-display)", fontSize: 22, fontWeight: 600 }}>
                  {loading ? "—" : value}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* ── Setup checklist (until complete) ───────────────────────── */}
        {!permsLoading && orgStatsFailed ? (
          <div style={{
            marginBottom: 22, padding: "16px 20px", borderRadius: "var(--radius-card)",
            border: "1.5px solid var(--color-error)", background: "var(--color-error-light, #fdeeee)",
            display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12,
          }}>
            <div style={{ fontSize: 13, color: "var(--color-text-secondary)" }}>
              Couldn't load your branches/staff counts — they may not actually be zero, the request just failed.
            </div>
            <button className="btn-outline" style={{ fontSize: 12, flexShrink: 0 }} onClick={refreshPermissions}>
              Retry
            </button>
          </div>
        ) : !setupDone && (
          <div style={{ marginBottom: 22, display: "flex", flexDirection: "column", gap: 12 }}>
            <SetupStep
              number={1} done={orgStats.branches > 0}
              title="Add your first branch"
              description="Set up the physical location(s) of your hospital."
              onClick={() => navigate(ROUTES.ADMIN.BRANCHES)}
            />
            <SetupStep
              number={2} done={orgStats.staff > 0 || orgStats.doctors > 0}
              disabled={orgStats.branches === 0}
              title="Invite staff members"
              description="Add doctors, nurses, front desk, lab techs, and pharmacists."
              onClick={() => navigate(ROUTES.ADMIN.STAFF)}
            />
          </div>
        )}

        {/* ── Two-column: hospital overview + action center ──────────── */}
        <div style={{ display: "grid", gridTemplateColumns: "1.6fr 1fr", gap: 16, marginBottom: 22 }}>
          {/* Overview KPIs */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 14, alignContent: "start" }}>
            <KpiCard label="Branches" value={orgStats.branches} loading={permsLoading}
              sub={permissions?.max_branches > 0 ? `of ${permissions.max_branches} on the ${permissions.license_tier} plan` : undefined}
              dotClass="dot-label--green" />
            <KpiCard label="Doctors"  value={orgStats.doctors}  loading={permsLoading}
              sub={permissions?.max_doctors > 0 ? `of ${permissions.max_doctors} on the ${permissions.license_tier} plan` : undefined}
              dotClass="dot-label--blue" />
            <KpiCard label="Staff"    value={orgStats.staff}    loading={permsLoading}
              sub={permissions?.max_staff > 0 ? `of ${permissions.max_staff} non-doctors` : "Non-doctors"}
              dotClass="dot-label--gold" />
          </div>

          {/* Action center */}
          <div className="card" style={{ padding: 0, overflow: "hidden" }}>
            <div style={{ padding: "14px 16px", borderBottom: "1px solid var(--color-border)" }}>
              <span className="dot-label dot-label--red">The action center</span>
            </div>
            <ActionRow icon={Users} label="Manage staff"     count={orgStats.doctors + orgStats.staff} onClick={() => navigate(ROUTES.ADMIN.STAFF)} />
            <ActionRow icon={Building2} label="Manage branches"  count={orgStats.branches}                  onClick={() => navigate(ROUTES.ADMIN.BRANCHES)} />
            <ActionRow icon={Settings} label="Hospital settings"                                          onClick={() => navigate(ROUTES.ADMIN.SETTINGS)} />
          </div>
        </div>

      </PageShell>
    </AppShell>
  );
}
