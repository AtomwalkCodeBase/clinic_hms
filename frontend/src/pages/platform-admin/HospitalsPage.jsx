/**
 * pages/platform-admin/HospitalsPage.jsx
 * -----------------------------------------
 * Full sortable/filterable hospital directory — the "spreadsheet" view of
 * every tenant on the platform, complementary to DashboardPage's card list.
 * Click a row to open that hospital's full detail page (Overview / Users &
 * Roles / Subscription / Audit Log tabs).
 */
import { useState, useEffect, useCallback, useMemo } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ArrowUp, ArrowDown, Building2 } from "lucide-react";
import { AppShell }  from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import apiClient     from "../../services/api.client";
import API_ENDPOINTS from "../../config/api.config";
import ROUTES        from "../../config/routes.config";
import {
  TIERS, TIER_LABEL, SUB_STATUS_META,
  StatusBadge, SubStatusBadge, TierBadge,
} from "./shared";

const COLUMNS = [
  { key: "name",    label: "Hospital" },
  { key: "city",    label: "Location" },
  { key: "tier",    label: "Tier" },
  { key: "status",  label: "Status" },
  { key: "doctors", label: "Doctors" },
  { key: "created", label: "Created" },
];

export default function HospitalsPage() {
  const api = apiClient;
  const navigate = useNavigate();
  // Supports being deep-linked from Subscriptions' plan table, e.g.
  // /platform/hospitals?tier=growth — filter pre-set from the URL on load.
  const [searchParams, setSearchParams] = useSearchParams();
  const [tenants, setTenants] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [tierFilter, setTierFilter] = useState(searchParams.get("tier") || "");
  const [statusFilter, setStatusFilter] = useState(searchParams.get("status") || "");
  const [sortKey, setSortKey] = useState("name");
  const [sortDir, setSortDir] = useState("asc");
  const [page, setPage] = useState(1);
  const [pagination, setPagination] = useState(null);

  const fetchAll = useCallback(async (targetPage, searchTerm, tier, status) => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ page: String(targetPage), page_size: "20" });
      if (searchTerm) params.set("search", searchTerm);
      if (tier) params.set("tier", tier);
      if (status) params.set("status", status);
      const { data: res } = await api.get(`${API_ENDPOINTS.PLATFORM.TENANTS}?${params.toString()}`);
      setTenants(res.data?.results || []);
      setPagination(res.data?.pagination || null);
    } catch {
      setTenants([]);
      setPagination(null);
    } finally {
      setLoading(false);
    }
  }, [api]);

  useEffect(() => {
    const t = setTimeout(() => { setPage(1); fetchAll(1, search, tierFilter, statusFilter); }, 300);
    return () => clearTimeout(t);
  }, [search, tierFilter, statusFilter, fetchAll]);

  useEffect(() => {
    if (page !== 1) fetchAll(page, search, tierFilter, statusFilter);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page]);

  function toggleSort(key) {
    if (sortKey === key) {
      setSortDir(d => d === "asc" ? "desc" : "asc");
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
  }

  const sorted = useMemo(() => {
    const arr = [...tenants];
    const dir = sortDir === "asc" ? 1 : -1;
    arr.sort((a, b) => {
      let av, bv;
      switch (sortKey) {
        case "tier":    av = a.subscription?.license_tier || ""; bv = b.subscription?.license_tier || ""; break;
        case "status":  av = a.subscription?.status || "";       bv = b.subscription?.status || "";       break;
        case "doctors": av = a.usage?.doctors ?? -1;              bv = b.usage?.doctors ?? -1;              break;
        case "created": av = a.created_at;                        bv = b.created_at;                        break;
        case "city":    av = a.city || "";                        bv = b.city || "";                        break;
        default:        av = a.name || "";                        bv = b.name || "";
      }
      if (av < bv) return -1 * dir;
      if (av > bv) return 1 * dir;
      return 0;
    });
    return arr;
  }, [tenants, sortKey, sortDir]);

  const thStyle = {
    textAlign: "left", padding: "10px 14px", fontSize: 11, fontWeight: 700,
    letterSpacing: "0.06em", textTransform: "uppercase", color: "var(--color-text-muted)",
    cursor: "pointer", userSelect: "none", whiteSpace: "nowrap",
  };
  const tdStyle = { padding: "12px 14px", fontSize: 13.5, borderTop: "1px solid var(--color-border)" };
  const selectStyle = {
    padding: "9px 12px", borderRadius: 8, fontSize: 13.5,
    border: "1.5px solid var(--color-border)", background: "var(--color-surface)",
    color: "var(--color-text)", outline: "none",
  };

  return (
    <AppShell>
      <PageShell title="Hospitals">
        <div style={{ display: "flex", gap: 12, marginBottom: 18, flexWrap: "wrap" }}>
          <input
            value={search} onChange={e => setSearch(e.target.value)}
            placeholder="Search hospitals…"
            style={{
              flex: "1 1 220px", padding: "9px 14px", borderRadius: 8, fontSize: 14,
              border: "1.5px solid var(--color-border)", background: "var(--color-surface)",
              color: "var(--color-text)", outline: "none",
            }}
          />
          <select value={tierFilter} onChange={e => setTierFilter(e.target.value)} style={selectStyle}>
            <option value="">All tiers</option>
            {TIERS.map(t => <option key={t} value={t}>{TIER_LABEL[t].label}</option>)}
          </select>
          <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)} style={selectStyle}>
            <option value="">All statuses</option>
            {Object.keys(SUB_STATUS_META).map(s => <option key={s} value={s}>{SUB_STATUS_META[s].label}</option>)}
          </select>
        </div>

        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          {loading ? (
            <div style={{ textAlign: "center", padding: 60, color: "var(--color-text-muted)" }}>Loading…</div>
          ) : sorted.length === 0 ? (
            <div style={{ textAlign: "center", padding: 60, color: "var(--color-text-muted)" }}>No hospitals match.</div>
          ) : (
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead>
                  <tr>
                    {COLUMNS.map(col => (
                      <th key={col.key} style={thStyle} onClick={() => toggleSort(col.key)}>
                        <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
                          {col.label}
                          {sortKey === col.key && (sortDir === "asc" ? <ArrowUp size={11} /> : <ArrowDown size={11} />)}
                        </span>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {sorted.map(t => (
                    <tr key={t.id} onClick={() => navigate(ROUTES.PLATFORM.HOSPITAL(t.id))}
                      style={{ cursor: "pointer" }}
                      onMouseEnter={e => e.currentTarget.style.background = "var(--color-surface-secondary, #f6f4ee)"}
                      onMouseLeave={e => e.currentTarget.style.background = "transparent"}>
                      <td style={tdStyle}>
                        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                          <div className="icon-chip icon-chip--green" style={{ width: 26, height: 26, flexShrink: 0 }}>
                            <Building2 size={12} />
                          </div>
                          <span style={{ fontWeight: 600 }}>{t.name}</span>
                        </div>
                      </td>
                      <td style={tdStyle}>{t.city}{t.state ? `, ${t.state}` : ""}</td>
                      <td style={tdStyle}><TierBadge tier={t.subscription?.license_tier} /></td>
                      <td style={tdStyle}>
                        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                          <StatusBadge isActive={t.is_active} />
                          <SubStatusBadge status={t.subscription?.status} />
                        </div>
                      </td>
                      <td style={tdStyle}>
                        {t.usage?.doctors ?? "—"}{t.subscription?.max_doctors ? ` / ${t.subscription.max_doctors}` : ""}
                      </td>
                      <td style={tdStyle}>{new Date(t.created_at).toLocaleDateString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {pagination && pagination.total_pages > 1 && (
          <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 16, marginTop: 20 }}>
            <button onClick={() => setPage(p => Math.max(1, p - 1))} disabled={!pagination.has_previous}
              style={{ padding: "7px 16px", borderRadius: 8, fontSize: 13, fontWeight: 600, border: "1.5px solid var(--color-border)", background: "var(--color-surface)", color: "var(--color-text)", cursor: pagination.has_previous ? "pointer" : "not-allowed", opacity: pagination.has_previous ? 1 : 0.5 }}>
              ← Previous
            </button>
            <span style={{ fontSize: 13, color: "var(--color-text-muted)" }}>
              Page {pagination.page} of {pagination.total_pages} · {pagination.total_count} hospitals
            </span>
            <button onClick={() => setPage(p => Math.min(pagination.total_pages, p + 1))} disabled={!pagination.has_next}
              style={{ padding: "7px 16px", borderRadius: 8, fontSize: 13, fontWeight: 600, border: "1.5px solid var(--color-border)", background: "var(--color-surface)", color: "var(--color-text)", cursor: pagination.has_next ? "pointer" : "not-allowed", opacity: pagination.has_next ? 1 : 0.5 }}>
              Next →
            </button>
          </div>
        )}
      </PageShell>
    </AppShell>
  );
}
