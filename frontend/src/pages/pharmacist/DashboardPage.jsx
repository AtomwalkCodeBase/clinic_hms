import { AppShell }  from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";

export default function DashboardPage() {
  return (
    <AppShell>
      <PageShell title="Dashboard">
        <div className="card" style={{ color: "var(--color-text-muted)", padding: 40, textAlign: "center" }}>
          Dashboard page — implementation in progress.
        </div>
      </PageShell>
    </AppShell>
  );
}
