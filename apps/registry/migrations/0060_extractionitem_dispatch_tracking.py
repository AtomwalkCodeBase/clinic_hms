from django.db import migrations, models


class Migration(migrations.Migration):
    """Remember when each extraction ticket was last queued, so lost tickets (Redis crash) can be re-sent."""

    dependencies = [
        ("registry", "0059_extractionitem_dismissed_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="extractionitem", name="dispatched_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="extractionitem", name="dispatch_count",
            field=models.PositiveSmallIntegerField(default=0),
        ),
    ]
