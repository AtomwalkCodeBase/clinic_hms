/**
 * pages/front-desk/HistoryPage.jsx
 * ------------------------------------
 * Searchable visit history — not limited to today like the live queue.
 * Shows the whole hospital, across all doctors and branches.
 */
import { AppShell }  from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import VisitHistoryView from "../../components/history/VisitHistoryView";

export default function FrontDeskHistoryPage() {
  return (
    <AppShell>
      <PageShell title="">
        <div className="fdc-header-row">
          <div>
            <div className="fdc-eyebrow">Front Desk</div>
            <div className="fdc-title">Visit History</div>
            <div className="fdc-subtitle">View past visits, consultations, and treatments across the hospital.</div>
          </div>
        </div>
        <VisitHistoryView role="front-desk" />
      </PageShell>
    </AppShell>
  );
}
