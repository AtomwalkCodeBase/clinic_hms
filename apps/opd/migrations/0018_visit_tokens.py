"""Queue numbers are counted per department and day now (they used to be counted per doctor): where two visits of one department and day share a
number, the later ones get the next free numbers, so the one-number-per-department-and-day rule can be enforced."""
from django.db import migrations


def renumber(apps, schema_editor):
    db = schema_editor.connection.alias
    Appointment = apps.get_model("opd", "Appointment")
    groups = {}
    for appointment in Appointment.objects.using(db).exclude(token_number__isnull=True).order_by("scheduled_date", "token_number", "created_at", "id"):
        groups.setdefault((appointment.branch_department_id, appointment.scheduled_date), []).append(appointment)
    for rows in groups.values():
        top = max(row.token_number for row in rows)
        taken = set()
        for row in rows:
            if row.token_number <= 0 or row.token_number in taken:
                top += 1
                row.token_number = top
                row.save(using=db, update_fields=["token_number"])
            taken.add(row.token_number)


class Migration(migrations.Migration):

    dependencies = [
        ("opd", "0017_visit_remove"),
    ]

    operations = [
        migrations.RunPython(renumber, migrations.RunPython.noop),
    ]
