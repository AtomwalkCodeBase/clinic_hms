"""Phase 3 of 3: drop the personal details from the hospital's patient row; they live in the shared patient record and the side tables."""
from django.db import migrations

DROPPED = [
    "full_name", "date_of_birth", "gender", "blood_group", "marital_status", "nationality", "occupation",
    "mobile", "alternate_mobile", "email", "address_line1", "city", "state", "pincode",
    "is_dependent", "guardian_name", "guardian_mobile",
    "emergency_contact_name", "emergency_contact_phone", "emergency_contact_relation",
    "payer_type", "insurance_provider", "policy_number", "tpa_name",
    "preferred_language",
    "identity_status", "is_mlc", "arrival_channel", "placeholder_label", "consent_deferred_reason",
]


class Migration(migrations.Migration):

    dependencies = [
        ("opd", "0010_patient_data"),
    ]

    operations = [migrations.RemoveField(model_name="hospitalpatient", name=name) for name in DROPPED]
