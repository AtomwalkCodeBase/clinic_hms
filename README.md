# Atomwalk HMS

Django + React hospital management system. Data lives in one shared `atomwalk` database and one database per hospital;
`core/db_router.py` picks the database from each app's `database` setting.

## Layout

```
manage.py
core/        project settings (core/settings/), urls, wsgi/asgi, Celery app, db router, shared helpers, auth/ (login, OTP, tokens)
apps/
  patients/          atomwalk DB   patient accounts, portal, guardians
  documents/         atomwalk DB   uploaded reports, extraction, health timeline
  hospital_master/   atomwalk DB   hospitals, subscriptions, platform-admin views
  hospital_setup/    hospital DB   branches, rooms, beds, staff, roles, compliance, notifications
  ipd/               hospital DB   admissions
  opd/               hospital DB   appointments, encounters, prescriptions, hospital patients
  billing/           hospital DB   invoices, payments
  lab/               hospital DB   lab requests and reports
  pharmacy/          hospital DB   drugs, stock, dispensing
frontend/            React + Vite
```

## Run

```
python manage.py runserver                      # core.settings.development by default
celery -A core worker -Q instant,bulk,celery --loglevel=info -P solo
celery -A core beat --loglevel=info
```
