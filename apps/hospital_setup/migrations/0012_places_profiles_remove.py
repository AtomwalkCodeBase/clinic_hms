"""Phase 3 of 3: drop the old tables and columns now that phase 2 has copied everything across, and tighten what the new design requires."""
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("hospital_setup", "0011_places_profiles_data"),
    ]

    operations = [
        # role -> permissions stops going through a model of its own; the table (id, role_id, permission_id) stays exactly as it is
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name="role", name="permissions",
                    field=models.ManyToManyField(blank=True, db_table="role_permission", related_name="roles", to="hospital_setup.permission")),
                migrations.DeleteModel(name="RolePermission"),
            ],
        ),
        migrations.DeleteModel(name="DoctorAvailabilitySlot"),
        migrations.DeleteModel(name="RoomAssignment"),
        migrations.DeleteModel(name="UserProfile"),
        migrations.DeleteModel(name="UserRole"),
        # a schedule belongs to a place of work, not to the staff member
        migrations.RemoveField(model_name="doctorschedule", name="doctor"),
        migrations.AlterField(
            model_name="doctorschedule", name="staff_branch_department",
            field=models.OneToOneField(
                limit_choices_to={"staff__group__system_role_key": "doctor"}, on_delete=django.db.models.deletion.CASCADE,
                related_name="sbd_schedule", to="hospital_setup.staffbranchdepartment")),
        # the places of work live in staff_branch_department only
        migrations.RemoveField(model_name="staffuser", name="branch_department"),
        migrations.AddConstraint(
            model_name="staffbranchdepartment",
            constraint=models.UniqueConstraint(condition=models.Q(("is_primary", True)), fields=("staff",), name="uniq_staff_primary_branch_department")),
        migrations.AlterField(
            model_name="staffbranchdepartment", name="branch_department",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="bdp_staff_links", to="hospital_setup.branchdepartment")),
        # rooms: the floor field is called floor
        migrations.RemoveConstraint(model_name="room", name="uniq_room_floor_name"),
        migrations.RenameField(model_name="room", old_name="floor_obj", new_name="floor"),
        migrations.AlterModelOptions(name="room", options={"ordering": ["floor__level", "name"]}),
        migrations.AddConstraint(model_name="room", constraint=models.UniqueConstraint(fields=("floor", "name"), name="uniq_room_floor_name")),
        # nothing that has history is deleted with its parent
        migrations.AlterField(
            model_name="branchdepartment", name="branch",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="b_departments", to="hospital_setup.branch")),
        migrations.AlterField(
            model_name="branchdepartment", name="department",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="d_branches", to="hospital_setup.department")),
        migrations.AlterField(
            model_name="branchdepartment", name="floor",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="f_departments", to="hospital_setup.floor")),
        migrations.AlterField(
            model_name="floor", name="branch",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="b_floors", to="hospital_setup.branch")),
        migrations.AlterField(
            model_name="bed", name="room",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="r_beds", to="hospital_setup.room")),
    ]
