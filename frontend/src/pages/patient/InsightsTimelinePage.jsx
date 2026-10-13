/**
 * pages/patient/InsightsTimelinePage.jsx
 * --------------------------------------
 * The patient's Health Timeline: the shared timeline (components/timeline/HealthTimeline) for the signed-in patient or
 * the family member they are viewing, read from GET /records/timeline/ (no medications) and its documents from the
 * portal's own document endpoint.
 */
import { useCallback } from "react";
import { AppShell } from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import HealthTimeline from "../../components/timeline/HealthTimeline";
import apiClient from "../../services/api.client";
import API_ENDPOINTS from "../../config/api.config";
import { usePatientContext } from "../../context/PatientContext";

export default function InsightsTimelinePage() {
  const { selectedPatient } = usePatientContext();
  const awpid = selectedPatient?.awpid;
  const forFamily = awpid ? { patient_awpid: awpid } : {};
  const fetchDocument = useCallback((id) => apiClient.get(API_ENDPOINTS.PORTAL.DOCUMENT(id), { params: awpid ? { patient_awpid: awpid } : {} }), [awpid]);
  return (
    <AppShell>
      <PageShell title={selectedPatient?.isSelf ? "Health Timeline" : `${selectedPatient?.name || "Family member"}'s Health Timeline`}>
        <HealthTimeline endpoint={API_ENDPOINTS.RECORDS.TIMELINE} params={{ include_hidden: 1, ...forFamily }} fetchDocument={fetchDocument} />
      </PageShell>
    </AppShell>
  );
}
