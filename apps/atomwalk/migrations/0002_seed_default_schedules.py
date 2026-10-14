"""The platform's default immunization schedule and developmental-milestone schedule: the templates every hospital
starts from."""
from django.db import migrations

SCHEDULES = [   # kind, name, description
    ('vaccination', 'Default Schedule', 'System default vaccination schedule, migrated from the old hardcoded DEFAULT_VACCINE_SCHEDULE list.'),
    ('milestone', 'Default Schedule', 'System default developmental-milestone schedule — a starting point every hospital can clone and customize for its own clinical protocol.'),
]
RULES = [   # kind, item, dose_number, scheduled_label, min_age_days, max_age_days, mandatory, sort_order, domain
    ('vaccination', 'BCG', 1, 'Birth', 0, None, True, 0, ''),
    ('vaccination', 'Hepatitis B - 1', 1, 'Birth', 0, None, True, 1, ''),
    ('vaccination', 'OPV - 0', 1, 'Birth', 0, None, True, 2, ''),
    ('vaccination', 'DTP - 1', 1, '6 weeks', 42, None, True, 3, ''),
    ('vaccination', 'OPV - 1', 1, '6 weeks', 42, None, True, 4, ''),
    ('vaccination', 'Hepatitis B - 2', 1, '6 weeks', 42, None, True, 5, ''),
    ('vaccination', 'DTP - 2', 1, '10 weeks', 70, None, True, 6, ''),
    ('vaccination', 'OPV - 2', 1, '10 weeks', 70, None, True, 7, ''),
    ('vaccination', 'DTP - 3', 1, '14 weeks', 98, None, True, 8, ''),
    ('vaccination', 'OPV - 3', 1, '14 weeks', 98, None, True, 9, ''),
    ('vaccination', 'Hepatitis B - 3', 1, '14 weeks', 98, None, True, 10, ''),
    ('vaccination', 'Measles - 1', 1, '9 months', 274, None, True, 11, ''),
    ('vaccination', 'MMR - 1', 1, '9 months', 274, None, True, 12, ''),
    ('vaccination', 'MMR - 2 (Booster)', 1, '16-18 months', 548, None, True, 13, ''),
    ('vaccination', 'DTP Booster - 1', 1, '16-18 months', 548, None, True, 14, ''),
    ('vaccination', 'DTP Booster - 2', 1, '5 years', 1825, None, True, 15, ''),
    ('vaccination', 'Typhoid Booster', 1, '6 years', 2190, None, True, 16, ''),
    ('vaccination', 'Tdap/Td Booster', 1, '10 years', 3650, None, True, 17, ''),
    ('milestone', 'Holds head up briefly when on tummy', 1, '2 months', 60, None, True, 0, 'gross_motor'),
    ('milestone', 'Begins to smile at people', 1, '2 months', 60, None, True, 1, 'social_emotional'),
    ('milestone', 'Holds head steady without support', 1, '4 months', 120, None, True, 2, 'gross_motor'),
    ('milestone', 'Brings hands to mouth', 1, '4 months', 120, None, True, 3, 'fine_motor'),
    ('milestone', 'Babbles, makes sounds other than crying', 1, '4 months', 120, None, True, 4, 'language'),
    ('milestone', 'Rolls over both ways', 1, '6 months', 180, None, True, 5, 'gross_motor'),
    ('milestone', 'Passes an object hand to hand', 1, '6 months', 180, None, True, 6, 'fine_motor'),
    ('milestone', 'Knows familiar faces, begins to recognize strangers', 1, '6 months', 180, None, False, 7, 'social_emotional'),
    ('milestone', 'Sits without support', 1, '9 months', 270, None, True, 8, 'gross_motor'),
    ('milestone', 'Looks for objects when dropped/hidden', 1, '9 months', 270, None, True, 9, 'cognitive'),
    ('milestone', "Understands 'no'", 1, '9 months', 270, None, False, 10, 'language'),
    ('milestone', 'Pulls to stand, may take steps holding on', 1, '12 months', 365, None, True, 11, 'gross_motor'),
    ('milestone', 'Uses pincer grasp (thumb and forefinger)', 1, '12 months', 365, None, True, 12, 'fine_motor'),
    ('milestone', "Says 'mama'/'dada' and at least one other word", 1, '12 months', 365, None, True, 13, 'language'),
    ('milestone', 'Plays simple interaction games (peekaboo)', 1, '12 months', 365, None, False, 14, 'social_emotional'),
    ('milestone', 'Walks alone', 1, '18 months', 548, None, True, 15, 'gross_motor'),
    ('milestone', 'Says several single words', 1, '18 months', 548, None, True, 16, 'language'),
    ('milestone', 'Points to show something interesting', 1, '18 months', 548, None, False, 17, 'cognitive'),
    ('milestone', 'Scribbles spontaneously', 1, '18 months', 548, None, False, 18, 'fine_motor'),
    ('milestone', 'Runs; kicks a ball', 1, '24 months', 730, None, True, 19, 'gross_motor'),
    ('milestone', 'Says short 2-word phrases', 1, '24 months', 730, None, True, 20, 'language'),
    ('milestone', 'Sorts shapes/colors; follows 2-step instructions', 1, '24 months', 730, None, False, 21, 'cognitive'),
    ('milestone', 'Shows increasing independence', 1, '24 months', 730, None, False, 22, 'social_emotional'),
    ('milestone', 'Climbs well; pedals a tricycle', 1, '36 months', 1095, None, True, 23, 'gross_motor'),
    ('milestone', 'Speaks in 3-word sentences, mostly understood by strangers', 1, '36 months', 1095, None, True, 24, 'language'),
    ('milestone', 'Copies a circle; turns pages one at a time', 1, '36 months', 1095, None, False, 25, 'fine_motor'),
    ('milestone', 'Shows affection for playmates; takes turns in games', 1, '36 months', 1095, None, False, 26, 'social_emotional'),
    ('milestone', 'Hops and stands on one foot up to 2 seconds', 1, '48 months', 1460, None, True, 27, 'gross_motor'),
    ('milestone', 'Tells stories; speaks clearly', 1, '48 months', 1460, None, True, 28, 'language'),
    ('milestone', 'Names some colors and numbers; understands counting', 1, '48 months', 1460, None, False, 29, 'cognitive'),
    ('milestone', 'Cooperates with other children; prefers to play with others', 1, '48 months', 1460, None, False, 30, 'social_emotional'),
    ('milestone', 'Hops, may be able to skip; does a somersault', 1, '60 months', 1825, None, True, 31, 'gross_motor'),
    ('milestone', 'Speaks very clearly; tells simple stories using full sentences', 1, '60 months', 1825, None, True, 32, 'language'),
    ('milestone', 'Counts 10+ objects; knows about everyday things (money, food)', 1, '60 months', 1825, None, False, 33, 'cognitive'),
    ('milestone', 'Wants to please friends; wants to be like friends; agrees with rules', 1, '60 months', 1825, None, False, 34, 'social_emotional'),
]


def seed(apps, schema_editor):
    db = schema_editor.connection.alias
    Schedule, Rule = apps.get_model("atomwalk", "Schedule"), apps.get_model("atomwalk", "ScheduleRule")
    made = {kind: Schedule.objects.using(db).create(kind=kind, name=name, description=text, is_template=True, active=True)
            for kind, name, text in SCHEDULES}
    Rule.objects.using(db).bulk_create(
        Rule(schedule=made[kind], item=item, dose_number=dose, scheduled_label=label, min_age_days=low, max_age_days=high,
             mandatory=mandatory, sort_order=order, domain=domain)
        for kind, item, dose, label, low, high, mandatory, order, domain in RULES)


class Migration(migrations.Migration):
    dependencies = [("atomwalk", "0001_initial")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
