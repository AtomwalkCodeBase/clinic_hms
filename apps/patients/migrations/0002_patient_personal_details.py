from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("patients", "0001_initial"),
    ]

    operations = [
        migrations.AddField(model_name="patient", name="alternate_mobile", field=models.CharField(blank=True, default="", max_length=15)),
        migrations.AddField(model_name="patient", name="address_line1", field=models.CharField(blank=True, default="", max_length=255)),
        migrations.AddField(model_name="patient", name="city", field=models.CharField(blank=True, default="", max_length=100)),
        migrations.AddField(model_name="patient", name="state", field=models.CharField(blank=True, default="", max_length=100)),
        migrations.AddField(model_name="patient", name="pincode", field=models.CharField(blank=True, default="", max_length=10)),
        migrations.AddField(model_name="patient", name="marital_status", field=models.CharField(blank=True, default="", max_length=20)),
        migrations.AddField(model_name="patient", name="nationality", field=models.CharField(blank=True, default="Indian", max_length=50)),
        migrations.AddField(model_name="patient", name="occupation", field=models.CharField(blank=True, default="", max_length=100)),
    ]
