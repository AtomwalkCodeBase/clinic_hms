from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("org", "0013_permission_role_rolepermission_role_permissions_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="DoctorSchedule",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("slot_duration_minutes", models.PositiveSmallIntegerField(default=15)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "doctor",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="schedule",
                        to="org.staffuser",
                    ),
                ),
            ],
            options={"app_label": "org", "db_table": "doctor_schedule"},
        ),
        migrations.CreateModel(
            name="DoctorAvailabilitySlot",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("day_of_week", models.SmallIntegerField(
                    choices=[
                        (0, "Monday"), (1, "Tuesday"), (2, "Wednesday"),
                        (3, "Thursday"), (4, "Friday"), (5, "Saturday"), (6, "Sunday"),
                    ]
                )),
                ("is_available", models.BooleanField(default=True)),
                ("start_time", models.TimeField()),
                ("end_time", models.TimeField()),
                (
                    "schedule",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="days",
                        to="org.doctorschedule",
                    ),
                ),
            ],
            options={
                "app_label": "org",
                "db_table": "doctor_availability_slot",
                "ordering": ["day_of_week"],
                "unique_together": {("schedule", "day_of_week")},
            },
        ),
    ]
