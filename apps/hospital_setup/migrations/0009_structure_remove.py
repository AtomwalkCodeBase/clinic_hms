"""Phase 3 of 3: drop the old columns and tables now that phase 2 has copied everything across."""
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("hospital_setup", "0008_structure_data"),
    ]

    operations = [
        # departments are one list for the hospital; the branch link lives in branch_department
        migrations.RemoveConstraint(model_name="department", name="uniq_department_branch_name"),
        migrations.RemoveField(model_name="department", name="branch"),
        migrations.AlterField(model_name="department", name="name", field=models.CharField(max_length=100, unique=True)),
        migrations.AlterModelOptions(name="department", options={"ordering": ["name"]}),
        # a room belongs to a floor, and the floor to a branch
        migrations.RemoveConstraint(model_name="room", name="uniq_room_branch_name"),
        migrations.RemoveField(model_name="room", name="branch"),
        migrations.RemoveField(model_name="room", name="department"),
        migrations.AlterField(
            model_name="room",
            name="floor_obj",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="f_rooms", to="hospital_setup.floor"),
        ),
        migrations.AddConstraint(
            model_name="room",
            constraint=models.UniqueConstraint(fields=("floor_obj", "name"), name="uniq_room_floor_name"),
        ),
        # staff: the user group and the place of work replace role, custom role, branch and department
        migrations.AlterField(
            model_name="staffuser",
            name="group",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="ro_staff", to="hospital_setup.role"),
        ),
        migrations.RemoveField(model_name="staffuser", name="role"),
        migrations.RemoveField(model_name="staffuser", name="custom_role"),
        migrations.RemoveField(model_name="staffuser", name="branch"),
        migrations.RemoveField(model_name="staffuser", name="department"),
        migrations.DeleteModel(name="StaffBranchMapping"),
        migrations.DeleteModel(name="DoctorProfile"),
        migrations.DeleteModel(name="StaffProfile"),
        migrations.AlterField(
            model_name="nursedoctorassignment",
            name="doctor",
            field=models.ForeignKey(limit_choices_to={"group__system_role_key": "doctor"}, on_delete=django.db.models.deletion.CASCADE, related_name="u_assigned_nurse_links", to="hospital_setup.staffuser"),
        ),
        migrations.AlterField(
            model_name="nursedoctorassignment",
            name="nurse",
            field=models.ForeignKey(limit_choices_to={"group__system_role_key": "nurse"}, on_delete=django.db.models.deletion.CASCADE, related_name="u_assigned_doctor_links", to="hospital_setup.staffuser"),
        ),
        migrations.AlterField(
            model_name="roomassignment",
            name="doctor",
            field=models.ForeignKey(limit_choices_to={"group__system_role_key": "doctor"}, on_delete=django.db.models.deletion.CASCADE, related_name="u_room_assignments", to="hospital_setup.staffuser"),
        ),
    ]
