# Atomwalk HMS — Application Knowledge Map

Prepared from direct inspection of the codebase at `D:\hospital_management_system` (Django REST backend + React/Vite frontend) and the handover documents in that same folder (`README.md`, `EMPLOYEE_LOGIN_CODES.md`, `INVESTOR_DEMO_CREDENTIALS.md`, `Clinical_HMS_External_System_Comparison.docx`, `IPD_Admission_Feature_Documentation.docx` + `_v2`, `HMS_OPD_IPD_HowItConnects_updated_v2.pptx`, `IPD_Full_Cycle.pptx`).

**Labeling convention used throughout:** ✅ FACT (verified directly in code, migrations, or a document), ⚠️ ASSUMPTION (reasonable inference, not directly confirmed), ❓ UNKNOWN (not enough information in what was provided).

**The single most important fact to internalize before anything else:** the codebase implements an **OPD-only** (outpatient) hospital management system. There is **no admission, ward, bed, ICU, OT, or nursing-inpatient module anywhere in the code**. Three of the six handover documents (`IPD_Admission_Feature_Documentation*.docx`, `IPD_Full_Cycle.pptx`, and half of `HMS_OPD_IPD_HowItConnects_updated_v2.pptx`) describe an IPD (in-patient department) system in detail — this is **planning/specification material for a feature that does not exist yet**, not documentation of something built. See §17 "Contradictions" for why this matters and how easy it is to get confused by the pptx in particular.

---

## APPLICATION AT A GLANCE

Atomwalk HMS is a multi-tenant (one Postgres database per hospital) SaaS platform for running a hospital's or clinic's **outpatient** operations end-to-end: a patient registers, books an appointment with a doctor, checks in, gets vitals taken by a nurse, sees the doctor (structured consultation notes + diagnosis + prescription + lab orders), gets billed, and can pick up their medicine from the hospital's own pharmacy or take a prescription elsewhere. A parallel **patient portal** lets patients (across every participating hospital, via one login) book appointments, view their prescriptions/lab reports/invoices, manage a family, track a child's growth/vaccination schedule, and generate an "Emergency QR" that any doctor can scan to see critical medical facts without the patient needing an account there. A **platform-admin** layer (run by Atomwalk itself, not any hospital) onboards new hospitals, manages their subscription tier and feature flags, and can see cross-tenant statistics. Staff log in with one of six fixed roles (hospital admin, doctor, nurse, front desk, lab technician, pharmacist) or a hospital-defined custom role. The system is Indian-healthcare-specific in places: DPDP Act 2023 consent tracking, a cross-hospital "Health Information Exchange" (HIE) that shares sanitized clinical facts between hospitals a patient has visited, NMC doctor registration numbers, and Rupee-denominated billing. It is built as Django REST Framework + PostgreSQL on the backend and React (Vite) on the frontend, with no native mobile app. An IPD (admission/ward/bed/OT/ICU) module is fully specified in handover documents but **not implemented** — everything described below as "built" or "live" refers only to the OPD + portal + platform-admin system that actually exists in the repository today.

---

## 1. APPLICATION OVERVIEW

