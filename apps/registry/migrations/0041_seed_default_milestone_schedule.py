"""
Data migration: seed a "Default Schedule" MilestoneSchedule/Rule set (system
template) and point every existing Tenant at it, mirroring
0018_seed_default_vaccination_schedule.py's pattern exactly.

IMPORTANT — same caveat as that migration's own _LEGACY_SCHEDULE, and as
apps/registry/vaccine_schedule.py's DEFAULT_VACCINE_SCHEDULE: this is a
reasonable, commonly-cited developmental-milestone checklist (loosely
modeled on widely published pediatric milestone checklists such as the
CDC's "Learn the Signs. Act Early." program), for demonstration purposes
only — it is what a hospital sees the first time it looks at Milestone
Schedules, and every hospital is free to clone-and-customize it (that's the
whole point of the hospital-configurable design). Before any of this is
relied on for real clinical guidance, a hospital's own pediatric team
should review and, if needed, replace these rows via
/api/v1/org/milestone-schedules/ (or the platform-admin template endpoint)
with milestones matching their own clinical protocol.
"""
from django.db import migrations

_DEFAULT_SCHEDULE_NAME = "Default Schedule"

# (domain, milestone, scheduled_label, min_age_days, mandatory)
_LEGACY_MILESTONES = [
    ("gross_motor",      "Holds head up briefly when on tummy",        "2 months",  60,   True),
    ("social_emotional", "Begins to smile at people",                   "2 months",  60,   True),
    ("gross_motor",      "Holds head steady without support",           "4 months",  120,  True),
    ("fine_motor",       "Brings hands to mouth",                       "4 months",  120,  True),
    ("language",         "Babbles, makes sounds other than crying",     "4 months",  120,  True),
    ("gross_motor",      "Rolls over both ways",                        "6 months",  180,  True),
    ("fine_motor",       "Passes an object hand to hand",                "6 months",  180,  True),
    ("social_emotional", "Knows familiar faces, begins to recognize strangers", "6 months", 180, False),
    ("gross_motor",      "Sits without support",                        "9 months",  270,  True),
    ("cognitive",        "Looks for objects when dropped/hidden",        "9 months",  270,  True),
    ("language",         "Understands 'no'",                             "9 months",  270,  False),
    ("gross_motor",      "Pulls to stand, may take steps holding on",    "12 months", 365,  True),
    ("fine_motor",       "Uses pincer grasp (thumb and forefinger)",     "12 months", 365,  True),
    ("language",         "Says 'mama'/'dada' and at least one other word", "12 months", 365, True),
    ("social_emotional", "Plays simple interaction games (peekaboo)",    "12 months", 365,  False),
    ("gross_motor",      "Walks alone",                                  "18 months", 548,  True),
    ("language",         "Says several single words",                    "18 months", 548,  True),
    ("cognitive",        "Points to show something interesting",         "18 months", 548,  False),
    ("fine_motor",       "Scribbles spontaneously",                       "18 months", 548,  False),
    ("gross_motor",      "Runs; kicks a ball",                            "24 months", 730,  True),
    ("language",         "Says short 2-word phrases",                     "24 months", 730,  True),
    ("cognitive",        "Sorts shapes/colors; follows 2-step instructions", "24 months", 730, False),
    ("social_emotional", "Shows increasing independence",                 "24 months", 730,  False),
    ("gross_motor",      "Climbs well; pedals a tricycle",                "36 months", 1095, True),
    ("language",         "Speaks in 3-word sentences, mostly understood by strangers", "36 months", 1095, True),
    ("fine_motor",       "Copies a circle; turns pages one at a time",    "36 months", 1095, False),
    ("social_emotional", "Shows affection for playmates; takes turns in games", "36 months", 1095, False),
    ("gross_motor",      "Hops and stands on one foot up to 2 seconds",   "48 months", 1460, True),
    ("language",         "Tells stories; speaks clearly",                 "48 months", 1460, True),
    ("cognitive",        "Names some colors and numbers; understands counting", "48 months", 1460, False),
    ("social_emotional", "Cooperates with other children; prefers to play with others", "48 months", 1460, False),
    ("gross_motor",      "Hops, may be able to skip; does a somersault",  "60 months", 1825, True),
    ("language",         "Speaks very clearly; tells simple stories using full sentences", "60 months", 1825, True),
    ("cognitive",        "Counts 10+ objects; knows about everyday things (money, food)", "60 months", 1825, False),
    ("social_emotional", "Wants to please friends; wants to be like friends; agrees with rules", "60 months", 1825, False),
]


def seed_default_schedule(apps, schema_editor):
    MilestoneSchedule = apps.get_model("registry", "MilestoneSchedule")
    MilestoneScheduleRule = apps.get_model("registry", "MilestoneScheduleRule")
    Tenant = apps.get_model("tenants", "Tenant")

    schedule, _ = MilestoneSchedule.objects.using("default").get_or_create(
        name=_DEFAULT_SCHEDULE_NAME,
        owner_tenant_id=None,
        defaults={
            "description": (
                "System default developmental-milestone schedule — a starting "
                "point every hospital can clone and customize for its own "
                "clinical protocol."
            ),
            "is_template": True,
            "active": True,
        },
    )

    if not MilestoneScheduleRule.objects.using("default").filter(schedule=schedule).exists():
        for sort_order, (domain, milestone, label, min_age_days, mandatory) in enumerate(_LEGACY_MILESTONES):
            MilestoneScheduleRule.objects.using("default").create(
                schedule=schedule,
                domain=domain,
                milestone=milestone,
                scheduled_label=label,
                min_age_days=min_age_days,
                max_age_days=None,
                mandatory=mandatory,
                sort_order=sort_order,
            )

    Tenant.objects.using("default").filter(
        active_milestone_schedule_id__isnull=True
    ).update(active_milestone_schedule_id=schedule.id)


def unseed_default_schedule(apps, schema_editor):
    MilestoneSchedule = apps.get_model("registry", "MilestoneSchedule")
    Tenant = apps.get_model("tenants", "Tenant")

    schedule = (
        MilestoneSchedule.objects.using("default")
        .filter(name=_DEFAULT_SCHEDULE_NAME, owner_tenant_id=None)
        .first()
    )
    if not schedule:
        return

    Tenant.objects.using("default").filter(
        active_milestone_schedule_id=schedule.id
    ).update(active_milestone_schedule_id=None)

    schedule.delete()


class Migration(migrations.Migration):

    dependencies = [
        ("registry", "0040_milestoneschedule_milestoneschedulerule_and_more"),
        ("tenants", "0013_tenant_active_milestone_schedule_id"),
    ]

    operations = [
        migrations.RunPython(seed_default_schedule, unseed_default_schedule),
    ]
