/** pages/nurse/HistoryPage.jsx */
import { AppShell }  from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import VisitHistoryView from "../../components/history/VisitHistoryView";

export default function NurseHistoryPage() {
  return (
    <AppShell>
      <PageShell title="Visit History">
        <VisitHistoryView role="nurse" />
      </PageShell>
    </AppShell>
  );
}
