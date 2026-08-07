# Atomwalk HMS — Onboarding, Authentication & RBAC Architecture

Status legend used throughout: **[BUILT]** exists in the codebase today · **[GAP]** doesn't exist, real limitation · **[RECOMMEND]** proposed change, not yet built.

---

## 1. Why DOB-based password reset is the wrong long-term answer

Quick note before the design, since it's what prompted this: date of birth is not a secret. It's low-entropy (365ish values), frequently public (documents, social media, coworkers), and it never rotates — once known, it's permanently known. It's a "security question," and the industry moved away from security questions over a decade ago after they turned out to be the weakest link in most account-recovery flows. DOB-verification is what you reach for when you have no SMS/email gateway and don't want to force every reset through an admin — a stopgap, not a control. Section 3.3 replaces it with the two mechanisms that are actually used in production: OTP over a channel you've already proven you own, and admin-mediated reset as the fallback.

---

## 2. Onboarding flow

### 2.1 Platform Admin provisions a tenant **[BUILT]**

```
Platform Admin
  → creates Tenant (name, subdomain, db_name, city, state, gstin)
  → assigns subscription tier (starter / growth / pro / enterprise)
      → tier sets max_doctors, max_branches, max_staff, feat_* flags
        (single source of truth: apps/tenants/constants.py)
  → system provisions an isolated PostgreSQL database for the tenant
  → system runs tenant-app migrations against that database
  → system creates the initial Hospital Admin StaffUser
      → temp password generated server-side, must_change_password=True
  → tenant is now active; hospital cannot self-register — provisioning
    is the ONLY way a tenant comes into existence
```

This already matches your "Approach 2" requirement exactly: no invite-based self-registration anywhere in the staff/admin path. The only self-registration in the system is the **patient portal** (patients registering themselves as consumers of the service) — a different actor, correctly separate from staff onboarding.

**[GAP]** Temporary credentials are returned in the API response for the platform admin to relay manually (copy-to-clipboard button exists). There's no SMS/email gateway wired in, so "receives temporary credentials through email/SMS" isn't literally true yet — the platform admin currently hand-delivers them. This is the same gap that shows up again in section 3.3.

**[RECOMMEND]** Wire an SMS gateway (MSG91, Gupshup, or similar — all have India-first pricing and DLT-registered templates, which is a regulatory requirement for transactional SMS in India) and/or an email provider (SES/Postmark). Once that exists, temp-credential delivery and OTP-based reset both become real instead of manual.

### 2.2 Hospital Admin first login — forced password reset **[BUILT]**

```
Hospital Admin logs in with temp password
  → StaffLoginView returns {access, refresh, must_change_password: true}
  → frontend redirects to /change-password before anything else is reachable
  → ChangePasswordPage posts new password (no current-password check needed —
    they just proved they know the temp password by logging in with it)
  → must_change_password flips to false
  → normal dashboard access begins
```

This is live for every staff role, not just Hospital Admin — anyone created with a temp password (invited by Hospital Admin, or reset by an admin) goes through the same forced-reset gate on next login.

### 2.3 Hospital Admin builds out the hospital **[BUILT]**

Branches → Departments → Staff (doctor / nurse / front_desk / lab_tech / pharmacist), each capped by the tenant's subscription limits (section 5 covers enforcement). Every invite generates a temp password server-side and forces reset on first login — same mechanism as 2.2, no self-registration anywhere in this chain.

---

## 3. Authentication design

### 3.1 Primary login identifier — recommendation

Your instinct to want flexibility (email OR mobile OR employee ID) is right for the India healthcare market, but I'd push back gently on making all three equally "primary" — that has real costs (see 3.1.3). Here's the tradeoff:

| Option | Fit for India healthcare |
|---|---|
| Email only | Poor — nurses, front desk, and lab staff frequently don't have an official work email, especially at smaller clinics. |
| Mobile only | Strong — near-universal, no infra dependency, doubles as the OTP channel. Weak point: mobile numbers get reassigned by telcos after ~90 days of inactivity in India, so a departed employee's old number can eventually be re-issued to someone else. |
| Employee ID only | Strong for large/enterprise hospitals with existing HR systems, but a new clinic has no employee ID scheme on day one — forces you to invent one just to onboard staff. |
| Email/mobile/employee ID, any one works | Maximum flexibility, but see the cost below. |

**3.1.1 Recommendation: mobile number as the primary/required identifier, with email and employee_id as optional secondary identifiers a hospital admin can add.**

