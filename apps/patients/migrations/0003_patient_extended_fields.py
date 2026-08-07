"""
Migration: 0003_patient_extended_fields
Add all registration fields to the Patient model:
  - marital_status, nationality, occupation
  - alternate_mobile, address_line1, city, state, pincode
  - emergency_contact_relation
  - payer_type, insurance_provider, policy_number, tpa_name
  - dpdp_consent_captured, dpdp_consent_at
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("patients", "0002_initial"),
    ]

    operations = [
        # Personal extras
        migrations.AddField(
            model_name="patient",
            name="marital_status",
            field=models.CharField(max_length=20, blank=True, default=""),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="patient",
            name="nationality",
            field=models.CharField(max_length=50, blank=True, default="Indian"),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="patient",
            name="occupation",
            field=models.CharField(max_length=100, blank=True, default=""),
            preserve_default=False,
        ),
        # Contact extras
        migrations.AddField(
            model_name="patient",
            name="alternate_mobile",
            field=models.CharField(max_length=15, blank=True, default=""),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="patient",
            name="address_line1",
            field=models.CharField(max_length=255, blank=True, default=""),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="patient",
            name="city",
            field=models.CharField(max_length=100, blank=True, default=""),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="patient",
            name="state",
            field=models.CharField(max_length=100, blank=True, default=""),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="patient",
            name="pincode",
            field=models.CharField(max_length=10, blank=True, default=""),
            preserve_default=False,
        ),
        # Emergency extras
        migrations.AddField(
            model_name="patient",
            name="emergency_contact_relation",
            field=models.CharField(max_length=50, blank=True, default=""),
            preserve_default=False,
        ),
        # Insurance / payment
        migrations.AddField(
            model_name="patient",
            name="payer_type",
            field=models.CharField(
                max_length=20,
                choices=[("self", "Self Pay"), ("insurance", "Insurance"), ("corporate", "Corporate")],
                default="self",
            ),
        ),
        migrations.AddField(
            model_name="patient",
            name="insurance_provider",
            field=models.CharField(max_length=200, blank=True, default=""),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="patient",
            name="policy_number",
            field=models.CharField(max_length=100, blank=True, default=""),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="patient",
            name="tpa_name",
            field=models.CharField(max_length=200, blank=True, default=""),
            preserve_default=False,
        ),
        # DPDP consent
        migrations.AddField(
            model_name="patient",
            name="dpdp_consent_captured",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="patient",
            name="dpdp_consent_at",
            field=models.DateTimeField(null=True, blank=True),
        ),
    ]
