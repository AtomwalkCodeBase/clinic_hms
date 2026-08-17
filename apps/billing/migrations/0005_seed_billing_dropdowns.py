"""
Data migration: seed the system-default rows for ServiceCategory,
PaymentModeOption, and InvoiceStatusOption — the same values that used to
be hardcoded `choices=` lists on BillingService.category, Payment.payment_mode,
and Invoice.status. Marked is_system=True so they can be relabelled but not
deleted, since Invoice status specifically has real backend logic tied to
its stored `value` (see PaymentCreateView / InvoiceItemCreateView).

Runs per-tenant DB (billing is a tenant-routed app — each hospital's own
database gets these seeded when `migrate` targets it), not the registry DB.
"""
from django.db import migrations


_SERVICE_CATEGORIES = ["Consultation", "Procedure", "Lab", "Pharmacy", "Room / Bed", "Other"]
_PAYMENT_MODES = ["Cash", "Card", "UPI", "Online", "Credit"]
_INVOICE_STATUSES = [
    ("draft", "Draft"),
    ("issued", "Issued"),
    ("paid", "Paid"),
    ("partially_paid", "Partially Paid"),
    ("cancelled", "Cancelled"),
]


def seed_dropdowns(apps, schema_editor):
    db = schema_editor.connection.alias
    ServiceCategory = apps.get_model("billing", "ServiceCategory")
    PaymentModeOption = apps.get_model("billing", "PaymentModeOption")
    InvoiceStatusOption = apps.get_model("billing", "InvoiceStatusOption")

    for i, name in enumerate(_SERVICE_CATEGORIES):
        ServiceCategory.objects.using(db).get_or_create(
            name=name, defaults={"is_system": True, "sort_order": i},
        )
    for i, name in enumerate(_PAYMENT_MODES):
        PaymentModeOption.objects.using(db).get_or_create(
            name=name, defaults={"is_system": True, "sort_order": i},
        )
    for i, (value, label) in enumerate(_INVOICE_STATUSES):
        InvoiceStatusOption.objects.using(db).get_or_create(
            value=value, defaults={"label": label, "is_system": True, "sort_order": i},
        )


def unseed_dropdowns(apps, schema_editor):
    db = schema_editor.connection.alias
    ServiceCategory = apps.get_model("billing", "ServiceCategory")
    PaymentModeOption = apps.get_model("billing", "PaymentModeOption")
    InvoiceStatusOption = apps.get_model("billing", "InvoiceStatusOption")

    ServiceCategory.objects.using(db).filter(is_system=True).delete()
    PaymentModeOption.objects.using(db).filter(is_system=True).delete()
    InvoiceStatusOption.objects.using(db).filter(is_system=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("billing", "0004_invoicestatusoption_paymentmodeoption_and_more"),
    ]

    operations = [
        migrations.RunPython(seed_dropdowns, unseed_dropdowns),
    ]
