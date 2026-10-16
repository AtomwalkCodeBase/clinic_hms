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
      services/        sir's timeline rules: config, clinical_rules, episodes, extraction, growth, immunization, timeline
      lib_processing.py   the LLM's facts -> rows, episodes, recurrence, the timeline payload
      integration.py      where the rules get a patient's date of birth, sex and a document's type, text and date from
      lib_documents.py    upload, extraction, classification rules, review step, hospital-issued documents
      lib_vitals.py       visit vitals and growth readings, hospital write-through, growth reference percentiles
      lib_roadmap.py      vaccination and milestone roadmaps, schedules as the API returns them
      views.py / views_timeline.py   the document views / sir's timeline views
      tests/           the document tests
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
