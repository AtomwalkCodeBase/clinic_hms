import { AppShell }  from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";

export default function PrescriptionsPage() {
  return (
    <AppShell>
      <PageShell title="Prescriptions">
        <div className="card" style={{ color: "var(--color-text-muted)", padding: 40, textAlign: "center" }}>
          Prescriptions page — implementation in progress.
        </div>
      </PageShell>
    </AppShell>
  );
}
