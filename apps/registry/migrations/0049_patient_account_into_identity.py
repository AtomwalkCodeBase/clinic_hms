"""
patient_account is folded into patient_identity: one row per person, with the portal login (mobile, password, photo,
emergency contact...) on it. PortalBooking.account and EmergencyAccessLog.generated_by_account_id now hold the
identity's id, so every existing login keeps its bookings. Anyone signed in before this runs must sign in again
(their token carries the old account id).
"""
from django.db import migrations, models
import django.db.models.deletion

_LOGIN = ["mobile", "password", "photo", "is_active", "last_login",
          "emergency_contact_name", "emergency_contact_phone", "emergency_contact_relation"]


def accounts_into_identities(apps, schema_editor):
    Identity, Account = apps.get_model("registry", "PatientIdentity"), apps.get_model("registry", "PatientAccount")
    Booking, Log = apps.get_model("registry", "PortalBooking"), apps.get_model("registry", "EmergencyAccessLog")
    new_id = {}
    for acct in Account.objects.using("default").all():
        identity = Identity.objects.using("default").filter(awpid=acct.awpid).first()
        if identity is None:     # an account without an identity row should not exist; make one rather than lose the login
            identity = Identity(awpid=acct.awpid, full_name=acct.full_name)
        for f in _LOGIN:
            setattr(identity, f, getattr(acct, f))
        identity.email = identity.email or acct.email or ""
        identity.date_of_birth = identity.date_of_birth or acct.date_of_birth
        identity.gender = identity.gender or acct.gender
        identity.save(using="default")
        new_id[acct.id] = identity.id
    # rewrite from a snapshot taken first, so a row is never remapped twice
    for model, column in ((Booking, "account_id"), (Log, "generated_by_account_id")):
        rows = list(model.objects.using("default").exclude(**{column: None}).values_list("pk", column))
        for pk, old in rows:
            if old in new_id:
                model.objects.using("default").filter(pk=pk).update(**{column: new_id[old]})
    schema_editor.execute("SET CONSTRAINTS ALL IMMEDIATE")


def identities_into_accounts(apps, schema_editor):
    Identity, Account = apps.get_model("registry", "PatientIdentity"), apps.get_model("registry", "PatientAccount")
    for identity in Identity.objects.using("default").exclude(password=""):
        Account.objects.using("default").create(
            id=identity.id, awpid=identity.awpid, full_name=identity.full_name, email=identity.email or None,
            gender=identity.gender[:1], date_of_birth=identity.date_of_birth,
            **{f: getattr(identity, f) for f in _LOGIN})     # same id, so bookings and log rows stay valid
    schema_editor.execute("SELECT setval(pg_get_serial_sequence('patient_account', 'id'), COALESCE((SELECT MAX(id) FROM patient_account), 1))")
    schema_editor.execute("SET CONSTRAINTS ALL IMMEDIATE")


class Migration(migrations.Migration):

    dependencies = [("registry", "0048_merge_schedules")]

    operations = [
        migrations.AddField("PatientIdentity", "mobile", models.CharField(blank=True, max_length=15, null=True, unique=True)),
        migrations.AddField("PatientIdentity", "password", models.CharField(blank=True, max_length=128)),
        migrations.AddField("PatientIdentity", "photo", models.TextField(blank=True)),
        migrations.AddField("PatientIdentity", "is_active", models.BooleanField(default=True)),
        migrations.AddField("PatientIdentity", "last_login", models.DateTimeField(blank=True, null=True)),
        migrations.AddField("PatientIdentity", "emergency_contact_name", models.CharField(blank=True, max_length=200)),
        migrations.AddField("PatientIdentity", "emergency_contact_phone", models.CharField(blank=True, max_length=15)),
        migrations.AddField("PatientIdentity", "emergency_contact_relation", models.CharField(blank=True, max_length=30)),
        # no database constraint while the booking rows still hold account ids
        migrations.AlterField("PortalBooking", "account", models.ForeignKey(
            db_constraint=False, on_delete=django.db.models.deletion.CASCADE, related_name="bookings", to="registry.patientidentity")),
        migrations.RunPython(accounts_into_identities, identities_into_accounts),
        migrations.AlterField("PortalBooking", "account", models.ForeignKey(
            on_delete=django.db.models.deletion.CASCADE, related_name="bookings", to="registry.patientidentity")),
        migrations.DeleteModel("PatientAccount"),
        migrations.CreateModel(name="PatientAccount", fields=[], options={"proxy": True, "indexes": [], "constraints": []},
                               bases=("registry.patientidentity",)),
    ]
