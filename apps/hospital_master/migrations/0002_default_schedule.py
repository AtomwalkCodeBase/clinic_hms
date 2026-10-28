"""The platform's default immunization schedule: the template every hospital starts from."""
from django.db import migrations

RULES = [   # item, dose_number, scheduled_label, min_age_days, max_age_days, mandatory, sort_order
    ('BCG', 1, 'Birth', 0, None, True, 0),
    ('Hepatitis B - 1', 1, 'Birth', 0, None, True, 1),
    ('OPV - 0', 1, 'Birth', 0, None, True, 2),
    ('DTP - 1', 1, '6 weeks', 42, None, True, 3),
    ('OPV - 1', 1, '6 weeks', 42, None, True, 4),
    ('Hepatitis B - 2', 1, '6 weeks', 42, None, True, 5),
    ('DTP - 2', 1, '10 weeks', 70, None, True, 6),
    ('OPV - 2', 1, '10 weeks', 70, None, True, 7),
    ('DTP - 3', 1, '14 weeks', 98, None, True, 8),
    ('OPV - 3', 1, '14 weeks', 98, None, True, 9),
    ('Hepatitis B - 3', 1, '14 weeks', 98, None, True, 10),
    ('Measles - 1', 1, '9 months', 274, None, True, 11),
    ('MMR - 1', 1, '9 months', 274, None, True, 12),
    ('MMR - 2 (Booster)', 1, '16-18 months', 548, None, True, 13),
    ('DTP Booster - 1', 1, '16-18 months', 548, None, True, 14),
    ('DTP Booster - 2', 1, '5 years', 1825, None, True, 15),
    ('Typhoid Booster', 1, '6 years', 2190, None, True, 16),
    ('Tdap/Td Booster', 1, '10 years', 3650, None, True, 17),
]


def seed(apps, schema_editor):
    db = schema_editor.connection.alias
    Schedule, Rule = apps.get_model("hospital_master", "Schedule"), apps.get_model("hospital_master", "ScheduleRule")
    schedule = Schedule.objects.using(db).create(
        kind="vaccination", name="Default Schedule", description="System default vaccination schedule.", is_template=True, active=True)
    Rule.objects.using(db).bulk_create(
        Rule(schedule=schedule, item=item, dose_number=dose, scheduled_label=label, min_age_days=low, max_age_days=high, mandatory=mandatory, sort_order=order)
        for item, dose, label, low, high, mandatory, order in RULES)


class Migration(migrations.Migration):
    dependencies = [("hospital_master", "0001_initial")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
