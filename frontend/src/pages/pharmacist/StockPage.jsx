import { AppShell }  from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";

export default function StockPage() {
  return (
    <AppShell>
      <PageShell title="Stock">
        <div className="card" style={{ color: "var(--color-text-muted)", padding: 40, textAlign: "center" }}>
          Stock page — implementation in progress.
        </div>
      </PageShell>
    </AppShell>
  );
}
