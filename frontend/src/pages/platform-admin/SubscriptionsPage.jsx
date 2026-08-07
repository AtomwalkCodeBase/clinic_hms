/**
 * pages/platform-admin/SubscriptionsPage.jsx
 * ---------------------------------------------
 * Subscription lifecycle view — groups every hospital by billing status
 * (trial/active/grace/read_only/frozen/suspended) so a platform admin can
 * see at a glance who needs attention, rather than scanning the full
 * hospital list. No payment gateway is wired up yet, so this is a manual
 * triage view, not an automated dunning dashboard.
 */
import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { AlertTriangle, Building2, Check, X } from "lucide-react";
import { AppShell }  from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import apiClient     from "../../services/api.client";
import API_ENDPOINTS from "../../config/api.config";
import ROUTES        from "../../config/routes.config";
import {
  TIERS, TIER_LABEL, SUB_STATUS_META, ATTENTION_STATUSES,
  TierBadge, TenantDetailDrawer,
} from "./shared";

const STATUS_ORDER = ["frozen", "suspended", "read_only", "grace", "trial", "active"];

const FEATURE_ROWS = [
  { key: "feat_lab",          label: "Lab" },
  { key: "feat_pharmacy",     label: "Pharmacy" },
  { key: "feat_whatsapp",     label: "WhatsApp" },
  { key: "feat_multi_branch", label: "Multi-branch" },
  { key: "feat_ai_voice",     label: "AI Voice Transcription" },
  { key: "feat_patient_app",  label: "Patient Portal App" },
  { key: "feat_analytics",    label: "Analytics" },
  { key: "feat_video",        label: "Video Consults" },
  { key: "feat_face_recog",   label: "Face Recognition" },
];

