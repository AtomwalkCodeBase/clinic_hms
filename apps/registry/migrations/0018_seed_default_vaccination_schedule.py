"""
Data migration: seed the "Default Schedule" VaccinationSchedule/Rule rows
from the old hardcoded DEFAULT_VACCINE_SCHEDULE list in
apps/registry/vaccine_schedule.py, and point every existing Tenant at it so
no hospital loses vaccination-roadmap functionality when this ships.

Values below are copied verbatim from DEFAULT_VACCINE_SCHEDULE as it stood
right before this migration was written — vaccine_name/label/due_days are
preserved exactly; due_days -> min_age_days 1:1 (same unit: age in days).
max_age_days is left null: the old list had no per-item upper bound, only
a single global "overdue grace" constant that this migration deliberately
does NOT carry forward, since the new status semantics never fabricate an
"overdue" verdict from a missing record (see vaccine_schedule.py).
"""
from django.db import migrations


# Exact copy of DEFAULT_VACCINE_SCHEDULE from apps/registry/vaccine_schedule.py
# at the time this migration was written. vaccine_name/label/due_days values
# must not be changed here independently of that list.
_LEGACY_SCHEDULE = [
    {"vaccine_name": "BCG",               "label": "Birth",       "due_days": 0},
    {"vaccine_name": "Hepatitis B - 1",   "label": "Birth",       "due_days": 0},
    {"vaccine_name": "OPV - 0",           "label": "Birth",       "due_days": 0},
    {"vaccine_name": "DTP - 1",           "label": "6 weeks",     "due_days": 42},
    {"vaccine_name": "OPV - 1",           "label": "6 weeks",     "due_days": 42},
    {"vaccine_name": "Hepatitis B - 2",   "label": "6 weeks",     "due_days": 42},
    {"vaccine_name": "DTP - 2",           "label": "10 weeks",    "due_days": 70},
    {"vaccine_name": "OPV - 2",           "label": "10 weeks",    "due_days": 70},
    {"vaccine_name": "DTP - 3",           "label": "14 weeks",    "due_days": 98},
    {"vaccine_name": "OPV - 3",           "label": "14 weeks",    "due_days": 98},
    {"vaccine_name": "Hepatitis B - 3",   "label": "14 weeks",    "due_days": 98},
    {"vaccine_name": "Measles - 1",       "label": "9 months",    "due_days": 274},
    {"vaccine_name": "MMR - 1",           "label": "9 months",    "due_days": 274},
    {"vaccine_name": "MMR - 2 (Booster)", "label": "16-18 months","due_days": 548},
    {"vaccine_name": "DTP Booster - 1",   "label": "16-18 months","due_days": 548},
    {"vaccine_name": "DTP Booster - 2",   "label": "5 years",     "due_days": 1825},
    {"vaccine_name": "Typhoid Booster",   "label": "6 years",     "due_days": 2190},
    {"vaccine_name": "Tdap/Td Booster",   "label": "10 years",    "due_days": 3650},
]

_DEFAULT_SCHEDULE_NAME = "Default Schedule"


def seed_default_schedule(apps, schema_editor):
    VaccinationSchedule = apps.get_model("registry", "VaccinationSchedule")
    VaccinationScheduleRule = apps.get_model("registry", "VaccinationScheduleRule")
    Tenant = apps.get_model("tenants", "Tenant")

    schedule, created = VaccinationSchedule.objects.using("default").get_or_create(
        name=_DEFAULT_SCHEDULE_NAME,
        owner_tenant_id=None,
        defaults={
            "description": (
                "System default vaccination schedule, migrated from the old "
                "hardcoded DEFAULT_VACCINE_SCHEDULE list."
            ),
            "is_template": True,
            "active": True,
        },
    )

    # Idempotent: if this migration runs more than once against a DB that
    # already has rules for this schedule (shouldn't happen in normal
    # forward-only usage, but keeps re-runs / squashes safe), don't
    # duplicate them.
    if not VaccinationScheduleRule.objects.using("default").filter(schedule=schedule).exists():
        for sort_order, item in enumerate(_LEGACY_SCHEDULE):
            VaccinationScheduleRule.objects.using("default").create(
                schedule=schedule,
                vaccine_name=item["vaccine_name"],
                dose_number=1,
                scheduled_label=item["label"],
                min_age_days=item["due_days"],
                max_age_days=None,
                mandatory=True,
                sort_order=sort_order,
            )

    # Every EXISTING tenant gets pointed at this schedule so nobody loses
    # vaccination functionality when this ships. Tenants that already have
    # a schedule assigned (shouldn't be possible pre-migration, but this is
    # belt-and-suspenders for repeat runs) are left alone.
    Tenant.objects.using("default").filter(
        active_vaccination_schedule_id__isnull=True
    ).update(active_vaccination_schedule_id=schedule.id)


def unseed_default_schedule(apps, schema_editor):
    VaccinationSchedule = apps.get_model("registry", "VaccinationSchedule")
    Tenant = apps.get_model("tenants", "Tenant")

    schedule = (
        VaccinationSchedule.objects.using("default")
        .filter(name=_DEFAULT_SCHEDULE_NAME, owner_tenant_id=None)
        .first()
    )
    if not schedule:
        return

    Tenant.objects.using("default").filter(
        active_vaccination_schedule_id=schedule.id
    ).update(active_vaccination_schedule_id=None)

    # Rules cascade-delete with the schedule.
    schedule.delete()


class Migration(migrations.Migration):

    dependencies = [
        ("registry", "0017_vaccinationschedule_vaccinationschedulerule"),
        ("tenants", "0007_tenant_active_vaccination_schedule_id"),
    ]

    operations = [
        migrations.RunPython(seed_default_schedule, unseed_default_schedule),
    ]
