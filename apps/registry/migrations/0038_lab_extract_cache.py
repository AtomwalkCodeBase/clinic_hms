"""
Create the DatabaseCache table backing the ``lab_extract`` cache
(settings.CACHES) on the registry DB — core.lab_value_extractor's answers,
kept in a separate table/alias from ``doc_classify`` since the two
pipelines' keys/TTLs/payloads don't overlap. Idempotent — ``createcachetable``
skips a table that already exists, so re-running the migration is safe.
"""

from django.core.management import call_command
from django.db import migrations


def _make(apps, schema_editor):
    if schema_editor.connection.alias != "default":
        return
    call_command("createcachetable", "lab_extract_cache",
                 database="default", verbosity=0)


def _drop(apps, schema_editor):
    if schema_editor.connection.alias != "default":
        return
    with schema_editor.connection.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS lab_extract_cache")


class Migration(migrations.Migration):

    dependencies = [
        ("registry", "0037_extracted_lab_value"),
    ]

    operations = [
        migrations.RunPython(_make, _drop),
    ]
