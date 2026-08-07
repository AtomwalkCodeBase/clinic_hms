from decimal import Decimal

from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone

from core.response import success, created, error, not_found
from core.permissions import IsHospitalStaff, IsFrontDesk
from core.pagination import paginate_queryset
from core.utils.nntm import get_next_number
from .serializers import InvoiceSerializer, InvoiceItemSerializer, PaymentSerializer, BillingServiceSerializer
from .models import Invoice, InvoiceItem, Payment, BillingService


def _recompute_invoice_totals(invoice, db):
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


class BillingServiceListView(APIView):
    permission_classes = [IsAuthenticated, IsHospitalStaff]

    def get(self, request):
        services = BillingService.objects.using(request.tenant_db).filter(is_active=True)
        return success(data=BillingServiceSerializer(services, many=True).data)


class InvoiceListCreateView(APIView):
    """
    GET  /api/v1/billing/invoices/  — list invoices (optionally filter by
                                       patient_id, appointment_id, or status)
    POST /api/v1/billing/invoices/  — create an invoice, optionally from an
                                       appointment and/or with line items in
                                       one call (what the front-desk Billing
                                       page uses) so it doesn't need three
                                       round trips to bill a walk-in.
    """
    permission_classes = [IsAuthenticated, IsHospitalStaff]

    def get(self, request):
        qs = Invoice.objects.using(request.tenant_db).order_by("-created_at")
        if pid := request.query_params.get("patient_id"):
            qs = qs.filter(patient_id=pid)
        if status_filter := request.query_params.get("status"):
            qs = qs.filter(status=status_filter)
        page_items, meta = paginate_queryset(request, qs)
        return success(data={
            "results": InvoiceSerializer(page_items, many=True).data,
            "pagination": meta,
        })

    def post(self, request):
        db = request.tenant_db
        patient_pk = request.data.get("patient")
        encounter_id = request.data.get("encounter")
        branch_id = request.data.get("branch")

        # Resolve patient/branch from an appointment when one is given —
        # this is the normal front-desk path (bill straight off the queue),
        # since Appointment.patient_id stores Patient.uuid, not Patient.id.
        appointment_id = request.data.get("appointment_id")
        if appointment_id:
            from apps.opd.models import Appointment
            from apps.patients.models import Patient
            try:
                appt = Appointment.objects.using(db).get(pk=appointment_id)
            except Appointment.DoesNotExist:
                return error("Appointment not found.")
            try:
                patient = Patient.objects.using(db).get(uuid=appt.patient_id)
            except Patient.DoesNotExist:
                return error("Patient record not found for this appointment.")
            patient_pk = patient.id
            branch_id = branch_id or appt.branch_id or patient.branch_id

        if not patient_pk:
            return error("patient (or appointment_id) is required.", errors={"patient": "Required."})
        branch_id = branch_id or 1

        inv_number, _ = get_next_number(branch_id=branch_id, entity="invoice", using=db)
        inv = Invoice.objects.using(db).create(
            patient_id=patient_pk,
            branch_id=branch_id,
            invoice_number=inv_number,
            encounter_id=encounter_id,
            notes=request.data.get("notes", ""),
            created_by_id=request.user.id,
        )

        # Optional line items in the same call — [{description, unit_price,
        # quantity, tax_rate, service}], service is a BillingService id.
        for item in request.data.get("items", []):
            InvoiceItem.objects.using(db).create(
                invoice=inv,
                service_id=item.get("service"),
                description=item.get("description", ""),
                quantity=item.get("quantity", 1),
                unit_price=item.get("unit_price", 0),
                tax_rate=item.get("tax_rate", 0),
                total=Decimal(str(item.get("unit_price", 0))) * int(item.get("quantity", 1)),
            )
        if request.data.get("items"):
            _recompute_invoice_totals(inv, db)
            inv.refresh_from_db(using=db)

        return created(data=InvoiceSerializer(inv).data)


class InvoiceDetailView(APIView):
    """
    GET   /api/v1/billing/invoices/{id}/ — invoice with items + payments
    PATCH /api/v1/billing/invoices/{id}/ — update status/notes/discount
                                            (e.g. mark issued, apply a discount)
    """
    permission_classes = [IsAuthenticated, IsHospitalStaff]

    def _get(self, request, pk):
        try:
            return Invoice.objects.using(request.tenant_db).get(pk=pk)
        except Invoice.DoesNotExist:
            return None

    def get(self, request, pk):
        inv = self._get(request, pk)
        if not inv:
            return not_found("Invoice not found.")
        return success(data=InvoiceSerializer(inv).data)

    def patch(self, request, pk):
        inv = self._get(request, pk)
        if not inv:
            return not_found("Invoice not found.")
        db = request.tenant_db

        if "discount_amount" in request.data:
            inv.discount_amount = Decimal(str(request.data["discount_amount"]))
            inv.save(using=db, update_fields=["discount_amount"])
            _recompute_invoice_totals(inv, db)
            inv.refresh_from_db(using=db)

        if "notes" in request.data:
            inv.notes = request.data["notes"]
            inv.save(using=db, update_fields=["notes"])

        status_val = request.data.get("status")
        if status_val:
            if status_val not in dict(Invoice.STATUS_CHOICES):
                return error("Invalid status.", errors={"status": "Invalid choice."})
            inv.status = status_val
            if status_val == "issued" and not inv.issued_at:
                inv.issued_at = timezone.now()
                inv.save(using=db, update_fields=["status", "issued_at"])
            else:
                inv.save(using=db, update_fields=["status"])

        return success(data=InvoiceSerializer(inv).data, message="Invoice updated.")


class InvoiceItemCreateView(APIView):
    """POST /api/v1/billing/invoices/{id}/items/ — add a line item, recompute totals."""
    permission_classes = [IsAuthenticated, IsHospitalStaff]

    def post(self, request, pk):
        db = request.tenant_db
        try:
            inv = Invoice.objects.using(db).get(pk=pk)
        except Invoice.DoesNotExist:
            return not_found("Invoice not found.")
        if inv.status not in ("draft", "issued"):
            return error(f"Cannot add items to a {inv.status} invoice.")

        s = InvoiceItemSerializer(data=request.data)
        if not s.is_valid():
            return error("Validation error.", errors=s.errors)
        d = s.validated_data
        item = InvoiceItem.objects.using(db).create(
            invoice=inv,
            service=d.get("service"),
            description=d["description"],
            quantity=d.get("quantity", 1),
            unit_price=d["unit_price"],
            tax_rate=d.get("tax_rate", 0),
            total=d["unit_price"] * d.get("quantity", 1),
        )
        _recompute_invoice_totals(inv, db)
        return created(data=InvoiceSerializer(inv.__class__.objects.using(db).get(pk=inv.pk)).data,
                       message="Item added.")


class PaymentCreateView(APIView):
    permission_classes = [IsAuthenticated, IsHospitalStaff]

    def post(self, request):
        s = PaymentSerializer(data=request.data)
        if not s.is_valid():
            return error("Validation error.", errors=s.errors)
        payment = Payment.objects.using(request.tenant_db).create(
            recorded_by=request.user, **s.validated_data
        )
        # Update invoice paid_amount
        inv = payment.invoice
        inv.paid_amount += payment.amount
        inv.status = "paid" if inv.paid_amount >= inv.total_amount else "partially_paid"
        inv.save(using=request.tenant_db, update_fields=["paid_amount", "status"])
        return created(data=PaymentSerializer(payment).data)
