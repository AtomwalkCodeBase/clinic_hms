from django.db import migrations, models


class Migration(migrations.Migration):
    """
    Extraction files are now kept: staging_key (temporary-sounding, bulk only)
    becomes file_key (permanent, both paths). Adds the stored file's size, the
    structured extraction JSON, and progress timestamps.
    """

    dependencies = [
        ("registry", "0055_extractionbatch_initiated_by_awpid_pushdevicetoken"),
    ]

    operations = [
        migrations.RenameField(model_name="extractionitem", old_name="staging_key", new_name="file_key"),
        migrations.AddField(
            model_name="extractionitem", name="file_size",
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name="extractionitem", name="extraction_json",
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="extractionitem", name="started_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="extractionbatch", name="queued_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
