from django.db import migrations, models

OLD, NEW = 5, 50     # every upload holds at most 50 files, so every upload is dispatched at once


def raise_to_50(apps, schema_editor):
    """Only a setting still at the old default is moved; a value an admin chose is left alone."""
    apps.get_model("records", "SweepConfig").objects.filter(pk=1, instant_max_files=OLD).update(instant_max_files=NEW)


class Migration(migrations.Migration):
    dependencies = [("records", "0012_sweep_interval_60_minutes")]

    operations = [
        migrations.AlterField("SweepConfig", "instant_max_files", models.PositiveIntegerField(default=NEW)),
        migrations.RunPython(raise_to_50, migrations.RunPython.noop),
    ]
