from django.db import migrations, models


class Migration(migrations.Migration):
    """The patient can dismiss a finished extraction from their Extracted reports list (hide only, nothing deleted)."""

    dependencies = [
        ("registry", "0058_extraction_recovery_states"),
    ]

    operations = [
        migrations.AddField(
            model_name="extractionitem", name="dismissed_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
    ]
