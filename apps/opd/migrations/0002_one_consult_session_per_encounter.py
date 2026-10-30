import django.db.models.deletion
from django.db import migrations, models


def keep_one_session_per_encounter(apps, schema_editor):
    """An encounter now has one pad session. Where an expired session was replaced by a new one, keep the session that holds the doctor's work
    (an archived note, else unsigned pages, else the most recently updated one) and delete the others."""
    ConsultSession = apps.get_model("opd", "ConsultSession")
    db = schema_editor.connection.alias
    seen = set()
    for sess in ConsultSession.objects.using(db).order_by("encounter_id", "-updated_at", "-id"):
        if sess.encounter_id in seen:
            continue
        seen.add(sess.encounter_id)
        rows = list(ConsultSession.objects.using(db).filter(encounter_id=sess.encounter_id).order_by("-updated_at", "-id"))
        if len(rows) < 2:
            continue
        keep = next((r for r in rows if r.note_pdf), None) or next((r for r in rows if r.rx_pages or r.note_pages), None) or rows[0]
        ConsultSession.objects.using(db).filter(encounter_id=sess.encounter_id).exclude(pk=keep.pk).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('opd', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(keep_one_session_per_encounter, migrations.RunPython.noop),
        migrations.RemoveField(model_name='consultsession', name='status'),
        migrations.RemoveField(model_name='consultsession', name='signed_at'),
        migrations.RemoveField(model_name='consultsession', name='expires_at'),
        migrations.AlterField(
            model_name='consultsession',
            name='encounter',
            field=models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='e_consult_session', to='opd.opdencounter'),
        ),
    ]
