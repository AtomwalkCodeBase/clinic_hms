/**
 * pages/front-desk/PatientIntakePage.jsx
 * -----------------------------------------
 * The consolidated "Patient Intake" workspace — reached either as its own
 * expandable sidebar group (see AppShell.jsx's NAV_BY_ROLE[ROLES.FRONT_DESK])
 * or by landing on any of its five tabs directly/via deep link.
 *
 * None of the five tabs are reimplemented here — each renders the exact
 * same content component that already powers its own standalone route
 * (still mounted in App.jsx for backward compatibility/deep links), via
 * that component's `embedded` prop, so there's one implementation, one set
 * of API calls, one set of form validations per step:
 *   Register Patient   → RegisterPatientPageContent   (RegisterPatientPage.jsx)
 *   Triage              → TriagePageContent            (TriagePage.jsx)
 *   Emergency Reg.       → EmergencyRegisterPageContent (EmergencyRegisterPage.jsx)
 *   OPD Booking          → AppointmentsPageContent      (AppointmentsPage.jsx)
 *   Referral Queue &     → AdmissionsPageContent        (AdmissionsPage.jsx)
 *   Admission
 *
 * Which tab is showing is read from the URL path (one of the five
 * ROUTES.FRONT_DESK.INTAKE_* routes — see routes.config.js) rather than
 * React state or a query param, so the sidebar's expandable submenu can
 * highlight the right child (NavLink prefix-matching needs distinct paths
 * to do that reliably) and the current step survives a reload or a direct
 * link. Visiting the bare .INTAKE path redirects to .INTAKE_REGISTER
 * (see App.jsx).
 */
import { useNavigate, useLocation } from "react-router-dom";
import { AppShell } from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import { RegisterPatientPageContent } from "./RegisterPatientPage";
import { TriagePageContent } from "./TriagePage";
import { EmergencyRegisterPageContent } from "./EmergencyRegisterPage";
import { AppointmentsPageContent } from "./AppointmentsPage";
import { AdmissionsPageContent } from "./AdmissionsPage";
import { ROUTES } from "../../config/routes.config";

const TABS = [
  { key: "register",  label: "Register Patient",             to: ROUTES.FRONT_DESK.INTAKE_REGISTER },
  { key: "triage",    label: "Triage",                        to: ROUTES.FRONT_DESK.INTAKE_TRIAGE },
  { key: "emergency", label: "Emergency Registration",        to: ROUTES.FRONT_DESK.INTAKE_EMERGENCY },
  { key: "opd",       label: "OPD Booking",                   to: ROUTES.FRONT_DESK.INTAKE_OPD },
  { key: "referrals", label: "Referral Queue & Admission",    to: ROUTES.FRONT_DESK.INTAKE_REFERRALS },
];

export default function PatientIntakePage() {
  const navigate = useNavigate();
  const location = useLocation();

  const tab = TABS.find(t => location.pathname.startsWith(t.to))?.key || "register";

  return (
    <AppShell>
      <PageShell title="">
        <div className="fdc-header-row">
          <div>
            <div className="fdc-eyebrow">Patient Intake</div>
            <div className="fdc-title">Register &amp; Manage Patients</div>
            <div className="fdc-subtitle">
              Find an existing patient or register a new one, then move them through
              triage, OPD booking, emergency registration or admission referral —
              all from one workspace.
            </div>
          </div>
          <button className="btn-outline" style={{ fontSize: 12 }}
            onClick={() => navigate(ROUTES.FRONT_DESK.PATIENTS)}>
            Browse All Patients →
          </button>
        </div>

        <div className="fdc-tabs" style={{ marginBottom: 20 }}>
          {TABS.map(t => (
            <button
              key={t.key}
              type="button"
              className={"fdc-tab" + (tab === t.key ? " active" : "")}
              onClick={() => navigate(t.to)}
            >
              {t.label}
            </button>
          ))}
        </div>

        {tab === "triage" ? (
          <TriagePageContent embedded />
        ) : tab === "emergency" ? (
          <EmergencyRegisterPageContent embedded />
        ) : tab === "opd" ? (
          <AppointmentsPageContent embedded />
        ) : tab === "referrals" ? (
          <AdmissionsPageContent embedded />
        ) : (
          <RegisterPatientPageContent embedded />
        )}
      </PageShell>
    </AppShell>
  );
}
