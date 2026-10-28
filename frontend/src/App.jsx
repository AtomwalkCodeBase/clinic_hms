/** App.jsx */

import { BrowserRouter, Routes, Route, Navigate, useLocation } from "react-router-dom";
import { useAuth } from "./hooks/useAuth";
import { ROUTES }  from "./config/routes.config";
import { ROLES, ACTS_AS_PRIORITY } from "./constants/roles";
import { moduleAllows } from "./constants/modules";
import { ErrorBoundary } from "./components/common/ErrorBoundary";
import { PatientProvider } from "./context/PatientContext";

// ── Lazy-loaded pages ─────────────────────────────────────────────────────────
import { lazy, Suspense } from "react";

const LoginPage         = lazy(() => import("./pages/auth/LoginPage"));
const SetupPasswordPage = lazy(() => import("./pages/auth/SetupPasswordPage"));
const ChangePasswordPage = lazy(() => import("./pages/auth/ChangePasswordPage"));
const StaffForgotPasswordPage   = lazy(() => import("./pages/auth/StaffForgotPasswordPage"));
const PatientForgotPasswordPage = lazy(() => import("./pages/auth/PatientForgotPasswordPage"));
const EmergencyViewPage         = lazy(() => import("./pages/public/EmergencyViewPage"));
const ViewReportPage            = lazy(() => import("./pages/public/ViewReportPage"));
const ConsultPadPage            = lazy(() => import("./pages/public/ConsultPadPage"));
const ShareRecordsPage          = lazy(() => import("./pages/public/ShareRecordsPage"));

// Platform Admin
const PlatformDashboard  = lazy(() => import("./pages/platform-admin/DashboardPage"));
const PlatformHospitals  = lazy(() => import("./pages/platform-admin/HospitalsPage"));
const PlatformHospitalDetail = lazy(() => import("./pages/platform-admin/HospitalDetailPage"));
const PlatformSubscriptions = lazy(() => import("./pages/platform-admin/SubscriptionsPage"));
const PlatformUsers      = lazy(() => import("./pages/platform-admin/UsersPage"));
const PlatformVaccinationTemplates = lazy(() => import("./pages/platform-admin/VaccinationTemplatesPage"));
const PlatformClassificationRules = lazy(() => import("./pages/platform-admin/ClassificationRulesPage"));

// Hospital Admin
const AdminDashboard = lazy(() => import("./pages/hospital-admin/DashboardPage"));
const AdminStaff     = lazy(() => import("./pages/hospital-admin/StaffPage"));
const AdminBranches  = lazy(() => import("./pages/hospital-admin/BranchesPage"));
const AdminRooms     = lazy(() => import("./pages/hospital-admin/RoomsPage"));
const AdminBillingSetup = lazy(() => import("./pages/hospital-admin/BillingSetupPage"));
const AdminBillingReports = lazy(() => import("./pages/hospital-admin/BillingReportsPage"));
const AdminCompliance = lazy(() => import("./pages/hospital-admin/CompliancePage"));
const AdminRoles     = lazy(() => import("./pages/hospital-admin/RolesPage"));
const AdminVaccinationSchedule = lazy(() => import("./pages/hospital-admin/VaccinationSchedulePage"));
const AdminSettings  = lazy(() => import("./pages/hospital-admin/SettingsPage"));

// Doctor
const DoctorDashboard = lazy(() => import("./pages/doctor/DashboardPage"));
const DoctorQueue     = lazy(() => import("./pages/doctor/QueuePage"));
const DoctorEncounter = lazy(() => import("./pages/doctor/EncounterPage"));
const DoctorPatients  = lazy(() => import("./pages/doctor/PatientsPage"));
const DoctorHistory   = lazy(() => import("./pages/doctor/HistoryPage"));
const DoctorMyProfile = lazy(() => import("./pages/doctor/MyProfilePage"));

// Nurse
const NurseDashboard = lazy(() => import("./pages/nurse/DashboardPage"));
const NurseVitals    = lazy(() => import("./pages/nurse/VitalsPage"));
const NurseTasks     = lazy(() => import("./pages/nurse/TasksPage"));
const NurseHistory   = lazy(() => import("./pages/nurse/HistoryPage"));
// Lab-order choice picker now lives inline in NurseTasksPage — see Tasks page.

