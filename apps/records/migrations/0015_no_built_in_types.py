from django.db import migrations


def forwards(apps, schema_editor):
    """There are no built-in types any more: only what Platform Admin configured. A document the rules had
    filed as the fallback "other" has no type (unable to classify); the keyword-less rows migration 0006 added
    for the old built-ins are removed (the admin screen cannot create a rule without keywords)."""
    Result = apps.get_model("records", "DocumentClassification")
    Rule = apps.get_model("records", "ClassificationRule")
    Result.objects.filter(classification_type="other", classified_by="system").update(classification_type=None)
    Rule.objects.filter(keywords="").delete()


class Migration(migrations.Migration):
    dependencies = [("records", "0014_sweep_interval_30_seconds")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
