from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("records", "0003_sweepconfig_sweep_interval_seconds")]

    operations = [migrations.RenameField("shareddocument", "s3_key", "file_path")]
