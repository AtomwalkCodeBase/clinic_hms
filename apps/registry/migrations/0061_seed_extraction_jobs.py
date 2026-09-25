from django.db import migrations

JOBS = [
    # name, task, every N minutes, description
    ("Process mobile bulk uploads", "apps.registry.tasks.process_bulk_extractions", 1,
     "Reads the oldest queued files of mobile bulk uploads, at most 'bulk_batch_limit' per run "
     "(Background Jobs -> Settings). Same idea as 'Process bulk uploads' for My Reports."),
    ("Recover mobile uploads", "apps.registry.tasks.periodic_reconcile", 5,
     "Closes stalled or abandoned mobile bulk uploads and fails files stuck in processing."),
]


def seed(apps, schema_editor):
    """
    The scheduled jobs of the mobile upload-and-extract flow. Beat reads its schedule
    from the database (django_celery_beat), so they have to exist as rows here — a
    CELERY_BEAT_SCHEDULE entry in settings would be ignored. Both stay editable on
    platform admin -> Background Jobs (interval, on/off).
    """
    alias = schema_editor.connection.alias
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    Interval = apps.get_model("django_celery_beat", "IntervalSchedule")
    for name, task, minutes, description in JOBS:
        if PeriodicTask.objects.using(alias).filter(name=name).exists():
            continue
        every, _ = Interval.objects.using(alias).get_or_create(every=minutes, period="minutes")
        PeriodicTask.objects.using(alias).create(
            name=name, task=task, interval=every, kwargs="{}", args="[]", enabled=True,
            description=description,
        )


class Migration(migrations.Migration):

    dependencies = [
        ('registry', '0060_extractionitem_dispatch_tracking'),
        ('django_celery_beat', '0019_alter_periodictasks_options'),
    ]

    operations = [
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
