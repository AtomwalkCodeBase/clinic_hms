"""
Migration: 0005_remove_legacy_address
---------------------------------------
The initial schema (0002) created `patient.address TEXT NOT NULL`.
Migration 0003 added `address_line1` as its replacement but never dropped
the old column.  Django doesn't include `address` in INSERTs (the model
field is gone), so PostgreSQL raises NotNullViolation on every new patient.

Fix: drop the legacy `address` column.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("patients", "0004_patient_uuid"),
    ]

    operations = [
        migrations.RunSQL(
            sql='ALTER TABLE "patient" DROP COLUMN IF EXISTS "address";',
            reverse_sql='ALTER TABLE "patient" ADD COLUMN "address" text NOT NULL DEFAULT \'\';',
        ),
    ]
