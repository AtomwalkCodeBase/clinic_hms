/**
 * App.jsx
 * -------
 * Top-level router. All route paths come from ROUTES constants —
 * never hardcoded strings.
 *
 * Route protection:
 *   <ProtectedRoute roles={[...]}> — redirects to /login if not authenticated
 *                                    or if the user's role is not in the list.
 *
 * Layout wrappers (to be created in components/layout/):
 *   <AppShell> — sidebar + topbar wrapper for authenticated pages
 */

import { BrowserRouter, Routes, Route, Navigate, useLocation } from "react-router-dom";
import { useAuth } from "./hooks/useAuth";
import { ROUTES }  from "./config/routes.config";
import { ROLES }   from "./constants/roles";
import { ErrorBoundary } from "./components/common/ErrorBoundary";
import { PatientProvider } from "./context/PatientContext";

// ── Lazy-loaded pages ─────────────────────────────────────────────────────────
// Each role has its own folder; import pages here as they are built.
import { lazy, Suspense } from "react";

const LoginPage         = lazy(() => import("./pages/auth/LoginPage"));
const SetupPasswordPage = lazy(() => import("./pages/auth/SetupPasswordPage"));
const ChangePasswordPage = lazy(() => import("./pages/auth/ChangePasswordPage"));
const ForgotPasswordPage = lazy(() => import("./pages/auth/ForgotPasswordPage"));

// Platform Admin
const PlatformDashboard  = lazy(() => import("./pages/platform-admin/DashboardPage"));
const PlatformHospitals  = lazy(() => import("./pages/platform-admin/HospitalsPage"));
const PlatformHospitalDetail = lazy(() => import("./pages/platform-admin/HospitalDetailPage"));
const PlatformSubscriptions = lazy(() => import("./pages/platform-admin/SubscriptionsPage"));
const PlatformUsers      = lazy(() => import("./pages/platform-admin/UsersPage"));
const PlatformVaccinationTemplates = lazy(() => import("./pages/platform-admin/VaccinationTemplatesPage"));

// Hospital Admin
const AdminDashboard = lazy(() => import("./pages/hospital-admin/DashboardPage"));
const AdminStaff     = lazy(() => import("./pages/hospital-admin/StaffPage"));
const AdminBranches  = lazy(() => import("./pages/hospital-admin/BranchesPage"));
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
const FrontDeskRegisterPatient= lazy(() => import("./pages/front-desk/RegisterPatientPage"));
const FrontDeskAppointments   = lazy(() => import("./pages/front-desk/AppointmentsPage"));
const FrontDeskQueue          = lazy(() => import("./pages/front-desk/QueuePage"));
const FrontDeskBilling        = lazy(() => import("./pages/front-desk/BillingPage"));
const FrontDeskHistory        = lazy(() => import("./pages/front-desk/HistoryPage"));

// Lab
const LabDashboard = lazy(() => import("./pages/lab/DashboardPage"));
const LabRequests  = lazy(() => import("./pages/lab/RequestsPage"));
const LabReports   = lazy(() => import("./pages/lab/ReportsPage"));
const LabCatalog   = lazy(() => import("./pages/lab/CatalogPage"));

// Pharmacist
const PharmacistDashboard     = lazy(() => import("./pages/pharmacist/DashboardPage"));
const PharmacistPrescriptions = lazy(() => import("./pages/pharmacist/PrescriptionsPage"));
const PharmacistStock         = lazy(() => import("./pages/pharmacist/StockPage"));
const PharmacistCatalog       = lazy(() => import("./pages/pharmacist/CatalogPage"));

// Shared — generic self-service "My Profile" (photo upload) for any
// non-doctor staff role. Doctor has its own richer version.
const SharedMyProfile = lazy(() => import("./pages/shared/MyProfilePage"));

