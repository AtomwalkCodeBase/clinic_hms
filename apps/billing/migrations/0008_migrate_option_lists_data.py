# v7 table-count redesign: copy every row from the four soon-to-be-retired
# tables into the merged OptionList table, verbatim — exact stored value
# strings preserved (reconciliation logic in billing/views.py depends on
# "paid" existing exactly as stored, e.g.). Depends on prescriptions' latest
# migration so apps.prescriptions.DrugFormType still exists in historical
# state at this point, even though prescriptions/models.py itself no longer
# defines it (0006 in that app drops the table once this migration has run).
from django.db import migrations


def copy_rows_forward(apps, schema_editor):
    db = schema_editor.connection.alias
    OptionList = apps.get_model("billing", "OptionList")
    ServiceCategory = apps.get_model("billing", "ServiceCategory")
    PaymentModeOption = apps.get_model("billing", "PaymentModeOption")
    InvoiceStatusOption = apps.get_model("billing", "InvoiceStatusOption")
    DrugFormType = apps.get_model("prescriptions", "DrugFormType")

    for row in ServiceCategory.objects.using(db).all():
        OptionList.objects.using(db).get_or_create(
            list_type="service_category", value=row.name,
            defaults={
                "label": row.name, "is_active": row.is_active,
                "is_system": row.is_system, "sort_order": row.sort_order,
                "created_at": row.created_at,
            },
        )

    for row in PaymentModeOption.objects.using(db).all():
        OptionList.objects.using(db).get_or_create(
            list_type="payment_mode", value=row.name,
            defaults={
                "label": row.name, "is_active": row.is_active,
                "is_system": row.is_system, "sort_order": row.sort_order,
                "created_at": row.created_at,
            },
        )

    for row in InvoiceStatusOption.objects.using(db).all():
        OptionList.objects.using(db).get_or_create(
            list_type="invoice_status", value=row.value,
            defaults={
                "label": row.label, "is_active": row.is_active,
                "is_system": row.is_system, "sort_order": row.sort_order,
                "created_at": row.created_at,
            },
        )

    for row in DrugFormType.objects.using(db).all():
        OptionList.objects.using(db).get_or_create(
            list_type="drug_form", value=row.name,
            defaults={
                "label": row.name, "is_active": row.is_active,
                "is_system": False, "sort_order": 0,
                "created_at": row.created_at,
            },
        )


def copy_rows_backward(apps, schema_editor):
    db = schema_editor.connection.alias
    OptionList = apps.get_model("billing", "OptionList")
    OptionList.objects.using(db).filter(
        list_type__in=["service_category", "payment_mode", "invoice_status", "drug_form"]
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0007_optionlist_add'),
        ('prescriptions', '0005_drug_default_mrp'),
    ]

    operations = [
        migrations.RunPython(copy_rows_forward, copy_rows_backward),
    ]