// Front Desk
const FrontDeskDashboard      = lazy(() => import("./pages/front-desk/DashboardPage"));
const FrontDeskTriage         = lazy(() => import("./pages/front-desk/TriagePage"));
const FrontDeskRegisterPatient= lazy(() => import("./pages/front-desk/RegisterPatientPage"));
const FrontDeskPatients       = lazy(() => import("./pages/front-desk/PatientsPage"));
const FrontDeskAppointments   = lazy(() => import("./pages/front-desk/AppointmentsPage"));
const FrontDeskQueue          = lazy(() => import("./pages/front-desk/QueuePage"));
const FrontDeskBilling        = lazy(() => import("./pages/front-desk/BillingPage"));
const FrontDeskHistory        = lazy(() => import("./pages/front-desk/HistoryPage"));

// Shared — generic self-service "My Profile" (photo upload) for any
const SharedMyProfile = lazy(() => import("./pages/shared/MyProfilePage"));

// Patient
const PatientDashboard     = lazy(() => import("./pages/patient/DashboardPage"));
const PatientAppointments  = lazy(() => import("./pages/patient/AppointmentsPage"));
const PatientHospitals       = lazy(() => import("./pages/patient/HospitalsPage"));
const PatientHospitalDoctors = lazy(() => import("./pages/patient/HospitalDoctorsPage"));
const PatientDoctorProfile   = lazy(() => import("./pages/patient/DoctorProfilePage"));
const PatientRecords       = lazy(() => import("./pages/patient/RecordsPage"));
const PatientPrescriptions = lazy(() => import("./pages/patient/PrescriptionsPage"));
const PatientMyReports     = lazy(() => import("./pages/patient/MyReportsPage"));
const PatientSharedRecordsPrivacy = lazy(() => import("./pages/patient/SharedRecordsPrivacyPage"));
const PatientNotifications = lazy(() => import("./pages/patient/NotificationsPage"));
const PatientMyProfile     = lazy(() => import("./pages/patient/MyProfilePage"));
const PatientCorrectionRequests = lazy(() => import("./pages/patient/CorrectionRequestsPage"));
const PatientEmergencyQR = lazy(() => import("./pages/patient/EmergencyQRPage"));

// ── Protected route wrapper ───────────────────────────────────────────────────
function ProtectedRoute({ children, roles = [] }) {
  const { user, isLoading } = useAuth();
  const location = useLocation();

  if (isLoading) return <PageLoader />;
  if (!user) return <Navigate to={ROUTES.LOGIN} replace />;
  if (roles.length > 0 && !roleAllowed(user, roles, location.pathname)) {
    return <Navigate to={getDefaultRoute(user)} replace />;
  }
  // key=pathname resets the boundary's error state on navigation — without
  return <ErrorBoundary key={location.pathname}>{children}</ErrorBoundary>;
}

/** True if `user` is allowed onto a route guarded by `roles`. Handles */
function roleAllowed(user, roles, pathname) {
  if (roles.includes(user.role)) return true;
  if (moduleAllows(user, roles, pathname)) return true;
  if (user.role !== "custom") return false;
  return (user.acts_as || []).some(r => roles.includes(r));
}

/** Redirect authenticated user to their role's default page. For a */
function getDefaultRoute(user) {
  const map = {
    [ROLES.PLATFORM_ADMIN]:  ROUTES.PLATFORM.DASHBOARD,
    [ROLES.HOSPITAL_ADMIN]:  ROUTES.ADMIN.DASHBOARD,
    [ROLES.DOCTOR]:          ROUTES.DOCTOR.DASHBOARD,
    [ROLES.NURSE]:           ROUTES.NURSE.DASHBOARD,
    [ROLES.FRONT_DESK]:      ROUTES.FRONT_DESK.DASHBOARD,
    [ROLES.PATIENT]:         ROUTES.PATIENT.DASHBOARD,
  };
  if (user.role === "custom") {
    const primary = ACTS_AS_PRIORITY.find(r => (user.acts_as || []).includes(r));
    return primary ? map[primary] : ROUTES.LOGIN;
  }
  return map[user.role] || ROUTES.LOGIN;
}

/** Wraps only the patient-portal page tree in PatientProvider — the shared */
function PatientRoute({ children }) {
  return (
    <ProtectedRoute roles={[ROLES.PATIENT]}>
      <PatientProvider>{children}</PatientProvider>
    </ProtectedRoute>
  );
}

