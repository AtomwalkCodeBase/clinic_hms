/**
 * pages/platform-admin/shared.jsx
 * --------------------------------
 * Shared constants + small components used across the platform-admin
 * Dashboard, Hospitals, and Subscriptions pages — kept in one place so the
 * three pages stay visually consistent instead of drifting.
 */
import { useState, useEffect } from "react";
import apiClient from "../../services/api.client";
import API_ENDPOINTS from "../../config/api.config";
import { useToast } from "../../hooks/useToast";

export const TIERS = ["starter", "growth", "pro", "enterprise"];

export const TIER_LABEL = {
  starter:    { label: "Starter",    color: "#64748b" },
  growth:     { label: "Growth",     color: "#0ea5e9" },
  pro:        { label: "Pro",        color: "#7c3aed" },
  enterprise: { label: "Enterprise", color: "#b45309" },
};

export const TIER_LIMITS = {
  starter:    "3 doctors, 1 branch",
  growth:     "10 doctors, 1 branch, lab + pharmacy",
  pro:        "50 doctors, 5 branches, AI voice, patient app",
  enterprise: "Unlimited, all features",
};

// Subscription lifecycle status — separate from the is_active kill switch.
// This is the billing state (trial/active/grace/read_only/frozen/suspended)
// that core/authentication.py actually enforces: frozen/suspended blocks
// all API access for that hospital's staff, read_only blocks writes.
export const SUB_STATUS_META = {
  trial:     { label: "Trial",        bg: "#e0f2fe", fg: "#075985" },
  active:    { label: "Active",       bg: "#dcfce7", fg: "#166534" },
  grace:     { label: "Grace Period", bg: "#fef3c7", fg: "#92400e" },
  read_only: { label: "Read Only",    bg: "#ffedd5", fg: "#9a3412" },
  frozen:    { label: "Frozen",       bg: "#fee2e2", fg: "#991b1b" },
  suspended: { label: "Suspended",    bg: "#f3e8ff", fg: "#6b21a8" },
};

// Statuses that mean "someone should look at this hospital" — used to
// surface an attention list on the Subscriptions page.
export const ATTENTION_STATUSES = ["grace", "read_only", "frozen", "suspended"];

export function StatusBadge({ isActive }) {
  return (
    <span className={`badge badge--${isActive ? "success" : "error"}`}>
      {isActive ? "Active" : "Suspended"}
    </span>
  );
}

export function SubStatusBadge({ status }) {
  if (!status) return null;
  const m = SUB_STATUS_META[status] || { label: status, bg: "#e5e7eb", fg: "#374151" };
  return (
    <span style={{
      display: "inline-block", padding: "2px 10px", borderRadius: 20,
      fontSize: 11, fontWeight: 600, background: m.bg, color: m.fg,
    }}>{m.label}</span>
  );
}

export function TierBadge({ tier }) {
  const t = TIER_LABEL[tier] || { label: tier, color: "#64748b" };
  return (
    <span style={{
      display: "inline-block", padding: "2px 10px", borderRadius: 20,
      fontSize: 11, fontWeight: 600,
      background: t.color + "22", color: t.color,
    }}>{t.label}</span>
  );
}

// Thin usage-vs-limit bar — e.g. "7 / 10 doctors". max=0 means unlimited.
// used=null means the tenant DB couldn't be reached (usage unknown).
export function UsageBar({ label, used, max }) {
  if (used === null || used === undefined) {
    return (
      <div>
        <div style={{ fontSize: 11, color: "var(--color-text-muted)", marginBottom: 3 }}>{label}</div>
        <div style={{ fontSize: 12, color: "var(--color-text-muted)" }}>Unavailable</div>
      </div>
    );
  }
  const unlimited = !max;
  const pct = unlimited ? 0 : Math.min(100, Math.round((used / max) * 100));
  const over = !unlimited && used > max;
  const near = !unlimited && !over && pct >= 80;
  const barColor = over ? "var(--color-error)" : near ? "var(--color-accent)" : "var(--color-primary)";
  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: "var(--color-text-muted)", marginBottom: 3 }}>
        <span>{label}</span>
        <span style={{ fontWeight: 600, color: over ? "var(--color-error)" : "var(--color-text)" }}>
          {used}{unlimited ? "" : ` / ${max}`}
        </span>
      </div>
      {!unlimited && (
        <div style={{ height: 5, borderRadius: 3, background: "var(--color-border)", overflow: "hidden" }}>
          <div style={{ height: "100%", width: `${pct}%`, background: barColor, borderRadius: 3 }} />
        </div>
      )}
    </div>
  );
}

export async function fetchAuditLog(tenantId) {
  const { data: res } = await apiClient.get(API_ENDPOINTS.PLATFORM.TENANT_AUDIT_LOG(tenantId));
  return res.data || [];
}

