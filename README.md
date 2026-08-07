# Atomwalk HMS — Hospital Management System

Atomwalk is a multi-tenant hospital management platform. One deployment serves many
hospitals, each with its own isolated database, while a shared registry layer lets
patients carry their medical identity across every hospital on the network (with their
consent) instead of being siloed at a single clinic.

It has three sides:

- **Hospital staff app** — front desk, nurses, doctors, lab techs, pharmacists, and
  hospital admins each get a role-specific workspace for running a clinic day to day:
  registering patients, queueing and consulting on OPD appointments, recording
  vitals, writing prescriptions, ordering and reporting lab tests, dispensing
  pharmacy stock, and billing.
- **Patient portal** — patients can search hospitals and doctors across the whole
  network, book appointments, see their queue position live, view prescriptions and
  lab reports, upload their own documents, and manage a family (dependents without
  their own login).
- **Platform admin console** — Atomwalk's own team onboards new hospitals, manages
  subscription tiers and feature flags, and gets cross-hospital usage visibility.

## How the multi-tenancy works

- A **registry database** holds cross-hospital data: the list of hospitals
  (`Tenant`), subscriptions, patient portal accounts, and the shared clinical history
  patients opt into sharing across hospitals (diagnoses, vitals, allergies, lab
  results, prescriptions, documents).
- Each hospital gets its **own Postgres database**, created automatically when the
  hospital is onboarded. All of that hospital's day-to-day data — its staff,
  patients, appointments, encounters, invoices, lab orders, pharmacy stock — lives
  there, completely isolated from every other hospital.
- A patient is identified across the network by an **AWPID** (Atomwalk Patient ID).
  When they visit a hospital for the first time, front desk resolves their AWPID
  instead of creating a disconnected new record, and — only if the patient consents
  — that hospital can see their shared history from other hospitals they've visited.

## Tech stack

- **Backend:** Django 4.2 + Django REST Framework, PyJWT for auth (not DRF
  SimpleJWT's own views — a custom implementation in `apps/auth_app`), PostgreSQL.
- **Frontend:** React + Vite single-page app.
- **API docs:** auto-generated via `drf-spectacular` at `/api/schema/` and
  `/api/docs/` (Swagger UI) once the server is running — always in sync with the
  actual endpoints.

## Project layout

```
apps/
  auth_app/       Login, JWT issuing/refresh, password reset, "me" endpoints
  platform_admin/ Hospital onboarding, tier/subscription management, cross-tenant stats
  org/            Branches, departments, staff, doctor/staff profiles, RBAC roles
  opd/            The live OPD flow: queue, vitals, SOAP encounters, prescriptions
  patients/       Staff-facing patient records + the patient portal (portal_urls.py)
  lab/            Lab test catalog, orders, results
  billing/        Invoices, payments
  pharmacy/       Stock, dispensing
  tasks/          Simple staff task board (nursing/housekeeping/supply/etc.)
  tenants/        Tenant provisioning + per-tenant database/migration management
  registry/       Cross-hospital registry models (Tenant, PatientAccount, shared history)
frontend/         React + Vite SPA (staff app + patient portal)
atomwalk/         Django project settings (base / development / production) and urls.py
```

`apps/clinical` and `apps/prescriptions` also exist and are routed, but are legacy —
earlier duplicate models that the live OPD flow (`apps/opd`) has since replaced.
`apps/notifications`, `apps/compliance`, and `apps/ai_pipeline` have data models
defined but no views/URLs wired up yet, so they aren't reachable via the API.

## Getting started (local development)

### Prerequisites

- Python 3.10+
- PostgreSQL running locally
- Node.js (for the frontend)

### 1. Backend setup

```bash
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS/Linux

pip install -r requirements.txt

copy .env.example .env         # Windows
# cp .env.example .env         # macOS/Linux
```

Edit `.env` with your local PostgreSQL credentials. At minimum, set real values for
`SECRET_KEY` and `JWT_SIGNING_KEY` (the file has a one-liner to generate one) —
everything else has sane local defaults.

Create the registry database once:

```bash
psql -U postgres -c "CREATE DATABASE atomwalk_registry;"
```

Run migrations. This is a **two-step process** — the registry DB and each hospital's
database are migrated separately, and it's easy to forget the second step:

```bash
python manage.py migrate --database=default
python manage.py migrate_tenants
```

Create a Django superuser (for `/admin/`, Django's built-in admin — separate from
platform-admin login):

```bash
python manage.py createsuperuser
```

### 2. Get some data to look at

Either onboard a hospital yourself:

```bash
python manage.py provision_tenant --name "Demo Hospital" --subdomain demo-hospital \
  --city Mumbai --state Maharashtra --admin-mobile 9999999999 --tier growth
```

...or seed a full demo environment (4 hospitals, staff for every role, patients at
every stage of the appointment lifecycle):

```bash
python manage.py seed_full_demo
```

This writes `DEMO_CREDENTIALS.md` in the project root with every generated login —
staff password `Demo@12345`, patient portal password `Patient@12345`.

### 3. Run the backend

```bash
python manage.py runserver
```

- API base: `http://localhost:8000/api/v1/`
- Interactive API docs: `http://localhost:8000/api/docs/`
- Health check: `http://localhost:8000/health/`

### 4. Run the frontend

```bash
cd frontend
npm install
npm run dev
```

Runs at `http://localhost:3000`, proxying `/api` requests to the backend.

## Logging in

There is no single login form — the endpoint depends on who's logging in:

| Who | Endpoint | Identifies with |
|---|---|---|
| Hospital staff | `POST /api/v1/auth/login/staff/` | Mobile number + password (or subdomain + employee ID + password) |
| Patient | `POST /api/v1/auth/login/patient/` | Mobile number or AWPID + password |
| Platform admin | `POST /api/v1/auth/login/platform/` | Django superuser username/email + password |

Hospital staff roles: `hospital_admin`, `doctor`, `nurse`, `front_desk`, `lab_tech`,
`pharmacist`. Each sees a different app shell after login, scoped to their
permissions.

## Deploying

This app has two things a typical Django deploy doesn't: it creates a new Postgres
database per hospital at runtime (so the database user needs `CREATEDB` privilege,
and connection poolers like RDS Proxy don't work well with it), and the two-step
migration process above needs to run on every deploy, not just the first one. See
`atomwalk/settings/production.py` for the production-specific settings (HTTPS
enforcement, proxy headers, static file serving via WhiteNoise).

## API reference

For a full endpoint-by-endpoint reference (every route, method, parameters, and
example response), see `Atomwalk_HMS_API_Reference.xlsx` in this repo, or hit
`/api/docs/` on a running server for the always-up-to-date interactive version.