function PageLoader() {
  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100vh" }}>
      <div style={{ color: "var(--color-primary)", fontSize: "14px" }}>Loading…</div>
    </div>
  );
}

// ── Root redirect: send authenticated users to their portal ──────────────────
function RootRedirect() {
  const { user, isLoading } = useAuth();
  if (isLoading) return <PageLoader />;
  if (!user) return <Navigate to={ROUTES.LOGIN} replace />;
  return <Navigate to={getDefaultRoute(user)} replace />;
}

// ── App ───────────────────────────────────────────────────────────────────────
export default function App() {
  return (
    <ErrorBoundary>
    <BrowserRouter>
      <Suspense fallback={<PageLoader />}>
        <Routes>
          {/* Root → role-based redirect */}
          <Route path="/" element={<RootRedirect />} />

          {/* Public */}
          <Route path={ROUTES.LOGIN}          element={<LoginPage />} />
          <Route path={ROUTES.SETUP_PASSWORD} element={<SetupPasswordPage />} />
          <Route path={ROUTES.FORGOT_PASSWORD_STAFF}   element={<StaffForgotPasswordPage />} />
          <Route path={ROUTES.FORGOT_PASSWORD_PATIENT} element={<PatientForgotPasswordPage />} />
          <Route path={ROUTES.EMERGENCY_VIEW(":token")} element={<EmergencyViewPage />} />
          <Route path={ROUTES.VIEW_REPORT(":token")} element={<ViewReportPage />} />
          <Route path={ROUTES.CONSULT_PAD(":token")} element={<ConsultPadPage />} />
          <Route path={ROUTES.SHARE_RECORDS_ENTRY} element={<ShareRecordsPage />} />
          <Route path={ROUTES.SHARE_RECORDS_ENTRY_ALT} element={<ShareRecordsPage />} />
          <Route path={ROUTES.SHARE_RECORDS} element={<ShareRecordsPage />} />
          <Route path={ROUTES.SHARE_RECORDS_TOKEN(":token")} element={<ShareRecordsPage />} />
          <Route path="/change-password"      element={<ProtectedRoute><ChangePasswordPage /></ProtectedRoute>} />

          {/* Platform Admin */}
          <Route path={ROUTES.PLATFORM.DASHBOARD}
            element={<ProtectedRoute roles={[ROLES.PLATFORM_ADMIN]}><PlatformDashboard /></ProtectedRoute>} />
          <Route path={ROUTES.PLATFORM.HOSPITALS}
            element={<ProtectedRoute roles={[ROLES.PLATFORM_ADMIN]}><PlatformHospitals /></ProtectedRoute>} />
          <Route path={ROUTES.PLATFORM.HOSPITAL(":id")}
            element={<ProtectedRoute roles={[ROLES.PLATFORM_ADMIN]}><PlatformHospitalDetail /></ProtectedRoute>} />
          <Route path={ROUTES.PLATFORM.SUBSCRIPTIONS}
            element={<ProtectedRoute roles={[ROLES.PLATFORM_ADMIN]}><PlatformSubscriptions /></ProtectedRoute>} />
          <Route path={ROUTES.PLATFORM.USERS}
            element={<ProtectedRoute roles={[ROLES.PLATFORM_ADMIN]}><PlatformUsers /></ProtectedRoute>} />
          <Route path={ROUTES.PLATFORM.VACCINATION_TEMPLATES}
            element={<ProtectedRoute roles={[ROLES.PLATFORM_ADMIN]}><PlatformVaccinationTemplates /></ProtectedRoute>} />
          <Route path={ROUTES.PLATFORM.CLASSIFICATION_RULES}
            element={<ProtectedRoute roles={[ROLES.PLATFORM_ADMIN]}><PlatformClassificationRules /></ProtectedRoute>} />

          {/* Hospital Admin */}
          <Route path={ROUTES.ADMIN.DASHBOARD}
            element={<ProtectedRoute roles={[ROLES.HOSPITAL_ADMIN]}><AdminDashboard /></ProtectedRoute>} />
          <Route path={ROUTES.ADMIN.STAFF}
            element={<ProtectedRoute roles={[ROLES.HOSPITAL_ADMIN]}><AdminStaff /></ProtectedRoute>} />
          <Route path={ROUTES.ADMIN.BRANCHES}
            element={<ProtectedRoute roles={[ROLES.HOSPITAL_ADMIN]}><AdminBranches /></ProtectedRoute>} />
          <Route path={ROUTES.ADMIN.ROOMS}
            element={<ProtectedRoute roles={[ROLES.HOSPITAL_ADMIN]}><AdminRooms /></ProtectedRoute>} />
          <Route path={ROUTES.ADMIN.SERVICES}
            element={<ProtectedRoute roles={[ROLES.HOSPITAL_ADMIN]}><AdminBillingSetup /></ProtectedRoute>} />
          <Route path={ROUTES.ADMIN.BILLING_REPORTS}
            element={<ProtectedRoute roles={[ROLES.HOSPITAL_ADMIN]}><AdminBillingReports /></ProtectedRoute>} />
          <Route path={ROUTES.ADMIN.COMPLIANCE}
            element={<ProtectedRoute roles={[ROLES.HOSPITAL_ADMIN]}><AdminCompliance /></ProtectedRoute>} />
          <Route path={ROUTES.ADMIN.ROLES}
            element={<ProtectedRoute roles={[ROLES.HOSPITAL_ADMIN]}><AdminRoles /></ProtectedRoute>} />
          <Route path={ROUTES.ADMIN.VACCINATION_SCHEDULE}
            element={<ProtectedRoute roles={[ROLES.HOSPITAL_ADMIN]}><AdminVaccinationSchedule /></ProtectedRoute>} />
          <Route path={ROUTES.ADMIN.SETTINGS}
            element={<ProtectedRoute roles={[ROLES.HOSPITAL_ADMIN]}><AdminSettings /></ProtectedRoute>} />
          <Route path={ROUTES.ADMIN.MY_PROFILE}
            element={<ProtectedRoute roles={[ROLES.HOSPITAL_ADMIN]}><SharedMyProfile /></ProtectedRoute>} />

          {/* Doctor */}
          <Route path={ROUTES.DOCTOR.DASHBOARD}
            element={<ProtectedRoute roles={[ROLES.DOCTOR]}><DoctorDashboard /></ProtectedRoute>} />
          <Route path={ROUTES.DOCTOR.QUEUE}
            element={<ProtectedRoute roles={[ROLES.DOCTOR]}><DoctorQueue /></ProtectedRoute>} />
          <Route path="/doctor/encounter/:id"
            element={<ProtectedRoute roles={[ROLES.DOCTOR]}><DoctorEncounter /></ProtectedRoute>} />
          <Route path={ROUTES.DOCTOR.PATIENTS}
            element={<ProtectedRoute roles={[ROLES.DOCTOR]}><DoctorPatients /></ProtectedRoute>} />
          <Route path={ROUTES.DOCTOR.HISTORY}
            element={<ProtectedRoute roles={[ROLES.DOCTOR]}><DoctorHistory /></ProtectedRoute>} />
          <Route path={ROUTES.DOCTOR.MY_PROFILE}
            element={<ProtectedRoute roles={[ROLES.DOCTOR]}><DoctorMyProfile /></ProtectedRoute>} />

          {/* Nurse */}
          <Route path={ROUTES.NURSE.DASHBOARD}
            element={<ProtectedRoute roles={[ROLES.NURSE]}><NurseDashboard /></ProtectedRoute>} />
          <Route path={ROUTES.NURSE.VITALS}
            element={<ProtectedRoute roles={[ROLES.NURSE]}><NurseVitals /></ProtectedRoute>} />
          <Route path={ROUTES.NURSE.TASKS}
            element={<ProtectedRoute roles={[ROLES.NURSE]}><NurseTasks /></ProtectedRoute>} />
          <Route path={ROUTES.NURSE.HISTORY}
            element={<ProtectedRoute roles={[ROLES.NURSE]}><NurseHistory /></ProtectedRoute>} />
          <Route path={ROUTES.NURSE.MY_PROFILE}
            element={<ProtectedRoute roles={[ROLES.NURSE]}><SharedMyProfile /></ProtectedRoute>} />

          {/* Front Desk — also accessible to hospital admin for oversight */}
          <Route path={ROUTES.FRONT_DESK.DASHBOARD}
            element={<ProtectedRoute roles={[ROLES.FRONT_DESK, ROLES.HOSPITAL_ADMIN]}><FrontDeskDashboard /></ProtectedRoute>} />
          {/* Kept mounted for backward compatibility / deep links — no longer */}
          <Route path={ROUTES.FRONT_DESK.TRIAGE}
            element={<ProtectedRoute roles={[ROLES.FRONT_DESK, ROLES.HOSPITAL_ADMIN]}><FrontDeskTriage /></ProtectedRoute>} />
          <Route path={ROUTES.FRONT_DESK.REGISTER_PATIENT}
            element={<ProtectedRoute roles={[ROLES.FRONT_DESK, ROLES.HOSPITAL_ADMIN]}><FrontDeskRegisterPatient /></ProtectedRoute>} />
          <Route path={ROUTES.FRONT_DESK.PATIENTS}
            element={<ProtectedRoute roles={[ROLES.FRONT_DESK, ROLES.HOSPITAL_ADMIN]}><FrontDeskPatients /></ProtectedRoute>} />
          <Route path={ROUTES.FRONT_DESK.APPOINTMENTS}
            element={<ProtectedRoute roles={[ROLES.FRONT_DESK, ROLES.HOSPITAL_ADMIN]}><FrontDeskAppointments /></ProtectedRoute>} />
          <Route path={ROUTES.FRONT_DESK.QUEUE}
            element={<ProtectedRoute roles={[ROLES.FRONT_DESK, ROLES.HOSPITAL_ADMIN]}><FrontDeskQueue /></ProtectedRoute>} />
          <Route path={ROUTES.FRONT_DESK.BILLING}
            element={<ProtectedRoute roles={[ROLES.FRONT_DESK, ROLES.HOSPITAL_ADMIN]}><FrontDeskBilling /></ProtectedRoute>} />
          <Route path={ROUTES.FRONT_DESK.HISTORY}
            element={<ProtectedRoute roles={[ROLES.FRONT_DESK, ROLES.HOSPITAL_ADMIN]}><FrontDeskHistory /></ProtectedRoute>} />
          <Route path={ROUTES.FRONT_DESK.MY_PROFILE}
            element={<ProtectedRoute roles={[ROLES.FRONT_DESK, ROLES.HOSPITAL_ADMIN]}><SharedMyProfile /></ProtectedRoute>} />

          {/* Patient Portal — wrapped in PatientProvider so "which family */}
          <Route path={ROUTES.PATIENT.DASHBOARD}
            element={<PatientRoute><PatientDashboard /></PatientRoute>} />
          <Route path={ROUTES.PATIENT.APPOINTMENTS}
            element={<PatientRoute><PatientAppointments /></PatientRoute>} />
          <Route path={ROUTES.PATIENT.HOSPITALS}
            element={<PatientRoute><PatientHospitals /></PatientRoute>} />
          <Route path="/patient/hospitals/:hospitalId/doctors"
            element={<PatientRoute><PatientHospitalDoctors /></PatientRoute>} />
          <Route path="/patient/hospitals/:hospitalId/doctors/:doctorId"
            element={<PatientRoute><PatientDoctorProfile /></PatientRoute>} />
          <Route path={ROUTES.PATIENT.RECORDS}
            element={<PatientRoute><PatientRecords /></PatientRoute>} />
          <Route path={ROUTES.PATIENT.PRESCRIPTIONS}
            element={<PatientRoute><PatientPrescriptions /></PatientRoute>} />
          <Route path={ROUTES.PATIENT.MY_REPORTS}
            element={<PatientRoute><PatientMyReports /></PatientRoute>} />
          <Route path={ROUTES.PATIENT.SHARED_RECORDS_PRIVACY}
            element={<PatientRoute><PatientSharedRecordsPrivacy /></PatientRoute>} />
          <Route path={ROUTES.PATIENT.NOTIFICATIONS}
            element={<PatientRoute><PatientNotifications /></PatientRoute>} />
          <Route path={ROUTES.PATIENT.MY_PROFILE}
            element={<PatientRoute><PatientMyProfile /></PatientRoute>} />
          <Route path={ROUTES.PATIENT.CORRECTION_REQUESTS}
            element={<PatientRoute><PatientCorrectionRequests /></PatientRoute>} />
          <Route path={ROUTES.PATIENT.EMERGENCY_QR}
            element={<PatientRoute><PatientEmergencyQR /></PatientRoute>} />

          {/* Catch-all */}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </BrowserRouter>
    </ErrorBoundary>
  );
}
