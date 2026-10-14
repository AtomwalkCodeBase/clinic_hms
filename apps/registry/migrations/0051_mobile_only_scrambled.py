"""
A patient's mobile number is no longer stored in plain form. Login and hospital matching both use the scrambled number
(patient_identity.mobile_hash). Before the plain column is dropped, any identity that has a plain number but no scrambled
one gets its scrambled number. NOTE: dropping the column is one-way; a rollback restores an empty column, not the numbers.
"""
from django.db import migrations


def scramble_before_dropping(apps, schema_editor):
    from core.utils.hashing import hash_mobile, normalize_mobile
    Identity = apps.get_model("registry", "PatientIdentity")
    used = set(Identity.objects.using("default").exclude(mobile_hash__isnull=True).values_list("mobile_hash", flat=True))
    for identity in Identity.objects.using("default").filter(mobile_hash__isnull=True).exclude(mobile__isnull=True).exclude(mobile=""):
        scrambled = hash_mobile(normalize_mobile(identity.mobile))
        if scrambled not in used:
            Identity.objects.using("default").filter(pk=identity.pk).update(mobile_hash=scrambled)
            used.add(scrambled)


class Migration(migrations.Migration):

    dependencies = [("registry", "0050_consult_pad_token_on_session")]

    operations = [
        migrations.RunPython(scramble_before_dropping, migrations.RunPython.noop),
        migrations.RemoveField("PatientIdentity", "mobile"),
    ]
