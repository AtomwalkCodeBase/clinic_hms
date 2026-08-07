/**
 * pages/nurse/HistoryPage.jsx
 * ------------------------------
 * Searchable visit history — not limited to today like the live monitoring
 * list. Shows the whole hospital, same scoping as the live queue.
 */
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
