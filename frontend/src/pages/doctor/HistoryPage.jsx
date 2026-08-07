/**
 * pages/doctor/HistoryPage.jsx
 * -------------------------------
 * Searchable visit history — not limited to today like the live queue.
 * Doctor sees only their own past patients (enforced server-side).
 */
import { useLocation } from "react-router-dom";
import { AppShell }  from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import VisitHistoryView from "../../components/history/VisitHistoryView";

export default function DoctorHistoryPage() {
  // Arriving here from the Patients page's "View" button carries the
  // patient's UHID in router state, so history opens pre-filtered to them.
  const location = useLocation();
  return (
    <AppShell>
      <PageShell title="Visit History">
        <VisitHistoryView role="doctor" initialPatient={location.state?.patient || ""} />
      </PageShell>
    </AppShell>
  );
}