// Slide-over drawer for viewing/editing one tenant's tier, subscription
// status, and audit trail — shared by HospitalsPage and SubscriptionsPage
// so both can offer the same controls DashboardPage's inline card has,
// without duplicating the patch/audit-log wiring in three places.
export function TenantDetailDrawer({ tenant, onClose, onChanged }) {
  const [tierPick, setTierPick] = useState(tenant.subscription?.license_tier || "starter");
  const [statusPick, setStatusPick] = useState(tenant.subscription?.status || "trial");
  const [savingTier, setSavingTier] = useState(false);
  const [savingStatus, setSavingStatus] = useState(false);
  const [auditLog, setAuditLog] = useState(null);
  const { toastSuccess, toastApiError } = useToast();

  useEffect(() => {
    fetchAuditLog(tenant.id).then(setAuditLog).catch(() => setAuditLog([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tenant.id]);

  async function applyTier() {
    if (tierPick === tenant.subscription?.license_tier) return;
    setSavingTier(true);
    try {
      await apiClient.patch(API_ENDPOINTS.PLATFORM.TENANT(tenant.id), { tier: tierPick });
      toastSuccess(`Tier changed to ${TIER_LABEL[tierPick]?.label || tierPick}.`);
      fetchAuditLog(tenant.id).then(setAuditLog);
      onChanged();
    } catch (err) {
      toastApiError(err, "Failed to change tier.");
    } finally {
      setSavingTier(false);
    }
  }

  async function applyStatus() {
    if (statusPick === tenant.subscription?.status) return;
    setSavingStatus(true);
    try {
      await apiClient.patch(API_ENDPOINTS.PLATFORM.TENANT(tenant.id), { status: statusPick });
      toastSuccess(`Status changed to ${SUB_STATUS_META[statusPick]?.label || statusPick}.`);
      fetchAuditLog(tenant.id).then(setAuditLog);
      onChanged();
    } catch (err) {
      toastApiError(err, "Failed to change status.");
    } finally {
      setSavingStatus(false);
    }
  }

  const selectStyle = {
    padding: "7px 10px", borderRadius: 8, fontSize: 13,
    border: "1.5px solid var(--color-border)", background: "var(--color-surface)",
    color: "var(--color-text)", outline: "none",
  };
  const usage = tenant.usage || {};

  return (
    <div style={{ position: "fixed", inset: 0, zIndex: 1000, display: "flex", justifyContent: "flex-end" }}>
      <div onClick={onClose} style={{ position: "absolute", inset: 0, background: "rgba(0,0,0,0.4)" }} />
      <div style={{
        position: "relative", width: "min(420px, 100%)", height: "100%",
        background: "var(--color-surface)", boxShadow: "-8px 0 30px rgba(0,0,0,0.15)",
        padding: 28, overflowY: "auto",
      }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 6 }}>
          <div>
            <div style={{ fontFamily: "var(--font-display)", fontSize: 19, fontWeight: 600 }}>{tenant.name}</div>
            <div style={{ fontSize: 13, color: "var(--color-text-muted)" }}>{tenant.city}{tenant.state ? `, ${tenant.state}` : ""}</div>
          </div>
          <button onClick={onClose} style={{ background: "none", border: "none", fontSize: 20, cursor: "pointer", color: "var(--color-text-muted)" }}>✕</button>
        </div>

        <div style={{ display: "flex", gap: 8, margin: "12px 0 20px" }}>
          <StatusBadge isActive={tenant.is_active} />
          <TierBadge tier={tenant.subscription?.license_tier} />
          <SubStatusBadge status={tenant.subscription?.status} />
        </div>

        <div style={{ display: "flex", gap: 24, marginBottom: 20 }}>
          <UsageBar label="Doctors" used={usage.doctors} max={tenant.subscription?.max_doctors} />
          <UsageBar label="Branches" used={usage.branches} max={tenant.subscription?.max_branches} />
        </div>

        <div style={{ display: "grid", gap: 18, marginBottom: 20 }}>
          <div>
            <div className="stat-label" style={{ marginBottom: 6 }}>Change tier</div>
            <div style={{ display: "flex", gap: 6 }}>
              <select value={tierPick} onChange={e => setTierPick(e.target.value)} style={selectStyle}>
                {TIERS.map(t => <option key={t} value={t}>{TIER_LABEL[t].label}</option>)}
              </select>
              <button onClick={applyTier} disabled={savingTier || tierPick === tenant.subscription?.license_tier}
                className="btn-outline" style={{ fontSize: 12, padding: "6px 14px" }}>
                {savingTier ? "…" : "Apply"}
              </button>
            </div>
          </div>
          <div>
            <div className="stat-label" style={{ marginBottom: 6 }}>Subscription status</div>
            <div style={{ display: "flex", gap: 6 }}>
              <select value={statusPick} onChange={e => setStatusPick(e.target.value)} style={selectStyle}>
                {Object.keys(SUB_STATUS_META).map(s => <option key={s} value={s}>{SUB_STATUS_META[s].label}</option>)}
              </select>
              <button onClick={applyStatus} disabled={savingStatus || statusPick === tenant.subscription?.status}
                className="btn-outline" style={{ fontSize: 12, padding: "6px 14px" }}>
                {savingStatus ? "…" : "Apply"}
              </button>
            </div>
          </div>
        </div>

        <div>
          <div className="dot-label" style={{ marginBottom: 8 }}>Recent changes</div>
          {auditLog === null ? (
            <div style={{ fontSize: 12.5, color: "var(--color-text-muted)" }}>Loading…</div>
          ) : (
            <AuditLogTrail entries={auditLog} />
          )}
        </div>
      </div>
    </div>
  );
}

export function AuditLogTrail({ entries }) {
  if (!entries || entries.length === 0) {
    return <div style={{ fontSize: 12.5, color: "var(--color-text-muted)" }}>No changes recorded yet.</div>;
  }
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8, maxHeight: 220, overflowY: "auto" }}>
      {entries.map(e => (
        <div key={e.id} style={{ fontSize: 12.5, display: "flex", gap: 8, alignItems: "baseline" }}>
          <span style={{ color: "var(--color-text-muted)", whiteSpace: "nowrap" }}>
            {new Date(e.created_at).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}
          </span>
          <span>
            <strong>{e.action_label}</strong>
            {e.before_value && e.after_value ? `: ${e.before_value} → ${e.after_value}` : ""}
            {e.actor_email && <span style={{ color: "var(--color-text-muted)" }}> · {e.actor_email}</span>}
          </span>
        </div>
      ))}
    </div>
  );
}
