"""
apps/billing/services.py
------------------------
Invoice logic shared by every app that bills (billing, opd, ipd, lab, pharmacy, patients).
Moved out of billing/views.py and opd/views.py, where other apps had to import
underscore-prefixed view functions to reach it.
"""

from decimal import Decimal

from .models import InvoiceItem


def recompute_invoice_totals(invoice, db):
    """Subtotal/tax/total are derived from line items — never set directly."""
    items = InvoiceItem.objects.using(db).filter(invoice=invoice)
    subtotal = sum((i.unit_price * i.quantity for i in items), Decimal("0"))
    tax_amount = sum(
        ((i.unit_price * i.quantity) * (i.tax_rate / Decimal("100")) for i in items), Decimal("0")
    )
    invoice.subtotal = subtotal
    invoice.tax_amount = tax_amount
    invoice.total_amount = subtotal + tax_amount - invoice.discount_amount
    invoice.save(using=db, update_fields=["subtotal", "tax_amount", "total_amount"])


def tenant_default_tax_rate(tenant_id):
    """The hospital's configured default tax rate (percent); 0 when unknown."""
    from apps.tenants.models import Tenant

    if not tenant_id:
        return Decimal("0")
    try:
        return Tenant.objects.using("default").get(pk=tenant_id).default_tax_rate
    except Tenant.DoesNotExist:
        return Decimal("0")
