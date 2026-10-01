from django.db import migrations, models

OLD, NEW = 30, 3600     # seconds: the dispatcher now runs every 60 minutes


def move_to_60_minutes(apps, schema_editor):
    """Only a setting still at the old default is moved; a value an admin chose is left alone."""
    Config = apps.get_model("records", "SweepConfig")
    if not Config.objects.filter(pk=1, sweep_interval_seconds=OLD).update(sweep_interval_seconds=NEW):
        return
    Interval = apps.get_model("django_celery_beat", "IntervalSchedule")
    Task = apps.get_model("django_celery_beat", "PeriodicTask")
    schedule, _ = Interval.objects.get_or_create(every=NEW, period="seconds")
    Task.objects.filter(name="records: recover_stuck_documents").update(interval=schedule)


class Migration(migrations.Migration):
    dependencies = [
        ("records", "0011_slim_tables_and_constraints"),
        ("django_celery_beat", "0019_alter_periodictasks_options"),
    ]

    operations = [
        migrations.AlterField("SweepConfig", "sweep_interval_seconds", models.PositiveIntegerField(default=NEW)),
        migrations.RunPython(move_to_60_minutes, migrations.RunPython.noop),
    ]
