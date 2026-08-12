# Atomwalk HMS — Demo Credentials
Generated: 05-Aug-2026 06:13

Password for every login below (all staff roles + the patient portal account): `hms@1234`
(Reset via `python manage.py reset_demo_passwords --password "hms@1234"`.)

**Staff login is mobile-number-based, not email-based.** The `email` column shown below exists on
each account but only works as a login value for staff created/edited after the email-login-index
backfill has been run (not yet done as of this writing) — until then, use the mobile number.
Login screen field: "Mobile Number or Email" — enter the mobile number for now.

## Lakeview Multispecialty Hospital (Bengaluru) — subdomain `lakeview-demo`
- Hospital Admin: `8000000005` — Ravi Malhotra (`ravi.admin@lakeview-demo.demo`)
- Doctor 1 (General Medicine): `8000000014` — Dr. Vikram Rao (`vikram.doctor1@lakeview-demo.demo`, employee ID `EMP-001`)
- Doctor 2 (Pediatrics): `8000000010` — Dr. Ananya Iyer (`ananya.doctor2@lakeview-demo.demo`)
- Doctor 3 (Orthopedics): `8000000011` — Dr. Karan Sethi (`karan.doctor3@lakeview-demo.demo`)
- Nurse 1: `8000000013` — Lakshmi Pillai (`lakshmi.nurse1@lakeview-demo.demo`) — **inactive, cannot log in**
- Nurse 2: `8000000012` — Ramesh Kumar (`ramesh.nurse2@lakeview-demo.demo`)
- Nurse 3: `8000000006` — Sunita Yadav (`sunita.nurse3@lakeview-demo.demo`) — **inactive, cannot log in**
- Front Desk: `8000000007` — Sanjay Kumar (`sanjay.frontdesk@lakeview-demo.demo`)
- Lab Technician: `8000000008` — Prakash Naidu (`prakash.labtech@lakeview-demo.demo`)
- Pharmacist: `8000000009` — Ajay Bhosale (`ajay.pharmacist@lakeview-demo.demo`)

## Horizon Care Hospital (Chennai) — subdomain `horizon-care-demo`
- Hospital Admin: `8000000015` — Sonal Agarwal (`sonal.admin@horizon-care-demo.demo`)
- Doctor 1 (Gynecology): `8000000022` — Dr. Meera Nair (`meera.doctor1@horizon-care-demo.demo`)
- Doctor 2 (Cardiology): `8000000016` — Dr. Rohan Kapoor (`rohan.doctor2@horizon-care-demo.demo`)
- Doctor 3 (Dermatology): `8000000023` — Dr. Divya Menon (`divya.doctor3@horizon-care-demo.demo`)
- Nurse 1: `8000000024` — Arvind Shetty (`arvind.nurse1@horizon-care-demo.demo`)
- Nurse 2: `8000000017` — Pooja Verma (`pooja.nurse2@horizon-care-demo.demo`)
- Nurse 3: `8000000018` — Manoj Tiwari (`manoj.nurse3@horizon-care-demo.demo`)
- Front Desk: `8000000019` — Kirti Shah (`kirti.frontdesk@horizon-care-demo.demo`)
- Lab Technician: `8000000020` — Shreya Kulkarni (`shreya.labtech@horizon-care-demo.demo`)
- Pharmacist: `8000000021` — Nandini Rao (`nandini.pharmacist@horizon-care-demo.demo`)

## Cedar Health Hospital (Hyderabad) — subdomain `cedar-health-demo`
- Hospital Admin: `8000000025` — Imran Sheikh (`imran.admin@cedar-health-demo.demo`)
- Doctor 1 (ENT): `8000000032` — Dr. Aditya Desai (`aditya.doctor1@cedar-health-demo.demo`)
- Doctor 2 (Endocrinology): `8000000033` — Dr. Priya Bhatt (`priya.doctor2@cedar-health-demo.demo`)
- Doctor 3 (Pulmonology): `8000000034` — Dr. Suresh Reddy (`suresh.doctor3@cedar-health-demo.demo`)
- Nurse 1: `8000000026` — Geeta Pandey (`geeta.nurse1@cedar-health-demo.demo`)
- Nurse 2: `8000000027` — Vishal Bose (`vishal.nurse2@cedar-health-demo.demo`)
- Nurse 3: `8000000028` — Anjali Chauhan (`anjali.nurse3@cedar-health-demo.demo`)
- Front Desk: `8000000029` — Manish Trivedi (`manish.frontdesk@cedar-health-demo.demo`)
- Lab Technician: `8000000030` — Anil Chopra (`anil.labtech@cedar-health-demo.demo`)
- Pharmacist: `8000000031` — Sameer Qureshi (`sameer.pharmacist@cedar-health-demo.demo`)

## Metro Wellness Hospital (Pune) — subdomain `metro-wellness-demo`
- Hospital Admin: `8000000035` — Radhika Nambiar (`radhika.admin@metro-wellness-demo.demo`)
- Doctor 1 (Gastroenterology): `8000000042` — Dr. Neha Joshi (`neha.doctor1@metro-wellness-demo.demo`)
- Doctor 2 (Nephrology): `8000000043` — Dr. Farhan Ali (`farhan.doctor2@metro-wellness-demo.demo`)
- Doctor 3 (Psychiatry): `8000000044` — Dr. Kavya Krishnan (`kavya.doctor3@metro-wellness-demo.demo`)
- Nurse 1: `8000000036` — Deepak Mishra (`deepak.nurse1@metro-wellness-demo.demo`)
- Nurse 2: `8000000037` — Swati Ghosh (`swati.nurse2@metro-wellness-demo.demo`)
- Nurse 3: `8000000038` — Ritesh Kulkarni (`ritesh.nurse3@metro-wellness-demo.demo`)
- Front Desk: `8000000039` — Rekha Iyer (`rekha.frontdesk@metro-wellness-demo.demo`)
- Lab Technician: `8000000040` — Bhavna Rathi (`bhavna.labtech@metro-wellness-demo.demo`)
- Pharmacist: `8000000041` — Tanvi Deshmukh (`tanvi.pharmacist@metro-wellness-demo.demo`)

## Flagship demo patient (switching hospitals + HIE consent)
- Patient portal login: mobile `9876500001` (AWPID `AWPID-20260805-FKFHCDAG` also works) / `hms@1234`
  (Email `meera.krishnan@patientdemo.com` is stored on the account but is NOT a valid login field — patient login only accepts mobile number or AWPID. Password is `hms@1234`, same as every other demo login in this file — not `Patient@12345`, which was the original seed value before `reset_demo_passwords` was last run.)
- Full name: Meera Krishnan (UHID at Lakeview Multispecialty Hospital: LKV-000013)
- Already has a full visit history (vitals, signed consultation, prescription, an abnormal HbA1c lab report as a real PDF, and one allergy) at **Lakeview Multispecialty Hospital**.
- Deliberately has NO record yet at **Horizon Care Hospital** — log in as her on the patient portal, search/browse a doctor at Horizon Care Hospital, and book. The HIE consent modal will fire (new hospital, no consent on file there yet). Agree to it, then log in as a doctor at Horizon Care Hospital and open her encounter — her Lakeview Multispecialty Hospital history (diagnosis, vitals, allergy, lab result, and an outside document) should now appear in the history sidebar.
