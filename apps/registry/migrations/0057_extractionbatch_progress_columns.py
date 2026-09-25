from django.db import migrations, models


class Migration(migrations.Migration):
    """Stores batch progress (processed / progress_percent) as real columns instead of computing it on read."""

    dependencies = [
        ("registry", "0056_extraction_file_key_json_progress"),
    ]

    operations = [
        migrations.AddField(
            model_name="extractionbatch", name="processed",
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name="extractionbatch", name="progress_percent",
            field=models.PositiveSmallIntegerField(default=0),
        ),
    ]
