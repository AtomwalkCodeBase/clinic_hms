"""
Create the DatabaseCache table backing the ``doc_classify`` cache
(settings.CACHES) on the registry DB. Idempotent — ``createcachetable``
skips a table that already exists, so re-running the migration is safe.
"""

from django.core.management import call_command
from django.db import migrations


def _make(apps, schema_editor):
    if schema_editor.connection.alias != "default":
        return
    call_command("createcachetable", "doc_classify_cache",
                 database="default", verbosity=0)


def _drop(apps, schema_editor):
    if schema_editor.connection.alias != "default":
        return
    with schema_editor.connection.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS doc_classify_cache")


class Migration(migrations.Migration):

    dependencies = [
        ("registry", "0031_document_report_categories"),
    ]

    operations = [
        migrations.RunPython(_make, _drop),
    ]
