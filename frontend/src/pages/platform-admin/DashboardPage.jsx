/**
 * pages/platform-admin/DashboardPage.jsx
 * ----------------------------------------
 * Platform admin home — hero overview of the whole platform, provision new
 * hospitals, and manage each tenant's tier/subscription/audit trail inline.
 *
 * Styled with the same premium hero-card / icon-chip language used across
 * the patient and staff portals (see MyProfilePage.jsx) rather than flat
 * boxes with hardcoded hex colors — this is the first screen a platform
 * admin sees, it should read as a control room, not a plain admin panel.
 */
import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { Building2, ShieldCheck, Search, Plus, History, ChevronDown, ExternalLink } from "lucide-react";
import { AppShell }  from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import apiClient     from "../../services/api.client";
import { useToast }  from "../../hooks/useToast";
import API_ENDPOINTS from "../../config/api.config";
import ROUTES        from "../../config/routes.config";
import {
  TIERS, TIER_LABEL, TIER_LIMITS, SUB_STATUS_META, ATTENTION_STATUSES,
  StatusBadge, SubStatusBadge, TierBadge, UsageBar, AuditLogTrail, fetchAuditLog,
} from "./shared";

function ProvisionModal({ onClose, onProvisioned }) {
  const api = apiClient;
  const { toastSuccess, toastApiError } = useToast();
  const [loading, setLoading] = useState(false);
  const [errors,  setErrors]  = useState({});
  const [form, setForm] = useState({
    name: "", city: "", state: "", gstin: "",
    admin_mobile: "", tier: "starter",
  });
  const [result, setResult] = useState(null);

  function set(field, value) {
    setForm(f => ({ ...f, [field]: value }));
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setErrors({});
    setLoading(true);
    try {
      const { data: res } = await api.post(API_ENDPOINTS.PLATFORM.TENANTS, form);
      setResult(res.data);
      toastSuccess(`${form.name} provisioned!`);
      onProvisioned();
    } catch (err) {
      if (err?.errors) setErrors(err.errors);
      toastApiError(err, "Failed to provision hospital.");
    } finally {
      setLoading(false);
    }
  }

  const inputStyle = (hasErr) => ({
    width: "100%", boxSizing: "border-box",
    border: `1.5px solid ${hasErr ? "var(--color-error)" : "var(--color-border)"}`,
    borderRadius: 8, padding: "9px 12px",
    fontSize: 14, background: "var(--color-surface)",
    color: "var(--color-text)", outline: "none",
  });

  const labelStyle = { display: "block", fontSize: 13, fontWeight: 600, marginBottom: 5 };

  return (
    <div style={{
      position: "fixed", inset: 0, zIndex: 1000,
      background: "rgba(0,0,0,0.45)",
      display: "flex", alignItems: "center", justifyContent: "center",
      padding: 24,
    }}>
      <div style={{
        background: "var(--color-surface)", borderRadius: 16,
        width: "100%", maxWidth: 560,
        maxHeight: "90vh", overflowY: "auto",
        padding: 32, boxShadow: "0 20px 60px rgba(0,0,0,0.3)",
      }}>
        {result ? (
          <div>
            <div style={{ textAlign: "center", marginBottom: 20 }}>
              <div style={{
                width: 56, height: 56, background: "#dcfce7",
                borderRadius: "50%", margin: "0 auto 12px",
                display: "flex", alignItems: "center", justifyContent: "center",
                fontSize: 24,
              }}>✓</div>
              <h2 style={{ margin: 0 }}>Hospital Provisioned!</h2>
              <p style={{ color: "var(--color-text-muted)", fontSize: 14, marginTop: 6 }}>
                Share these credentials with the hospital admin.
              </p>
            </div>
            <div style={{
              background: "var(--color-bg)", borderRadius: 10, padding: 20,
              fontFamily: "monospace", fontSize: 13, lineHeight: "1.8",
              border: "1px solid var(--color-border)",
            }}>
              <div><strong>Hospital:</strong> {result.name}</div>
              <div><strong>Tier:</strong> {result.subscription?.license_tier}</div>
              {result.credentials && (
                <>
                  <div style={{ marginTop: 10, borderTop: "1px solid var(--color-border)", paddingTop: 10 }}>
                    <strong>Hospital Code:</strong> {result.credentials.subdomain}
                  </div>
                  <div><strong>Admin Mobile:</strong> {result.credentials.admin_mobile}</div>
                  {result.credentials.employee_id && (
                    <div><strong>Employee ID:</strong> {result.credentials.employee_id}</div>
                  )}
                  <div><strong>Temp Password:</strong> {result.credentials.temp_password}</div>
                  <div style={{ marginTop: 8, fontSize: 12, color: "var(--color-text-muted)" }}>
                    {result.credentials.note}
                  </div>
                </>
              )}
            </div>
            {result.credentials?.temp_password && (
              <button type="button" onClick={() => {
                navigator.clipboard?.writeText(result.credentials.temp_password).catch(() => {});
                toastSuccess("Password copied!");
              }}
                style={{ width: "100%", marginTop: 12, padding: "9px 0", borderRadius: 8, border: "1.5px solid var(--color-primary)", background: "none", color: "var(--color-primary)", cursor: "pointer", fontSize: 14, fontWeight: 600 }}>
                Copy Password
              </button>
            )}
            <button className="btn-primary" onClick={onClose}
              style={{ width: "100%", marginTop: 12 }}>
              Done
            </button>
          </div>
        ) : (
          <form onSubmit={handleSubmit}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 24 }}>
              <h2 style={{ margin: 0, fontSize: 20 }}>Add New Hospital</h2>
              <button type="button" onClick={onClose}
                style={{ background: "none", border: "none", fontSize: 20, cursor: "pointer", color: "var(--color-text-muted)" }}>
                ✕
              </button>
            </div>

            <div style={{ display: "grid", gap: 16 }}>
              <div>
                <label style={labelStyle}>Hospital Name *</label>
                <input style={inputStyle(!!errors.name)}
                  value={form.name} onChange={e => set("name", e.target.value)}
                  placeholder="Apollo Hospitals Delhi" required />
                {errors.name && <div style={{ color: "var(--color-error)", fontSize: 12, marginTop: 4 }}>{errors.name}</div>}
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                <div>
                  <label style={labelStyle}>City</label>
                  <input style={inputStyle(false)}
                    value={form.city} onChange={e => set("city", e.target.value)}
                    placeholder="New Delhi" />
                </div>
                <div>
                  <label style={labelStyle}>State</label>
                  <input style={inputStyle(false)}
                    value={form.state} onChange={e => set("state", e.target.value)}
                    placeholder="Delhi" />
                </div>
              </div>

              <div>
                <label style={labelStyle}>GSTIN</label>
                <input style={inputStyle(false)}
                  value={form.gstin} onChange={e => set("gstin", e.target.value)}
                  placeholder="07AABCU9603R1ZX" />
              </div>

              <div>
                <label style={labelStyle}>Admin Mobile Number *</label>
                <input style={inputStyle(!!errors.admin_mobile)}
                  type="tel" value={form.admin_mobile} onChange={e => set("admin_mobile", e.target.value)}
                  placeholder="98xxxxxxxx" required />
                {errors.admin_mobile && <div style={{ color: "var(--color-error)", fontSize: 12, marginTop: 4 }}>{errors.admin_mobile}</div>}
              </div>

              <div>
                <label style={labelStyle}>License Tier</label>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 8 }}>
                  {TIERS.map(t => (
                    <label key={t} style={{
                      display: "flex", alignItems: "flex-start", gap: 8,
                      padding: "10px 12px", borderRadius: 8, cursor: "pointer",
                      border: `2px solid ${form.tier === t ? TIER_LABEL[t].color : "var(--color-border)"}`,
                      background: form.tier === t ? TIER_LABEL[t].color + "11" : "var(--color-surface)",
                      transition: "all 0.15s",
                    }}>
                      <input type="radio" name="tier" value={t}
                        checked={form.tier === t} onChange={() => set("tier", t)}
                        style={{ marginTop: 2 }} />
                      <div>
                        <div style={{ fontWeight: 600, fontSize: 13, color: TIER_LABEL[t].color }}>
                          {TIER_LABEL[t].label}
                        </div>
                        <div style={{ fontSize: 11, color: "var(--color-text-muted)", marginTop: 2 }}>
                          {TIER_LIMITS[t]}
                        </div>
                      </div>
                    </label>
                  ))}
                </div>
              </div>
            </div>

            <div style={{ display: "flex", gap: 12, marginTop: 24 }}>
              <button type="button" onClick={onClose}
                style={{
                  flex: 1, padding: "10px 0", borderRadius: 8,
                  border: "1.5px solid var(--color-border)", background: "none",
                  color: "var(--color-text)", cursor: "pointer", fontSize: 14, fontWeight: 600,
                }}>
                Cancel
              </button>
              <button type="submit" disabled={loading}
                className="btn-primary" style={{ flex: 2 }}>
                {loading ? "Provisioning…" : "Provision Hospital"}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}