// Patient
const PatientDashboard     = lazy(() => import("./pages/patient/DashboardPage"));
const PatientAppointments  = lazy(() => import("./pages/patient/AppointmentsPage"));
const PatientHospitals       = lazy(() => import("./pages/patient/HospitalsPage"));
const PatientHospitalDoctors = lazy(() => import("./pages/patient/HospitalDoctorsPage"));
const PatientDoctorProfile   = lazy(() => import("./pages/patient/DoctorProfilePage"));
const PatientRecords       = lazy(() => import("./pages/patient/RecordsPage"));
const PatientPrescriptions = lazy(() => import("./pages/patient/PrescriptionsPage"));
const PatientLabReports    = lazy(() => import("./pages/patient/LabReportsPage"));
const PatientMyProfile     = lazy(() => import("./pages/patient/MyProfilePage"));

// ── Protected route wrapper ───────────────────────────────────────────────────
function ProtectedRoute({ children, roles = [] }) {
  const { user, isLoading } = useAuth();
  const location = useLocation();

  if (isLoading) return <PageLoader />;
  if (!user) return <Navigate to={ROUTES.LOGIN} replace />;
  if (roles.length > 0 && !roles.includes(user.role)) {
    return <Navigate to={getDefaultRoute(user.role)} replace />;
  }
  // key=pathname resets the boundary's error state on navigation — without
  // it, clicking to a different page after a crash would keep showing the
  // old page's fallback instead of actually trying to render the new one.
  return <ErrorBoundary key={location.pathname}>{children}</ErrorBoundary>;
}

/** Redirect authenticated user to their role's default page. */
function getDefaultRoute(role) {
  const map = {
    [ROLES.PLATFORM_ADMIN]:  ROUTES.PLATFORM.DASHBOARD,
    [ROLES.HOSPITAL_ADMIN]:  ROUTES.ADMIN.DASHBOARD,
    [ROLES.DOCTOR]:          ROUTES.DOCTOR.DASHBOARD,
    [ROLES.NURSE]:           ROUTES.NURSE.DASHBOARD,
    [ROLES.FRONT_DESK]:      ROUTES.FRONT_DESK.DASHBOARD,
    [ROLES.LAB_TECH]:        ROUTES.LAB.DASHBOARD,
    [ROLES.PHARMACIST]:      ROUTES.PHARMACIST.DASHBOARD,
    [ROLES.PATIENT]:         ROUTES.PATIENT.DASHBOARD,
  };
  return map[role] || ROUTES.LOGIN;
}

