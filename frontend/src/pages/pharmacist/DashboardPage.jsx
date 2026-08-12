/**
 * pages/pharmacist/DashboardPage.jsx
 * ------------------------------------
 * At-a-glance counts for the pharmacist: how many prescriptions are
 * waiting, how many batches are low on stock, total batches on hand.
 */
import { AppShell }  from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import { useApi }    from "../../hooks/useApi";
import API_ENDPOINTS from "../../config/api.config";

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

export default function DashboardPage() {
  const { data: rxData, isLoading: rxLoading } = useApi(API_ENDPOINTS.PHARMACY.PRESCRIPTIONS, { params: { status: "finalized", page_size: 1 } });
  const { data: stockData, isLoading: stockLoading } = useApi(API_ENDPOINTS.PHARMACY.STOCK, { params: { page_size: 500 } });

  const stock = stockData?.results || [];
  const lowCount = stock.filter(s => s.is_low).length;
  const pendingCount = rxData?.pagination?.total_count ?? rxData?.results?.length ?? 0;

  return (
    <AppShell>
      <PageShell title="Dashboard">
        <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
          <StatCard label="Prescriptions waiting" value={rxLoading ? "…" : pendingCount} />
          <StatCard label="Batches on hand" value={stockLoading ? "…" : stock.length} />
          <StatCard label="Low on stock" value={stockLoading ? "…" : lowCount} tone={lowCount > 0 ? "warn" : "default"} />
        </div>
      </PageShell>
    </AppShell>
  );
}
