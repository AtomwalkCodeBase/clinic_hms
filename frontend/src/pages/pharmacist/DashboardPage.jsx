/**
 * pages/pharmacist/DashboardPage.jsx
 * ------------------------------------
 * Pharmacist landing page: stat cards up top, then two live preview panels
 * (prescriptions actually waiting, drugs actually low) so the page has real
 * work to jump into instead of three numbers and nothing else.
 */
import { useNavigate } from "react-router-dom";
import { ClipboardList, PackageSearch, AlertTriangle, ArrowRight } from "lucide-react";
import { AppShell }  from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import { useApi }    from "../../hooks/useApi";
import API_ENDPOINTS from "../../config/api.config";
import { ROUTES }    from "../../config/routes.config";

function StatCard({ label, value, tone }) {
  const colors = {
    default: { bg: "var(--color-surface)", fg: "var(--color-text)" },
    warn:    { bg: "#FEF2F2", fg: "#991B1B" },
  }[tone || "default"];
  return (
    <div className="card" style={{ background: colors.bg, padding: 20, flex: 1, minWidth: 160 }}>
      <div style={{ fontSize: 11, fontWeight: 700, color: "var(--color-text-muted)", marginBottom: 6, textTransform: "uppercase" }}>{label}</div>
      <div style={{ fontSize: 28, fontWeight: 700, color: colors.fg }}>{value}</div>
    </div>
  );
}

function Panel({ icon: Icon, title, count, accent, onViewAll, loading, empty, emptyText, children }) {
  return (
    <div className="card" style={{ padding: 0, overflow: "hidden", flex: 1, minWidth: 320 }}>
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        padding: "14px 18px", borderBottom: "1px solid var(--color-border)",
      }}>
        <span style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, fontWeight: 700 }}>
          <Icon size={15} style={{ color: accent }} />
          {title}
          {count != null && (
            <span style={{
              fontSize: 11, fontWeight: 700, color: accent, background: `color-mix(in srgb, ${accent} 14%, transparent)`,
              borderRadius: 999, padding: "1px 8px",
            }}>{count}</span>
          )}
        </span>
        <button className="btn-outline" style={{ fontSize: 11.5, padding: "4px 12px", display: "flex", alignItems: "center", gap: 4 }}
          onClick={onViewAll}>
          View all <ArrowRight size={12} />
        </button>
      </div>
      {loading ? (
        <div style={{ padding: 28, textAlign: "center", color: "var(--color-text-muted)", fontSize: 12.5 }}>Loading…</div>
      ) : empty ? (
        <div style={{ padding: 28, textAlign: "center", color: "var(--color-text-muted)", fontSize: 12.5 }}>{emptyText}</div>
      ) : (
        <div>{children}</div>
      )}
    </div>
  );
}

export default function DashboardPage() {
  const navigate = useNavigate();

  // status: "active" — matches the pharmacist Prescriptions page's default
  // "Pending" tab and the backend's default filter (Prescription.STATUS_ACTIVE).
  // Was previously "finalized", a status value that doesn't exist on the
  // model, so this always silently returned zero rows regardless of what
  // was actually waiting in the queue.
  const { data: rxData, isLoading: rxLoading } = useApi(API_ENDPOINTS.PHARMACY.PRESCRIPTIONS, { params: { status: "active", page_size: 5 } });
  const { data: stockData, isLoading: stockLoading } = useApi(API_ENDPOINTS.PHARMACY.STOCK, { params: { page_size: 1 } });
  const { data: lowStockData, isLoading: lowLoading } = useApi(API_ENDPOINTS.PHARMACY.STOCK, { params: { low_only: 1, page_size: 5 } });

  const stockCount = stockData?.pagination?.total_count ?? 0;
  const lowCount = lowStockData?.pagination?.total_count ?? lowStockData?.results?.length ?? 0;
  const pendingCount = rxData?.pagination?.total_count ?? rxData?.results?.length ?? 0;
  const pendingRx = rxData?.results || [];
  const lowStock = lowStockData?.results || [];

  return (
    <AppShell>
      <PageShell title="Dashboard">
        <div style={{ display: "flex", gap: 16, flexWrap: "wrap", marginBottom: 20 }}>
          <StatCard label="Prescriptions waiting" value={rxLoading ? "…" : pendingCount} />
          <StatCard label="Batches on hand" value={stockLoading ? "…" : stockCount} />
          <StatCard label="Low on stock" value={lowLoading ? "…" : lowCount} tone={lowCount > 0 ? "warn" : "default"} />
        </div>

        <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
          <Panel
            icon={ClipboardList} title="Prescriptions waiting" count={pendingCount} accent="var(--color-primary)"
            loading={rxLoading} empty={pendingRx.length === 0} emptyText="Nothing waiting — the queue is clear."
            onViewAll={() => navigate(ROUTES.PHARMACIST.PRESCRIPTIONS)}
          >
            {pendingRx.map(rx => (
              <div key={rx.id} style={{
                display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10,
                padding: "10px 18px", borderBottom: "1px solid var(--color-border)",
              }}>
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontSize: 12.5, fontWeight: 600, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                    {rx.patient_name || "—"}
                  </div>
                  <div style={{ fontSize: 11, color: "var(--color-text-muted)" }}>
                    Dr. {rx.doctor_name || "—"} · {rx.items?.length ?? 0} item{rx.items?.length === 1 ? "" : "s"}
                  </div>
                </div>
                <span style={{
                  fontSize: 11, fontWeight: 800, color: "var(--color-primary)", flexShrink: 0,
                  fontFamily: "var(--font-display)",
                }}>
                  {rx.rx_number || "—"}
                </span>
              </div>
            ))}
          </Panel>

          <Panel
            icon={AlertTriangle} title="Low on stock" count={lowCount} accent="#991B1B"
            loading={lowLoading} empty={lowStock.length === 0} emptyText="Nothing running low right now."
            onViewAll={() => navigate(ROUTES.PHARMACIST.STOCK, { state: { lowOnly: true } })}
          >
            {lowStock.map(s => (
              <div key={s.id} style={{
                display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10,
                padding: "10px 18px", borderBottom: "1px solid var(--color-border)",
              }}>
                <div style={{ fontSize: 12.5, fontWeight: 600 }}>{s.drug_name || "—"}</div>
                <div style={{ fontSize: 11, color: "#991B1B", fontWeight: 700 }}>
                  {s.quantity} left <span style={{ color: "var(--color-text-muted)", fontWeight: 400 }}>· reorder at {s.reorder_level}</span>
                </div>
              </div>
            ))}
          </Panel>
        </div>

        <div style={{ display: "flex", gap: 10, marginTop: 20, flexWrap: "wrap" }}>
          <button className="btn-outline" style={{ fontSize: 12.5, padding: "8px 16px", display: "flex", alignItems: "center", gap: 6 }}
            onClick={() => navigate(ROUTES.PHARMACIST.STOCK)}>
            <PackageSearch size={14} /> Manage stock
          </button>
          <button className="btn-outline" style={{ fontSize: 12.5, padding: "8px 16px", display: "flex", alignItems: "center", gap: 6 }}
            onClick={() => navigate(ROUTES.PHARMACIST.PRESCRIPTIONS)}>
            <ClipboardList size={14} /> Go to dispensing queue
          </button>
        </div>
      </PageShell>
    </AppShell>
  );
}
