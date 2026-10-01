from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("records", "0007_three_tables_cleanup")]

    operations = [
        migrations.AddField("MedicalDocument", "size", models.PositiveBigIntegerField(null=True, blank=True)),
    ]
