"""apps/billing/services.py — invoice lines are BillingItem rows and payments live on the invoice row as JSON (see models.py); the arithmetic is here."""

from decimal import ROUND_HALF_UP, Decimal

from django.utils import timezone

CENT = Decimal("0.01")


def money(value):
    return Decimal(str(value or 0))


def line_amounts(line):
    """(amount before tax, tax) of one invoice line. A tax-inclusive price already contains its tax; otherwise the tax is added on top."""
    gross = money(line["unit_price"]) * int(line["quantity"])
    rate = money(line.get("tax_rate")) / Decimal("100")
    if line.get("tax_inclusive"):
        net = (gross / (1 + rate)).quantize(CENT, ROUND_HALF_UP)
        return net, gross - net
    return gross, (gross * rate).quantize(CENT, ROUND_HALF_UP)


def line_from_item(item, quantity=1, unit_price=None):
    """An invoice line for a price-list item. A price the list does not allow to change is always the listed one."""
    if unit_price is None or not item.is_price_editable:
        unit_price = item.unit_price
    return {"item_id": item.pk, "description": item.name, "quantity": quantity, "unit_price": str(unit_price), "tax_rate": str(item.tax_rate),
            "tax_inclusive": item.tax_inclusive, "total": str(unit_price * quantity)}


def line_from_request(data, item=None):
    """An invoice line from a request: the price list decides price, tax rate and tax mode when an item is named."""
    quantity = int(data.get("quantity", 1))
    price = money(data["unit_price"]) if data.get("unit_price") is not None else None
    if item is not None:
        line = line_from_item(item, quantity, price)
        line["description"] = data.get("description") or line["description"]
        return line
    price = price or Decimal("0")
    return {"item_id": None, "description": data.get("description", ""), "quantity": quantity, "unit_price": str(price), "tax_rate": str(money(data.get("tax_rate"))),
            "tax_inclusive": bool(data.get("tax_inclusive", False)), "total": str(price * quantity)}


def recompute_invoice_totals(invoice, db):
    """Subtotal/tax/total are derived from the lines — never set directly."""
    amounts = [line_amounts(l) for l in invoice.lines]
    invoice.subtotal = sum((net for net, _ in amounts), Decimal("0"))
    invoice.tax_amount = sum((tax for _, tax in amounts), Decimal("0"))
    invoice.total_amount = invoice.subtotal + invoice.tax_amount - invoice.discount_amount
    invoice.save(using=db, update_fields=["lines", "subtotal", "tax_amount", "total_amount", "updated_at"])


def add_payment(invoice, db, amount, payment_mode, transaction_ref="", recorded_by_id=None):
    """Append a payment to the invoice and move its paid amount and status. The caller holds the invoice row locked."""
    payment = {"payment_id": len(invoice.payments) + 1, "amount": str(amount), "payment_mode": payment_mode, "transaction_ref": transaction_ref or "",
               "recorded_by_id": recorded_by_id, "paid_at": timezone.now().isoformat()}
    invoice.payments = [*invoice.payments, payment]
    invoice.paid_amount += amount
    invoice.status = "paid" if invoice.paid_amount >= invoice.total_amount else "partially_paid"
    invoice.save(using=db, update_fields=["payments", "paid_amount", "status", "updated_at"])
    return payment


def hospital_default_tax_rate(hospital_id):
    """The hospital's configured default tax rate (percent); 0 when unknown."""
    from apps.hospital_master.models import HospitalParameters

    if not hospital_id:
        return Decimal("0")
    params = HospitalParameters.objects.using("default").filter(hospital_id=hospital_id).first()
    return params.default_tax_rate if params else Decimal("0")
