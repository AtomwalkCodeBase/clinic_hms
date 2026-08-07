# Hospital Management System (HMS)

A web app for hospitals to manage patients, appointments, doctors, lab tests,
pharmacy, and billing — plus a patient portal where patients can book
appointments and view their records online.

## Who uses it

- **Hospital staff** (front desk, nurses, doctors, lab techs, pharmacists,
  admins) — run the day-to-day clinic operations.
- **Patients** — book appointments, view prescriptions and lab reports.
- **Platform admins** — onboard new hospitals onto the system.

## Setup

**Backend**

```bash
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt
copy .env.example .env         # then fill in your database details
python manage.py migrate --database=default
python manage.py migrate_tenants
python manage.py runserver
```

**Frontend**

```bash
cd frontend
npm install
npm run dev
```

The app runs at `http://localhost:3000` and the backend at
`http://localhost:8000`.

## Adding a hospital / demo data

To load a full set of demo hospitals, staff, and patients:

```bash
python manage.py seed_full_demo
```

This creates a `DEMO_CREDENTIALS.md` file with login details for every account.

## Logging in

- Staff: `POST /api/v1/auth/login/staff/`
- Patient: `POST /api/v1/auth/login/patient/`
- Platform admin: `POST /api/v1/auth/login/platform/`