function PlanComparisonTable({ plans }) {
  const navigate = useNavigate();
  if (!plans) return <div style={{ color: "var(--color-text-muted)", fontSize: 13.5 }}>Loading plans…</div>;
  const cellStyle = { padding: "10px 14px", textAlign: "center", borderTop: "1px solid var(--color-border)" };
  return (
    <div className="card" style={{ padding: 0, overflow: "hidden", marginBottom: 28 }}>
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr>
              <th style={{ textAlign: "left", padding: "12px 14px", fontSize: 11, fontWeight: 700, textTransform: "uppercase", color: "var(--color-text-muted)" }}>Feature</th>
              {plans.map(p => (
                <th key={p.tier} style={{ padding: "12px 14px", textAlign: "center", cursor: "pointer" }}
                  onClick={() => navigate(`${ROUTES.PLATFORM.HOSPITALS}?tier=${p.tier}`)}
                  title={`View hospitals on the ${TIER_LABEL[p.tier]?.label} plan`}>
                  <div style={{ fontWeight: 700, fontSize: 13.5, color: TIER_LABEL[p.tier]?.color, textDecoration: "underline", textDecorationStyle: "dotted", textUnderlineOffset: 3 }}>
                    {TIER_LABEL[p.tier]?.label}
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            <tr>
              <td style={{ padding: "10px 14px", fontSize: 13, borderTop: "1px solid var(--color-border)" }}>Max Doctors</td>
              {plans.map(p => <td key={p.tier} style={cellStyle}>{p.max_doctors === 0 ? "Unlimited" : p.max_doctors}</td>)}
            </tr>
            <tr>
              <td style={{ padding: "10px 14px", fontSize: 13, borderTop: "1px solid var(--color-border)" }}>Max Branches</td>
              {plans.map(p => <td key={p.tier} style={cellStyle}>{p.max_branches === 0 ? "Unlimited" : p.max_branches}</td>)}
            </tr>
            {FEATURE_ROWS.map(f => (
              <tr key={f.key}>
                <td style={{ padding: "10px 14px", fontSize: 13, borderTop: "1px solid var(--color-border)" }}>{f.label}</td>
                {plans.map(p => (
                  <td key={p.tier} style={cellStyle}>
                    {p[f.key]
                      ? <Check size={15} style={{ color: "var(--color-success)" }} />
                      : <X size={15} style={{ color: "var(--color-text-muted)", opacity: 0.4 }} />}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function TenantRow({ tenant, onManage }) {
  const usage = tenant.usage || {};
  return (
    <div className="card card--interactive" style={{
      display: "flex", alignItems: "center", gap: 14, padding: "14px 18px", cursor: "pointer",
    }} onClick={() => onManage(tenant)}>
      <div className="icon-chip icon-chip--green" style={{ width: 34, height: 34, flexShrink: 0 }}>
        <Building2 size={16} />
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontWeight: 700, fontSize: 14.5 }}>{tenant.name}</div>
        <div style={{ fontSize: 12.5, color: "var(--color-text-muted)" }}>
          {tenant.city}{tenant.state ? `, ${tenant.state}` : ""}
        </div>
      </div>
      <TierBadge tier={tenant.subscription?.license_tier} />
      <div style={{ fontSize: 12, color: "var(--color-text-muted)", width: 80, textAlign: "right" }}>
        {usage.doctors ?? "—"}{tenant.subscription?.max_doctors ? ` / ${tenant.subscription.max_doctors}` : ""} docs
      </div>
    </div>
  );
}

export default function SubscriptionsPage() {
  const api = apiClient;
  const [tenants, setTenants] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState(null);
  const [plans, setPlans] = useState(null);

  useEffect(() => {
    api.get(API_ENDPOINTS.PLATFORM.PLANS)
      .then(({ data: res }) => setPlans(res.data))
      .catch(() => setPlans(null));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    try {
      const { data: res } = await api.get(`${API_ENDPOINTS.PLATFORM.TENANTS}?page=1&page_size=100`);
      setTenants(res.data?.results || []);
    } catch {
      setTenants([]);
    } finally {
      setLoading(false);
    }
  }, [api]);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  const grouped = STATUS_ORDER.reduce((acc, s) => {
    acc[s] = tenants.filter(t => t.subscription?.status === s);
    return acc;
  }, {});
  const tierCounts = TIERS.reduce((acc, t) => {
    acc[t] = tenants.filter(x => x.subscription?.license_tier === t).length;
    return acc;
  }, {});
  const attentionTotal = ATTENTION_STATUSES.reduce((sum, s) => sum + grouped[s].length, 0);

  return (
    <AppShell>
      <PageShell title="Subscriptions">
        <div className="dot-label" style={{ marginBottom: 10 }}>Plans</div>
        <PlanComparisonTable plans={plans} />

        {loading ? (
          <div style={{ textAlign: "center", padding: 60, color: "var(--color-text-muted)" }}>Loading…</div>
        ) : (
          <>
            {/* Tier distribution strip */}
            <div className="card" style={{ padding: "18px 22px", marginBottom: 24 }}>
              <div className="stat-label" style={{ marginBottom: 12 }}>Tier distribution</div>
              <div style={{ display: "flex", gap: 22, flexWrap: "wrap" }}>
                {TIERS.map(t => (
                  <div key={t} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <span style={{ width: 10, height: 10, borderRadius: "50%", background: TIER_LABEL[t].color, display: "inline-block" }} />
                    <span style={{ fontSize: 13.5 }}>{TIER_LABEL[t].label}</span>
                    <span style={{ fontWeight: 700, fontSize: 13.5 }}>{tierCounts[t]}</span>
                  </div>
                ))}
              </div>
            </div>

            {attentionTotal > 0 && (
              <div style={{
                display: "flex", alignItems: "center", gap: 10, padding: "12px 18px", borderRadius: 12,
                background: "var(--color-error-light)", color: "var(--color-error)", marginBottom: 24, fontSize: 13.5, fontWeight: 600,
              }}>
                <AlertTriangle size={16} />
                {attentionTotal} hospital{attentionTotal === 1 ? "" : "s"} need attention below.
              </div>
            )}

            {STATUS_ORDER.map(status => {
              const list = grouped[status];
              if (list.length === 0) return null;
              const meta = SUB_STATUS_META[status];
              return (
                <div key={status} style={{ marginBottom: 28 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
                    <span style={{ width: 8, height: 8, borderRadius: "50%", background: meta.fg, display: "inline-block" }} />
                    <span style={{ fontSize: 13, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.06em", color: meta.fg }}>
                      {meta.label}
                    </span>
                    <span style={{ fontSize: 12.5, color: "var(--color-text-muted)" }}>({list.length})</span>
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                    {list.map(t => (
                      <TenantRow key={t.id} tenant={t} onManage={setSelected} />
                    ))}
                  </div>
                </div>
              );
            })}

            {tenants.length === 0 && (
              <div className="card" style={{ textAlign: "center", padding: 60, color: "var(--color-text-muted)" }}>
                No hospitals yet.
              </div>
            )}
          </>
        )}

        {selected && (
          <TenantDetailDrawer
            tenant={selected}
            onClose={() => setSelected(null)}
            onChanged={fetchAll}
          />
        )}
      </PageShell>
    </AppShell>
  );
}
