"""
Bring commit 7e6961a's new non-medical keywords into the rules table.

That commit added four pharmacy-bill tokens to core/doc_classifier.py's
built-in _NON_MEDICAL_HINTS. Since 0046 the live keyword lists come from the
doc_classification_rule table (edited on platform admin → Document
Classifier), so the new words must be added there too or they'd have no
effect. Only appended when missing — an admin's own edits are kept.
(The stronger billing tier, _NON_MEDICAL_STRONG, stays in code.)
"""

from django.db import migrations

NEW_WORDS = ["op receipt", "net payable", "total outstanding", "d.l.no"]


def add_words(apps, schema_editor):
    Rule = apps.get_model("registry", "DocumentClassificationRule")
    for rule in Rule.objects.using(schema_editor.connection.alias).filter(doc_type="not_medical"):
        words = [w.strip().lower() for w in (rule.keywords or "").split("|") if w.strip()]
        missing = [w for w in NEW_WORDS if w not in words]
        if missing:
            rule.keywords = "|".join(words + missing)
            rule.updated_by = "migration 0052 (commit 7e6961a)"
            rule.save(update_fields=["keywords", "updated_by"])


class Migration(migrations.Migration):

    dependencies = [
        ("registry", "0051_upload_routing"),
    ]

    operations = [
        migrations.RunPython(add_words, migrations.RunPython.noop),
    ]
