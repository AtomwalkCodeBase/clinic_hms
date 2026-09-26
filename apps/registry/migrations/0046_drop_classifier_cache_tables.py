from django.db import migrations


class Migration(migrations.Migration):
    """The old classifier / lab-extractor answer caches (0032, 0038) — nothing uses them now."""

    dependencies = [
        ("registry", "0045_drop_old_document_tables"),
    ]

    operations = [
        migrations.RunSQL(
            "DROP TABLE IF EXISTS doc_classify_cache; DROP TABLE IF EXISTS lab_extract_cache;",
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