/** Wraps only the patient-portal page tree in PatientProvider — the shared
 *  "which family member am I viewing" context. Kept as a small per-route
 *  wrapper (rather than a single nested <Route> parent) so the existing flat
 *  <Route path={ROUTES.PATIENT.X}> declarations below don't need to be
 *  restructured into relative nested paths, and no other role's routes are
 *  touched. */
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
  return <Navigate to={getDefaultRoute(user.role)} replace />;
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
          <Route path={ROUTES.FORGOT_PASSWORD} element={<ForgotPasswordPage />} />
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

          {/* Hospital Admin */}
          <Route path={ROUTES.ADMIN.DASHBOARD}
            element={<ProtectedRoute roles={[ROLES.HOSPITAL_ADMIN]}><AdminDashboard /></ProtectedRoute>} />
          <Route path={ROUTES.ADMIN.STAFF}
            element={<ProtectedRoute roles={[ROLES.HOSPITAL_ADMIN]}><AdminStaff /></ProtectedRoute>} />
          <Route path={ROUTES.ADMIN.BRANCHES}
            element={<ProtectedRoute roles={[ROLES.HOSPITAL_ADMIN]}><AdminBranches /></ProtectedRoute>} />
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
          <Route path={ROUTES.FRONT_DESK.REGISTER_PATIENT}
            element={<ProtectedRoute roles={[ROLES.FRONT_DESK, ROLES.HOSPITAL_ADMIN]}><FrontDeskRegisterPatient /></ProtectedRoute>} />
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

          {/* Lab — also accessible to hospital admin */}
          <Route path={ROUTES.LAB.DASHBOARD}
            element={<ProtectedRoute roles={[ROLES.LAB_TECH, ROLES.HOSPITAL_ADMIN]}><LabDashboard /></ProtectedRoute>} />
          <Route path={ROUTES.LAB.REQUESTS}
            element={<ProtectedRoute roles={[ROLES.LAB_TECH, ROLES.HOSPITAL_ADMIN]}><LabRequests /></ProtectedRoute>} />
          <Route path={ROUTES.LAB.REPORTS}
            element={<ProtectedRoute roles={[ROLES.LAB_TECH, ROLES.HOSPITAL_ADMIN]}><LabReports /></ProtectedRoute>} />
          <Route path={ROUTES.LAB.CATALOG}
            element={<ProtectedRoute roles={[ROLES.LAB_TECH, ROLES.HOSPITAL_ADMIN]}><LabCatalog /></ProtectedRoute>} />
          <Route path={ROUTES.LAB.MY_PROFILE}
            element={<ProtectedRoute roles={[ROLES.LAB_TECH, ROLES.HOSPITAL_ADMIN]}><SharedMyProfile /></ProtectedRoute>} />

          {/* Pharmacist — also accessible to hospital admin */}
          <Route path={ROUTES.PHARMACIST.DASHBOARD}
            element={<ProtectedRoute roles={[ROLES.PHARMACIST, ROLES.HOSPITAL_ADMIN]}><PharmacistDashboard /></ProtectedRoute>} />
          <Route path={ROUTES.PHARMACIST.PRESCRIPTIONS}
            element={<ProtectedRoute roles={[ROLES.PHARMACIST, ROLES.HOSPITAL_ADMIN]}><PharmacistPrescriptions /></ProtectedRoute>} />
          <Route path={ROUTES.PHARMACIST.STOCK}
            element={<ProtectedRoute roles={[ROLES.PHARMACIST, ROLES.HOSPITAL_ADMIN]}><PharmacistStock /></ProtectedRoute>} />
          <Route path={ROUTES.PHARMACIST.CATALOG}
            element={<ProtectedRoute roles={[ROLES.PHARMACIST, ROLES.HOSPITAL_ADMIN]}><PharmacistCatalog /></ProtectedRoute>} />
          <Route path={ROUTES.PHARMACIST.MY_PROFILE}
            element={<ProtectedRoute roles={[ROLES.PHARMACIST, ROLES.HOSPITAL_ADMIN]}><SharedMyProfile /></ProtectedRoute>} />

          {/* Patient Portal — wrapped in PatientProvider so "which family
              member am I viewing" is shared across every page below. */}
          <Route path={ROUTES.PATIENT.DASHBOARD}
            element={<PatientRoute><PatientDashboard /></PatientRoute>} />
          <Route path={ROUTES.PATIENT.APPOINTMENTS}
            element={<PatientRoute><PatientAppointments /></PatientRoute>} />
          <Route path={ROUTES.PATIENT.HOSPITALS}
            element={<PatientRoute><PatientHospitals /></PatientRoute>} />
          <Route path="/patient/hospitals/:tenantId/doctors"
            element={<PatientRoute><PatientHospitalDoctors /></PatientRoute>} />
          <Route path="/patient/hospitals/:tenantId/doctors/:doctorId"
            element={<PatientRoute><PatientDoctorProfile /></PatientRoute>} />
          <Route path={ROUTES.PATIENT.RECORDS}
            element={<PatientRoute><PatientRecords /></PatientRoute>} />
          <Route path={ROUTES.PATIENT.PRESCRIPTIONS}
            element={<PatientRoute><PatientPrescriptions /></PatientRoute>} />
          <Route path={ROUTES.PATIENT.LAB_REPORTS}
            element={<PatientRoute><PatientLabReports /></PatientRoute>} />
          <Route path={ROUTES.PATIENT.MY_PROFILE}
            element={<PatientRoute><PatientMyProfile /></PatientRoute>} />

          {/* Catch-all */}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </BrowserRouter>
    </ErrorBoundary>
  );
}
