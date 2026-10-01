from django.db import migrations, models

OLD, NEW = 3600, 30     # seconds: the dispatcher runs every 30 seconds again


def back_to_30_seconds(apps, schema_editor):
    """Only a setting still at the 60-minute default of migration 0012 is moved; a value an admin chose stays."""
    Config = apps.get_model("records", "SweepConfig")
    if not Config.objects.filter(pk=1, sweep_interval_seconds=OLD).update(sweep_interval_seconds=NEW):
        return
    Interval = apps.get_model("django_celery_beat", "IntervalSchedule")
    Task = apps.get_model("django_celery_beat", "PeriodicTask")
    schedule, _ = Interval.objects.get_or_create(every=NEW, period="seconds")
    Task.objects.filter(name="records: recover_stuck_documents").update(interval=schedule)


class Migration(migrations.Migration):
    dependencies = [("records", "0013_instant_max_files_50")]

    operations = [
        migrations.AlterField("SweepConfig", "sweep_interval_seconds", models.PositiveIntegerField(default=NEW)),
        migrations.RunPython(back_to_30_seconds, migrations.RunPython.noop),
    ]
