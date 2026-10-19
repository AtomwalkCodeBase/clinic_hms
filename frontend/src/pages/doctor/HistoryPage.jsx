/** pages/doctor/HistoryPage.jsx */
import { useLocation } from "react-router-dom";
import { AppShell }  from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import VisitHistoryView from "../../components/history/VisitHistoryView";

export default function DoctorHistoryPage() {
  // Arriving here from the Patients page's "View" button carries the
  const location = useLocation();
  return (
    <AppShell>
      <PageShell title="Visit History">
        <VisitHistoryView role="doctor" initialPatient={location.state?.patient || ""} />
      </PageShell>
    </AppShell>
  );
}
