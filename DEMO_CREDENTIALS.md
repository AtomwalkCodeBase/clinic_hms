# Atomwalk HMS — Demo Credentials
Generated: 03-Sep-2026 06:11

Default staff password (all roles, all hospitals): `Demo@12345`
Default patient portal password: `Patient@12345`

## Lakeview Multispecialty Hospital (Bengaluru) — subdomain `lakeview-demo`
- Hospital Admin: `ravi.admin@lakeview-demo.demo`
- Doctor 1 (General Medicine): `vikram.doctor1@lakeview-demo.demo` — Dr. Vikram Rao
- Doctor 2 (Pediatrics): `ananya.doctor2@lakeview-demo.demo` — Dr. Ananya Iyer
- Doctor 3 (Orthopedics): `karan.doctor3@lakeview-demo.demo` — Dr. Karan Sethi
- Nurse 1: `lakshmi.nurse1@lakeview-demo.demo`
- Nurse 2: `ramesh.nurse2@lakeview-demo.demo`
- Nurse 3: `sunita.nurse3@lakeview-demo.demo`
- Front Desk: `sanjay.frontdesk@lakeview-demo.demo`
- Lab Technician: `prakash.labtech@lakeview-demo.demo`
- Pharmacist: `ajay.pharmacist@lakeview-demo.demo`

## Horizon Care Hospital (Chennai) — subdomain `horizon-care-demo`
- Hospital Admin: `sonal.admin@horizon-care-demo.demo`
- Doctor 1 (Gynecology): `meera.doctor1@horizon-care-demo.demo` — Dr. Meera Nair
- Doctor 2 (Cardiology): `rohan.doctor2@horizon-care-demo.demo` — Dr. Rohan Kapoor
- Doctor 3 (Dermatology): `divya.doctor3@horizon-care-demo.demo` — Dr. Divya Menon
- Nurse 1: `arvind.nurse1@horizon-care-demo.demo`
- Nurse 2: `pooja.nurse2@horizon-care-demo.demo`
- Nurse 3: `manoj.nurse3@horizon-care-demo.demo`
- Front Desk: `kirti.frontdesk@horizon-care-demo.demo`
- Lab Technician: `shreya.labtech@horizon-care-demo.demo`
- Pharmacist: `nandini.pharmacist@horizon-care-demo.demo`

## Cedar Health Hospital (Hyderabad) — subdomain `cedar-health-demo`
- Hospital Admin: `imran.admin@cedar-health-demo.demo`
- Doctor 1 (ENT): `aditya.doctor1@cedar-health-demo.demo` — Dr. Aditya Desai
- Doctor 2 (Endocrinology): `priya.doctor2@cedar-health-demo.demo` — Dr. Priya Bhatt
- Doctor 3 (Pulmonology): `suresh.doctor3@cedar-health-demo.demo` — Dr. Suresh Reddy
- Nurse 1: `geeta.nurse1@cedar-health-demo.demo`
- Nurse 2: `vishal.nurse2@cedar-health-demo.demo`
- Nurse 3: `anjali.nurse3@cedar-health-demo.demo`
- Front Desk: `manish.frontdesk@cedar-health-demo.demo`
- Lab Technician: `anil.labtech@cedar-health-demo.demo`
- Pharmacist: `sameer.pharmacist@cedar-health-demo.demo`

## Metro Wellness Hospital (Pune) — subdomain `metro-wellness-demo`
- Hospital Admin: `radhika.admin@metro-wellness-demo.demo`
- Doctor 1 (Gastroenterology): `neha.doctor1@metro-wellness-demo.demo` — Dr. Neha Joshi
- Doctor 2 (Nephrology): `farhan.doctor2@metro-wellness-demo.demo` — Dr. Farhan Ali
- Doctor 3 (Psychiatry): `kavya.doctor3@metro-wellness-demo.demo` — Dr. Kavya Krishnan
- Nurse 1: `deepak.nurse1@metro-wellness-demo.demo`
- Nurse 2: `swati.nurse2@metro-wellness-demo.demo`
- Nurse 3: `ritesh.nurse3@metro-wellness-demo.demo`
- Front Desk: `rekha.frontdesk@metro-wellness-demo.demo`
- Lab Technician: `bhavna.labtech@metro-wellness-demo.demo`
- Pharmacist: `tanvi.pharmacist@metro-wellness-demo.demo`

## Flagship demo patient (switching hospitals + HIE consent)
- Patient portal login: `meera.krishnan@patientdemo.com` / `Patient@12345`
- Full name: Meera Krishnan (UHID at Lakeview Multispecialty Hospital: LKV-000013)
- Already has a full visit history (vitals, signed consultation, prescription, an abnormal HbA1c lab report as a real PDF, and one allergy) at **Lakeview Multispecialty Hospital**.
- Deliberately has NO record yet at **Horizon Care Hospital** — log in as her on the patient portal, search/browse a doctor at Horizon Care Hospital, and book. The HIE consent modal will fire (new hospital, no consent on file there yet). Agree to it, then log in as a doctor at Horizon Care Hospital and open her encounter — her Lakeview Multispecialty Hospital history (diagnosis, vitals, allergy, lab result, and an outside document) should now appear in the history sidebar.