**What is this application?** ✅ A multi-tenant hospital/clinic management system ("Atomwalk HMS" / "Atomwalk Clinical HMS" per the codebase's own naming in `atomwalk/settings/base.py` and the handover pptx decks) covering outpatient registration, scheduling, consultation, prescribing, lab ordering, pharmacy dispensing, and billing, plus a cross-hospital patient portal and a platform-admin console for onboarding hospitals. ❓ Note: this is a distinct codebase from "Atomwalk360" (a laboratory management system product) if that name is encountered elsewhere — the two should not be assumed to be the same product without confirming with the team.

**What problem does it solve?** ✅ Replaces paper/spreadsheet-based OPD operations at small-to-mid-size Indian hospitals and clinics with a structured digital workflow, while giving Atomwalk (the vendor) a single SaaS platform it can sell to many hospitals from one codebase, and giving patients one login that follows them across every hospital on the platform.

**Who uses it?** ✅ Hospital staff (hospital admin, doctor, nurse, front desk, lab technician, pharmacist, and hospital-defined custom roles), patients (via a self-service portal), and Atomwalk's own platform administrators.

**Main user types/roles:** ✅ `hospital_admin`, `doctor`, `nurse`, `front_desk`, `lab_tech`, `pharmacist`, `custom` (a hospital-defined bundle of the above), `patient`, and `platform_admin` — these are the literal values of `StaffUser.role` / the JWT `role` claim (`apps/org/models.py`, `core/permissions.py`).

**Overall purpose:** ✅ Digitize and standardize the OPD patient journey from registration to billing, across many independently-run hospitals, on one shared codebase with hard data isolation between hospitals (separate Postgres database per tenant) but a shared, opt-in layer for patient identity and clinical history that follows the patient between hospitals.

**Major business workflows (built today):** ✅ Patient registration (front-desk or self-service) → appointment booking → check-in/queue → vitals → doctor consultation (SOAP-style encounter) → prescription and/or lab order → pharmacy dispensing and/or lab processing → billing/invoicing/payment. Supporting workflows: staff onboarding (invite + self-service password setup), hospital onboarding (platform admin creates a Tenant + Subscription + dedicated database), patient portal self-service (booking, records, family accounts, vaccination roadmap, Emergency QR), and DPDP/HIE consent capture.

**Major modules/features (built today):** ✅ Registration/Patient Identity, Appointments/Queue, Vitals, OPD Encounters (EMR), Prescriptions, Lab, Pharmacy, Billing, Organization/Staff/RBAC, Compliance (DPDP), Notifications (partially wired), Patient Portal, Platform Admin/Multi-Tenancy, Emergency QR, Vaccination tracking.

**Major modules described in specs but NOT built:** ✅ IPD Admission, Bed/Ward Allocation, Inpatient Nursing, Doctor Rounds/eMAR, Investigations & OT/Surgery, Transfers/ICU Escalation, Discharge Planning.

---

## 2. COMPLETE MODULE LIST

Each module below is a Django "app" (`apps/<name>/`) unless noted otherwise. Status is called out explicitly because several apps are **retired/dead code kept only so old migrations remain resolvable** — this is unusual and important for a new developer to know before spending time reading them.

### 2.1 `auth_app` — Authentication
- **Purpose:** Login, logout, token refresh, password setup/change, OTP request/verify, forgot-password, "who am I" (`/me/`), permissions lookup.
- **Who uses it:** Everyone (staff, patients, platform admins) — it's the front door.
- **Main features:** Three separate login endpoints (`login/staff/`, `login/platform/`, `login/patient/` + `login/patient/otp/`), custom PyJWT tokens (not SimpleJWT's own view), OTP flows for patient login/registration/password reset (SMS or email), staff invite → self-service password setup, logout via a token-blacklist table.
- **Inputs:** Mobile/employee-ID/email + password, or mobile/email + OTP.
- **Outputs:** A signed JWT access + refresh token pair carrying `role`, `tenant_id`, `db_name`, `license_tier`, `is_platform`, `acts_as`, `branch_id`.
- **Dependencies:** `apps.org.StaffUser` (tenant DB), `apps.registry.PatientAccount`/`StaffMobileIndex`/`OTPCode`/`BlacklistedToken` (registry DB), `core.otp`, `core.sms`, `core.email`.
- **Business rules:** ✅ Staff can log in by mobile number OR (hospital-code + employee ID) OR email — resolved via `StaffMobileIndex` in the registry DB so the login form never needs a subdomain. ✅ A deactivated staff account is blocked at next login **and** an already-issued token is invalidated on the very next request (live `is_active` re-check in `core/authentication.py`), not just at next login. ✅ OTP codes are 6-digit, `secrets`-generated, SHA-256+pepper hashed, max 5 verify attempts, 60s resend cooldown, 10-minute TTL. ✅ No models file — this app has no models of its own; it operates on `org.StaffUser` and `registry.PatientAccount`/`OTPCode`.
- **Unclear areas:** ❓ Rate-limit tuning (`login`: 10/min, `otp`: 6/min) — whether these have been validated against real usage patterns is not stated anywhere.

### 2.2 `org` — Organization / Staff / RBAC
- **Purpose:** Branches, departments, staff records, doctor/staff profiles, role-based access control, doctor working hours, rooms and room assignments, tenant-level settings, vaccination-schedule configuration (per-hospital).
- **Who uses it:** Hospital admin (manages staff/branches/rooms/roles), every staff role (self-service profile), any staff (read doctor list).
- **Main features:** Staff invite + resend, doctor/non-doctor profile split, `Role`/`Permission`/`RolePermission`/`UserRole` table-driven RBAC (enterprise-tier only, `feat_custom_roles`), `NurseDoctorAssignment` (which nurse sees which doctor's patients), `StaffBranchMapping` (multi-branch doctors), `DoctorSchedule`/`DoctorAvailabilitySlot` (weekly working hours → booking slots), `Room`/`RoomAssignment` (which doctor sits where and when, auto-resolved onto appointments), per-hospital `VaccinationSchedule`/`VaccinationScheduleRule`.
- **Inputs:** Staff invite details, branch/department/room definitions, doctor working-hours config, role/permission assignments.
- **Outputs:** `StaffUser` records, JWT `role`/`acts_as`/`branch_id` claims, doctor availability used by the booking engine.
- **Dependencies:** Used by nearly every other tenant app (they all import `StaffUser`/`Branch`).
- **Business rules:** ✅ Two parallel RBAC systems exist: the **live, hardcoded** `Is*` DRF permission classes (`core/permissions.py`) checked on every request, and a **fully-built but largely unused** table-driven `Role`/`Permission` system (only matters for `feat_custom_roles` tenants). ✅ `role="custom"` staff are treated as whichever of the 6 system roles appear in their `acts_as` JSON list (set once at login, baked into the JWT — a role change takes effect on next login, not instantly). ✅ A `StaffUser.custom_role` is `on_delete=PROTECT` (can't delete a Role still assigned as someone's primary role) but `UserRole` (extra roles) is `CASCADE`. ✅ At most one "primary" branch per staff member enforced by a partial unique constraint. ✅ Deleting/deactivating a doctor's `custom_role` never silently strips their base permissions because system roles don't depend on it.
- **Unclear areas:** ❓ Exactly how much of the product currently exercises the table-driven RBAC vs. the hardcoded `Is*` checks in practice (the comparison document explicitly calls the table-driven system "fully-modeled but entirely unused").

### 2.3 `patients` — Patient Records (per-tenant)
- **Purpose:** The hospital-local patient record (`Patient`), allergies, growth/vaccination tracking, and the entire **patient portal** (a separate, large surface: `portal_views.py`, `portal_urls.py`) plus the public **Emergency QR** endpoint (`emergency_views.py`, `emergency_urls.py`).
- **Who uses it:** Front desk (registration), doctors/nurses (history, allergies), patients themselves (portal — the biggest single consumer), anyone with an Emergency QR link (no login).
- **Main features:** Front-desk registration with DPDP + HIE consent capture, dependent/guardian patient linking, patient search/lookup, cross-tenant "family tree" via `PatientRelationship`, allergy list (also mirrored to the registry DB), child growth charts, vaccination roadmap (with doctor-ordered/declined states, self-reported-with-verification states), Emergency QR generation with signed short-lived tokens and consent logging, and the full patient-portal feature set (hospital/doctor discovery, booking, rescheduling, records, documents, lab orders, prescriptions, invoices, family accounts, notifications).
- **Inputs:** Registration form data, consent flags, uploaded documents/vaccination certificates.
- **Outputs:** `Patient` rows, `Allergy` rows, mirrored `registry.Shared*` rows, `ConsentRecord` rows, `PortalBooking` rows.
- **Dependencies:** `org.Branch`, `registry.PatientIdentity`/`PatientAccount`/`Shared*` tables, `opd` (appointments/encounters the portal reads), `lab`/`billing`/`prescriptions` (portal reads across all of these).
- **Business rules:** ✅ A `Patient.awpid` links to the cross-tenant `PatientIdentity` but there's **no DB foreign key** between tenant DBs and the registry DB — enforced only by convention/application code (see §7 for why). ✅ Dependents (children, anyone without their own mobile) never get a `mobile_hash`; they're deduplicated via `guardian_mobile_hash` + `PatientRelationship` instead. ✅ HIE consent (`hie_consent_given`) is separate from DPDP processing consent (`dpdp_consent_captured`) — one lets a hospital process the patient's data at all, the other lets it *see other hospitals'* data about the same patient.
- **Unclear areas:** ❓ Whether front-desk walk-in registration captures HIE/DPDP consent as rigorously as the portal flow — a code comment in `Patient` explicitly flags this as "out of scope here" for front-desk registration.

### 2.4 `opd` — Outpatient Visit Flow (the clinical core)
- **Purpose:** Appointment booking + queue, vitals capture, the SOAP-style consultation ("encounter"), prescriptions, drug-favourite templates. This is the busiest, most central app in the system.
- **Who uses it:** Front desk (booking/queue), nurse (vitals, monitoring), doctor (encounter, prescription), patient portal (booking, reading their own history).
- **Main features:** `Appointment` with a **server-enforced status state machine** (see §9), room/floor auto-resolution from `org.RoomAssignment`, `Vitals` with auto-computed BMI, `OPDEncounter` (SOAP notes + ICD-10 diagnoses as JSON + investigations + referral + AI-transcription placeholder fields), `Prescription`/`PrescriptionItem` with an in-house-vs-outside patient choice and its own payment-preference/status sub-flow (mirrors lab's), `PrescriptionFavourite` (doctor's saved drug bundles), voice dictation (`TranscribeView` — Whisper-based, Phase 2 per the model's own comments), a stats endpoint, and PDF generation for encounter summaries.
- **Inputs:** Booking requests, vitals readings, consultation notes, diagnosis codes, prescription line items.
- **Outputs:** `Appointment`, `Vitals`, `OPDEncounter`, `Prescription`+`PrescriptionItem` rows; on encounter sign-off, an auto-generated draft `Invoice` (billing) and a write-through to the registry DB's `Shared*` tables (the HIE mechanism).
- **Dependencies:** `patients.Patient`, `org.StaffUser`/`Branch`/`Room`/`RoomAssignment`, `billing.Invoice` (created from here), `prescriptions.Drug` (catalog FK), `lab` (LabRequest FKs back to `OPDEncounter`).
- **Business rules:** ✅ Appointment status transitions are enforced server-side, not just conventionally (`AppointmentStatusView.ALLOWED_TRANSITIONS` — see §9). ✅ A new same-day booking gets `STATUS_WAITING` immediately; a future-dated booking gets `STATUS_SCHEDULED` (a past bug had every booking get `WAITING` unconditionally — since fixed, per an inline comment). ✅ Signing an encounter (`OPDEncounter.sign()`) atomically flips the linked `Appointment` to `STATUS_DONE` and stamps `completed_at`, in the same call. ✅ Invoice auto-generation "never blocks sign-off" — i.e. it is deliberately best-effort/non-atomic with the sign-off itself (see §7.11 for the consistency implication). ✅ Consultation fee charged depends on `appointment_type` (`followup_fee` vs `consultation_fee` on `DoctorProfile`), not a flat fee. ✅ `apps.clinical` (the old Encounter/Vital/Diagnosis/FollowUp/ClinicalDocument models) is **confirmed dead** — nothing in `opd` or the frontend ever wrote to it; it was formally retired.
- **Unclear areas:** ❓ How complete/production-ready the Whisper voice-transcription feature (`TranscribeView`) actually is — the model docstring calls it "Phase 2."

### 2.5 `lab` — Laboratory
- **Purpose:** Lab test catalog, lab requests (orders), lab reports, individual result parameters.
- **Who uses it:** Doctor (orders a test from an encounter), lab technician (processes/uploads reports), patient portal (views results, chooses in-house vs. outside, pays).
- **Main features:** Tenant-managed `LabTest` catalog, `LabRequest` with the same in-house/outside/payment-preference/payment-status shape as `opd.Prescription`, sequential `request_number` (NNTM), report upload with structured `LabReportItem` rows (parameter/value/unit/reference-range/abnormal-flag), `LabReport.deliver()` writing a sanitized copy to `registry.SharedLabResult` (the HIE mechanism), billing triggered at report delivery (not at order time).
- **Inputs:** Doctor's test order (urgency, clinical notes), lab technician's uploaded result values/files.
- **Outputs:** `LabRequest`, `LabReport`, `LabReportItem` rows; a `billing.Invoice` line (via `_bill_lab_request`, called at delivery); a `registry.SharedLabResult` row.
- **Dependencies:** `org.StaffUser`/`Branch`, `patients.Patient`, `opd.OPDEncounter` (order origin), `billing.Invoice`.
- **Business rules:** ✅ Gated behind `feat_lab` (Subscription feature flag) at the view layer. ✅ Billed only once a report is actually delivered/performed, not at order time — mirrors the philosophy of "don't bill for a service not yet rendered." ✅ Maps conceptually to FHIR `DiagnosticReport` per the model docstring, though this is a design note, not an actual FHIR API.
- **Unclear areas:** ❓ Whether "urgency" (routine/urgent) on `LabRequest` actually drives any queue prioritization in the lab-tech UI, or is purely informational — the external-comparison document explicitly flags urgency/priority as a **gap** worth adding, which is a signal it may not be fully wired end-to-end today.

### 2.6 `pharmacy` — Pharmacy / Dispensing
- **Purpose:** Stock/inventory per drug per branch, stock movement audit trail, dispensing against a doctor's prescription, and inpatient-style dose logging (used today for any medication administration, not specifically IPD).
- **Who uses it:** Pharmacist (stock, dispensing), nurse (dose administration logging).
- **Main features:** `Stock` (batch-level quantity/expiry/cost/MRP per drug+branch), `StockTransaction` (append-only audit of every quantity change: purchase/dispense/return/expiry/adjustment, storing before/after quantity), `Dispense` (against `opd.PrescriptionItem` — see the important bug-fix note below), `MedicationDoseLog` (given/skipped/refused, by a nurse).
- **Inputs:** Stock receipt data, dispense requests, dose-administration records.
- **Outputs:** `Stock` quantity updates, `StockTransaction` rows, `Dispense` rows, `MedicationDoseLog` rows, a billing invoice line (dispense is priced from `Stock.mrp`, added to the same invoice as the originating prescription — see `opd.Prescription.invoice`).
- **Dependencies:** `org.StaffUser`/`Branch`, `patients.Patient`, `prescriptions.Drug`, `opd.Prescription`/`PrescriptionItem`.
- **Business rules:** ✅ **Historically significant bug, now fixed:** `Dispense` used to point at the legacy `apps.prescriptions.Prescription`/`PrescriptionItem` models, which the live doctor-consultation flow never wrote to — meaning a prescription a doctor actually wrote could never reach the pharmacist's dispensing queue. It now correctly points at `apps.opd.PrescriptionItem`, the model doctors actually use. This is a good example of why the retired-app boundaries matter to a new developer: pointing new code at the wrong twin model is an easy, previously-real mistake here. ✅ Gated behind `feat_pharmacy`. ✅ `MedicationDoseLog` exists and is described as "inpatient medication dose administration" in its own docstring, but since there is no IPD admission concept, it is presumably used for any tracked medication administration today (⚠️ ASSUMPTION — not explicitly confirmed how it's invoked from the frontend).
- **Unclear areas:** ❓ Exact reorder/low-stock alerting behavior — `Stock.reorder_level` exists as a field but whether anything actively surfaces a "below reorder level" alert wasn't verified in the view layer.

### 2.7 `billing` — Billing & Invoicing
- **Purpose:** Service price catalog, invoices, invoice line items, payments, revenue reporting, and tenant-configurable dropdown lists (service categories, payment modes, invoice statuses, drug forms — unified into one `OptionList` table).
- **Who uses it:** Front desk/billing desk (create/manage invoices, record payments), hospital admin (configure catalog/categories/tax), doctor/nurse indirectly (their actions auto-generate invoice lines), patient portal (view/pay/download invoices).
- **Main features:** `BillingService` price catalog with per-service tax rate (falling back to the tenant's `default_tax_rate`), `Invoice`/`InvoiceItem`/`Payment` (multiple partial payments per invoice supported), PDF invoice generation, revenue reports, and the `OptionList` unified configuration table.
- **Inputs:** Service definitions, invoice line items (manual or auto-generated from OPD/lab/pharmacy), payment records.
- **Outputs:** `Invoice`, `InvoiceItem`, `Payment` rows; PDF documents.
- **Dependencies:** `patients.Patient`, `org.Branch`/`StaffUser`; is a **downstream dependency of** `opd` (consultation), `lab` (report delivery), `pharmacy` (dispense) — all three create invoice lines here.
- **Business rules:** ✅ `Invoice.status`, `BillingService.category`, `Payment.payment_mode`, and `prescriptions.Drug.form` are all **plain CharFields validated at the view/serializer layer against `OptionList` rows — not DB-enforced choices or foreign keys.** This is a deliberate design choice (tenant-configurable dropdowns) but means the database itself does not prevent an invalid/typo'd status or category from being written outside the API. ✅ `OptionList` rows flagged `is_system=True` (seeded defaults like "paid") cannot be deleted via the API because backend logic depends on their existence, but they can be relabeled. ✅ A `BillingService.tax_rate` of zero falls back to the tenant's `default_tax_rate`.
- **Unclear areas:** ❓ Whether there is any real payment gateway integration — the external-comparison document explicitly states **"payment" today means front-desk staff manually recording a transaction that already happened elsewhere** — i.e., no electronic payment collection exists; this should be confirmed with the previous team as it is a significant product gap if patients are expected to "pay online."

### 2.8 `prescriptions` — Drug Catalog (partially retired)
- **Purpose today:** Only the tenant drug catalog (`Drug` model) and drug search/CRUD endpoints. The `Prescription`/`PrescriptionItem` models that used to live here are **retired dead code** — the live flow uses `apps.opd.Prescription`/`PrescriptionItem` instead.
- **Who uses it:** Pharmacist (catalog maintenance), doctor (drug search/autocomplete while prescribing).
- **Main features:** Drug search, drug catalog CRUD, drug-form-type list (now actually backed by `billing.OptionList(list_type="drug_form")`, not a model in this app).
- **Dependencies:** Read by `opd.PrescriptionItem` (optional FK to `Drug`) and `pharmacy.Stock`.
- **Business rules:** ✅ `Drug.form` is free text validated against `OptionList`, not a DB constraint. ✅ The retirement note in the code is explicit and names the actual bug this caused historically (see §2.6).

### 2.9 `compliance` — DPDP Act Compliance
- **Purpose:** Patient right-to-correction requests (`RecordAmendment`) and an immutable consent audit trail (`ConsentRecord`).
- **Who uses it:** Patient (via portal, raises amendment requests), hospital admin/compliance staff (reviews/resolves them), compliance/audit-log viewers (reads `org.AuditLog`, not a model in this app).
- **Main features:** DPDP Article 13 correction-request workflow (pending → approved/rejected, with before/after value tracking), consent-event logging separate from the boolean consent flags on `Patient` (so a leaked/overwritten flag doesn't erase proof of what was actually agreed to and when).
- **Business rules:** ✅ Data is **never deleted** regardless of account status — stated as a legal requirement in the model docstring. ✅ `AccessLog` (a planned PHI-access audit table) was explicitly removed as dead/duplicate — `org.AuditLog` is the **only** PHI access-log table in the system; a developer should not go looking for a second one.

### 2.10 `notifications` — Notification Log (mostly a dead scaffold)
- **Purpose:** Delivery log for outbound notifications (SMS/email/in-app), read by the patient portal's notification list.
- **What's real:** ✅ `NotificationLog` model and a `generate_reminders` background command exist and are used by `PortalNotificationsView`/`PortalNotificationMarkReadView` (a genuinely mounted endpoint, `/api/v1/portal/notifications/`).
- **What's dead:** ✅ `NotificationTemplate` and `DeviceToken` models were retired (zero call sites found before removal); the app has **no URL mount of its own** (`apps/notifications/urls.py` is empty) — it's only reachable through the `patients` app's portal endpoints.
- **Unclear areas:** ❓ Whether SMS/WhatsApp notifications are actually being sent in production or only logged — `SMS_BACKEND` defaults to `"log"` (writes to the app log, doesn't actually send) unless a real gateway (MSG91 or a self-hosted Android SMS gateway) is configured via environment variables.

### 2.11 `clinical`, `tasks`, `ai_pipeline` — Fully retired apps
- ✅ All three have **empty `models.py`** files with explicit docstrings explaining they were confirmed dead (zero frontend consumers, in `tasks`' case a *complete working backend* nobody ever called) and are kept registered in `INSTALLED_APPS` purely so old migration history stays resolvable. `clinical` also has an empty `urls.py`; `tasks` too; `ai_pipeline`'s `urls.py` is a literal empty file and was **never mounted** in `atomwalk/urls.py` at all.
- **Why this matters for a new developer:** these three app names will show up in `INSTALLED_APPS`, in old migrations, and possibly in search results, but contain no active functionality. Do not build on them; do not assume "the app exists" means "the feature exists."

### 2.12 `registry` — Registry-DB models (cross-tenant)
- **Purpose:** Everything that must exist outside any single hospital's database: cross-hospital patient identity (`PatientIdentity`, `PatientRelationship`), the patient portal's login account (`PatientAccount`), staff login routing (`StaffMobileIndex`), OTP codes (`OTPCode`), JWT revocation (`BlacklistedToken`), portal-side booking mirror (`PortalBooking`), the Emergency QR audit trail (`EmergencyAccessLog`), and the **Health Information Exchange (HIE)** "Shared" tables (`SharedDiagnosis`, `SharedPrescription`+`Item`, `SharedLabResult`, `SharedAllergy`, `SharedDocument`, `SharedVital`, `SharedVaccination`) plus vaccination schedule configuration (`VaccinationSchedule`, `VaccinationScheduleRule`).
- **Who uses it:** Every tenant app writes sanitized copies here on relevant events (diagnosis recorded, prescription finalized, lab result delivered, allergy recorded, vital finalized, vaccination recorded); every tenant app's doctor-facing "shared history" view reads it back for a patient who has consented to HIE sharing.
- **Business rules:** ✅ DPDP-driven design: **no plain mobile numbers are stored in this database** — only `mobile_hash = SHA-256(normalized mobile)`. ✅ `source_tenant_id` is stored on every Shared* row but **never returned to other tenants' API responses** (enforced at the serializer layer, per the model docstring) — a hospital can see *what* another hospital recorded about a shared patient, never *which* hospital or *which* doctor recorded it. ✅ `SharedVaccination.verification_status` is deliberately overloaded as a full lifecycle field (`verified`/`pending_review`/`rejected`/`ordered`/`declined`) rather than adding a second status column — explained at length in the model's own docstring as a considered, not accidental, design decision.
- **Unclear areas:** ❓ Whether the HIE write-through is transactionally guaranteed to happen (i.e., could a tenant-side write succeed while the registry-side mirror silently fails?) — see §7.11.

### 2.13 `tenants` — Tenant Provisioning & Licensing (registry DB)
- **Purpose:** `Tenant` (one row per hospital), `Subscription` (tier + feature flags + billing lifecycle status), `TenantAuditLog` (platform-admin action trail), `NextNumber` (registry-side NNTM, separate table from the tenant-side one in `org`).
- **Who uses it:** Platform admin exclusively for management; every tenant-side request reads `Subscription` to enforce tier/feature gates and billing-lapse restrictions.
- **Business rules:** ✅ Subscription statuses form a real lifecycle: `trial → active → grace (day 1–7) → read_only (day 8–30) → frozen (day 31–90) → suspended`. `read_only` blocks all non-safe HTTP methods; `frozen`/`suspended` block everything, enforced live on every request via `JWTTenantAuthentication` (not just at login). ✅ Feature flags (`feat_lab`, `feat_pharmacy`, `feat_whatsapp`, `feat_multi_branch`, `feat_ai_voice`, `feat_patient_app`, `feat_analytics`, `feat_video`, `feat_face_recog`, `feat_custom_roles`) are cached-from-tier but individually overridable per tenant by platform admin — i.e., a custom enterprise deal can turn on any flag regardless of nominal tier. ✅ Soft seat limits: `max_doctors`, `max_branches`, `max_staff` (0 = unlimited; `max_staff` excludes doctors, who have their own cap). ✅ `Tenant.db_name` is immutable once set (per design-spec comment) and is the PostgreSQL database alias the router uses.
- **Unclear areas:** ❓ How exactly a hospital transitions between subscription statuses in practice (manual platform-admin action vs. an automated billing-lapse job) — no scheduled job for this was found in the code inspected.

### 2.14 `platform_admin` — Platform Administration (no models of its own)
- **Purpose:** Views/serializers only — operates on `tenants.Tenant`/`Subscription`, `org.StaffUser` (cross-tenant, by iterating tenant DBs), and `registry.VaccinationSchedule` (system templates).
- **Main features:** Tenant CRUD, tenant audit log, platform-wide stats, per-tenant staff list/detail/password-reset (as platform admin, not the hospital's own admin), platform user list, plan list, and system-level vaccination-schedule templates that hospital admins can clone.
- **Who uses it:** Only `role == "platform_admin"` (a pure literal check, never reachable via a custom Role — see `core/permissions.py`).

### 2.15 Frontend structure (React/Vite) — mirrors the roles exactly
- ✅ `frontend/src/pages/` has one directory per role: `auth`, `doctor`, `front-desk`, `hospital-admin`, `lab`, `nurse`, `patient`, `pharmacist`, `platform-admin`, `public` (the unauthenticated Emergency QR view), `shared` (a generic profile page). **There is no `ipd` directory anywhere in the frontend** — confirming the backend finding that IPD is not built on the client either.
- ✅ Key supporting files: `services/api.client.js` (single Axios-style API client), `config/api.config.js` (endpoint constants), `config/routes.config.js` (role→route mapping), `context/{Auth,Patient,Permission,Tenant,Theme}Context.jsx`.

---

## 3. END-TO-END USER JOURNEYS

### 3.1 The standard OPD visit (front desk / nurse / doctor / billing)
✅ Reconstructed directly from `apps/opd/models.py` + `apps/opd/views.py` state machine.

```
Patient → Front desk books/records Appointment (status=scheduled or waiting)
        → Patient checks in → Front desk/queue marks WAITING (same-day bookings start here automatically)
        → Nurse records Vitals → status auto-advances to VITALS_DONE
        → Doctor calls patient from queue, opens encounter → status auto-advances to IN_PROGRESS
        → Doctor writes SOAP note (subjective/objective/assessment/plan), records ICD-10 diagnoses,
          optionally orders Lab tests and/or writes a Prescription
        → Doctor signs the encounter (OPDEncounter.sign())
            → Appointment flips to DONE, completed_at stamped (same transaction)
            → A draft Invoice is auto-generated from the doctor's real consultation/follow-up fee
              (best-effort — does not block sign-off if it fails)
            → Sanitized clinical facts are written through to the registry DB's Shared* tables (HIE)
        → If a lab test was ordered: Lab tech collects sample → processes → uploads report →
          delivers it (billing line added at delivery, not at order) → sanitized copy → registry DB
        → If a prescription was written: Patient chooses in-house or outside fulfilment
            → In-house: Pharmacist dispenses against Stock (stock decremented, StockTransaction logged,
              a billing line added to the SAME invoice as the consultation)
            → Outside: no further in-system action (patient takes the paper/PDF prescription elsewhere)
        → Front desk / billing desk records Payment(s) against the Invoice (partial payments allowed)
        → Final outcome: Appointment=DONE, Invoice=paid/partially_paid, all clinical facts visible in
          patient's own portal and (if HIE-consented) to any other hospital's doctor
```
Cancellation/no-show branch: ✅ `scheduled`/`waiting` can move to `cancelled`; `waiting` can also move to `no_show`. Both are terminal for that appointment.

### 3.2 Front-desk / self-service patient registration
✅ From `apps/patients/services.py` + `apps/patients/models.py`.
```
New patient arrives → Front desk searches by mobile/AWPID first (cross-hospital dedup)
  → If PatientIdentity already exists (registered at any hospital before): reuse it, create a new
    tenant-local Patient row linked by awpid, generate a new hospital-local UHID (NNTM)
  → If not: create a new PatientIdentity (registry DB) + a new tenant-local Patient row
  → Capture DPDP consent (data processing) and, separately, HIE consent (cross-hospital history sharing)
  → For a dependent (child, no own mobile): link via guardian_mobile_hash + PatientRelationship instead
    of creating a disconnected identity
→ Outcome: patient can now be booked, billed, and (if HIE-consented) their history from other
  hospitals becomes visible to this hospital's doctors
```

### 3.3 Patient portal booking journey (cross-hospital)
✅ From `apps/patients/portal_urls.py`/`portal_views.py`.
```
Patient logs in (mobile+password or OTP) → registry-wide account (PatientAccount), not tied to one hospital
  → Browses hospitals / searches by specialty, symptom, city, doctor name
  → Picks a doctor → sees real available slots (derived from org.DoctorSchedule/DoctorAvailabilitySlot
    and existing bookings, 2-month booking cap)
  → Books for self or a linked family member (PatientRelationship) → consent captured if this is a
    new hospital for that identity
  → PortalBooking (registry DB, for "my bookings across hospitals") + Appointment (tenant DB,
    authoritative) both created
  → Can reschedule/cancel from the portal (subject to the same status rules as staff-side cancellation)
  → After the visit: sees prescriptions, lab reports, invoices, and discharge-style summaries as they're
    produced by the OPD flow — the portal is a read surface on the same data, not a separate system
```

### 3.4 Hospital onboarding (platform admin)
⚠️ Reconstructed from `apps/tenants/models.py` + `apps/platform_admin/views.py` names; exact step-by-step API sequencing in the view code was not traced line-by-line.
```
Platform admin creates Tenant (name, subdomain, db_name) → creates linked Subscription (tier, trial dates,
  feature flags, seat limits) → a dedicated Postgres database is provisioned for db_name and migrated
  (migrate_tenants management command, per README) → hospital admin's first StaffUser is created/invited
  → hospital admin logs in, configures branches/departments/rooms/staff/billing catalog/doctor schedules
  → hospital is now operational for OPD bookings
```

### 3.5 Staff invite → self-service activation
✅ From `apps/org/models.py` (`must_change_password`, `set_unusable_password`) + `README.md`.
```
Hospital admin invites staff (name, role, phone, branch) → StaffUser created with an unusable password
  → Invite token sent → staff visits setup-password link → sets their own password → can now log in
  → (Doctor/other roles then fill in their own self-service profile fields — bio, photo, languages, etc.
     — separately from what the admin entered at invite time)
```

### 3.6 Emergency QR journey (no login required for the viewer)
✅ From `apps/patients/emergency_views.py`/`emergency_urls.py`, `core/emergency_access.py`, `registry.EmergencyAccessLog`.
```
Patient (in portal) explicitly confirms a consent prompt → generates a signed, ~20-minute JWT with no PHI
  embedded in the payload itself → EmergencyAccessLog row (event=generated, consent_confirmed=True)
  → Patient shows the QR/link to anyone (a doctor at a hospital NOT necessarily on this platform)
→ Viewer opens the link (public, unauthenticated, rate-limited at 20/min/IP) → EmergencySummaryView
  resolves the token → EmergencyAccessLog row (event=viewed) → critical facts shown (allergies, active
  diagnoses, blood group, emergency contact — exact field list not fully enumerated in what was read)
→ Token expires ~20 minutes after generation regardless of whether it was viewed
```

### 3.7 The IPD Admission journey — PLANNED ONLY, NOT BUILT
✅ Explicitly marked "Nothing described here is built yet — this is planning and specification only" in `IPD_Admission_Feature_Documentation_v2.docx`. Included here because the handover documents describe it at length and a new developer will encounter it.
```
Doctor decides patient needs inpatient care (from OPD consult, ward round, or ER exam) → orders admission
  (type: emergency/elective/day_care/referral)
→ Front desk logs the request → Admission record created, status=requested (v2 spec: ALWAYS logged by
  front desk on a doctor's order; v1 spec additionally allowed nurse/walk-in "Admission Referral" rows
  routed to a doctor for review — see §17 for this version conflict)
→ Front desk completes registration (identity, payer, consent) → status=admitted (awaiting bed)
  (emergency admissions may skip ahead of full paperwork completion — registration happens in parallel,
  never blocks bed allocation for a true emergency)
→ [OUT OF SCOPE of the Admission-phase document] Bed Allocation assigns a bed → status=active
→ [Per IPD_Full_Cycle.pptx only — no accompanying data spec found] Daily Care loop (rounds, orders,
  eMAR, nursing) repeats until the doctor decides: continue / escalate / procedure / begin discharge
→ [Conditional] Procedure/OT branch → Recovery → returns to ward or escalates to ICU
→ Discharge Planning (4 parallel clearances: clinical, medication reconciliation, billing, documentation)
→ Discharge & Closure → bed released → Admission status=discharged, later closed (read-only)
→ Hands back to the SAME billing/invoicing module used for OPD (per the "How It Connects" deck)
```
**None of this has a corresponding Django app, model, migration, URL, or frontend page in the repository as inspected.**

---

## 4. USER ROLES & RESPONSIBILITIES

| Role | What they do | Modules they access | Important actions | Permissions/limitations |
|---|---|---|---|---|
| **Hospital Admin** (`hospital_admin`) ✅ | Runs one hospital's operational setup | org, billing setup, compliance, rooms, roles, vaccination schedule config | Invite/manage staff, configure branches/rooms/billing catalog/tax, assign custom roles, view compliance/audit log | Cannot act on other tenants; cannot originate clinical actions (no diagnosis/prescription authority) |
| **Doctor** (`doctor`) ✅ | Clinical consultation | opd (encounter, prescription, lab order), patients (history), org (own schedule/profile) | Write SOAP notes, diagnose (ICD-10), prescribe, order labs, sign encounters, set own consultation fee (if `fee_ownership=doctor`) | Cannot log the front-desk queue actions or complete registration; cannot dispense drugs or process lab samples |
| **Nurse** (`nurse`) ✅ | Pre-consultation care, monitoring | opd (vitals, monitoring list), patients (history, vaccination admin) | Record vitals, monitor assigned doctors' patients (`NurseDoctorAssignment`-scoped), administer/verify vaccinations, log medication doses | Sees only patients of doctors they're assigned to, not the whole hospital; cannot diagnose or prescribe |
| **Front Desk** (`front_desk`) ✅ | Registration, scheduling, queue, billing intake | patients (registration), opd (booking/queue), billing (invoice/payment) | Register patients, book/check-in/cancel appointments, record payments | Cannot write clinical notes (explicitly called out in the IPD admission spec too, as a cross-cutting rule) |
| **Lab Technician** (`lab_tech`) ✅ | Sample processing, reporting | lab | Update request status (collected/processing/completed), upload report + parameter results, verify/deliver reports | Scoped by `feat_lab`; cannot originate a lab order (only a doctor can) |
| **Pharmacist** (`pharmacist`) ✅ | Inventory, dispensing | pharmacy, prescriptions (catalog) | Receive stock, dispense against a prescription, manage drug catalog/forms | Scoped by `feat_pharmacy`; cannot write or alter a prescription's clinical content |
| **Custom** (`custom`) ✅ | Hospital-defined bundle of the above (e.g., solo-clinic "does everything") | Whatever `acts_as` includes | Resolves at login to acting as each listed system role | Only available on tenants with `feat_custom_roles` (enterprise tier) |
| **Patient** (`patient`) ✅ | Self-service across every participating hospital | Full patient portal | Book/reschedule/cancel, view records/prescriptions/labs/invoices, manage family, vaccination roadmap, Emergency QR, raise DPDP correction requests | No access to any staff-side view; scoped strictly to their own AWPID + linked family |
| **Platform Admin** (`platform_admin`) ✅ | Runs Atomwalk's own onboarding/ops layer | platform_admin, tenants | Onboard hospitals, manage subscriptions/feature flags/tiers, cross-tenant stats, reset a hospital's staff password | Not reachable via any custom Role; entirely separate from hospital-side RBAC |

⚠️ **Assumption:** roles not explicitly spelled out for every single endpoint (e.g., whether a `front_desk` user can view — not just create — an `Invoice`) were inferred from the permission classes named in `core/permissions.py` and each app's URL/view names, not from reading every single view's `permission_classes` line by line.

❓ **Missing:** a formal permission matrix (which of the ~40+ `Permission.code` catalog entries maps to which of the 6 system roles by default) exists in code (`apps.org.rbac.SYSTEM_ROLE_PERMISSIONS`) but was not read in full — worth reviewing directly during handover if fine-grained permission auditing is needed.

---

## 5. FUNCTIONALITY BREAKDOWN

This section covers cross-cutting mechanics not already detailed per-module in §2. For each, backend effect is described as observed in code/comments.

### 5.1 Appointment booking
- **User does:** picks a doctor + date/time slot (front desk or patient portal).
- **Why:** to reserve a consultation.
- **Backend:** validates the slot against `org.DoctorAvailabilitySlot` (day-of-week + time window) and existing `Appointment` rows for that doctor/date (double-booking prevention — ✅ stated explicitly in the "How It Connects" deck and consistent with the unique constraints seen on scheduling-adjacent tables); resolves `room_id`/`room_name`/`floor` once at booking time from `org.RoomAssignment` and bakes them onto the `Appointment` row (so a later change to room assignments doesn't retroactively change what a patient was already told); enforces a 2-month booking cap (⚠️ stated in the pptx and consistent with typical booking-engine limits, not independently re-derived from a specific line of view code).
- **Data created:** `Appointment` (status `scheduled` or `waiting` depending on date).
- **Other modules affected:** none yet — billing/lab/prescription only happen from the encounter onward.
- **Exceptional cases:** ✅ Reschedule is only allowed from `scheduled`/`waiting` (not once queued further); cancel is allowed from more states (see §9).

### 5.2 Check-in / OPD queue
- **User does:** front desk marks patient arrived, or a same-day booking auto-starts in `waiting`.
- **Backend:** live, branch-scoped queue query; nurse's queue is filtered to only doctors she's assigned to (`NurseDoctorAssignment`), not the whole branch.
- **Status changes:** `scheduled`/`created` → `waiting`.
- **Notifications:** ❓ not confirmed whether a real-time push/poll mechanism exists beyond the frontend polling the list endpoint (no WebSocket/Channels usage was found in `INSTALLED_APPS` or `ASGI_APPLICATION` beyond the bare Django ASGI app).

### 5.3 Vitals capture
- **User does:** nurse enters BP/pulse/SpO2/temperature/weight/height/etc.
- **Backend:** `Vitals.save()` auto-computes BMI from weight+height at save time; appointment status auto-advances to `vitals_done`.
- **Data created:** one `Vitals` row per appointment (`OneToOneField`).
- **Other modules affected:** the vitals get mirrored to `registry.SharedVital` on finalization (per the model's docstring — "written on finalization"), making them visible to other hospitals if the patient is HIE-consented.

### 5.4 Consultation / encounter sign-off
- **User does:** doctor writes SOAP notes, diagnoses (ICD-10 list), orders labs/writes prescription, clicks "sign."
- **Backend:** `OPDEncounter.sign()` — one method does three things atomically: marks the encounter `signed` + timestamps it, flips the linked `Appointment` to `done` + timestamps `completed_at`, and saves both. **Outside** that atomic method call, invoice auto-generation and the HIE write-through happen as separate, explicitly best-effort steps that "never block sign-off."
- **Data created/updated:** `OPDEncounter` (signed), `Appointment` (done), draft `Invoice`+`InvoiceItem` (billing), `registry.Shared*` rows (diagnosis, prescription, vitals as applicable).
- **Exceptional cases:** ✅ Once signed, an encounter cannot be re-edited via the normal `PATCH` endpoint (`EncounterDetailView.patch()` checks `status == STATUS_SIGNED` and presumably blocks further edits — the amendment path for a signed record would go through `compliance.RecordAmendment` instead, consistent with "clinical records are corrected by amendment, never silently overwritten," a rule explicitly stated for the *planned* IPD module and ⚠️ assumed to apply to the live OPD encounter too, though not independently re-verified in `EncounterDetailView`'s exact code).

### 5.5 Lab ordering and reporting
- **User does:** doctor orders a test from an encounter; lab tech updates status through collected → processing → completed, uploads results, delivers the report.
- **Backend:** billing line generated at *delivery*, not at order (`_bill_lab_request`, called from the delivery view); `LabReport.deliver()` writes to `registry.SharedLabResult`.
- **Exceptional case:** patient can choose `outside` fulfilment — in that case the "report" the patient later has is whatever they upload themselves via the patient-document flow (`registry.SharedDocument`, with `source_ref` linking it back to the originating `LabRequest`), not a `LabReport` row created by this hospital's own lab.

### 5.6 Prescribing and dispensing
- **User does:** doctor writes structured drug lines (dosage/frequency/route/duration); patient/nurse chooses in-house or outside fulfilment; pharmacist dispenses.
- **Backend:** first dispense against a prescription creates the `Invoice`; every subsequent dispense against the same Rx adds line items to that *same* invoice rather than creating duplicates; `Dispense` decrements `Stock.quantity` and writes a `StockTransaction` row recording before/after quantity for audit.
- **Exceptional case:** a drug not yet in the tenant's catalog can still be typed freeform onto a prescription (`PrescriptionItem.drug` FK is nullable) — the catalog link is optional, not mandatory.

### 5.7 Cross-hospital Health Information Exchange (HIE)
- **User does:** nothing extra — this happens automatically as a side effect of normal clinical actions, gated entirely on the patient's `hie_consent_given` flag.
- **Backend:** each tenant app writes a sanitized copy of diagnosis/prescription/lab result/allergy/vital/vaccination/document data to the corresponding `registry.Shared*` table, stripped of hospital/doctor identity (`source_tenant_id` stored but never exposed to other tenants).
- **Why it matters:** this is the mechanism behind "one patient, one longitudinal record across every hospital on the platform" — a real, working, opt-in feature, not aspirational.

---

## 6. DATA & DATABASE UNDERSTANDING (conceptual — see §7 for full architecture detail)

### 6.1 Main entities and why they exist
- **PatientIdentity** (registry DB) — ✅ the one global patient record; exists so the same human is recognized across every hospital instead of getting a disconnected record per hospital.
- **Patient** (tenant DB) — ✅ the hospital-local record (UHID, local contact/insurance info); exists because each hospital needs its own operational record even though identity is shared.
- **PatientAccount** (registry DB) — ✅ the portal login; deliberately separate from `Patient` because a person can have a portal login before ever visiting a specific hospital, and a `Patient` row can exist (front-desk-registered) without the person ever creating a portal login.
- **Appointment** (tenant DB) — ✅ the booking + the entire OPD visit's status machine; almost everything else in the OPD flow hangs off it (Vitals, OPDEncounter are `OneToOneField`s to it).
- **OPDEncounter** (tenant DB) — ✅ the actual clinical record of the visit (SOAP + diagnoses); created when a doctor starts seeing the patient.
- **Prescription/PrescriptionItem, LabRequest/LabReport(+Item), Invoice/InvoiceItem/Payment** (tenant DB) — ✅ the three "outputs" of a consultation, each capable of standing alone or feeding into billing.
- **Tenant/Subscription** (registry DB) — ✅ exist to make one codebase serve many independent hospitals with independent licensing.
- **StaffUser** (tenant DB) — ✅ per-hospital staff identity; deliberately *not* Django's `AUTH_USER_MODEL` (kept as a plain model) because each tenant DB needs its own independent staff table.

### 6.2 Master vs. transactional vs. audit data
- **Master/config data** (tenant DB, admin-configured): `Branch`, `Department`, `Room`, `RoomAssignment`, `DoctorSchedule`/`DoctorAvailabilitySlot`, `LabTest` catalog, `Drug` catalog, `BillingService` catalog, `OptionList` (categories/payment-modes/invoice-statuses/drug-forms), `Role`/`Permission`, `VaccinationSchedule`/`Rule`.
- **Transactional data:** `Appointment`, `Vitals`, `OPDEncounter`, `Prescription`+items, `LabRequest`/`LabReport`+items, `Dispense`, `StockTransaction`, `Invoice`+items, `Payment`.
- **Audit/history data:** `org.AuditLog` (the single PHI access/action log), `pharmacy.StockTransaction` (append-only stock ledger), `tenants.TenantAuditLog` (platform-admin actions), `compliance.ConsentRecord` (append-only consent trail), `registry.EmergencyAccessLog`.
- **Reference/config-in-DB data (registry):** `VaccinationSchedule`/`Rule` (system templates + per-hospital clones), `NextNumber`/NNTM counters (both registry-side and org-side tables exist — see §7.4 for why there are two).

---

## 7. DATABASE ARCHITECTURE & DATABASE DESIGN

### 7.1 Database technology
✅ PostgreSQL (`psycopg2-binary` driver, `django.db.backends.postgresql` engine everywhere). ✅ **Database-per-tenant**: one shared "registry" database (`default` alias) plus one dedicated PostgreSQL database per hospital, dynamically registered into `settings.DATABASES` at runtime. ✅ No read replicas, no separate reporting DB, no caching layer (no Redis/Memcached configured — `.env.example` mentions Celery/Redis but ✅ per the comparison document, "never implemented"). ❓ Hosting/infrastructure (managed Postgres service, self-hosted, cloud provider) is not stated anywhere in the code — only connection parameters via environment variables. ❓ Exact Postgres version is not pinned anywhere found. ❓ Dev/staging/production database topology (same host, different instances, etc.) is not documented beyond the three Django settings modules (`base`/`development`/`production`), which only vary connection *behavior* (SSL, logging), not architecture.

### 7.2 Database architecture — plain-language + diagram
Every request enters through Django, is authenticated, and its JWT tells the ORM which physical database to talk to for anything that isn't a "registry" model. This is enforced by a custom router reading a thread-local variable set by middleware — **not** by a client-supplied string, which is a deliberate, verified-in-code anti-pattern-avoidance (the external-comparison document calls this out explicitly as something the platform does correctly compared to the two reference mobile apps, which trusted a client-stored tenant string).

```
Browser / Patient Portal / Staff App
        ↓  HTTPS + JWT Bearer token
Django REST Framework (atomwalk/urls.py → per-app urls.py → Views)
        ↓
core.middleware.JWTTenantMiddleware  → decodes JWT → set_tenant_db(db_name) on a thread-local
core.authentication.JWTTenantAuthentication → builds request.user (MockUser), checks subscription/active status
        ↓
Django ORM (models in apps/*)
        ↓
core.db_router.TenantDatabaseRouter
    ├── app_label in {tenants, registry, auth, contenttypes, sessions, admin} → "default" (Registry DB)
    └── everything else (org, patients, opd, lab, pharmacy, billing, prescriptions, compliance,
        notifications, [clinical/tasks/ai_pipeline — retired, empty]) → the tenant's own DB,
        resolved from the JWT's db_name claim
        ↓
PostgreSQL
    ├── "default" (Registry DB) — Tenant, Subscription, PatientIdentity, PatientAccount,
    │                              StaffMobileIndex, OTPCode, BlacklistedToken, PortalBooking,
    │                              EmergencyAccessLog, Shared* (HIE) tables, VaccinationSchedule
    └── one database PER HOSPITAL (e.g. "aw_sunrise_clinic") — Branch, Department, Room, StaffUser,
        Patient, Appointment, Vitals, OPDEncounter, Prescription, LabRequest/Report, Stock,
        Invoice/Payment, AuditLog, ConsentRecord, RecordAmendment, NotificationLog, Drug, OptionList
```
This is a **shared-nothing, database-per-tenant** pattern for hospital data, with one small **shared** database for identity/licensing/cross-tenant concerns — not a single shared multi-tenant schema (no `tenant_id` column-based row filtering is used for hospital data; isolation is at the *database* level, which is a materially stronger isolation guarantee than a shared-table approach). ✅ Cross-DB relations are explicitly disallowed at the ORM level (`TenantDatabaseRouter.allow_relation` returns `False` unless both models resolve to the same DB alias) — any reference from a tenant DB to the registry DB (e.g., `Patient.awpid` → `PatientIdentity.awpid`) is necessarily a **plain string/int field, not a Django `ForeignKey`**, matched by application code, never by the database itself.

### 7.3 Database schema structure
✅ No custom Postgres schemas beyond the default `public` schema were found (`search_path=public` is set explicitly in the registry DB's `OPTIONS`). ✅ No custom views, stored procedures, functions, or triggers were found anywhere in the codebase — **all** business logic (including the sequential-number generation in §7.4 and the BMI auto-calc in `Vitals.save()`) lives in Django application code, not in the database itself. ✅ Standard Django migration-managed tables only — every table has a `db_table` explicitly set to a snake_case name matching the model's purpose (e.g. `opd_encounter`, `lab_report_item`, `staff_mobile_index`).

Selected major tables (table → purpose → PK → key fields → FKs → who writes/reads):
- **`tenant`** (registry) → one row per hospital → `id` (BigAutoField) → `db_name`, `subdomain`, `fee_ownership`, billing-config fields, `logo`, `storage_folder` → no FKs out → written by platform_admin, read by every request's middleware.
- **`subscription`** (registry) → licensing → `id` → `license_tier`, `status`, `feat_*` flags, `max_*` limits → `OneToOne → tenant` → written by platform_admin, read on every staff-authenticated request.
- **`patient_identity`** (registry) → global patient → `id` → `awpid` (unique), `mobile_hash` (unique, nullable), `guardian_mobile_hash` → no FKs out (deliberately, per §7.2) → written by any tenant's registration flow, read for cross-hospital dedup.
- **`patient`** (tenant) → hospital-local patient → `id` → `awpid` (string, not FK), `uhid` (unique) → `FK → branch` → written by front desk/portal registration, read by nearly every clinical/billing view.
- **`appointment`** (tenant) → booking/queue/visit state → `id` (**UUID**, not auto-increment) → `patient_id`/`doctor_user_id` (UUID fields, **not real FKs** — see note below), `status`, `scheduled_date/time`, `room_id`/`room_name`/`floor` (denormalized) → written by booking flow, read constantly (queue, dashboards, history).
- **`opd_encounter`** (tenant) → clinical note → `id` (UUID) → `OneToOne → appointment`, JSON `diagnoses` field → written by doctor, read by portal/HIE sync/PDF generation.
- **`invoice`** / **`invoice_item`** / **`payment`** (tenant) → billing → `id` → `invoice_number` (unique, NNTM-generated), `status` (plain string, validated against `option_list`, not FK) → `FK → patient`, `branch` → written by opd/lab/pharmacy auto-generation + billing desk, read by portal and reports.
- **`shared_*`** tables (registry) → HIE mirror → `id` → `awpid`, clinical payload, `source_tenant_id` (never exposed) → written by every tenant on the relevant clinical event, read by any tenant's "shared history" view for a consented patient.

⚠️ **Important architectural note:** `Appointment.patient_id` and `Appointment.doctor_user_id` are typed as `UUIDField` with a comment "FK → patients.patient.id" / "registry_user.id" but are **not actual Django ForeignKeys** — they are matched by application code. ❓ It was not confirmed whether `patients.Patient.id` is itself a UUID (the model shows `id` as the default BigAutoField plus a *separate* `uuid` field) — this is worth a direct question during handover, since a mismatch between `Appointment.patient_id`'s expected type and `Patient`'s actual PK type would be a real bug waiting to happen if ever queried carelessly. Treat this as ⚠️ ASSUMPTION requiring verification, not confirmed FACT.

### 7.4 Entity relationships (plain English, FACT unless marked)
- One `Tenant` has one `Subscription` (1:1). ✅
- One `Tenant` has many `StaffUser`, `Branch`, `Patient`, etc. — but only *conceptually*, since these live in a **different physical database**; there is no DB-level FK from tenant-DB rows back to `Tenant`. ✅
- One `Branch` has many `Department`, `Room`, `Patient`, `StaffUser` (primary branch). ✅
- One `StaffUser` (doctor) has one `DoctorProfile` (1:1) and one `DoctorSchedule` (1:1), which has many `DoctorAvailabilitySlot` (one per day-of-week, max 7). ✅
- One `StaffUser` (doctor) can have many `RoomAssignment` rows (recurring weekly slots) and many `StaffBranchMapping` rows (works at multiple branches) — both many-to-many in effect, implemented as explicit join tables with extra fields (day/time, is_primary). ✅
- One `Patient` has many `Appointment`, each `Appointment` has at most one `Vitals` and at most one `OPDEncounter` (1:1 each). ✅
- One `OPDEncounter` has at most one `Prescription` (1:1) and many `LabRequest` (1:many, via `encounter` FK). ✅
- One `Prescription` has many `PrescriptionItem`; one `PrescriptionItem` can have many `Dispense` records (partial dispensing across visits is structurally possible) and many `MedicationDoseLog` entries. ✅
- One `PatientIdentity` can have many `PatientRelationship` rows linking it as guardian to multiple dependents, or as a dependent under one primary guardian — a small hierarchical (parent/child) structure, not a general graph. ✅
- One `Invoice` has many `InvoiceItem` and many `Payment` (partial payments). ✅ A `Prescription` and a `LabRequest` each hold an optional FK *to* an `Invoice` (`invoice = models.ForeignKey("billing.Invoice", ..., related_name="+")`) — meaning billing lines from different sources (consultation, lab, pharmacy) can converge onto the **same** invoice for one visit. ✅
- **Junction/mapping tables:** `StaffBranchMapping` (staff↔branch), `NurseDoctorAssignment` (nurse↔doctor), `RolePermission` (role↔permission), `UserRole` (staff↔extra role), `RoomAssignment` (doctor↔room, with day/time). ✅
- **Two separate NNTM tables exist** — `tenants.NextNumber` (registry DB) and `org.NextNumber` (tenant DB) — because the registry DB and each tenant DB are physically separate databases and a sequence generator table must live in whichever DB actually needs atomic counters (registry-side entities like nothing currently listed vs. tenant-side UHID/invoice/lab/Rx/queue numbers). ✅ This is a deliberate duplication, not an oversight — explained by the DB-per-tenant architecture itself.

### 7.5 Primary keys & foreign keys
- ✅ Most tenant-DB tables use Django's default **auto-incrementing `BigAutoField`** (`DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"`, set globally).
- ✅ A deliberate subset uses **UUID primary keys** instead: `opd.Appointment`, `opd.Vitals`, `opd.OPDEncounter`, `opd.Prescription`, `opd.PrescriptionItem`, `opd.PrescriptionFavourite` — all in the `opd` app, all `models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)`. ⚠️ Not explicitly stated why these specific models get UUIDs while nearly everything else uses BigAutoField, but a reasonable inference is that these are the models most likely to be referenced by ID in a URL or exposed to a patient/external context, where a sequential integer ID would leak count/ordering information (e.g. a prescription number in a portal URL). This is ⚠️ ASSUMPTION, not stated in any comment found.
- ✅ Natural/business keys used as **unique constraints, not primary keys**: `Tenant.subdomain`/`db_name`, `Patient.uhid`, `Invoice.invoice_number`, `LabRequest.request_number`, `Prescription.rx_number`, `PatientIdentity.awpid`, `StaffUser.phone`/`employee_id`.
- ✅ Cross-database references (`Patient.awpid` → `PatientIdentity.awpid`, `Appointment.patient_id`, every `source_tenant_id` field, `Tenant.active_vaccination_schedule_id`) are **plain fields, never real FKs** — this is a consistent, explicitly-documented architectural convention (multiple model docstrings state this explicitly as "matching this codebase's existing convention" of avoiding cross-app/cross-DB FKs even where technically possible within the same DB).
- ✅ IDs are Django-auto-generated (BigAutoField) or `uuid.uuid4()` — never business-generated except the human-readable sequential numbers (UHID, invoice number, etc.) which are a *separate* field from the primary key, generated by NNTM.

### 7.6 Normalization & data design
⚠️ The schema is largely normalized in the classic sense (one fact per table, FKs for one-to-many), but with **deliberate, documented denormalization** in specific, narrow places:
- `Appointment.room_id`/`room_name`/`floor` — denormalized at booking time from `RoomAssignment` so a later room-assignment edit doesn't retroactively change a patient's already-communicated visit details. ✅
- `InvoiceItem.description` — denormalized copy of the service name at time of billing. ✅
- `registry.PortalBooking.hospital_name`/`doctor_name` — denormalized so the portal's "my bookings across hospitals" list doesn't need N cross-tenant lookups. ✅
- `Payment`/`StockTransaction`/audit tables are inherently append-only/historical rather than "normalized" in the transactional sense — this is intentional (audit requirements), not a normalization failure.
- ⚠️ ASSUMPTION: no evidence of pathological duplication (the same fact stored redundantly with no stated reason) was found; every denormalized field found had an explicit justifying comment.

### 7.7 Master data vs. transactional data
Covered in §6.2 above — repeated here per the requested structure: **master/config** (Branch, Department, Room, RoomAssignment, DoctorSchedule/Slot, LabTest, Drug, BillingService, OptionList, Role/Permission, VaccinationSchedule/Rule) vs. **transactional** (Appointment, Vitals, OPDEncounter, Prescription+items, LabRequest/Report+items, Dispense, StockTransaction, Invoice+items, Payment). Master data drives transactional records by **validation, not DB constraint**, in the billing/pharmacy/prescriptions apps specifically (`OptionList`-validated CharFields) — meaning a hospital can extend these lists via the API without a schema migration, at the cost of the database not itself preventing an invalid value written outside the API layer.

### 7.8 Configuration data in the database
✅ Configurable-and-DB-backed: `OptionList` (service categories, payment modes, invoice statuses, drug forms — merged into one table with a `list_type` discriminator, explicitly replacing four near-identical tables in a "v7 redesign"), `Role`/`Permission`/`RolePermission` (custom RBAC, enterprise-tier only), `DoctorSchedule`/`DoctorAvailabilitySlot` (working hours), `RoomAssignment`, `VaccinationSchedule`/`Rule` (per-hospital, cloned from system templates), `Tenant.fee_ownership`/`registration_fee_*`/`default_tax_rate` (billing policy), `Subscription.feat_*` (feature flags).
✅ Configurable-via-environment-variable (not DB, not admin UI): SMS backend selection (`SMS_BACKEND`), email backend, S3 bucket/region, JWT lifetimes, throttle rates, `PLATFORM_ADMIN_SECRET`, field-encryption keys.
✅ Hardcoded-in-code (not configurable at all today): the 6 system roles and their default permission sets (`apps.org.rbac.SYSTEM_ROLE_PERMISSIONS`), the `Is*` permission-class logic itself, NNTM's `VALID_ENTITIES` set, appointment status transition rules (`AppointmentStatusView.ALLOWED_TRANSITIONS`).
**Configuration change flow (verified for `OptionList`):** Hospital admin edits a dropdown value via the admin UI → `OptionList` row created/updated in the tenant DB → next request that creates/validates an invoice/payment/drug reads the current `OptionList` rows via the view/serializer layer → behavior changes immediately, no deploy needed, **except** for `is_system=True` seeded rows which can be relabeled but not deleted (protecting logic that depends on their existence, e.g. the literal string "paid" driving payment reconciliation). ✅

### 7.9 Data lifecycle
✅ Most clinical/financial data is **never hard-deleted** — `compliance` module docstring states this explicitly as a legal requirement, and no `on_delete=CASCADE` chains were found that would silently wipe clinical history; deletions that do exist are either `SET_NULL` (e.g. deactivating a drug catalog entry doesn't corrupt past prescriptions) or `PROTECT` (e.g. you cannot delete a `Patient` that has `Invoice`s, `LabRequest`s, etc. — `on_delete=models.PROTECT` used pervasively for exactly this reason). ✅ Soft-disable pattern used widely instead of deletion: `is_active` flags on `Branch`, `Department`, `Room`, `LabTest`, `Drug`, `BillingService`, `Tenant`, `StaffUser`; `VaccinationSchedule.active` similarly. ✅ Amendment-not-overwrite pattern for corrections: `compliance.RecordAmendment` records a requested correction with before/after values rather than the original field being silently edited (this is explicitly the *planned* rule for the IPD module too, per its spec docs — "clinical records are corrected by amendment, never silently overwritten"). ❓ Whether this amendment discipline is actually enforced at the OPD encounter level today (i.e., is there a hard block preventing a doctor from just editing a signed encounter directly?) was not independently verified beyond the `status == SIGNED` check inferred in `EncounterDetailView.patch()`.

### 7.10 CRUD operations
⚠️ General pattern observed across every tenant app: Create and Read are used constantly; Update is common for master data and for narrow, permitted transitions on transactional records (status fields, not clinical content once signed); **Delete is rare and, where it exists, is almost always a soft-delete (`is_active=False`) rather than a real row deletion.** No view was found that issues a hard SQL DELETE against clinical data (Patient, Appointment, OPDEncounter, Invoice, LabReport). The clearest real hard-delete-adjacent operations found are `FavouriteDeleteView` (a doctor's own saved prescription template — harmless to actually delete) and `RoomAssignmentDetailView`/similar config-table detail views (still master data, not patient data).

### 7.11 Transactions & data consistency
✅ **Confirmed atomic/locked operations:**
  - NNTM (`core/utils/nntm.py`): every sequential number (UHID, invoice, lab report, Rx, queue token) is generated inside `transaction.atomic()` using `SELECT FOR UPDATE` on the `NextNumber` row for that branch+entity — this is the one place in the codebase explicitly engineered against a race condition, and it's used for **every** human-readable sequence number in the system.
  - `OPDEncounter.sign()` — encounter-signed + appointment-done are saved together inside one Python method (though ⚠️ not confirmed to be wrapped in an explicit `transaction.atomic()` block itself; it calls `.save()` twice in sequence within one method, which Django will run as two separate statements unless the caller or a decorator wraps them).
  - Patient registration and portal booking flows (`apps/patients/services.py`, `apps/patients/portal_views.py`) explicitly use `transaction.atomic(using="default")` around the registry-DB writes (creating/reusing `PatientIdentity`, consent records) — ✅ confirmed by direct code inspection (`grep` hits shown in the tables above).
  - `apps/org/views.py` uses `transaction.atomic()` in two places (⚠️ not identified exactly which endpoints without reading those specific line ranges — worth a follow-up read if this matters, e.g. role/permission bulk changes).
✅ **Explicitly NOT wrapped in a single transaction, by design:** invoice auto-generation after encounter sign-off — the code comment states this "never blocks sign-off," meaning a failure in invoice creation does not roll back the clinical sign-off. This is a **deliberate consistency trade-off favoring clinical-record durability over billing completeness** — worth knowing, because it means a small number of signed encounters could in theory end up with no auto-generated invoice, requiring a manual billing desk fix. ❓ Whether any retry/reconciliation job exists for this gap was not found.
❓ **Unconfirmed:** whether the tenant-DB write and the registry-DB HIE write-through (`_sync_to_hie`) are in any way atomic with each other — since they are, by the database-per-tenant architecture, **necessarily two separate database connections**, true cross-database atomicity is not possible with vanilla Django transactions regardless of intent; this is an inherent architectural limitation of the design, not a specific bug, but it does mean a crash between the two writes could leave the tenant-side record without its HIE mirror. No compensating reconciliation mechanism was found.
❓ **Concurrency/locking beyond NNTM:** no other explicit `select_for_update()` usage was found (e.g., for `Stock.quantity` decrements during dispensing, or for the "a bed can never be allocated to two active admissions at once" rule promised for the *planned* IPD module) — the pharmacy dispense flow's concurrency safety under simultaneous dispenses against the same batch was not verified.

### 7.12 Indexing & performance
✅ Explicit `db_index=True` / `models.Index(...)` usage is extensive and clearly intentional: `Appointment` has three composite indexes (`scheduled_date+doctor_user_id`, `patient_id+scheduled_date`, `status+scheduled_date`) tuned exactly for the queue/dashboard/history queries the app actually runs; `OPDEncounter`, `LabRequest`, `Invoice`, `AuditLog`, `NotificationLog`, `SharedVaccination` all carry targeted indexes on their most-filtered fields. ⚠️ ASSUMPTION / POTENTIAL RISK: `org.AuditLog` and `registry.EmergencyAccessLog`/`OTPCode` are append-only, ever-growing tables with no archiving/partitioning strategy found — at high volume (every PHI access logged) these are the most likely tables to become large and eventually need partitioning or an archival job; nothing in the code currently addresses this. ⚠️ ASSUMPTION / POTENTIAL RISK: `pharmacy.StockTransaction` is similarly append-only and could grow large at a busy pharmacy. ✅ Pagination: DRF's `PageNumberPagination`, page size 25, is the global default — applied automatically to any list endpoint that doesn't override it.

### 7.13 Auditability & traceability
✅ `org.AuditLog` answers "who did what, to what, when" for any call site that invokes `core.audit.log_action()` — captures `actor_user_id`/`actor_email`/`actor_role`, `action` (a free-text code like `"encounter.sign"`), `resource_type`/`resource_id`, `patient_id`, `ip_address`, and a JSON `metadata` blob. ✅ It does **not** capture "what was the previous value" for a generic field-level change — that level of detail exists specifically for `compliance.RecordAmendment` (which does store `current_value`/`requested_value`) and for `tenants.TenantAuditLog` (which stores `before_value`/`after_value` for tenant-level admin actions), but not as a generic mechanism for every table. ✅ `log_action()` **never raises** — an audit-write failure is logged and swallowed, never allowed to break the request it's auditing; this is a deliberate reliability trade-off (worth knowing: a busy period with a broken audit DB connection would silently produce **gaps** in the audit trail, not failed requests). ✅ A real historical bug is documented in `org.AuditLog`'s own model docstring: `actor_user_id` used to be typed as a UUID while `StaffUser`'s real PK is a `BigAutoField`, so every staff-actor audit write was silently failing at INSERT time (swallowed by the try/except) until the field type was fixed on 2026-08-17 — meaning **audit history for authenticated staff actions before that date is likely incomplete**, worth flagging explicitly to whoever relies on historical audit data.

### 7.14 Data integrity
✅ **Database-level:** standard Django FK constraints and `unique_together`/`UniqueConstraint`s are used extensively (e.g., one primary branch per staff member, no duplicate staff+branch mapping, no duplicate nurse→doctor assignment, unique `(branch, entity)` NNTM rows). `NOT NULL` is the Django default for non-`blank=True`/`null=True` fields. ✅ **Application-level (not DB-enforced):** every "configurable dropdown" value (`Invoice.status`, `BillingService.category`, `Payment.payment_mode`, `Drug.form`) is validated against `OptionList` rows at the view/serializer layer only — the database itself has no `CHECK` constraint or FK forcing this. ❓ **Frontend-level validation:** not independently verified (frontend code was surveyed for structure, not read for validation logic) — ⚠️ ASSUMPTION that basic form validation exists client-side as is typical, but not confirmed.
✅ File uploads go through `core/file_validation.py`'s magic-byte check (not just trusting the client's claimed MIME type) before ever reaching S3 storage — a real, code-verified integrity control on user-uploaded PHI documents.

### 7.15 Database migrations & version control
✅ Standard Django migrations, one folder per app, committed to the repo. Migration counts observed: `registry` 23, `org` 19, `tenants` 12, `billing` 9, `opd` 9, `patients` 7, `prescriptions` 6, `lab` 5, `notifications` 4, `compliance`/`ai_pipeline`/`tasks`/`clinical` 3 each, `auth_app` 0 (no models). This distribution (registry and org have by far the most migrations) is consistent with those being the most actively evolved parts of the schema. ✅ The retired apps (`clinical`, `tasks`, `ai_pipeline`) each have a final migration that **drops their tables** rather than the app being deleted outright — a deliberate choice to keep migration history resolvable, called out explicitly in each app's docstring. ✅ `README.md` documents the expected process: `python manage.py migrate --database=default` then `python manage.py migrate_tenants` (a custom management command, presumably iterating every registered tenant DB and running tenant-app migrations against each — ⚠️ ASSUMPTION on the exact mechanics, the command's own source wasn't read). ❓ Whether a *new* tenant's database is auto-migrated at onboarding time by the same command, and how schema drift across many tenant databases is monitored/prevented over time, was not confirmed — worth asking directly, since database-per-tenant architectures are notoriously prone to migration drift between tenants if the rollout process isn't rigorous.

### 7.16 Backup & recovery
❓ UNKNOWN — no backup strategy, frequency, retention policy, replication setup, RPO/RTO target, or restore procedure is documented anywhere in the code or handover documents provided. This is a **critical gap** for a database-per-tenant architecture holding PHI (see §18).

### 7.17 Environments
✅ Three Django settings modules exist: `base.py` (shared), `development.py` (DEBUG=True, permissive CORS, SQL query logging, `ALLOWED_HOSTS=["*"]`), `production.py` (DEBUG=False, HSTS/SSL redirect, JSON structured logging, Sentry integration if `SENTRY_DSN` set, strict `CSRF_TRUSTED_ORIGINS`). ❓ No explicit "staging" settings module exists — a staging environment, if one exists, presumably reuses `production.py` with different environment variables (⚠️ ASSUMPTION). ❓ Whether seed/master data differs between environments, and what the actual hosting environments are (cloud provider, container orchestration), is not stated.

### 7.18 Database dependencies (shared tables across modules)
The most cross-module-depended-on tenant-DB tables: `org.StaffUser`/`Branch` (imported by literally every clinical/billing app), `patients.Patient` (imported by lab/pharmacy/billing/compliance/notifications), `opd.Appointment`/`OPDEncounter`/`Prescription`/`PrescriptionItem` (imported by lab, pharmacy, billing). The most cross-module-depended-on registry-DB tables: `tenants.Tenant`/`Subscription` (read on every authenticated staff request), `registry.PatientIdentity`/`PatientAccount` (read on every patient-portal request and every front-desk registration). **Changing any of these five or six tables' shape is the highest-blast-radius schema change possible in this system.**

### 7.19 Database impact analysis (illustrative, not exhaustive)
- **`org.StaffUser`** → depended on by: every app's FK to a doctor/nurse/pharmacist/lab-tech/front-desk actor, every `Is*` permission check (via JWT claims baked from it at login), the entire RBAC system, `DoctorProfile`/`StaffProfile`/`DoctorSchedule`. A breaking schema change here (e.g., changing `role` from a CharField to something else) would ripple through essentially every app in the system and the JWT claim shape itself.
- **`opd.Appointment`** → depended on by: `Vitals`, `OPDEncounter` (1:1s), `LabRequest.appointment_id` (denormalized), the entire queue/dashboard UI, billing's follow-up-fee logic, the patient portal's booking history. Changing its status enum would require touching the frontend queue UI, `AppointmentStatusView.ALLOWED_TRANSITIONS`, and every place that branches on status.
- **`billing.Invoice`** → depended on by: `opd.Prescription.invoice`, `lab.LabRequest.invoice`, the patient portal's invoice list/PDF receipts, revenue reports. A change to how `status` values are validated (currently `OptionList`-based) would need to stay backward-compatible with three different producers writing to the same table.
- **`registry.PatientIdentity`/`awpid`** → depended on by every tenant's `Patient.awpid` field (string match, no FK) — a change to the `awpid` format would require a coordinated update across every tenant database simultaneously, since there is no database-level mechanism to enforce or migrate this centrally.

### 7.20 Database architecture summary

**At a glance:**
- Technology: PostgreSQL, Django ORM, no custom DB objects (views/procs/triggers).
- Pattern: database-per-tenant (shared-nothing for hospital data) + one shared registry DB, custom thread-local router, JWT-derived tenant resolution (never client-supplied).
- Main "schemas" (conceptually, not literal Postgres schemas): Registry (identity, licensing, HIE), per-tenant OPD/Clinical, per-tenant Org/RBAC, per-tenant Billing/Pharmacy/Lab, per-tenant Compliance/Audit.
- Most important relationships: Tenant↔Subscription (1:1), Patient↔Appointment↔{Vitals,OPDEncounter}↔{Prescription,LabRequest}→Invoice, PatientIdentity↔PatientRelationship (guardian/dependent).
- Configuration storage: mostly DB-backed (`OptionList`, `Role`/`Permission`, schedules), some env-var-backed (integrations, secrets), a little hardcoded (system roles, status enums).
- Transactional data: Appointment/Vitals/Encounter/Prescription/LabRequest/Dispense/Invoice/Payment.
- Audit/history approach: single `org.AuditLog` for PHI access/actions (best-effort, never blocks the request, has a documented historical gap), plus append-only ledgers for stock and consent, plus amendment-not-overwrite for corrections.
- Migration strategy: standard Django migrations, per-app, including explicit table-drop migrations for retired apps.
- Backup/recovery: ❓ UNKNOWN — not documented.
- Performance approach: targeted composite indexes on genuinely hot query paths; no caching layer, no read replicas.
- Major dependencies: `org.StaffUser`, `patients.Patient`, `opd.Appointment`, `tenants.Tenant`/`Subscription`, `registry.PatientIdentity`.
- Known risks: append-only audit/log tables with no archiving strategy; cross-database (tenant↔registry) writes are not atomic with each other; invoice auto-generation is deliberately non-atomic with encounter sign-off; historical audit-log gap before 2026-08-17.
- Unknown areas: hosting/infra, backup/DR, staging environment setup, exact tenant-provisioning migration automation, whether `Appointment.patient_id`'s type genuinely matches `Patient`'s PK.

**Architecture diagram (adapted to this application):**
```
Frontend (React/Vite SPA)
        ↓
Backend/API (Django REST Framework, /api/v1/*)
        ↓
Business Services (view classes + core/ helpers: audit, otp, storage, permissions, response)
        ↓
Data Access Layer (Django ORM + core.db_router.TenantDatabaseRouter)
        ↓
PostgreSQL
├── Registry DB ("default")
│     ├── Tenant / Subscription / TenantAuditLog / NextNumber   (licensing & provisioning)
│     ├── PatientIdentity / PatientRelationship / PatientAccount / StaffMobileIndex   (identity)
│     ├── OTPCode / BlacklistedToken                             (auth support)
│     ├── PortalBooking / EmergencyAccessLog                     (cross-hospital portal support)
│     └── Shared* (Diagnosis/Prescription/LabResult/Allergy/Document/Vital/Vaccination)  (HIE)
└── Per-Hospital DB (one per tenant, e.g. "aw_sunrise_clinic")
      ├── Org/RBAC        — Branch, Department, StaffUser, DoctorProfile, Role/Permission, Room
      ├── Patient/Clinical — Patient, Allergy, Appointment, Vitals, OPDEncounter
      ├── Prescription/Lab/Pharmacy — Prescription+Items, LabRequest/Report+Items, Stock, Dispense
      ├── Billing          — BillingService, Invoice+Items, Payment, OptionList
      ├── Compliance/Audit — AuditLog, ConsentRecord, RecordAmendment
      └── Notifications    — NotificationLog
```
(IPD/Admission/Bed/Ward/OT/ICU tables do **not** exist in this diagram because they do not exist in the database — see §17.)

### DATABASE QUESTIONS TO ASK DURING HANDOVER
🔴 What is the actual backup/recovery strategy and RPO/RTO for both the registry DB and every per-tenant DB — and has a restore ever actually been tested?
🔴 How is a new tenant's database provisioned and migrated at onboarding time — is it fully automated (`migrate_tenants` + something else), and what happens if it partially fails?
🔴 What production access controls exist on the databases themselves (who can connect directly, is there a bastion/VPN, are queries logged)?
🟠 Is there any process to detect migration drift across the many per-tenant databases over time?
🟠 Is `Appointment.patient_id`'s type actually consistent with `Patient`'s primary key, and has this ever caused a real bug?
🟠 Is there a plan for archiving/partitioning the ever-growing `AuditLog`/`EmergencyAccessLog`/`OTPCode`/`StockTransaction` tables?
🟠 Is the tenant-DB-to-registry-DB HIE write-through monitored for silent failures (given it cannot be transactionally atomic with the tenant-side write)?
🟢 Why were UUID primary keys chosen specifically for the `opd` app's models and nothing else?
🟢 Is there a data-cleanup/archiving policy once a hospital's subscription is `suspended` for a long time, or is the data retained indefinitely?

---

## 8. CONFIGURATION / CONFIGURABILITY

| What is configurable | Who configures it | Where stored | How it affects runtime | Code change needed? |
|---|---|---|---|---|
| Service categories, payment modes, invoice statuses, drug forms | Hospital admin (billing setup screens) | `billing.OptionList` (tenant DB) | Validated against at the view/serializer layer whenever a matching field is written | No |
| Billing catalog / prices / tax rates | Hospital admin | `billing.BillingService`, `Tenant.default_tax_rate` | Drives auto-generated and manual invoice line pricing | No |
| Registration fee, fee ownership (doctor vs hospital sets consultation fee) | Hospital admin | `Tenant.registration_fee_*`/`fee_ownership` | Changes who can edit `DoctorProfile.consultation_fee` and whether registration is billed | No |
| Doctor working hours / slot duration | Doctor or hospital admin | `org.DoctorSchedule`/`DoctorAvailabilitySlot` | Directly determines which slots the booking engine offers | No |
| Rooms and which doctor sits where/when | Hospital admin | `org.Room`/`RoomAssignment` | Auto-resolved onto new appointments at booking time | No |
| Custom roles & permissions | Hospital admin (enterprise tier only, `feat_custom_roles`) | `org.Role`/`Permission`/`RolePermission` | Extends beyond the 6 hardcoded system roles | No (for granting/revoking); the permission **catalog** itself is a deploy-time constant, not admin-editable |
| Vaccination schedule (which vaccines, ages, mandatory/optional) | Hospital admin (clones a platform template) or platform admin (defines templates) | `registry.VaccinationSchedule`/`VaccinationScheduleRule` | Drives the child-health roadmap shown to nurses/doctors/patients | No |
| Feature flags (lab, pharmacy, WhatsApp, multi-branch, AI voice, patient app, analytics, video, face-recog, custom roles) | Platform admin only | `tenants.Subscription.feat_*` | Gates entire modules/endpoints via `RequireFeature()` permission factory | No |
| License tier & seat limits | Platform admin only | `tenants.Subscription` | Gates via `RequireTier()`; caps doctor/staff/branch counts | No |
| SMS/Email delivery backend | DevOps/deployer (environment variables) | `.env` (`SMS_BACKEND`, `EMAIL_BACKEND`, MSG91/gateway credentials) | Switches between logging-only, MSG91, or a self-hosted Android SMS gateway, with an optional automatic fallback backend | Requires a restart/redeploy, not a code change |
| S3 storage bucket/region/expiry | DevOps/deployer | `.env` | Where uploaded PHI documents live and how long presigned URLs stay valid | Requires redeploy |
| JWT/OTP lifetimes, throttle rates | DevOps/deployer | `.env` + `atomwalk/settings/base.py` defaults | Session length, brute-force resistance | Requires redeploy for env changes; hardcoded defaults require a code change |
| Appointment status transition rules | ❌ Not configurable | Hardcoded in `AppointmentStatusView.ALLOWED_TRANSITIONS` | — | Yes, code change required |
| 6 system roles & their default permissions | ❌ Not configurable | Hardcoded in `apps.org.rbac` | — | Yes |
| NNTM valid entity types | ❌ Not configurable | Hardcoded `VALID_ENTITIES` set in `core/utils/nntm.py` | — | Yes (a real historical bug: `"drug"` was missing from this set and had to be added when the drug catalog's auto-code generation started failing) |

**Configuration change flow example (verified):** Hospital admin adds a new payment mode "UPI - GPay" via Settings → `OptionList(list_type="payment_mode", value="UPI - GPay")` row created in the tenant DB → next time front desk records a payment, the payment-mode dropdown/validation includes the new value immediately → no deploy, no code change. ✅

---

## 9. INVENTORY / RESOURCE MANAGEMENT

- **What resources are tracked?** ✅ Pharmacy drug stock (batch-level, per branch), consultation rooms, doctor time slots (via schedule + appointment bookings), and — only in the *planned, unbuilt* IPD spec — beds/wards/OT slots.
- **Pharmacy stock — how created:** ✅ `Stock` rows created on "receive stock" (batch number, expiry, quantity, unit cost, MRP) by a pharmacist.
- **How allocated/consumed:** ✅ `Dispense` against a specific `Stock` batch decrements `Stock.quantity`; every movement (purchase/dispense/return/expiry write-off/adjustment) is logged in `StockTransaction` with before/after quantities for audit.
- **How availability is maintained:** ✅ `Stock.quantity` is the live count; `Stock.reorder_level` exists as a configured threshold, though whether an active low-stock alert is surfaced anywhere was not confirmed (❓).
- **What happens when something is unavailable?** ❓ Not confirmed what UI/API behavior occurs when a pharmacist tries to dispense more than `Stock.quantity` available — ⚠️ ASSUMPTION that the dispense view validates this and rejects/errors, consistent with the care taken elsewhere in the codebase, but not independently verified.
- **Reservation/allocation logic:** ✅ For **rooms**, `RoomAssignment` is a recurring weekly reservation (doctor+room+day+time), with overlap for the same room+day explicitly rejected at the API layer before being written (per the model docstring) — the same discipline applied to appointment double-booking prevention. ✅ For **doctor time**, an `Appointment` at a given date/time/doctor functions as the reservation; double-booking prevention is validated at booking time.
- **Audit trail:** ✅ Full audit trail for pharmacy stock (`StockTransaction`); no dedicated "room booking history" table was found beyond the `RoomAssignment` rows themselves (which are the current configuration, not a historical log of past bookings — though `Appointment.room_id`/`room_name`/`floor` being baked in at booking time does preserve a historical record of which room a given past visit actually used, even after `RoomAssignment` changes later).
- **Return/cancellation:** ✅ `StockTransaction` has a `"return"` transaction type for returned stock. ✅ A cancelled `Appointment` simply becomes terminal (`status=cancelled`) — the room/slot it held is implicitly freed since availability is computed live from non-cancelled appointments, not from a separate "reserved" flag that would need explicit release.
- **Planned-but-not-built (IPD) resource concepts, per the spec docs:** bed/ward inventory with states `available/reserved/occupied/cleaning`, updated in real time; a rule that "a bed can never be allocated to two active admissions at once" described as something to be *enforced*, not just conventionally avoided; OT slot scheduling with release-on-cancellation. ✅ These are documented **intentions**, not existing code — do not assume any of this exists.

---

## 10. STATUS & STATE TRANSITIONS

### 10.1 Appointment status (✅ FACT — server-enforced in `AppointmentStatusView.ALLOWED_TRANSITIONS`)
```
scheduled ──────┬──> waiting ──────┬──> vitals_done ──┬──> in_progress ──> done
                │                  │                   │
                └──> cancelled     ├──> in_progress     └──> waiting (back-transition allowed)
                                   ├──> cancelled
                                   └──> no_show
```
- `scheduled`: booking made for a future date. Front desk/system. → `waiting` or `cancelled`.
- `waiting`: patient checked in / same-day booking. Front desk/nurse. → `vitals_done`, `in_progress`, `cancelled`, or `no_show`.
- `vitals_done`: nurse has recorded vitals (auto-set by the vitals endpoint, not a manual status click). → `in_progress` or back to `waiting`.
- `in_progress`: doctor has opened/started the encounter (auto-set when an encounter is created against a `waiting`/`vitals_done` appointment). → `done` or back to `waiting`.
- `done`: encounter signed (auto-set inside `OPDEncounter.sign()`, alongside `completed_at`). Terminal for the normal path.
- `cancelled` / `no_show`: terminal, reachable from earlier states as shown.
- **What's affected:** the booking UI, the queue list, the doctor's dashboard, and downstream billing (a `done` encounter is what triggers invoice auto-generation) all key off this field.

### 10.2 OPD Encounter status (✅ FACT)
```
draft ──(sign)──> signed
```
- `draft`: created when doctor starts the visit; editable via `PATCH`.
- `signed`: terminal via the normal API; `signed_at` stamped; triggers the `Appointment→done` transition, invoice auto-generation, and the HIE write-through, all as side effects of one `sign()` call.

### 10.3 Prescription / LabRequest fulfilment choice (✅ FACT, same shape for both)
```
Prescription.status:     active ──> dispensed        (also: active ──> expired)
Prescription.patient_choice: pending ──> in_house | outside
Prescription.payment_status: unpaid ──> pending_online ──> paid   (or unpaid ──> paid directly)
LabRequest.status:        ordered ──> collected ──> processing ──> completed   (or ──> cancelled)
LabRequest.patient_choice / payment_preference / payment_status: same shape as Prescription's
```
- Who changes it: `patient_choice` can be set by the patient (portal) or a nurse on the patient's behalf (`choice_made_by`); `LabRequest.status` progresses via lab-tech actions; `Prescription.status="dispensed"` set when a pharmacist dispenses.

### 10.4 Subscription lifecycle (✅ FACT, `tenants.Subscription.STATUS_CHOICES`)
```
trial ──> active ──> grace (payment lapse, day 1–7) ──> read_only (day 8–30) ──> frozen (day 31–90) ──> suspended (platform review)
```
- Enforced live on every staff-authenticated request (not just at login): `frozen`/`suspended` block everything; `read_only` blocks any non-`GET/HEAD/OPTIONS` request. ❓ What actually advances a tenant through this lifecycle automatically (a scheduled job checking `payment_lapse_since`) versus requiring manual platform-admin action was not found in the code inspected — worth confirming during handover, since an un-automated lifecycle would mean these day-count thresholds are aspirational, not actually enforced by a timer.

### 10.5 Vaccination record lifecycle (✅ FACT, `registry.SharedVaccination.verification_status`)
```
(clinic-administered) ──────────────────────────────────> verified
(self-reported upload) ──> pending_review ──> verified | rejected
(doctor ad-hoc order) ──> ordered ──> [administered → verified, clinic-source] 
(doctor decline) ──> declined  (terminal)
```
- A single field deliberately doing double duty as both "has this upload been reviewed" and "where is this record in its overall lifecycle" — explained at length in the model's own docstring as a considered design choice, not an accidental overload.

### 10.6 Record Amendment lifecycle (✅ FACT, `compliance.RecordAmendment.STATUS_CHOICES`)
```
pending ──> approved (and applied) | rejected (with reason)
```

### 10.7 Planned IPD Admission lifecycle (⚠️ SPEC ONLY — not built; two versions of the spec disagree slightly, see §17)
```
requested ──> admitted (awaiting bed) ──> active ──> discharge_initiated ──> discharged ──> closed
      └──────────────────────────────> cancelled (terminal, only reachable before "active")
```

---

## 11. INTEGRATIONS & DEPENDENCIES

| Integration | Purpose | Data exchanged | Direction | Trigger | Dependency/risk |
|---|---|---|---|---|---|
| AWS S3 (`boto3`) ✅ | Object storage for PHI documents (photos, signatures, lab reports, patient uploads, vaccination certs, hospital logos) | File bytes + metadata | Outbound (upload), inbound (presigned-URL read) | Any file upload/view action | Bucket must be private; blank credentials degrade gracefully to "no file" rather than crashing (per code comment), but **no bucket configured means the upload feature silently doesn't work** in that deployment |
| MSG91 (SMS) ✅ | OTP delivery, notifications | Phone number + templated message | Outbound | OTP request, reminders | Requires a DLT-approved template on the customer's own MSG91 account — "Atomwalk cannot provision this on the hospital's behalf," per a code comment; if unconfigured, falls back to `SMS_BACKEND="log"` (no real send) |
| Self-hosted "SMS Gateway for Android" ✅ | Alternative SMS relay via a phone+SIM instead of a paid aggregator | Same as above | Outbound | Same as above | Requires the phone to be reachable on the same network (Local mode) or via a cloud relay |
| SMTP / console email backend ✅ | OTP delivery, notifications via email | Email | Outbound | OTP request | DEBUG defaults to console (log only); production requires real SMTP credentials, again customer-supplied |
| Sentry (`sentry_sdk`) ✅ | Error tracking | Exception/stack traces (PII scrubbed — `send_default_pii=False`) | Outbound | Unhandled exceptions in production | Optional — only activates if `SENTRY_DSN` is set |
| drf-spectacular ✅ | Auto-generated OpenAPI schema + Swagger UI | N/A (dev tooling) | N/A | `/api/schema/`, `/api/docs/` | "Installed since the start of this project but never wired up until now," per a code comment — i.e. genuinely useful API documentation may not have existed for most of the project's life |
| Payment gateway | ❌ **Not integrated** | — | — | — | ✅ Confirmed absent — "payment" today is a front-desk staff member manually recording a transaction that already happened elsewhere (cash, card via a separate terminal, etc.), per the external-comparison document's direct code inspection. This is a real product gap if online payment collection is an expectation. |
| Celery/Redis (background jobs) | ❌ **Not implemented** | — | — | — | ✅ Referenced only in `.env.example`; no actual task queue exists. The `generate_reminders` notification job and `migrate_tenants` are plain management commands, presumably run via external cron rather than an in-app scheduler (❓ not confirmed how they're actually invoked in production). |
| WhatsApp | ❌ **Not integrated** despite a `feat_whatsapp` flag existing | — | — | — | The feature flag exists in `Subscription` but no WhatsApp Business API integration code was found — ⚠️ ASSUMPTION that this flag is aspirational/reserved for a future integration, not yet wired to anything. |
| Accounting/ERP (Tally, Oracle, Atomwalk ERP) | Mentioned in the "How It Connects" pptx as available via "APIs/connectors" | — | — | — | ⚠️ **No corresponding code was found anywhere in the repository.** This appears to be a roadmap/marketing statement in the pptx, not a built integration — flag this as unverified if it's being represented to stakeholders as existing today. |
| Native mobile apps | ❌ **Do not exist for this codebase** | — | — | — | The `Clinical_HMS_External_System_Comparison.docx` is specifically comparing this web-only HMS against two *separate*, *different* Atomwalk-branded mobile apps built on an unrelated generic CRM backend — see §17 for why this is easy to misread as "this system has a mobile app." |

---

## 12. TECHNICAL ARCHITECTURE

**Plain-language version:** A Django REST API backend talks to one of many PostgreSQL databases depending on which hospital the logged-in user belongs to, decided by reading their login token on every request. A React single-page app is the only client — there's no native mobile app. Files (photos, reports, signatures) are stored in Amazon S3, never directly in the database. Background-ish jobs (reminders, tenant migration) appear to be run as manual/cron-invoked management commands rather than a real task queue.

**Technical version:**
- **Backend:** ✅ Django 4.2.13 + Django REST Framework 3.15.1, Python (version not pinned in what was read — ❓). Custom JWT (PyJWT 2.8.0) rather than `djangorestframework-simplejwt`'s own views (the package is installed but only used for its token-lifetime settings object, `SIMPLE_JWT`, per a code comment — actual issuing/verification is hand-rolled in `apps/auth_app/views.py` and `core/authentication.py`).
- **Frontend:** ✅ React + Vite, plain JS (not TypeScript — `.jsx` files, no `.tsx` seen), `react-router-dom` for routing, `axios` for HTTP, `react-toastify` for notifications, `lucide-react`/`react-icons` for icons. No state-management library beyond React Context (`AuthContext`, `PatientContext`, `PermissionContext`, `TenantContext`, `ThemeContext`) — ❓ no Redux/Zustand/etc. found.
- **Database:** PostgreSQL, database-per-tenant (see §7).
- **APIs:** ✅ REST, versioned under `/api/v1/`, `drf-spectacular` for OpenAPI schema/Swagger UI (recently wired up per a code comment). Standard response envelope enforced project-wide: `{success, message, data}` / `{success, message, errors}` (`core/response.py` — "ALL views must use these functions, never return raw serializer data").
- **Authentication/authorization:** ✅ Custom JWT (HS256, separate signing key from Django's `SECRET_KEY`), three separate login surfaces (staff/platform/patient), JWT-carried claims drive both tenant DB routing and role-based permissions, a registry-DB token-blacklist table makes logout actually revoke a still-valid token, live subscription/active-status re-checks on every request (not just at login).
- **Messaging/events:** ❌ No message queue, no event bus, no WebSockets/Channels found. Real-time-feeling features (the OPD queue) are ⚠️ ASSUMED to be implemented via frontend polling, not push.
- **Storage:** ✅ AWS S3 for files (private bucket, presigned URLs, magic-byte validation before upload) — explicitly replacing an older base64-in-Postgres-TextField convention that is called out as still present on a specific list of legacy fields (`StaffUser.photo`, `PatientAccount.photo`, `Tenant.logo`, `DoctorProfile.digital_signature`, `LabReport.file_url`, and the `registry.Shared*` file fields) that have **not yet been migrated** to the new S3 pattern as of this inspection.
- **Deployment:** ✅ `gunicorn` (WSGI) + `whitenoise` (static file serving, compressed + manifest-hashed) referenced in `requirements.txt`/settings; `ASGI_APPLICATION` is also defined but nothing found that actually requires ASGI (no Channels/async views identified) — ⚠️ ASSUMPTION this is present for future-proofing or an unrelated deployment requirement, not actively used.
- **Infrastructure:** ❓ UNKNOWN — no IaC (Terraform/CloudFormation), Dockerfile, or CI/CD pipeline was inspected in this pass (a `.github` directory exists in the repo root but its contents were not read — worth checking directly for CI configuration).
- **Frameworks/key libraries:** Django, DRF, `django-environ`/`python-decouple` (env config), `django-cors-headers`, `django-filter`, `Pillow` (image handling), `reportlab` (PDF generation — invoices, prescriptions, encounter summaries), `qrcode` (Emergency QR), `phonenumbers` (mobile validation), `cryptography` (field-encryption groundwork, not yet applied to any field per a code comment), `sentry-sdk`, `python-json-logger`.

---

## 13. BUSINESS RULES

Explicit rules found directly in code/comments (✅), organized as IF/THEN where possible:

1. ✅ IF a hospital's subscription `status` is `frozen` or `suspended` THEN every API request from that hospital's staff is rejected (`PermissionDenied`), regardless of role.
2. ✅ IF a hospital's subscription `status` is `read_only` AND the request method is not GET/HEAD/OPTIONS THEN the request is rejected.
3. ✅ IF a staff member's `is_active` flag is False (deactivated) THEN their next request is rejected even if their JWT hasn't expired yet — checked live, not just at login.
4. ✅ IF a booking is for today's date THEN the new `Appointment` starts in `waiting`; ELSE it starts in `scheduled`.
5. ✅ IF an `OPDEncounter` is signed THEN its linked `Appointment` automatically becomes `done` in the same operation — a doctor cannot sign an encounter without the appointment being marked complete.
6. ✅ IF an appointment's `appointment_type` is `followup` THEN the doctor's `followup_fee` is charged (falling back to `consultation_fee` if the doctor never set one) instead of the normal consultation fee.
7. ✅ IF a `LabRequest`/`Prescription` is billed THEN the billing happens at the point the service is actually rendered (report delivered / first dispense) — not at order time.
8. ✅ IF a second dispense happens against the same prescription THEN it is added to the **same** invoice as the first dispense, not a new one.
9. ✅ IF a patient has no mobile number of their own (a dependent) THEN they never get a `mobile_hash`, and are instead deduplicated via their guardian's mobile hash plus an explicit relationship record.
10. ✅ IF a patient has not given HIE consent THEN no other hospital can see their shared clinical history, regardless of whether that history exists in the registry DB.
11. ✅ IF a `Role` (custom, table-driven) is still assigned as someone's **primary** role THEN it cannot be deleted (`on_delete=PROTECT`) — but it CAN be deleted if only held as an **extra** role via `UserRole` (`on_delete=CASCADE`), because the person still has a fallback identity.
12. ✅ IF a doctor works at more than one branch THEN their `StaffUser.branch` (legacy single FK, still what JWTs carry) remains their "primary" branch, and `StaffBranchMapping` only adds *additional*, explicitly-selectable branches — changing this mapping never changes default scoping for existing flows.
13. ✅ IF a room assignment would overlap an existing one for the same room+day THEN it is rejected at the API layer before being written — the same discipline applied to appointment double-booking.
14. ✅ IF an `OptionList` row is flagged `is_system=True` THEN it cannot be deleted via the API (though it can be relabeled) — because backend logic depends on specific stored values (e.g., the literal string "paid") continuing to exist.
15. ✅ (Explicitly stated, PLANNED for IPD, not enforced anywhere today since IPD doesn't exist): "A bed can never be allocated to two active admissions at once — this is enforced, not just conventionally avoided," and "Orders are never edited in place — a change discontinues the old order and creates a new one, both kept in history."
16. **Implied rule** (⚠️ not stated as a single sentence anywhere, but consistent across every module): staff never originate a clinical decision outside their role — a front-desk user cannot write a diagnosis, a nurse cannot order an admission or write a prescription, a pharmacist cannot alter prescription content. This is enforced by the combination of role-scoped permission classes and which fields each role's views expose, rather than by one central rule.
17. **Unknown rule area:** ❓ minor/guardian consent signing process and medico-legal-case (MLC) handling are both explicitly flagged as *undecided even in the planning documents* ("[OPEN QUESTION]") — these gaps exist in the product's own thinking, not just in what was implemented.

---

## 14. NOTIFICATIONS & EVENTS

- **SMS** ✅ — OTP codes (login/registration/password-reset), routed through `SMS_BACKEND` (log/MSG91/Android gateway, with an optional automatic fallback backend on send failure).
- **Email** ✅ — Same OTP flows, alternative channel to SMS; console-logged in DEBUG, real SMTP in production.
- **In-app notifications** ✅ — `notifications.NotificationLog` with `channel` including `"in_app"`, read via `PortalNotificationsView`/marked read via `PortalNotificationMarkReadView`; a `reference` field provides idempotency (e.g. `"appt_reminder:<uuid>"`) so a daily reminder job re-run doesn't double-notify.
- **Generated reminders** ✅ — a `generate_reminders` management command exists (referenced in the `notifications` app's own docstring) — ❓ how/when this is actually invoked in production (cron? manual?) was not confirmed, since no Celery/scheduler was found.
- **Push notifications** ❌ — not implemented (no native mobile app, no web-push code found; `DeviceToken` model was explicitly retired as dead).
- **System events triggered automatically:** appointment status auto-advances (vitals recorded → `vitals_done`; encounter started → `in_progress`; encounter signed → `done`), invoice auto-generation on encounter sign, HIE write-through on diagnosis/prescription/lab-result/allergy/vital/vaccination events, JWT auto-registration of a tenant DB config on first use after a restart (lazy re-registration in `JWTTenantMiddleware`).
- **Who receives what:** ⚠️ Not exhaustively mapped from the notification-content templates themselves (not read in full) — but structurally, patients receive appointment/OTP/reminder notifications via the portal and SMS/email; staff receive nothing beyond in-app UI state changes, as no staff-facing notification channel was found besides the live queue/dashboard views themselves.

---

## 15. REPORTS & DOCUMENTS

| Document | Generated by | When | Contents | Where used |
|---|---|---|---|---|
| Invoice PDF ✅ | `billing.InvoicePDFView` (reportlab) | On demand, any time after invoice creation | Line items, tax, discount, total, paid amount, hospital branding | Front desk, patient portal |
| Encounter summary PDF ✅ | `opd.EncounterSummaryPDFView` (reportlab) | On demand after signing | SOAP note, diagnosis, plan — explicitly replaces an older, purely client-side plain-text download that "could never reflect anything not already sitting in the browser's own state" | Doctor, patient (handed at end of visit) |
| Prescription receipt PDF ✅ | `patients.PortalPrescriptionReceiptPDFView` | On demand from the portal | Drug lines, dosage, instructions | Patient portal |
| Lab report file ✅ | Uploaded by lab tech (`LabReportUploadView`), delivered (`LabReportDeliverView`) | On report completion | Result values (`LabReportItem`), or an uploaded file (PDF/image) | Lab tech, doctor, patient portal |
| Emergency QR summary ✅ | `patients.emergency_views.EmergencySummaryView` | On patient-triggered generation, valid ~20 min | Critical facts (allergies, active diagnoses, etc. — exact field list not fully enumerated) | Any viewer with the link/QR, no login |
| Revenue report ✅ | `billing.RevenueReportView` | On demand | Aggregated payment/revenue data | Hospital admin/billing desk |
| Tenant audit log ✅ | `platform_admin.TenantAuditLogView` / `tenants.TenantAuditLog` | On demand | Platform-admin actions on a given hospital | Platform admin |
| Compliance audit log ✅ | `compliance.AuditLogListView` (reads `org.AuditLog`) | On demand | Who did what, to which patient record, when | Hospital admin/compliance staff |
| API schema / Swagger UI ✅ | `drf-spectacular`, auto-generated | Always available at `/api/schema/`, `/api/docs/` | Full OpenAPI spec of every endpoint | Developers |
| Discharge summary (planned, IPD) | ❌ Not built | — | Per the spec: diagnosis, treatment, medications, instructions, follow-up — with an "AI-assisted" auto-draft from stay data described as an *intended* feature | — |

---

## 15A. SECURITY & ACCESS CONTROL

- **Login:** ✅ Three separate surfaces (staff/platform/patient), each issuing the same custom JWT shape with different claims. Staff can log in via mobile, (hospital-code + employee ID), or email; patients via mobile/email+password or OTP.
- **Authentication:** ✅ Custom PyJWT (HS256), signing key separate from Django's `SECRET_KEY` (so a `SECRET_KEY` rotation doesn't invalidate every session, and vice versa) and from the OTP hashing pepper (independently rotatable). Access tokens default to 60 minutes, refresh tokens to 7 days (both configurable via env). Logout uses a registry-DB blacklist table keyed by JWT `jti` — checked on every authenticated request, so logout has an immediate effect rather than waiting for natural expiry.
- **Authorization:** ✅ Two layers — hardcoded `Is*` DRF permission classes (the one actually enforced everywhere, per the external comparison document) and a fully-modeled but largely-unused table-driven `Role`/`Permission` system for enterprise-tier custom roles. `IsPlatformAdmin`/`IsPatient` are pure literal role checks, never satisfiable via a custom Role bundle — a deliberate boundary.
- **Data visibility / tenant isolation:** ✅ Enforced at the database level (separate physical database per hospital), not just at the query level — a materially stronger guarantee than row-level tenant filtering. The tenant DB alias is derived server-side from the verified JWT, never accepted as client input.
- **Audit logs:** ✅ `org.AuditLog` (PHI access/actions, best-effort, one documented historical gap before 2026-08-17), `tenants.TenantAuditLog` (platform actions), `compliance.ConsentRecord` (append-only consent trail), `registry.EmergencyAccessLog` (Emergency QR generation/viewing).
- **Sensitive operations requiring extra scrutiny:** ✅ Emergency QR generation requires fresh explicit consent every time (not a standing preference). ✅ Staff/patient deactivation takes effect on the very next request, not just at next login. ✅ File uploads are magic-byte validated before being trusted, regardless of client-claimed MIME type.
- **Rate limiting:** ✅ Global DRF throttles (anon 100/min, authenticated user 300/min) plus scoped throttles for `login` (10/min), `otp` (6/min), and the public `emergency` endpoint (20/min/IP) — explicitly added because "no rate limiting existed anywhere (including login) before this," per a code comment, implying this was a deliberately-closed gap at some point in the project's history.
- **What is NOT documented / not found:** ❓ Whether multi-factor authentication beyond OTP-as-a-login-method exists for staff; ❓ whether there's any IP allowlisting for platform-admin or direct-database access; ❓ formal penetration-testing or security-audit history.

---

## 16. EXCEPTIONS & EDGE CASES

**Documented in code:**
- ✅ A hospital with a lapsed subscription moving through `grace → read_only → frozen → suspended` progressively restricts, then fully blocks, access — a graceful degradation path rather than an abrupt cutoff.
- ✅ A missing S3 bucket configuration degrades file-related features to "no file" rather than a 500 error.
- ✅ A missing/invalid `db_name` in a JWT is rejected with 401 rather than allowed to silently query the wrong (or a nonexistent) database — explicitly checked against `Tenant.objects.filter(db_name=..., is_active=True)` before lazily registering that DB alias.
- ✅ A `PatientAccount` whose numeric ID has been reassigned (e.g. after a registry-DB reseed during a go-live) is caught and rejected on the next request — a specific, real-world edge case the authentication code was written to defend against, per its own extensive inline comment.
- ✅ A drug not in the catalog can still be prescribed freeform (nullable FK) — the system doesn't force strict catalog compliance at the point of prescribing.
- ✅ Follow-up visits are billed and labeled differently from first consultations, rather than "identically to a first consultation" (a bug the current code explicitly fixed, per its own comment).
- ✅ A prescription/lab test the patient chooses to fulfil "outside" the hospital is still tracked (payment/choice fields, and an outside lab report can be attached via patient document upload) rather than simply falling out of the system.

**Documented as explicitly unresolved (in the planning docs, not the live system):**
- ❓ [OPEN QUESTION in the spec] Minor/guardian consent — who signs, how a guardian's identity is verified.
- ❓ [OPEN QUESTION in the spec] Medico-legal cases (MLC) — no flag or distinct workflow exists even in the plan; currently would just follow the generic Emergency path with nothing marking it as an MLC.

**Recommended to clarify (not stated anywhere — genuine open questions for the previous team):**
- 🟡 What happens if a pharmacist attempts to dispense more than the available `Stock.quantity`? (Not confirmed either way.)
- 🟡 What happens if two staff members try to book the last available slot for a doctor at the exact same moment — is there a lock, or a possible race condition, given no `select_for_update()` was found on the appointment-booking path itself (only on NNTM)?
- 🟡 What happens to `Appointment.room_id`/`room_name`/`floor` if the referenced `Room` is later deactivated — since the appointment holds a denormalized copy, presumably nothing (the historical record is preserved), but this wasn't independently verified.
- 🟡 Given invoice auto-generation deliberately doesn't block encounter sign-off, is there any process (manual or automated) to catch and fix an encounter that ended up with no invoice?

---

## 17. WHAT IS MISSING? (and the contradictions worth resolving first)

### 17.0 The contradiction that matters most: IPD is described as built in one document and explicitly marked unbuilt in another
- `IPD_Admission_Feature_Documentation_v2.docx` states, in its own scope table: **"Nothing described here is built yet — this is planning and specification only."** This is unambiguous.
- `HMS_OPD_IPD_HowItConnects_updated_v2.pptx`, however, is written entirely in **present tense**, as one continuous "how it all connects" description covering both OPD and IPD with no visual or textual distinction between "this exists" and "this is planned" — e.g. slide 11 says "Bed & Ward Inventory: live ward/room/bed availability... updated in real time," and slide 21's closing summary literally counts "Modules across OPD + IPD: 8 + 1" as if both halves are equally real. A reader who only sees this pptx (a very plausible scenario — it's the kind of deck that gets shown to investors or new hires first) will walk away believing IPD is a working part of the product. **It is not.** Direct code inspection confirms: no `ipd` Django app, no admission/bed/ward/OT/ICU models anywhere, no corresponding frontend pages, and the codebase's own `apps.clinical` app (which once held generic inpatient-adjacent clinical models) was explicitly retired as dead code.
- `Clinical_HMS_External_System_Comparison.docx` — a *third*, independently-produced document — directly and explicitly resolves this ambiguity in the platform's favor: **"No IPD/admission/ward/bed/nursing/surgery module — the system is OPD-only today"** and **"our HMS is OPD-only by design today."** This document should be treated as the most reliable single source on what is actually live, since it states plainly that it was produced by direct code inspection.
- **Resolution for a new developer:** treat every OPD-side claim in the "How It Connects" deck as live/real, and every IPD-side claim (slides 10–16, plus the IPD-related bullets embedded in slides 7 and 9) as **aspirational/planned only**, regardless of the present-tense phrasing.

### 17.1 A second, smaller contradiction: the two versions of the IPD Admission spec disagree on the data model
- `IPD_Admission_Feature_Documentation.docx` (v1) defines a whole extra entity, **Admission Referral**, to model nurse-initiated escalations and walk-in patient requests being routed to a doctor for review before an `Admission` record can exist. It also names the admitting-doctor field `attending_doctor_id`.
- `IPD_Admission_Feature_Documentation_v2.docx` (v2, dated later) **removes the Admission Referral entity entirely**, simplifies the story to "only a doctor can order an admission, front desk always logs it," and renames the doctor field to `ordering_doctor_id` with a separate `logged_by_staff_id`.
- Since neither version is built, this isn't a code bug — but it is a **live disagreement between two versions of the same specification document sitting in the same folder**, and whoever picks up IPD work next needs to know which one is authoritative (⚠️ ASSUMPTION: v2, being the later-dated, explicitly-versioned file, supersedes v1 — but this should be confirmed with whoever wrote them, not assumed).
- Additionally, `IPD_Full_Cycle.pptx` (a third IPD document, a "quick-reference companion") explicitly states it summarizes a document called **`IPD_Complete_Workflow_Functional_Requirements.docx`** — describing all 8 phases of the full IPD cycle in detail, including bed allocation, daily care, procedures, discharge. **This document does not exist anywhere in the folder that was provided.** Either it was never delivered as part of this handover, or it exists somewhere else and needs to be requested — this is a real, concrete gap, not a stylistic one, since the pptx is explicitly described as only "the map," with that missing document being "the territory."

### 17.2 Functional gaps
- 🟠 No electronic payment gateway — all "payment" is manual staff-recorded, despite the frontend and appointment model having a `pay_online` preference option that isn't wired to a real gateway.
- 🟠 No background job queue — reminders/scheduled tasks rely on management commands with an unconfirmed invocation mechanism.
- 🟠 `apps.tasks` (a complete, working staff task-assignment backend) has zero frontend consumers — a fully-built feature sitting unused.
- 🟠 `notifications` app has models and a generation command but no dedicated URL mount of its own.
- 🟠 IPD/Admission/Ward/Bed/OT/ICU/Discharge — entirely unbuilt, as covered above.

### 17.3 Technical gaps
- 🟠 No CI/CD pipeline contents were reviewed (a `.github` folder exists but wasn't opened in this pass).
- 🟠 No Dockerfile/IaC was found in the top-level listing reviewed — containerization/infra-as-code status is unconfirmed.
- 🟠 Legacy base64-in-Postgres file storage still exists on a specific, named list of fields that haven't been migrated to the newer S3 pattern.
- 🟠 `ASGI_APPLICATION` is configured but no async/WebSocket usage was found — unclear if this is load-bearing for anything.

### 17.4 Database gaps
- 🔴 No backup/recovery/DR documentation found anywhere (see §7.16).
- 🟠 No confirmed automated tenant-DB migration-drift detection.
- 🟠 `Appointment.patient_id`/`doctor_user_id` typed as UUID with only a comment (not an enforced FK) pointing at models whose actual PK types weren't independently cross-checked in this pass.

### 17.5 Deployment/DevOps gaps
- ❓ Hosting provider, environment topology (dev/staging/prod), container orchestration, and secrets management approach are all unconfirmed beyond "reads from environment variables."

### 17.6 Configuration gaps
- 🟢 `feat_whatsapp` feature flag exists with no corresponding WhatsApp integration code found.
- 🟢 ERP/accounting connector claims in the pptx (Tally, Oracle, "Atomwalk ERP") have no corresponding code found.

### 17.7 Integration gaps
- 🟠 SMS/Email are both configured to degrade to logging-only by default — worth confirming which hospitals, if any, currently have a real gateway configured in production.

### 17.8 Security/access gaps
- 🟡 MFA beyond OTP-as-login-method: not found.
- 🟡 Production database access controls: not documented.

### 17.9 Business-rule gaps
- 🟠 Minor/guardian consent and MLC handling are explicitly open questions even in the planning documents, let alone the live system.
- 🟡 Low-stock / dispense-exceeding-quantity behavior not confirmed.

### 17.10 Operational/support gaps
- ❓ On-call/incident-response process, SLAs, and support escalation paths were not part of any document provided.

---

## 18. QUESTIONS TO ASK DURING HANDOVER

🔴 **Critical**
1. Is `IPD_Complete_Workflow_Functional_Requirements.docx` (referenced by `IPD_Full_Cycle.pptx` as the authoritative full-cycle spec) available somewhere, and if so, can it be provided? It appears to be missing from this handover.
2. What is the actual backup/recovery strategy for the registry DB and every per-tenant DB, and has a restore ever been tested?
3. Between `IPD_Admission_Feature_Documentation.docx` (v1) and `_v2.docx`, which is authoritative, and is any IPD implementation work already scheduled/committed against either version?
4. Is there a payment gateway integration planned or in progress, given the current system is 100% manual payment recording despite a `pay_online` field already existing on the appointment model?

🟠 **Important**
5. How is a new tenant's database actually provisioned and migrated at onboarding — is it fully automated, and what's the failure/rollback path if it partially completes?
6. Is `apps.tasks` (fully built, zero frontend usage) intended to be wired up, deprecated formally, or left as-is?
7. What actually advances a `Subscription` through its `trial → active → grace → read_only → frozen → suspended` lifecycle — is there an automated job, or is this currently a manual platform-admin process?
8. What is the CI/CD pipeline (the `.github` folder wasn't reviewed in this pass) and how are migrations actually rolled out to production and to every tenant DB?
9. Is the base64-in-Postgres-TextField legacy storage pattern (still present on several named fields) scheduled to be migrated to S3, or intentionally left as-is for those specific fields?
10. Are SMS/Email gateways actually configured and sending in any live production hospital today, or is everything currently running on the log-only fallback?

🟢 **Nice to know**
11. Why were UUID primary keys chosen specifically for the `opd` app's models and not elsewhere in the codebase?
12. Is the table-driven `Role`/`Permission` RBAC system in active use by any real enterprise-tier customer today, or is it built-but-unused so far?
13. Is there a product decision already made on minor/guardian consent and medico-legal-case handling that simply hasn't made it into the spec documents yet?
14. What's the actual status of the two Atomwalk-branded mobile apps referenced in the comparison document (`Doctor_HMS`, `health-care-Apps`) — are they live products, prototypes, or abandoned experiments, and do they share any backend with this system at all (the comparison document states they do **not**)?

---

## 19. NEW DEVELOPER CHEAT SHEET

1. **What it does:** Multi-tenant OPD hospital/clinic management system + cross-hospital patient portal + platform-admin onboarding console. IPD/admission/ward/bed is fully speced but **not built**.
2. **Main users:** Hospital staff (admin, doctor, nurse, front desk, lab tech, pharmacist, or a custom bundle role), patients (via portal), Atomwalk platform admins.
3. **Main modules:** `org` (staff/RBAC/rooms/schedules), `patients` (patient records + the entire portal), `opd` (appointments/vitals/encounters/prescriptions — the clinical core), `lab`, `pharmacy`, `billing`, `compliance` (DPDP), `registry`+`tenants` (cross-tenant identity, licensing, HIE — registry DB only). Ignore `clinical`, `tasks`, `ai_pipeline` — retired, empty, kept only for migration history.
4. **Most important workflow:** Register → Book → Check-in/Queue → Vitals → Consultation (sign encounter auto-completes the appointment, auto-drafts an invoice, and write-throughs to the cross-hospital HIE) → Prescription/Lab (in-house or outside) → Dispense/Report → Billing/Payment. Everything else is a variation or a supporting flow around this spine.
5. **Most important DB entities:** `Tenant`/`Subscription` (registry), `PatientIdentity`/`PatientAccount` (registry), `Patient` (tenant), `Appointment`→`Vitals`/`OPDEncounter`→`Prescription`/`LabRequest`→`Invoice` (tenant). Two physically separate databases per hospital's data: registry (shared) and tenant (per hospital) — never joined by a real FK, only matched by application code via `awpid`/`tenant_id`/`db_name`.
6. **Important configurations:** `OptionList` (billing/pharmacy dropdowns), `Role`/`Permission` (custom RBAC, enterprise only), `DoctorSchedule`/`RoomAssignment` (drives booking), `Subscription.feat_*`/tier/seat-limits (drives what a hospital can even see).
7. **Important integrations:** AWS S3 (files), MSG91/Android-gateway (SMS), SMTP (email), Sentry (errors) — all customer/deployment-configured via environment variables, all optional/degradable. No payment gateway, no Celery/Redis, no native mobile app, no WhatsApp integration despite a feature flag existing for it.
8. **Important business rules:** subscription status gates every request live; role-based `Is*` permission classes are the real enforcement layer; billing happens at service-rendered time, not order time; encounter sign-off is the one "big atomic-feeling" operation in the system (though invoice generation is deliberately decoupled from it); tenant DB isolation is physical (separate database), not just a `tenant_id` column.
9. **Known technical risks:** invoice generation can silently fail without rolling back a signed encounter; the tenant-DB↔registry-DB HIE write cannot be truly atomic across two databases; `AuditLog`/`EmergencyAccessLog`/`OTPCode`/`StockTransaction` have no archiving strategy and will grow indefinitely; a documented historical audit-log gap exists before 2026-08-17; no confirmed backup/DR strategy.
10. **Before taking ownership, you absolutely need to:** (a) get `IPD_Complete_Workflow_Functional_Requirements.docx` or confirm it doesn't exist and IPD planning stopped at the two Admission-phase docs + the Full-Cycle pptx; (b) get a straight answer on backup/DR; (c) understand exactly which of the two RBAC systems (hardcoded `Is*` vs. table-driven `Role`/`Permission`) you're expected to extend for new permission checks; (d) confirm whether any hospital currently has a real SMS/email gateway configured, since the default is silent no-op logging; (e) read `core/authentication.py`, `core/middleware.py`, and `core/db_router.py` end-to-end yourself — they are short, extremely well-commented, and are the three files that determine how *every single request* in the system behaves.

---

## 20. FACT / ASSUMPTION / UNKNOWN — RECAP

This labeling was applied inline throughout every section above rather than only here, per the instruction to never present an assumption as fact. As a rough census of confidence: the **overwhelming majority of claims about the built OPD/portal/platform-admin system are ✅ FACT**, directly grounded in model definitions, URL configurations, middleware/permission code, and the unusually extensive inline code comments this codebase already contains (many of which document their own historical bugs and fixes, which is why this report could cite several real past incidents by name). The **IPD material is treated throughout as either explicitly-labeled planning/spec content or explicitly flagged as a contradiction** — never presented as built. The **thinnest area of confidence** is view-layer business logic that wasn't read line-by-line for every single endpoint (frontend form validation, exact dispense-quantity-exceeded behavior, exact CI/CD and infrastructure setup) — these are called out individually as ❓ UNKNOWN wherever they appear rather than guessed at.

---

# IF I HAD TO UNDERSTAND THIS APPLICATION IN ONE DAY

1. **First hour — the shape of the system, not the code:** Read `README.md`, then this document's §0 (the OPD-vs-IPD framing) and §1 (overview). Get the one-sentence mental model fixed before touching code: *multi-tenant OPD system, database-per-hospital, IPD is a spec, not a feature.*
2. **Next hour — how a request actually flows:** Read, in order, `core/middleware.py`, `core/db_router.py`, `core/authentication.py`, `core/permissions.py`. These four short files determine tenant routing, auth, and access control for literally every request in the system. Everything else is downstream of understanding these.
3. **Next 90 minutes — the clinical spine:** Read `apps/opd/models.py` in full, then `apps/opd/views.py`'s `AppointmentStatusView`, `EncounterCreateView`/`EncounterSignView`, and `_auto_generate_invoice`. This is the busiest, most central app — understanding `Appointment`'s status machine and `OPDEncounter.sign()`'s side effects unlocks how billing, lab, and pharmacy all get triggered.
4. **Next hour — identity and multi-tenancy:** Read `apps/tenants/models.py` and `apps/registry/models.py` in full. Understand why `Patient.awpid` is a string, not an FK, and what the `Shared*` tables are for (the HIE mechanism) — this is the part of the architecture most likely to surprise a developer used to single-database systems.
5. **Next hour — the money and the supply chain:** Read `apps/billing/models.py`, `apps/lab/models.py`, `apps/pharmacy/models.py`. Notice how all three converge on `Invoice` from different directions, and how `OptionList` replaces what would otherwise be five separate configuration tables.
6. **Next 45 minutes — org/RBAC:** Read `apps/org/models.py` and skim `core/permissions.py` again with fresh eyes. Understand the `role`/`acts_as`/custom-Role distinction — it's used everywhere but easy to misread on a first pass.
7. **Last hour — walk the actual demo:** Use the credentials in `INVESTOR_DEMO_CREDENTIALS.md`/`EMPLOYEE_LOGIN_CODES.md` to log in as a front-desk user, then a doctor, then check the patient portal, following exactly the journey in this document's §3.1. Seeing the real system reinforces everything read above far faster than more reading would.
8. **Whenever you get to it, not necessarily today:** Skim the three IPD documents once, purely so you recognize them and don't confuse their contents with the live system when they inevitably come up in a planning meeting. Do not spend real time studying their data model until IPD is actually greenlit for implementation — and when it is, read this document's §17.1 first so you don't accidentally build against the superseded v1 spec.