This is what's actually built today **[BUILT]** — `StaffUser.phone` is required + unique per tenant DB, and a registry-wide `StaffMobileIndex` (mobile → tenant) lets login work without asking which hospital you're at ("profile-based routing" per your own diagram: request → user → hospital → tenant DB). Email is present but optional and no longer used for login.

**3.1.2 What I'd add on top, not built yet [RECOMMEND]:** an optional `employee_id` field, unique *per tenant* (not globally — two hospitals can both have an "EMP-001"), settable by the Hospital Admin for hospitals that already run an HR/payroll system with IDs. Login would then accept **mobile OR employee_id** (not email — see 3.1.3) + password, resolved the same way mobile is today: a registry-side index table (`StaffEmployeeIdIndex`, tenant-scoped uniqueness) maps `(tenant_subdomain_hint, employee_id) → tenant`. Since employee IDs aren't globally unique, this login path needs a tenant hint (subdomain, or a hospital picker) — mobile-only login doesn't need this because mobile numbers *are* globally unique.

**3.1.3 Why I'd deliberately leave email out of login, even though it's tempting to include for symmetry:** every identifier you accept for login is an attack surface (enumeration, credential-stuffing target) and a UX decision about which one wins in a collision. Email is the *least* reliable identifier in your stated context (many staff don't have one) and the *most* commonly reused across unrelated services (so a leaked password elsewhere is more likely to be tried against an email-keyed login than a phone-keyed one). Keep it as a profile field for notifications, not a login key. This mirrors the decision already made and implemented this session — the system was migrated *away* from email login specifically because staff without an official email couldn't be onboarded.

### 3.2 Proposed User model — reconciled with what exists

Your proposed shape is close to what's actually implemented; here's the mapping plus the gaps:

```
StaffUser                                  [BUILT, per-tenant DB]
  id
  first_name, last_name
  email               nullable, unique     [BUILT]
  phone               required, unique     [BUILT — primary login identifier]
  employee_id         nullable, unique per tenant   [GAP — recommend adding]
  password            hashed                [BUILT]
  role                enum                  [BUILT — see RBAC below]
  branch              FK, single             [BUILT, but see 4.3 — multi-branch gap]
  department          FK, nullable          [BUILT]
  date_of_birth       nullable              [BUILT]
  is_active           boolean               [BUILT — enforced per-request, not just at login]
  must_change_password boolean              [BUILT]
  date_joined, last_login                   [BUILT]
```

One deliberate deviation from your sketch worth flagging: there's no single global `users` table with a `tenant_id` column — each tenant gets its **own isolated PostgreSQL database**, and `StaffUser` lives inside it. A thin registry database holds only `Tenant`, `Subscription`, and the login-routing indexes (`StaffMobileIndex` etc.) — no clinical or staff PII. This is stronger tenant isolation than a shared table with a `tenant_id` filter (a bug in a `WHERE tenant_id = ?` clause can leak across tenants; a bug that reaches into the wrong *database* generally can't, because the app doesn't even have that DB connection unless it explicitly resolves it). I'd keep this — it's the right call for healthcare data specifically, where cross-tenant leakage is a compliance incident, not just a bug.

### 3.3 Password reset / account recovery — the real design

**[BUILT] today, and I'd keep it only as the fallback, not the primary:** mobile + date-of-birth self-service reset, added earlier this session as an interim measure explicitly because no SMS/OTP gateway existed. I flagged it as weak at the time; your question today is the right prompt to formalize the replacement.

**[RECOMMEND] Primary path — OTP via the registered mobile number:**

```
1. User enters mobile number on "Forgot password"
2. Backend looks up StaffMobileIndex → confirms an active account exists
   (never reveals whether it does — same generic "if this number is
   registered, you'll receive a code" response either way, to prevent
   account enumeration)
3. Backend generates a 6-digit OTP, stores {mobile, otp_hash, expires_at,
   attempt_count} in a short-lived table (see 5.4), sends it via SMS gateway
4. User enters OTP + new password within a short window (5–10 min)
5. Backend verifies OTP (max 5 attempts, then locked out for the window),
   sets new password, must_change_password=False, invalidates the OTP
6. All existing sessions for that user are revoked (force re-login
   everywhere — the whole point of a reset is "I might have been
   compromised")
```

**[RECOMMEND] Fallback path — admin-mediated reset**, for when OTP delivery isn't available yet, or the user no longer controls the registered mobile number (lost/changed phone without updating their profile — a real and common case): Hospital Admin (or Platform Admin, for Hospital Admins themselves) resets the password from the staff management screen, generates a new temp password, forces `must_change_password=True`. **This already exists** — `TenantStaffResetPasswordView` / `StaffResendInviteView` — so this fallback needs no new work, only for OTP to become the front door instead of DOB.

**Until the SMS gateway exists:** keep DOB-verification as a clearly-labeled "weak identity check, contact your admin if this fails" bridge (which is already how it's worded), but don't market it as the permanent design — the UI copy should make it obvious this is a stopgap, and OTP should replace it as the primary path the moment a gateway is wired in, with DOB removed entirely rather than kept as a second option (having two reset paths of different strength is itself a vulnerability — an attacker picks the weaker one).

### 3.4 Session & token design **[BUILT]**

JWT access (60 min) + refresh (7 days), with:
- Per-jti revocation list (`BlacklistedToken`) — used on logout and token refresh checks.
- Live `is_active` re-check on every authenticated request (not just at login) — added this session specifically because a "Deactivate" button that only blocked *future* logins while an existing token kept working was misleading. This is stronger than a lot of production systems ship with, honestly — many rely on short token TTL alone.
- Subscription-status re-check per request (grace/frozen/suspended tenants get blocked mid-session, not just at next login).

---

## 4. RBAC design

### 4.1 Hierarchy — as built **[BUILT]**

```
Platform Admin (Django superuser, is_platform=True, no tenant context)
      │
      ▼
Tenant (isolated DB) ── Subscription (tier, limits, feature flags)
      │
      ▼
Hospital Admin (StaffUser.role == "hospital_admin")
      │
      ├── Doctor
      ├── Nurse
      ├── Front Desk
      ├── Lab Technician
      └── Pharmacist
```

This matches your diagram exactly. Hospital Admin is itself a `StaffUser` row (not a separate table) — the only thing distinguishing it is `role`, which is also why the "last active hospital_admin can't be deactivated or role-changed away" safeguard exists (built earlier this session) — without it, a hospital could accidentally lock itself out of its own admin panel with no recovery path except a Platform Admin intervention.

### 4.2 Current permission model — role-based, not table-driven **[BUILT, with a real limitation]**

Today, permissions are **hardcoded per-role DRF permission classes** (`IsHospitalAdmin`, `IsDoctor`, `IsNurse`, `IsFrontDesk`, `IsLabTech`, `IsPharmacist`, plus `IsDoctorOrNurse` and `IsHospitalStaff` for shared endpoints), applied per-view:

```python
permission_classes = [IsAuthenticated, IsDoctor]
```

This is simple, fast, and hard to misconfigure — but it means **permissions are fixed at deploy time**, not configurable per hospital. A hospital can't say "our senior nurses should also be able to view lab catalogs" without a code change. That's fine for a 6-role fixed system; it stops being fine the moment any hospital wants a custom role or a permission tweak.

Actual permissions as implemented, matching your example format:

**Doctor** — view patient records (own hospital only), create/sign consultation notes (`OPDEncounter`), prescribe medicines (`Prescription`), order lab tests, view own patient queue and history, edit own doctor profile (bio, signature, languages — not registration/qualification, which only Hospital Admin sets).

**Nurse** — capture vitals, view assigned/queued patients, manage nurse task queue, record lab-order patient choices on a patient's behalf when needed, edit own profile.

**Front Desk** — register patients, create/manage appointments, manage the check-in queue, handle billing intake, edit own profile.

**Lab Technician** — manage lab test catalog, process lab requests, upload/deliver reports, edit own profile.

**Pharmacist** — dispense prescriptions, manage stock/transactions, edit own profile.

**Hospital Admin** — everything above (as oversight — several routes explicitly allow `[FRONT_DESK, HOSPITAL_ADMIN]`, `[LAB_TECH, HOSPITAL_ADMIN]` etc. for exactly this reason) plus branch/department/staff management, role assignment, subscription-tier-gated feature access, hospital profile editing.

**Platform Admin** — cross-tenant: provisioning, tier/status changes, cross-tenant staff directory, audit trail, no clinical data access (by design — platform admin doesn't need and shouldn't default to patient-data visibility).

### 4.3 [RECOMMEND] Evolving toward table-driven RBAC

For "future expansion to large hospitals" specifically, I'd introduce a permissions layer *without* throwing away the fast-path role checks — enterprise hospitals get configurability, everyone else keeps the simple default:

```
roles                    — per-tenant custom roles, seeded with the 6 defaults
  id, tenant_id (nullable = platform default), name, is_system_role

permissions               — the fixed catalog of grantable actions
  id, code (e.g. "patient.view", "prescription.create", "lab.catalog.manage")
  description

role_permissions           — many-to-many
  role_id, permission_id

user_roles                 — many-to-many (see 4.4 — this is also how you'd
                              support one person holding two roles, e.g. a
                              doctor who's also the hospital admin at a small
                              clinic, without ambiguity)
  staff_id, role_id
```

A hospital on `enterprise` tier could define "Senior Nurse" with an extra permission or two; a `starter` hospital just gets the 6 system roles with no UI for editing them (`RequireTier`/`RequireFeature`, already built, gates exactly this kind of thing). Until a hospital actually asks for a custom role, the existing hardcoded classes stay as the fast path — don't pay the query-per-request cost of a permission-table join for every one of the 95%+ of tenants that will only ever use the 6 defaults.

### 4.4 Branch-level access & multi-branch doctors — the real gap

**[GAP], and it's the one place your requirements and the current schema genuinely don't match:** `StaffUser.branch` is a **single nullable ForeignKey**. A doctor who consults at two branches of the same hospital (very common — a cardiologist doing Tuesday/Thursday at the city-center branch and Saturday at the suburb branch) has no way to be represented today; they're pinned to one branch, and appointments/queues are branch-scoped off that single value.

**[RECOMMEND]** Replace the single FK with a many-to-many mapping, and make "primary branch" an attribute of the relationship rather than a separate field:

```
user_branch_mapping
  id
  staff_id      FK → StaffUser
  branch_id     FK → Branch
  is_primary    boolean   — drives default queue/dashboard scoping,
                             exactly one TRUE per staff member
  created_at
```

**How branch switching would work:** the JWT payload already carries `branch_id` as a claim (set at login from the user's single branch today). With multi-branch, the JWT would carry the **primary** branch as the default claim, and the frontend would offer a branch switcher (visible only to staff with >1 mapped branch) that calls a lightweight endpoint to re-scope the *session* to a different mapped branch — either by re-issuing a short-lived token with a different `branch_id` claim, or (simpler, no extra token churn) by making `branch_id` a request-time query param/header on branch-scoped endpoints, validated server-side against `user_branch_mapping` so a doctor can't scope themselves into a branch they're not assigned to. I'd lean toward the header/param approach — it avoids re-authenticating on every branch switch and keeps the access-token lifetime meaningful.

Front desk, nurse, lab tech, and pharmacist realistically stay single-branch in almost every real deployment (they work a physical desk), so I wouldn't force the migration complexity onto every role — `user_branch_mapping` with one row is equivalent to today's single FK for those roles, and doctors are the only ones who actually need >1 row in practice. This keeps the migration low-risk: existing single-branch assignments become single-row mappings, nothing breaks.

---

## 5. Database design

### 5.1 Registry DB (cross-tenant, no clinical data) — as built **[BUILT]**

```
tenant                    — id, name, subdomain, db_name, city, state, gstin,
                             is_active, created_at
subscription               — tenant_id (1:1), license_tier, status,
                             trial_ends_on, current_period_start/end,
                             feat_lab / feat_pharmacy / feat_whatsapp /
                             feat_multi_branch / feat_ai_voice /
                             feat_patient_app / feat_analytics / feat_video /
                             feat_face_recog,
                             max_doctors, max_branches, max_staff (0 = unlimited)
tenant_audit_log            — tenant_id, action, before_value, after_value,
                             actor_email, created_at  (platform-admin actions:
                             tier changes, status changes, provisioning)
staff_mobile_index          — mobile (unique), tenant_id, db_name
                             (login routing: which tenant DB owns this number)
blacklisted_token           — jti, expires_at  (revoked JWTs)
patient_account,
patient_identity,
portal_booking, etc.        — cross-tenant patient-portal + HIE-sharing tables
                             (out of scope for this doc, already built)
```

**[RECOMMEND, additions for this design]**

```
staff_employee_id_index     — (tenant_id, employee_id) unique together,
                             db_name   — mirrors staff_mobile_index, for 3.1.2
otp_challenge                — id, mobile, purpose (enum: "staff_reset",
                             "patient_reset"), otp_hash, expires_at,
                             attempt_count, consumed_at, created_at
                             (short TTL, purge job or TTL index; never store
                             the OTP in plaintext, hash it same as a password)
```

### 5.2 Per-tenant DB (isolated per hospital) — as built **[BUILT]**

```
branch                      — name, address, city, state, pincode, phone,
                             lat/lng, is_active
department                  — branch_id, name, is_active
staff_user                  — see 3.2 above
doctor_profile               — staff_id (1:1), registration_no, specialisation,
                             qualification, experience_years, consultation_fee,
                             digital_signature, bio, languages, known_for
staff_profile                 — staff_id (1:1), the non-doctor equivalent:
                             registration_no, council_name, qualification,
                             experience_years, gender, bio, languages, extra (JSON)
audit_log                    — actor_user_id, actor_email, actor_role, action,
                             resource_type, resource_id, patient_id,
                             ip_address, metadata (JSON), created_at
                             (append-only; every clinical/administrative
                             action funnels through core.audit.log_action())
next_number                  — NNTM sequence generator (UHID/invoice/lab/Rx/
                             queue numbering, per branch)
```

Plus the clinical tables (Patient, Appointment, OPDEncounter, Prescription, LabRequest, etc.) — out of scope here since this doc is specifically about onboarding/auth/RBAC, not the clinical schema.

**[RECOMMEND, additions for this design]**

```
role                          — id, tenant_id (nullable), name, is_system_role
permission                     — id, code, description
role_permission                — role_id, permission_id
user_role                      — staff_id, role_id   (supports one person,
                             multiple roles — e.g. doctor + admin at a small
                             clinic — without overloading the single `role`
                             column; keep `staff_user.role` as the *primary*
                             role for fast-path checks and JWT claims, add
                             user_role only for tenants that opt into custom
                             RBAC)
user_branch_mapping            — staff_id, branch_id, is_primary
                             (replaces the single branch_id FK — see 4.4)
```

### 5.3 Why per-tenant databases instead of a shared `users` table with `tenant_id`

Since your sketch used a shared-table shape, worth being explicit about why this codebase deliberately doesn't: with a shared table, every single query anywhere in the codebase must remember to filter by `tenant_id`, forever, with no structural backstop — one missed `WHERE` clause in a large team's future PR is a cross-hospital data leak. With isolated databases, the *connection itself* is tenant-scoped (resolved once per request from the JWT's `db_name` claim), so a query bug can return wrong data *within* a tenant but structurally cannot reach into a different hospital's database. For healthcare specifically — where a leak is a compliance and trust incident, not just a bug ticket — I'd keep this even though it's more operationally complex (a migration has to run against N databases, not one). This tradeoff is already made and working in your codebase; flagging it here because your sketch implied the opposite and I want you to know it was a deliberate choice, not an oversight.

### 5.4 Password reset lifecycle — state machine

```
must_change_password: False ──(admin creates/resets)──▶ True
                                                          │
                                          (user logs in with temp password,
                                           forced to /change-password)
                                                          │
                                                          ▼
                                                     False (normal)
```

```
otp_challenge lifecycle:
  created (otp sent) ──▶ consumed (password changed, all sessions revoked)
                     ╲─▶ expired (TTL passed, must request a new one)
                     ╲─▶ locked (5 failed attempts, must request a new one)
```

---

## 6. Security & operational considerations

**Multi-tenancy isolation [BUILT]** — per-tenant database, covered in 5.3.

**Subscription limit enforcement [BUILT, this session]** — every doctor/branch/staff-creating endpoint checks against the tenant's tier limits and **fails closed**: if the limit check itself can't be verified (DB hiccup, etc.), the request is rejected rather than silently allowed through. This was a real bug fixed this session — the original implementation failed *open* (`except Exception: pass`), which defeats the purpose of a hard cap.

**Staff deactivation [BUILT]** — `is_active=False` is checked on *every* authenticated request, not just at login, so deactivating someone mid-session actually cuts off access immediately rather than waiting for their token to expire naturally.

**Last-admin lockout prevention [BUILT]** — can't deactivate or role-change away the only active Hospital Admin at a tenant.

**Duplicate-identifier hijack prevention [BUILT]** — a mobile number already routed to a different hospital can't be silently reassigned (would hijack that person's login at their real hospital); same protection would extend to `employee_id` if 3.1.2 is built.

**Audit logging [BUILT, two layers]** — `TenantAuditLog` (registry DB, platform-admin actions: tier changes, provisioning, status changes) and `AuditLog` (per-tenant DB, clinical/staff actions: who signed which encounter, who viewed which patient). Append-only from the application layer — no update/delete API exposed for either.

**[GAP] Rate limiting exists on login (`10/min` via DRF `ScopedRateThrottle`) but not yet on the OTP-reset flow proposed in 3.3** — needs its own tighter scope (e.g. `3/hour` per mobile number) once built, since OTP endpoints are a classic brute-force target.

**[GAP] No SMS/email gateway** — the single biggest real gap standing between "what's built" and "what you described as the target state." Everything in section 3.3's OTP design and section 2.1's credential-delivery design is blocked on this. Recommend prioritizing gateway integration over the table-driven RBAC in 4.3 — RBAC-as-config is a nice-to-have for large hospitals later; OTP delivery is a correctness gap affecting every hospital today.
