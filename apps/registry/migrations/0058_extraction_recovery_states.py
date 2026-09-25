from django.db import migrations, models


class Migration(migrations.Migration):
    """
    Recovery + state model for the extraction pipeline: per-item attempt claims,
    batch progress/start-failure timestamps, and the failed / cancelled batch states.
    """

    dependencies = [
        ("registry", "0057_extractionbatch_progress_columns"),
    ]

    operations = [
        migrations.AddField(
            model_name="extractionitem", name="attempts",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="extractionbatch", name="last_progress_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="extractionbatch", name="start_failed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="extractionbatch", name="status",
            field=models.CharField(
                choices=[("pending", "Pending"), ("queued", "Queued"), ("processing", "Processing"),
                         ("done", "Done"), ("partial", "Partial"), ("failed", "Failed"),
                         ("cancelled", "Cancelled")],
                db_index=True, default="pending", max_length=12),
        ),
    ]
