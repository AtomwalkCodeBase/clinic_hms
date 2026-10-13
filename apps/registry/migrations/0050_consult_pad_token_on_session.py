"""
The consultation-pad QR token moves from the patient's shared identity onto each ConsultSession, so a link says which
consultation (and so which patient and hospital) it is for. patient_identity loses consult_pad_token and
consult_pad_owner_tenant_id. Sessions that already exist get a token of their own.
"""
import secrets

from django.db import migrations, models

import apps.registry.models


def give_each_session_a_token(apps, schema_editor):
    Session = apps.get_model("registry", "ConsultSession")
    for session in Session.objects.using("default").filter(token__isnull=True):
        Session.objects.using("default").filter(pk=session.pk).update(token=secrets.token_urlsafe(32))


class Migration(migrations.Migration):

    dependencies = [("registry", "0049_patient_account_into_identity")]

    operations = [
        migrations.AddField("ConsultSession", "token", models.CharField(max_length=64, null=True)),
        migrations.RunPython(give_each_session_a_token, migrations.RunPython.noop),
        migrations.AlterField("ConsultSession", "token", models.CharField(
            db_index=True, default=apps.registry.models.new_pad_token, max_length=64, unique=True)),
        migrations.RemoveField("PatientIdentity", "consult_pad_token"),
        migrations.RemoveField("PatientIdentity", "consult_pad_owner_tenant_id"),
    ]
