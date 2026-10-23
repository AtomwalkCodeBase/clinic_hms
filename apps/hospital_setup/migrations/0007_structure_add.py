"""Phase 1 of 3: the new structure beside the old (departments by branch, user groups, one profile). Nothing is removed or filled in here."""
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("hospital_setup", "0006_prefixed_related_names"),
    ]

    operations = [
        # the old per-branch Department keeps working until phase 3; free the reverse name the new link table takes
        migrations.AlterField(
            model_name="department",
            name="branch",
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="b_old_departments", to="hospital_setup.branch"),
        ),
        migrations.CreateModel(
            name="BranchDepartment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("branch", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="b_departments", to="hospital_setup.branch")),
                ("department", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="d_branches", to="hospital_setup.department")),
                ("floor", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="f_departments", to="hospital_setup.floor")),
            ],
            options={
                "db_table": "branch_department",
                "ordering": ["branch__name", "department__name"],
            },
        ),
        migrations.AddConstraint(
            model_name="branchdepartment",
            constraint=models.UniqueConstraint(fields=("branch", "department"), name="uniq_branch_department"),
        ),
        migrations.CreateModel(
            name="StaffBranchDepartment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("branch_department", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="bdp_staff_links", to="hospital_setup.branchdepartment")),
                ("staff", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="u_branch_departments", to="hospital_setup.staffuser")),
            ],
            options={
                "db_table": "staff_branch_department",
            },
        ),
        migrations.AddConstraint(
            model_name="staffbranchdepartment",
            constraint=models.UniqueConstraint(fields=("staff", "branch_department"), name="uniq_staff_branch_department"),
        ),
        migrations.CreateModel(
            name="UserProfile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("registration_no", models.CharField(blank=True, max_length=50)),
                ("council_name", models.CharField(blank=True, max_length=150)),
                ("registration_expiry", models.DateField(blank=True, null=True)),
                ("qualification", models.CharField(blank=True, max_length=200)),
                ("experience_years", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("specialisation", models.CharField(blank=True, max_length=100)),
                ("consultation_fee", models.DecimalField(blank=True, decimal_places=2, max_digits=8, null=True)),
                ("followup_fee", models.DecimalField(blank=True, decimal_places=2, max_digits=8, null=True)),
                ("digital_signature", models.CharField(blank=True, max_length=255)),
                ("known_for", models.CharField(blank=True, max_length=300)),
                ("gender", models.CharField(blank=True, choices=[("M", "Male"), ("F", "Female"), ("O", "Other")], max_length=1)),
                ("bio", models.TextField(blank=True)),
                ("languages", models.CharField(blank=True, max_length=200)),
                ("extra", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("staff", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="u_profile", to="hospital_setup.staffuser")),
            ],
            options={
                "db_table": "user_profile",
            },
        ),
        migrations.AddField(
            model_name="room",
            name="branch_department",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="bdp_rooms", to="hospital_setup.branchdepartment"),
        ),
        # null only until phase 2 has filled it in
        migrations.AddField(
            model_name="staffuser",
            name="group",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name="ro_staff", to="hospital_setup.role"),
        ),
        migrations.AddField(
            model_name="staffuser",
            name="branch_department",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="bdp_staff", to="hospital_setup.branchdepartment"),
        ),
    ]
