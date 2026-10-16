/**
 * pages/patient/InsightsTimelinePage.jsx
 * --------------------------------------
 * The patient's Health Journey: the signed-in patient, or the family member they are viewing, from
 * GET /peds/patients/<awpid>/health-timeline/ (components/healthJourney). A mark opens the report it came from.
 */
import { useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { AppShell } from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import HealthJourney from "../../components/healthJourney/HealthJourney";
import { openDocumentWith } from "../../components/healthJourney/openDocument";
import { apiClient } from "../../services/api.client";
import API_ENDPOINTS from "../../config/api.config";
import { useAuth } from "../../hooks/useAuth";
import { usePatientContext } from "../../context/PatientContext";
import ROUTES from "../../config/routes.config";

export default function InsightsTimelinePage() {
  const { user } = useAuth();
  const { selectedPatient } = usePatientContext();
  const navigate = useNavigate();
  const awpid = selectedPatient?.awpid || user?.awpid;
  const children = useMemo(() => [{ id: awpid, name: selectedPatient?.name || "Your" }], [awpid, selectedPatient?.name]);
  const openDocument = useMemo(
    () => openDocumentWith(API_ENDPOINTS.PORTAL.DOCUMENT, selectedPatient?.awpid ? { patient_awpid: selectedPatient.awpid } : {}),
    [selectedPatient?.awpid],
  );
  return (
    <AppShell>
      <PageShell title={selectedPatient?.isSelf ? "Health Timeline" : `${selectedPatient?.name || "Family member"}'s Health Timeline`}>
        {awpid && <HealthJourney key={awpid} http={apiClient} children={children} onOpenDocument={openDocument}
          emptyAction={{ label: "Upload a report", onClick: () => navigate(ROUTES.PATIENT.MY_REPORTS) }} />}
      </PageShell>
    </AppShell>
  );
}
