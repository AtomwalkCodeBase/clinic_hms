"""
scripts/e2e_smoke_test.py
--------------------------
End-to-end smoke test for the unified OPD/IPD/Emergency intake build
(docs/PENDING_IMPROVEMENTS.md items 1 and 3). Exercises the real HTTP
views through Django's test Client against a real (ephemeral) tenant DB —
not mocked — and prints PASS/FAIL per scenario.

Run with `python manage.py shell < scripts/e2e_smoke_test.py` is NOT used
here because we need django.setup() + a fully provisioned tenant DB first;
instead this is executed directly as `python scripts/e2e_smoke_test.py`
after DJANGO_SETTINGS_MODULE is set and django.setup() has run — see the
bottom of this file.
"""
import os
import sys
import uuid

# ── Bootstrap an ephemeral real Postgres (pgserver) BEFORE Django settings
# import, since REGISTRY_DB_HOST etc. are read at settings-import time. ────
import pgserver
_PG_DIR = os.path.expanduser("~/pgdata_smoke")
_srv = pgserver.get_server(_PG_DIR)

os.environ["REGISTRY_DB_HOST"] = _PG_DIR
os.environ["REGISTRY_DB_PORT"] = "5432"
os.environ["REGISTRY_DB_USER"] = "postgres"
os.environ["REGISTRY_DB_PASSWORD"] = ""
os.environ["REGISTRY_DB_NAME"] = "atomwalk_registry"
os.environ["TENANT_DB_HOST"] = _PG_DIR
os.environ["TENANT_DB_PORT"] = "5432"
os.environ["TENANT_DB_USER"] = "postgres"
os.environ["TENANT_DB_PASSWORD"] = ""

import psycopg2
_conn = psycopg2.connect(host=_PG_DIR, port=5432, user="postgres", dbname="postgres")
_conn.autocommit = True
_cur = _conn.cursor()
_cur.execute("SELECT 1 FROM pg_database WHERE datname = 'atomwalk_registry'")
if not _cur.fetchone():
    _cur.execute("CREATE DATABASE atomwalk_registry;")
_conn.close()

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "atomwalk.settings.development")
sys.path.insert(0, os.getcwd())
import django
django.setup()

from django.conf import settings
from django.test import Client
from django.db import connections

RESULTS = []


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    RESULTS.append((name, status, detail))
    print(f"[{status}] {name}" + (f" — {detail}" if detail and status == 'FAIL' else ""))
    return condition


