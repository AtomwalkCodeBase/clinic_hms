from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("registry", "0046_drop_classifier_cache_tables")]
    operations = [
        migrations.AddField(
            model_name="consultsession",
            name="note_pdf",
            field=models.CharField(blank=True, max_length=500),
        ),
    ]
