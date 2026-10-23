"""The rules the new design enforces in the database: choices, protected links, one queue number per department and day, dated status changes."""
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("opd", "0018_visit_tokens"),
        ("billing", "0007_prefixed_related_names"),
    ]

    operations = [
        migrations.AlterField(
            model_name="appointment", name="appointment_type",
            field=models.CharField(choices=[("opd", "OPD"), ("followup", "Follow-up"), ("emergency", "Emergency")], default="opd", max_length=15)),
        migrations.AlterField(
            model_name="appointment", name="room",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="r_appointments", to="hospital_setup.room")),
        migrations.AlterField(
            model_name="patientemergencyintake", name="identity_status",
            field=models.CharField(choices=[("confirmed", "Confirmed"), ("provisional", "Provisional")], default="confirmed", max_length=12)),
        migrations.AlterField(
            model_name="patientemergencyintake", name="patient",
            field=models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="p_emergency_intake", to="opd.hospitalpatient")),
        migrations.AlterField(
            model_name="prescription", name="invoice",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="+", to="billing.invoice")),
        migrations.AddIndex(model_name="appointment", index=models.Index(fields=["scheduled_date", "branch_department"], name="appointment_schedul_77ebe7_idx")),
        migrations.AddIndex(model_name="opdencounter", index=models.Index(fields=["status"], name="opd_encount_status_82626c_idx")),
        migrations.AddConstraint(
            model_name="appointment",
            constraint=models.UniqueConstraint(
                condition=models.Q(("token_number__isnull", False)), fields=("branch_department", "scheduled_date", "token_number"),
                name="uniq_appt_queue_token_per_dept_day")),
        migrations.AddConstraint(
            model_name="appointment",
            constraint=models.CheckConstraint(check=models.Q(("token_number__isnull", True), ("token_number__gt", 0), _connector="OR"), name="appointment_token_positive")),
        migrations.AddConstraint(
            model_name="appointment",
            constraint=models.CheckConstraint(
                check=models.Q(models.Q(("status", "done"), _negated=True), ("completed_at__isnull", False), _connector="OR"), name="appointment_done_is_dated")),
        migrations.AddConstraint(
            model_name="hospitalpatient",
            constraint=models.CheckConstraint(
                check=models.Q(("dpdp_consent_captured", False), ("dpdp_consent_at__isnull", False), _connector="OR"), name="patient_dpdp_consent_is_dated")),
        migrations.AddConstraint(
            model_name="hospitalpatient",
            constraint=models.CheckConstraint(
                check=models.Q(("hie_consent_given", False), ("hie_consent_at__isnull", False), _connector="OR"), name="patient_hie_consent_is_dated")),
        migrations.AddConstraint(
            model_name="opdencounter",
            constraint=models.CheckConstraint(
                check=models.Q(models.Q(("status", "signed"), _negated=True), ("signed_at__isnull", False), _connector="OR"), name="encounter_signed_is_dated")),
        migrations.AddConstraint(
            model_name="opdencounter",
            constraint=models.CheckConstraint(
                check=models.Q(("follow_up_in_days__isnull", True), ("follow_up_in_days__gt", 0), _connector="OR"), name="encounter_follow_up_positive")),
        migrations.AddConstraint(
            model_name="opdencounter",
            constraint=models.CheckConstraint(
                check=models.Q(("followup_nurse_booked", False), ("followup_ask_nurse", True), _connector="OR"), name="encounter_nurse_follow_up_was_asked")),
    ]