def main():
    from apps.tenants.utils import build_tenant_db_name, create_tenant_database, run_tenant_migrations
    from apps.org.models import Branch, Department, StaffUser, DoctorSchedule, DoctorAvailabilitySlot, Ward, Bed
    from apps.patients.models import Patient
    from apps.ipd.models import AdmissionReferral, Admission
    from apps.billing.models import OptionList
    from django.core.management import call_command
    from django.utils import timezone
    import datetime
    import jwt

    # ── 1. Registry DB migrate ──────────────────────────────────────────
    call_command("migrate", database="default", verbosity=0, interactive=False)
    print("Registry DB migrated.")

    # ── 2. Provision a fresh tenant DB ──────────────────────────────────
    db_name = build_tenant_db_name(f"smoketest-{uuid.uuid4().hex[:8]}")
    create_tenant_database(db_name)
    run_tenant_migrations(db_name)
    print(f"Tenant DB provisioned: {db_name}")

    # ── 3. Seed minimal tenant data: branch, department, staff, schedule ─
    branch = Branch.objects.using(db_name).create(name="Meridian Yelahanka", city="Bengaluru", state="Karnataka")

    # NNTM counter rows — normally seeded by BranchListCreateView.post()
    # (_seed_next_numbers) when a branch is created through the real API;
    # replicated here since this script creates the Branch directly via the
    # ORM. "admission" is seeded the same way ipd's own migration seeds it
    # for pre-existing branches — this branch didn't exist when that
    # migration ran, so it needs the same treatment by hand.
    from apps.org.views import _seed_next_numbers
    from apps.org.models import NextNumber
    _seed_next_numbers(branch.id, db_name)
    NextNumber.objects.using(db_name).get_or_create(
        branch_id=branch.id, entity="admission",
        defaults={"prefix": "ADM-", "last_number": 0, "pad_length": 6},
    )

    dept_gm = Department.objects.using(db_name).create(branch=branch, name="General Medicine")
    dept_ortho = Department.objects.using(db_name).create(branch=branch, name="Orthopaedics")

    doctor = StaffUser.objects.using(db_name).create(
        first_name="Anitha", last_name="Rao", role="doctor", phone="9000000001",
        branch=branch, department=dept_gm, is_active=True,
    )
    front_desk = StaffUser.objects.using(db_name).create(
        first_name="Priya", last_name="N", role="front_desk", phone="9000000002",
        branch=branch, is_active=True,
    )
    admin = StaffUser.objects.using(db_name).create(
        first_name="Admin", last_name="User", role="hospital_admin", phone="9000000003",
        branch=branch, is_active=True,
    )

    # Doctor is scheduled to work today, all day — Orthopaedics has NO doctor at all.
    today = datetime.date.today()
    sched = DoctorSchedule.objects.using(db_name).create(doctor=doctor, slot_duration_minutes=15)
    DoctorAvailabilitySlot.objects.using(db_name).create(
        schedule=sched, day_of_week=today.weekday(), is_available=True,
        start_time=datetime.time(0, 0), end_time=datetime.time(23, 59),
    )

    ward = Ward.objects.using(db_name).create(branch=branch, name="General Ward", ward_type="general")
    bed_a = Bed.objects.using(db_name).create(ward=ward, bed_number="1A")
    bed_b = Bed.objects.using(db_name).create(ward=ward, bed_number="1B")

    # ── Auth helper — mint a JWT the same shape the real login views mint ─
    from apps.auth_app.views import _make_tokens

    def token_for(staff, role):
        return _make_tokens({
            "user_id": staff.id, "role": role, "db_name": db_name,
            "tenant_id": 999999999, "branch_id": branch.id, "acts_as": [],
            "is_platform": False,
        })["access"]

    def auth_header(staff, role):
        return {"HTTP_AUTHORIZATION": f"Bearer {token_for(staff, role)}"}

    client = Client()

    # =====================================================================
    # PATH 1 — OPD, with front-desk triage
    # =====================================================================
    print("\n--- PATH 1: OPD triage ---")
    resp = client.get(
        f"/api/v1/org/departments/availability/?branch_id={branch.id}",
        **auth_header(front_desk, "front_desk"),
    )
    check("triage endpoint returns 200", resp.status_code == 200, resp.content[:300].decode(errors="replace"))
    body = resp.json() if resp.status_code == 200 else {}
    rows = {r["department_name"]: r for r in body.get("data", [])} if body else {}
    check("General Medicine shows available today",
          rows.get("General Medicine", {}).get("is_available_today") is True, str(rows.get("General Medicine")))
    check("Orthopaedics shows NOT available today (no doctor at all)",
          rows.get("Orthopaedics", {}).get("is_available_today") is False, str(rows.get("Orthopaedics")))

    # Register a normal OPD patient, then book an OPD appointment (existing endpoints).
    resp = client.post(
        "/api/v1/patients/register/",
        data={
            "full_name": "Ramesh Kulkarni", "mobile": "9845012345", "branch_id": branch.id,
            "dpdp_consent": True, "hie_consent": True,
        },
        content_type="application/json",
        **auth_header(front_desk, "front_desk"),
    )
    check("OPD patient registration succeeds", resp.status_code == 201, resp.content[:500].decode(errors="replace"))
    patient_data = resp.json()["data"] if resp.status_code == 201 else {}

    resp = client.post(
        "/api/v1/opd/appointments/",
        data={
            "patient_id": patient_data.get("uuid"), "patient_awpid": patient_data.get("awpid"),
            "doctor_user_id": str(uuid.uuid4()), "doctor_name": "Dr. Anitha Rao",
            "appointment_type": "opd", "scheduled_date": str(today),
            "chief_complaint": "Fever, 3 days",
        },
        content_type="application/json",
        **auth_header(front_desk, "front_desk"),
    )
    check("OPD appointment booking succeeds", resp.status_code == 201, resp.content[:500].decode(errors="replace"))

    # =====================================================================
    # PATH 3 — Emergency registration, then resolves into an IPD referral
    # =====================================================================
    print("\n--- PATH 3: Emergency registration -> doctor referral -> admission ---")
    resp = client.post(
        "/api/v1/patients/register-emergency/",
        data={
            "branch_id": branch.id, "placeholder_label": "Unknown Male, approx. 30yrs",
            "is_mlc": True, "arrival_channel": "ambulance",
        },
        content_type="application/json",
        **auth_header(front_desk, "front_desk"),
    )
    check("Emergency registration succeeds", resp.status_code == 201, resp.content[:500].decode(errors="replace"))
    emg_patient = resp.json()["data"] if resp.status_code == 201 else {}
    check("Emergency patient is provisional", emg_patient.get("identity_status") == "provisional", str(emg_patient))
    check("Emergency patient has no DPDP consent captured (deferred, not skipped silently)",
          emg_patient.get("dpdp_consent_captured") is False and bool(emg_patient.get("consent_deferred_reason")),
          str(emg_patient))

    # Front desk CANNOT originate a referral — confirm this is still enforced.
    resp = client.post(
        "/api/v1/ipd/referrals/recommend/",
        data={
            "patient_id": emg_patient.get("id"), "department_id": dept_gm.id,
            "admission_type": "emergency", "admission_source": "involuntary_mlc",
            "reason_for_admission": "Suspected fracture, unresponsive on arrival.", "is_mlc": True,
        },
        content_type="application/json",
        **auth_header(front_desk, "front_desk"),
    )
    check("Front desk is REJECTED from creating a referral (403)", resp.status_code == 403, resp.content[:300].decode(errors="replace"))

    # Doctor recommends admission — the only legal way in, even for an emergency case.
    resp = client.post(
        "/api/v1/ipd/referrals/recommend/",
        data={
            "patient_id": emg_patient.get("id"), "department_id": dept_gm.id,
            "admission_type": "emergency", "admission_source": "involuntary_mlc",
            "reason_for_admission": "Suspected fracture, unresponsive on arrival.", "is_mlc": True,
        },
        content_type="application/json",
        **auth_header(doctor, "doctor"),
    )
    check("Doctor referral for emergency-sourced admission succeeds", resp.status_code == 201, resp.content[:500].decode(errors="replace"))
    referral = resp.json()["data"] if resp.status_code == 201 else {}
    check("involuntary_mlc referral does NOT require acceptance (doctor's own action already suffices)",
          referral.get("requires_acceptance") is False, str(referral))

    resp = client.get("/api/v1/ipd/referrals/", **auth_header(front_desk, "front_desk"))
    check("Front desk sees the pending referral in its worklist",
          resp.status_code == 200 and any(r["id"] == referral.get("id") for r in resp.json().get("data", [])))

    # Front desk completes the admission, deferring the bed.
    resp = client.post(
        "/api/v1/ipd/admissions/register/",
        data={
            "referral_id": referral.get("id"), "attendant_name": "Not present (MLC)",
            "consent_given": True,
        },
        content_type="application/json",
        **auth_header(front_desk, "front_desk"),
    )
    check("Admission completes with bed deferred", resp.status_code == 201, resp.content[:500].decode(errors="replace"))
    admission = resp.json()["data"] if resp.status_code == 201 else {}
    check("Admission shows awaiting_bed=True, bed=None", admission.get("awaiting_bed") is True and admission.get("bed") is None, str(admission))

    resp = client.get("/api/v1/ipd/admissions/awaiting-bed/", **auth_header(front_desk, "front_desk"))
    check("Awaiting-bed worklist includes this admission",
          resp.status_code == 200 and any(a["id"] == admission.get("id") for a in resp.json().get("data", [])))

    # Later: front desk assigns a bed off the worklist.
    resp = client.post(
        f"/api/v1/ipd/admissions/{admission.get('id')}/assign-bed/",
        data={"bed_id": bed_a.id}, content_type="application/json",
        **auth_header(front_desk, "front_desk"),
    )
    check("Deferred bed assignment succeeds", resp.status_code == 200, resp.content[:500].decode(errors="replace"))
    admission2 = resp.json()["data"] if resp.status_code == 200 else {}
    check("Admission now shows the assigned bed, awaiting_bed=False",
          admission2.get("bed") == bed_a.id and admission2.get("awaiting_bed") is False, str(admission2))

    bed_a.refresh_from_db(using=db_name)
    check("Bed status flipped to occupied", bed_a.status == Bed.STATUS_OCCUPIED)

    # =====================================================================
    # PATH 2 — IPD with IMMEDIATE bed assignment at completion
    # =====================================================================
    print("\n--- PATH 2: IPD referral -> admission -> immediate bed ---")
    resp = client.post(
        "/api/v1/patients/register/",
        data={
            "full_name": "Lakshmi Devaraj", "mobile": "9845099999", "branch_id": branch.id,
            "dpdp_consent": True, "hie_consent": True,
        },
        content_type="application/json",
        **auth_header(front_desk, "front_desk"),
    )
    check("Second (IPD) patient registration succeeds", resp.status_code == 201, resp.content[:300].decode(errors="replace"))
    ipd_patient = resp.json()["data"] if resp.status_code == 201 else {}

    resp = client.post(
        "/api/v1/ipd/referrals/recommend/",
        data={
            "patient_id": ipd_patient.get("id"), "department_id": dept_gm.id,
            "admission_type": "elective", "admission_source": "opd_consultation",
            "reason_for_admission": "Elective admission for observation.",
        },
        content_type="application/json",
        **auth_header(doctor, "doctor"),
    )
    check("Elective IPD referral succeeds", resp.status_code == 201, resp.content[:500].decode(errors="replace"))
    referral2 = resp.json()["data"] if resp.status_code == 201 else {}

    resp = client.post(
        "/api/v1/ipd/admissions/register/",
        data={"referral_id": referral2.get("id"), "attendant_name": "Suresh Devaraj", "consent_given": True},
        content_type="application/json",
        **auth_header(front_desk, "front_desk"),
    )
    check("Second admission completes", resp.status_code == 201, resp.content[:500].decode(errors="replace"))
    admission3 = resp.json()["data"] if resp.status_code == 201 else {}

    resp = client.post(
        f"/api/v1/ipd/admissions/{admission3.get('id')}/assign-bed/",
        data={"bed_id": bed_b.id}, content_type="application/json",
        **auth_header(front_desk, "front_desk"),
    )
    check("Immediate bed assignment at completion succeeds", resp.status_code == 200, resp.content[:500].decode(errors="replace"))
    admission3b = resp.json()["data"] if resp.status_code == 200 else {}
    check("Second admission shows its own bed (not the first admission's)",
          admission3b.get("bed") == bed_b.id, str(admission3b))

    # Double-assignment must be rejected — a bed already occupied.
    resp = client.post(
        f"/api/v1/ipd/admissions/{admission.get('id')}/assign-bed/",
        data={"bed_id": bed_b.id}, content_type="application/json",
        **auth_header(front_desk, "front_desk"),
    )
    check("Assigning an already-occupied bed elsewhere is rejected", resp.status_code == 400, resp.content[:300].decode(errors="replace"))

    # ── Cleanup ──────────────────────────────────────────────────────────
    from apps.tenants.utils import drop_tenant_database
    try:
        connections[db_name].close()
    except Exception:
        pass
    drop_tenant_database(db_name)
    print(f"\nTenant DB {db_name} dropped.")

    passed = sum(1 for _, s, _ in RESULTS if s == "PASS")
    failed = sum(1 for _, s, _ in RESULTS if s == "FAIL")
    print(f"\n==== {passed} passed, {failed} failed (of {len(RESULTS)}) ====")
    if failed:
        print("\nFAILED CHECKS:")
        for name, status, detail in RESULTS:
            if status == "FAIL":
                print(f"  - {name}: {detail}")
    return failed == 0


if __name__ == "__main__":
    ok = False
    try:
        ok = main()
    finally:
        try:
            _srv.cleanup()
        except Exception:
            pass
    sys.exit(0 if ok else 1)
