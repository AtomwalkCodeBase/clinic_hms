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

## Create superadmin

```bash
python manage.py createsuperuser
```

Use this account to log in as a platform admin.

## Add a hospital

```bash
python manage.py provision_tenant --name "Demo Hospital" --subdomain demo-hospital \
  --city Mumbai --state Maharashtra --admin-mobile 9999999999 --tier growth
```

This creates the hospital and its first admin login (staff mobile number +
password shown in the command output).

## Logging in

- Staff: `POST /api/v1/auth/login/staff/`
- Patient: `POST /api/v1/auth/login/patient/`
- Platform admin: `POST /api/v1/auth/login/platform/`