function TenantCard({ tenant, onTierChange }) {
  const api = apiClient;
  const navigate = useNavigate();
  const { toastSuccess, toastApiError } = useToast();
  const [expanded, setExpanded] = useState(false);
  const [toggling, setToggling] = useState(false);
  const [tierPick, setTierPick] = useState(tenant.subscription?.license_tier || "starter");
  const [statusPick, setStatusPick] = useState(tenant.subscription?.status || "trial");
  const [subdomainPick, setSubdomainPick] = useState(tenant.subdomain || "");
  const [savingTier, setSavingTier] = useState(false);
  const [savingStatus, setSavingStatus] = useState(false);
  const [savingSubdomain, setSavingSubdomain] = useState(false);
  const [auditLog, setAuditLog] = useState(null);
  const [auditLoading, setAuditLoading] = useState(false);

  useEffect(() => {
    if (expanded && auditLog === null && !auditLoading) {
      setAuditLoading(true);
      fetchAuditLog(tenant.id)
        .then(setAuditLog)
        .catch(() => setAuditLog([]))
        .finally(() => setAuditLoading(false));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [expanded]);

  async function toggleActive() {
    setToggling(true);
    try {
      await api.patch(API_ENDPOINTS.PLATFORM.TENANT(tenant.id), { is_active: !tenant.is_active });
      toastSuccess(`Hospital ${tenant.is_active ? "suspended" : "reactivated"}.`);
      setAuditLog(null);
      onTierChange();
    } catch (err) {
      toastApiError(err, "Failed to update.");
    } finally {
      setToggling(false);
    }
  }

  async function applyTier() {
    if (tierPick === tenant.subscription?.license_tier) return;
    setSavingTier(true);
    try {
      await api.patch(API_ENDPOINTS.PLATFORM.TENANT(tenant.id), { tier: tierPick });
      toastSuccess(`Tier changed to ${TIER_LABEL[tierPick]?.label || tierPick}.`);
      setAuditLog(null);
      onTierChange();
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
      await api.patch(API_ENDPOINTS.PLATFORM.TENANT(tenant.id), { status: statusPick });
      toastSuccess(`Subscription status changed to ${SUB_STATUS_META[statusPick]?.label || statusPick}.`);
      setAuditLog(null);
      onTierChange();
    } catch (err) {
      toastApiError(err, "Failed to change status.");
    } finally {
      setSavingStatus(false);
    }
  }

  async function applySubdomain() {
    const cleaned = subdomainPick.trim().toLowerCase();
    if (!cleaned || cleaned === tenant.subdomain) return;
    setSavingSubdomain(true);
    try {
      await api.patch(API_ENDPOINTS.PLATFORM.TENANT(tenant.id), { subdomain: cleaned });
      toastSuccess(`Hospital Code changed to "${cleaned}".`);
      setAuditLog(null);
      onTierChange();
    } catch (err) {
      toastApiError(err, "Failed to change Hospital Code.");
    } finally {
      setSavingSubdomain(false);
    }
  }

  const selectStyle = {
    padding: "6px 10px", borderRadius: 8, fontSize: 12.5,
    border: "1.5px solid var(--color-border)", background: "var(--color-surface)",
    color: "var(--color-text)", outline: "none",
  };

  const tierColor = TIER_LABEL[tenant.subscription?.license_tier]?.color || "#64748b";
  const usage = tenant.usage || {};

  return (
    <div className="card card--interactive" style={{ overflow: "hidden", padding: 0 }}>
      <div style={{ padding: "16px 20px", display: "flex", alignItems: "center", gap: 14, cursor: "pointer" }}
        onClick={() => setExpanded(e => !e)}>
        <div className="icon-chip icon-chip--green" style={{ width: 40, height: 40, flexShrink: 0 }}>
          <Building2 size={18} />
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
            <span
              style={{ fontWeight: 700, fontSize: 16, fontFamily: "var(--font-display)", cursor: "pointer" }}
              onClick={e => { e.stopPropagation(); navigate(ROUTES.PLATFORM.HOSPITAL(tenant.id)); }}
              title="Open full profile"
            >
              {tenant.name}
            </span>
            <ExternalLink size={13} style={{ color: "var(--color-text-muted)", cursor: "pointer" }}
              onClick={e => { e.stopPropagation(); navigate(ROUTES.PLATFORM.HOSPITAL(tenant.id)); }} />
            <StatusBadge isActive={tenant.is_active} />
            <TierBadge tier={tenant.subscription?.license_tier} />
            <SubStatusBadge status={tenant.subscription?.status} />
          </div>
          <div style={{ color: "var(--color-text-muted)", fontSize: 13, marginTop: 4 }}>
            {tenant.city}{tenant.state ? `, ${tenant.state}` : ""}
          </div>
        </div>
        <div style={{ display: "flex", gap: 20, flexShrink: 0 }}>
          <div style={{ width: 90 }}>
            <UsageBar label="Doctors" used={usage.doctors} max={tenant.subscription?.max_doctors} />
          </div>
          <div style={{ width: 90 }}>
            <UsageBar label="Branches" used={usage.branches} max={tenant.subscription?.max_branches} />
          </div>
        </div>
        <ChevronDown size={18} style={{ color: "var(--color-text-muted)", transform: expanded ? "rotate(180deg)" : "none", transition: "transform 0.15s", flexShrink: 0 }} />
      </div>

      {expanded && (
        <div style={{ borderTop: "1px solid var(--color-border)", padding: "18px 20px", background: "var(--color-surface-secondary, #f9f7f2)" }}>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: 12, marginBottom: 18 }}>
            {[
              { label: "DB Name", value: tenant.db_name },
              { label: "GSTIN", value: tenant.gstin || "—" },
              { label: "Lab", value: tenant.subscription?.feat_lab ? "✓" : "✗" },
              { label: "Pharmacy", value: tenant.subscription?.feat_pharmacy ? "✓" : "✗" },
              { label: "AI Voice", value: tenant.subscription?.feat_ai_voice ? "✓" : "✗" },
              { label: "Patient App", value: tenant.subscription?.feat_patient_app ? "✓" : "✗" },
              { label: "Analytics", value: tenant.subscription?.feat_analytics ? "✓" : "✗" },
              { label: "Video", value: tenant.subscription?.feat_video ? "✓" : "✗" },
            ].map(({ label, value }) => (
              <div key={label}>
                <div className="stat-label">{label}</div>
                <div style={{ fontSize: 14, marginTop: 2, fontWeight: 600 }}>{value}</div>
              </div>
            ))}
          </div>

          <div style={{ display: "flex", flexWrap: "wrap", gap: 24, marginBottom: 18 }}>
            <div>
              <div className="stat-label" style={{ marginBottom: 6 }}>Hospital Code</div>
              <div style={{ display: "flex", gap: 6 }}>
                <input value={subdomainPick}
                  onChange={e => setSubdomainPick(e.target.value.toLowerCase())}
                  style={{ ...selectStyle, width: 150, fontFamily: "monospace" }} />
                <button onClick={applySubdomain} disabled={savingSubdomain || !subdomainPick.trim() || subdomainPick.trim().toLowerCase() === tenant.subdomain}
                  className="btn-outline" style={{ fontSize: 12, padding: "6px 14px" }}>
                  {savingSubdomain ? "…" : "Apply"}
                </button>
              </div>
              <div style={{ fontSize: 11, color: "var(--color-text-muted)", marginTop: 4, maxWidth: 220 }}>
                Used for Employee ID login at this hospital. Safe to change any time — doesn't affect the database name.
              </div>
            </div>

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
              <div style={{ fontSize: 11, color: "var(--color-text-muted)", marginTop: 4, maxWidth: 220 }}>
                Resets this hospital's feature flags and limits to the new tier's defaults.
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
              <div style={{ fontSize: 11, color: "var(--color-text-muted)", marginTop: 4, maxWidth: 260 }}>
                Frozen/Suspended blocks all staff logins at this hospital. Read Only blocks new/edited records but allows viewing.
              </div>
            </div>

            <div>
              <div className="stat-label" style={{ marginBottom: 6 }}>Platform kill switch</div>
              <button onClick={toggleActive} disabled={toggling}
                style={{
                  padding: "7px 16px", borderRadius: 8, fontSize: 13, fontWeight: 600,
                  cursor: "pointer", border: "1.5px solid",
                  borderColor: tenant.is_active ? "var(--color-error)" : "var(--color-success)",
                  color: tenant.is_active ? "var(--color-error)" : "var(--color-success)",
                  background: "none",
                }}>
                {toggling ? "…" : tenant.is_active ? "Suspend" : "Reactivate"}
              </button>
            </div>
          </div>

          <div>
            <div className="dot-label" style={{ marginBottom: 8 }}><History size={11} style={{ marginRight: 2 }} />Recent changes</div>
            {auditLoading ? (
              <div style={{ fontSize: 12.5, color: "var(--color-text-muted)" }}>Loading…</div>
            ) : (
              <AuditLogTrail entries={auditLog} />
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default function DashboardPage() {
  const api = apiClient;
  const [tenants,    setTenants]    = useState([]);
  const [loading,    setLoading]    = useState(true);
  const [showForm,   setShowForm]   = useState(false);
  const [search,     setSearch]     = useState("");
  const [tierFilter, setTierFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [page,       setPage]       = useState(1);
  const [pagination, setPagination] = useState(null);
  const [stats,      setStats]      = useState({ total: 0, active: 0, tiers: {}, statuses: {} });
  const [platformStats, setPlatformStats] = useState(null);

  useEffect(() => {
    api.get(API_ENDPOINTS.PLATFORM.STATS)
      .then(({ data: res }) => setPlatformStats(res.data))
      .catch(() => setPlatformStats(null));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const fetchTenants = useCallback(async (targetPage, searchTerm, tier, status) => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ page: String(targetPage), page_size: "20" });
      if (searchTerm) params.set("search", searchTerm);
      if (tier) params.set("tier", tier);
      if (status) params.set("status", status);
      const { data: res } = await api.get(`${API_ENDPOINTS.PLATFORM.TENANTS}?${params.toString()}`);
      setTenants(res.data?.results || []);
      setPagination(res.data?.pagination || null);
      setStats(res.data?.stats || { total: 0, active: 0, tiers: {}, statuses: {} });
    } catch {
      setTenants([]);
      setPagination(null);
    } finally {
      setLoading(false);
    }
  }, [api]);

  useEffect(() => {
    const t = setTimeout(() => {
      setPage(1);
      fetchTenants(1, search, tierFilter, statusFilter);
    }, 300);
    return () => clearTimeout(t);
  }, [search, tierFilter, statusFilter, fetchTenants]);

  useEffect(() => {
    if (page !== 1) fetchTenants(page, search, tierFilter, statusFilter);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page]);

  const refetchCurrentPage = useCallback(
    () => fetchTenants(page, search, tierFilter, statusFilter),
    [fetchTenants, page, search, tierFilter, statusFilter]
  );

  const attentionCount = ATTENTION_STATUSES.reduce((sum, s) => sum + (stats.statuses?.[s] || 0), 0);

  const selectStyle = {
    padding: "9px 12px", borderRadius: 8, fontSize: 13.5,
    border: "1.5px solid var(--color-border)", background: "var(--color-surface)",
    color: "var(--color-text)", outline: "none",
  };

  return (
    <AppShell>
      <PageShell title="Platform Overview">

        {/* Hero banner */}
        <div className="hero-card" style={{ marginBottom: 24 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: 20 }}>
            <div>
              <div className="stat-label" style={{ marginBottom: 6 }}>Atomwalk Platform</div>
              <div style={{ fontFamily: "var(--font-display)", fontSize: 24, fontWeight: 600 }}>
                Managing {stats.total} hospital{stats.total === 1 ? "" : "s"} across the network
              </div>
              {attentionCount > 0 && (
                <div className="hero-sub" style={{ marginTop: 8, display: "flex", alignItems: "center", gap: 6 }}>
                  <ShieldCheck size={14} />
                  {attentionCount} hospital{attentionCount === 1 ? "" : "s"} need attention (grace period, read-only, frozen, or suspended)
                </div>
              )}
            </div>
            <div style={{ display: "flex", gap: 28 }}>
              <div>
                <div className="hero-number">{stats.total}</div>
                <div className="stat-label">Total</div>
              </div>
              <div>
                <div className="hero-number">{stats.active}</div>
                <div className="stat-label">Active</div>
              </div>
              <div>
                <div className="hero-number">{stats.total - stats.active}</div>
                <div className="stat-label">Suspended</div>
              </div>
            </div>
          </div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 18 }}>
            {TIERS.map(t => (
              <span key={t} className="tag-pill" style={{ background: "rgba(255,255,255,0.14)", color: "var(--color-hero-text)" }}>
                {TIER_LABEL[t].label}: {stats.tiers?.[t] || 0}
              </span>
            ))}
          </div>
        </div>

        {/* Usage metrics + recent activity */}
        {platformStats && (
          <div style={{ display: "grid", gridTemplateColumns: "1.4fr 1fr", gap: 16, marginBottom: 24 }}>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))", gap: 12 }}>
              {[
                { label: "Doctors", value: platformStats.usage.doctors },
                { label: "Staff", value: platformStats.usage.staff },
                { label: "Patients", value: platformStats.usage.patients },
                { label: "Appointments Today", value: platformStats.usage.appointments_today },
                { label: "New This Month", value: platformStats.new_this_month },
              ].map(({ label, value }) => (
                <div key={label} className="card" style={{ padding: "14px 16px" }}>
                  <div style={{ fontSize: 22, fontWeight: 800, color: "var(--color-primary)" }}>{value.toLocaleString()}</div>
                  <div style={{ fontSize: 11.5, color: "var(--color-text-muted)", marginTop: 2 }}>{label}</div>
                </div>
              ))}
              {platformStats.unreachable_tenants > 0 && (
                <div style={{ gridColumn: "1 / -1", fontSize: 11.5, color: "var(--color-text-muted)" }}>
                  {platformStats.unreachable_tenants} hospital database{platformStats.unreachable_tenants === 1 ? "" : "s"} unreachable — excluded from totals above.
                </div>
              )}
            </div>

            <div className="card" style={{ padding: "16px 18px" }}>
              <div className="dot-label" style={{ marginBottom: 10 }}><History size={11} style={{ marginRight: 2 }} />Recent activity</div>
              {platformStats.recent_activity.length === 0 ? (
                <div style={{ fontSize: 12.5, color: "var(--color-text-muted)" }}>No changes recorded yet.</div>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 9, maxHeight: 190, overflowY: "auto" }}>
                  {platformStats.recent_activity.map(a => (
                    <div key={a.id} style={{ fontSize: 12.5 }}>
                      <strong>{a.hospital_name}</strong> — {a.action_label.toLowerCase()}
                      {a.before_value && a.after_value ? `: ${a.before_value} → ${a.after_value}` : ""}
                      <div style={{ color: "var(--color-text-muted)", fontSize: 11 }}>
                        {new Date(a.created_at).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}
                        {a.actor_email ? ` · ${a.actor_email}` : ""}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}

        {/* Header + actions */}
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 20, flexWrap: "wrap" }}>
          <div style={{ position: "relative", flex: "1 1 220px" }}>
            <Search size={15} style={{ position: "absolute", left: 12, top: "50%", transform: "translateY(-50%)", color: "var(--color-text-muted)" }} />
            <input
              value={search} onChange={e => setSearch(e.target.value)}
              placeholder="Search hospitals…"
              style={{
                width: "100%", boxSizing: "border-box", padding: "9px 14px 9px 34px", borderRadius: 8, fontSize: 14,
                border: "1.5px solid var(--color-border)", background: "var(--color-surface)",
                color: "var(--color-text)", outline: "none",
              }}
            />
          </div>
          <select value={tierFilter} onChange={e => setTierFilter(e.target.value)} style={selectStyle}>
            <option value="">All tiers</option>
            {TIERS.map(t => <option key={t} value={t}>{TIER_LABEL[t].label}</option>)}
          </select>
          <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)} style={selectStyle}>
            <option value="">All statuses</option>
            {Object.keys(SUB_STATUS_META).map(s => <option key={s} value={s}>{SUB_STATUS_META[s].label}</option>)}
          </select>
          <button className="btn-primary" onClick={() => setShowForm(true)}
            style={{ whiteSpace: "nowrap", display: "flex", alignItems: "center", gap: 6 }}>
            <Plus size={15} /> Add Hospital
          </button>
        </div>

        {/* Hospital list */}
        {loading ? (
          <div style={{ textAlign: "center", padding: 60, color: "var(--color-text-muted)" }}>
            Loading hospitals…
          </div>
        ) : tenants.length === 0 ? (
          <div className="card" style={{ textAlign: "center", padding: 60, color: "var(--color-text-muted)" }}>
            {search || tierFilter || statusFilter ? "No hospitals match your filters." : "No hospitals yet. Add one to get started."}
          </div>
        ) : (
          <>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              {tenants.map(t => (
                <TenantCard key={t.id} tenant={t} onTierChange={refetchCurrentPage} />
              ))}
            </div>

            {pagination && pagination.total_pages > 1 && (
              <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 16, marginTop: 24 }}>
                <button
                  onClick={() => setPage(p => Math.max(1, p - 1))}
                  disabled={!pagination.has_previous}
                  style={{
                    padding: "7px 16px", borderRadius: 8, fontSize: 13, fontWeight: 600,
                    border: "1.5px solid var(--color-border)", background: "var(--color-surface)",
                    color: "var(--color-text)", cursor: pagination.has_previous ? "pointer" : "not-allowed",
                    opacity: pagination.has_previous ? 1 : 0.5,
                  }}>
                  ← Previous
                </button>
                <span style={{ fontSize: 13, color: "var(--color-text-muted)" }}>
                  Page {pagination.page} of {pagination.total_pages} · {pagination.total_count} hospitals
                </span>
                <button
                  onClick={() => setPage(p => Math.min(pagination.total_pages, p + 1))}
                  disabled={!pagination.has_next}
                  style={{
                    padding: "7px 16px", borderRadius: 8, fontSize: 13, fontWeight: 600,
                    border: "1.5px solid var(--color-border)", background: "var(--color-surface)",
                    color: "var(--color-text)", cursor: pagination.has_next ? "pointer" : "not-allowed",
                    opacity: pagination.has_next ? 1 : 0.5,
                  }}>
                  Next →
                </button>
              </div>
            )}
          </>
        )}

        {showForm && (
          <ProvisionModal
            onClose={() => setShowForm(false)}
            onProvisioned={() => { setPage(1); fetchTenants(1, search, tierFilter, statusFilter); }}
          />
        )}
      </PageShell>
    </AppShell>
  );
}
