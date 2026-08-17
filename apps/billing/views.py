from decimal import Decimal
from datetime import timedelta

from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone
from django.db.models import Sum

from core.response import success, created, error, not_found
from core.permissions import IsHospitalStaff, IsFrontDesk, IsHospitalAdmin
from core.pagination import paginate_queryset
from core.utils.nntm import get_next_number
from .serializers import (
    InvoiceSerializer, InvoiceItemSerializer, PaymentSerializer, BillingServiceSerializer,
    ServiceCategorySerializer, PaymentModeOptionSerializer, InvoiceStatusOptionSerializer,
)
from .models import (
    Invoice, InvoiceItem, Payment, BillingService,
    ServiceCategory, PaymentModeOption, InvoiceStatusOption,
)


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
    """
    GET  /api/v1/billing/services/  — list the active price catalog (any staff)
    POST /api/v1/billing/services/  — add a new catalog entry (hospital admin
         only). Previously GET-only — the catalog could only be populated by
         a direct DB write; this is what lets a hospital actually manage
         their own price list instead of one being hand-seeded for them.
    """
    def get_permissions(self):
        if self.request.method == "GET":
            return [IsAuthenticated(), IsHospitalStaff()]
        return [IsAuthenticated(), IsHospitalAdmin()]

    def get(self, request):
        services = BillingService.objects.using(request.tenant_db).filter(is_active=True)
        return success(data=BillingServiceSerializer(services, many=True).data)

    def post(self, request):
        s = BillingServiceSerializer(data=request.data)
        if not s.is_valid():
            return error("Validation error.", errors=s.errors)
        svc = BillingService(**s.validated_data)
        svc.save(using=request.tenant_db)
        return created(data=BillingServiceSerializer(svc).data, message="Service added.")


class BillingServiceDetailView(APIView):
    """
    PATCH  /api/v1/billing/services/{id}/ — edit name/price/tax/category
    DELETE /api/v1/billing/services/{id}/ — deactivate (soft delete)
    """
    permission_classes = [IsAuthenticated, IsHospitalAdmin]

    def _get(self, request, pk):
        try:
            return BillingService.objects.using(request.tenant_db).get(pk=pk)
        except BillingService.DoesNotExist:
            return None

    def patch(self, request, pk):
        svc = self._get(request, pk)
        if not svc:
            return not_found("Service not found.")
        s = BillingServiceSerializer(svc, data=request.data, partial=True)
        if not s.is_valid():
            return error("Validation error.", errors=s.errors)
        for attr, val in s.validated_data.items():
            setattr(svc, attr, val)
        svc.save(using=request.tenant_db)
        return success(data=BillingServiceSerializer(svc).data, message="Service updated.")

    def delete(self, request, pk):
        svc = self._get(request, pk)
        if not svc:
            return not_found("Service not found.")
        svc.is_active = False
        svc.save(using=request.tenant_db, update_fields=["is_active"])
        return success(message="Service deactivated.")


# ── Configurable dropdown lists ──────────────────────────────────────────────
# Replace what used to be hardcoded `choices=` lists on BillingService.category,
# Payment.payment_mode, and Invoice.status — same "tenant-managed lookup table"
# pattern as apps.prescriptions.DrugFormType. Three near-identical resources,
# so the CRUD logic lives once in these base classes; each subclass just
# points at its own model/serializer.

class _DropdownListCreateView(APIView):
    model = None
    serializer_class = None
    identity_field = "name"  # the field that must be unique / can't change on a system row

    def get_permissions(self):
        if self.request.method == "GET":
            return [IsAuthenticated(), IsHospitalStaff()]
        return [IsAuthenticated(), IsHospitalAdmin()]

    def get(self, request):
        qs = self.model.objects.using(request.tenant_db).filter(is_active=True)
        return success(data=self.serializer_class(qs, many=True).data)

    def post(self, request):
        s = self.serializer_class(data=request.data)
        if not s.is_valid():
            return error("Validation error.", errors=s.errors)
        lookup = {self.identity_field: s.validated_data.get(self.identity_field)}
        if self.model.objects.using(request.tenant_db).filter(**lookup).exists():
            return error("This value already exists.", errors={self.identity_field: "Already in use."})
        obj = self.model(is_system=False, **s.validated_data)
        obj.save(using=request.tenant_db)
        return created(data=self.serializer_class(obj).data, message="Added.")


class _DropdownDetailView(APIView):
    permission_classes = [IsAuthenticated, IsHospitalAdmin]
    model = None
    serializer_class = None
    identity_field = "name"

    def _get(self, request, pk):
        try:
            return self.model.objects.using(request.tenant_db).get(pk=pk)
        except self.model.DoesNotExist:
            return None

    def patch(self, request, pk):
        obj = self._get(request, pk)
        if not obj:
            return not_found("Not found.")
        if obj.is_system and self.identity_field in request.data \
                and request.data[self.identity_field] != getattr(obj, self.identity_field):
            return error(f"This is a system value — its {self.identity_field} can't be changed, only its label/active state.")
        if obj.is_system and request.data.get("is_active") is False:
            return error("System values can't be deactivated — the backend relies on them.")
        s = self.serializer_class(obj, data=request.data, partial=True)
        if not s.is_valid():
            return error("Validation error.", errors=s.errors)
        for attr, val in s.validated_data.items():
            setattr(obj, attr, val)
        obj.save(using=request.tenant_db)
        return success(data=self.serializer_class(obj).data, message="Updated.")

    def delete(self, request, pk):
        obj = self._get(request, pk)
        if not obj:
            return not_found("Not found.")
        if obj.is_system:
            return error("System values can't be removed — deactivate a custom one you added instead.")
        obj.delete(using=request.tenant_db)
        return success(message="Removed.")


class ServiceCategoryListCreateView(_DropdownListCreateView):
    """GET/POST /api/v1/billing/service-categories/"""
    model = ServiceCategory
    serializer_class = ServiceCategorySerializer
    identity_field = "name"


class ServiceCategoryDetailView(_DropdownDetailView):
    """PATCH/DELETE /api/v1/billing/service-categories/{id}/"""
    model = ServiceCategory
    serializer_class = ServiceCategorySerializer
    identity_field = "name"


class PaymentModeListCreateView(_DropdownListCreateView):
    """GET/POST /api/v1/billing/payment-modes/"""
    model = PaymentModeOption
    serializer_class = PaymentModeOptionSerializer
    identity_field = "name"


class PaymentModeDetailView(_DropdownDetailView):
    """PATCH/DELETE /api/v1/billing/payment-modes/{id}/"""
    model = PaymentModeOption
    serializer_class = PaymentModeOptionSerializer
    identity_field = "name"


class InvoiceStatusListCreateView(_DropdownListCreateView):
    """GET/POST /api/v1/billing/invoice-statuses/"""
    model = InvoiceStatusOption
    serializer_class = InvoiceStatusOptionSerializer
    identity_field = "value"


class InvoiceStatusDetailView(_DropdownDetailView):
    """PATCH/DELETE /api/v1/billing/invoice-statuses/{id}/"""
    model = InvoiceStatusOption
    serializer_class = InvoiceStatusOptionSerializer
    identity_field = "value"


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
            valid_statuses = set(
                InvoiceStatusOption.objects.using(db)
                .filter(is_active=True).values_list("value", flat=True)
            )
            if status_val not in valid_statuses:
                return error("Invalid status.", errors={"status": "Invalid choice."})
            inv.status = status_val
            if status_val == "issued" and not inv.issued_at:
                inv.issued_at = timezone.now()
                inv.save(using=db, update_fields=["status", "issued_at"])
            else:
                inv.save(using=db, update_fields=["status"])

        return success(data=InvoiceSerializer(inv).data, message="Invoice updated.")


class InvoicePDFView(APIView):
    """
    GET /api/v1/billing/invoices/{id}/pdf/

    Renders the invoice as a real PDF (reportlab — see apps/billing/pdf.py)
    with a QR "receipt" embedded (HMS-09c-1 / HMS-09c-2). Returned as a
    base64 data URI in the standard envelope, not a raw
    application/pdf response — every other file viewer in this app follows
    that same convention (see frontend/src/utils/fileViewer.js) because auth
    here is a JWT bearer header, not a cookie, so a plain <a href> straight
    to the API wouldn't carry credentials.
    """
    permission_classes = [IsAuthenticated, IsHospitalStaff]

    def get(self, request, pk):
        import base64
        from apps.patients.models import Patient
        from apps.org.models import Branch
        from apps.tenants.models import Tenant
        from .pdf import generate_invoice_pdf

        db = request.tenant_db
        try:
            inv = Invoice.objects.using(db).prefetch_related("items", "payments").get(pk=pk)
        except Invoice.DoesNotExist:
            return not_found("Invoice not found.")

        patient = Patient.objects.using(db).filter(pk=inv.patient_id).first()
        branch = Branch.objects.using(db).filter(pk=inv.branch_id).first()
        tenant = Tenant.objects.using("default").filter(pk=request.tenant_id).first()
        hospital_name = tenant.name if tenant else "Hospital"

        pdf_bytes = generate_invoice_pdf(
            invoice=inv,
            items=list(inv.items.all()),
            payments=list(inv.payments.all().order_by("paid_at")),
            patient=patient,
            branch=branch,
            hospital_name=hospital_name,
        )
        data_uri = "data:application/pdf;base64," + base64.b64encode(pdf_bytes).decode("ascii")
        return success(data={
            "file_data": data_uri,
            "file_name": f"{inv.invoice_number}.pdf",
            "mime_type": "application/pdf",
        })


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
    """
    POST /api/v1/billing/payments/  — record a payment against an invoice.
    GET  /api/v1/billing/payments/  — payment ledger (HMS-09d-1): every
         payment recorded, newest first, with the invoice/patient it belongs
         to resolved so this reads as an actual ledger and not a bare list
         of amounts. ?date_from=&date_to= (on paid_at), ?payment_mode=,
         ?patient_id= narrow it down. The ledger total in the response is
         computed over the WHOLE filtered set, not just the current page —
         same "totals shouldn't lie about pagination" rule used everywhere
         else in this app (see e.g. OPD's status_counts).
    """
    permission_classes = [IsAuthenticated, IsHospitalStaff]

    def get(self, request):
        from apps.patients.models import Patient
        from apps.org.models import StaffUser

        db = request.tenant_db
        qs = Payment.objects.using(db).select_related("invoice").order_by("-paid_at")

        if date_from := request.query_params.get("date_from"):
            qs = qs.filter(paid_at__date__gte=date_from)
        if date_to := request.query_params.get("date_to"):
            qs = qs.filter(paid_at__date__lte=date_to)
        if mode := request.query_params.get("payment_mode"):
            qs = qs.filter(payment_mode=mode)
        if patient_id := request.query_params.get("patient_id"):
            qs = qs.filter(invoice__patient_id=patient_id)

        total_amount = qs.aggregate(total=Sum("amount"))["total"] or Decimal("0")
        page_items, meta = paginate_queryset(request, qs)

        patient_ids = {p.invoice.patient_id for p in page_items}
        patients = {p.id: p for p in Patient.objects.using(db).filter(pk__in=patient_ids)}
        recorder_ids = {p.recorded_by_id for p in page_items if p.recorded_by_id}
        recorders = {s.id: s for s in StaffUser.objects.using(db).filter(pk__in=recorder_ids)}

        results = []
        for p in page_items:
            patient = patients.get(p.invoice.patient_id)
            recorder = recorders.get(p.recorded_by_id)
            results.append({
                "id": p.id,
                "amount": p.amount,
                "payment_mode": p.payment_mode,
                "transaction_ref": p.transaction_ref,
                "paid_at": p.paid_at,
                "invoice_id": p.invoice_id,
                "invoice_number": p.invoice.invoice_number,
                "invoice_status": p.invoice.status,
                "patient_name": patient.full_name if patient else "",
                "patient_uhid": patient.uhid if patient else "",
                "recorded_by_name": (f"{recorder.first_name} {recorder.last_name}".strip() or recorder.email) if recorder else "",
            })

        return success(data={
            "results": results,
            "pagination": meta,
            "total_amount": total_amount,
        })

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


class RevenueReportView(APIView):
    """
    GET /api/v1/billing/reports/revenue/?date_from=&date_to=  (HMS-09d-2)

    Defaults to the last 30 days. Two different date bases, deliberately:
    "billed" is invoices ISSUED/created in the window (what got charged),
    "collected" is payments RECEIVED in the window (what actually came in)
    — the two aren't the same invoices necessarily (an invoice billed near
    the window's start may get paid after it), which is exactly why both
    numbers are worth showing side by side instead of collapsing to one.
    Cancelled invoices are excluded from "billed" — they were never real
    revenue.
    """
    permission_classes = [IsAuthenticated, IsHospitalAdmin]

    def get(self, request):
        from django.db.models.functions import TruncDate

        db = request.tenant_db
        date_to = request.query_params.get("date_to") or timezone.localdate().isoformat()
        date_from = request.query_params.get("date_from") or (
            timezone.localdate() - timedelta(days=29)
        ).isoformat()

        invoices = Invoice.objects.using(db).filter(
            created_at__date__gte=date_from, created_at__date__lte=date_to,
        ).exclude(status=Invoice.STATUS_CANCELLED)
        payments = Payment.objects.using(db).filter(
            paid_at__date__gte=date_from, paid_at__date__lte=date_to,
        )

        total_billed = invoices.aggregate(t=Sum("total_amount"))["t"] or Decimal("0")
        total_collected = payments.aggregate(t=Sum("amount"))["t"] or Decimal("0")
        # Outstanding is a point-in-time balance (not date-scoped) across
        # every not-yet-settled invoice — mixing in a date filter here would
        # hide money still owed from before the window, which defeats the
        # point of showing it at all.
        total_outstanding = (
            Invoice.objects.using(db)
            .exclude(status__in=[Invoice.STATUS_CANCELLED, Invoice.STATUS_PAID])
            .aggregate(t=Sum("total_amount"))["t"] or Decimal("0")
        ) - (
            Invoice.objects.using(db)
            .exclude(status__in=[Invoice.STATUS_CANCELLED, Invoice.STATUS_PAID])
            .aggregate(t=Sum("paid_amount"))["t"] or Decimal("0")
        )

        by_mode = list(
            payments.values("payment_mode").annotate(amount=Sum("amount")).order_by("-amount")
        )

        daily_billed = {
            row["day"]: row["amount"] for row in
            invoices.annotate(day=TruncDate("created_at")).values("day").annotate(amount=Sum("total_amount")).order_by("day")
        }
        daily_collected = {
            row["day"]: row["amount"] for row in
            payments.annotate(day=TruncDate("paid_at")).values("day").annotate(amount=Sum("amount")).order_by("day")
        }
        all_days = sorted(set(daily_billed) | set(daily_collected))
        daily = [
            {"date": str(d), "billed": daily_billed.get(d, Decimal("0")), "collected": daily_collected.get(d, Decimal("0"))}
            for d in all_days
        ]

        return success(data={
            "date_from": date_from,
            "date_to": date_to,
            "total_billed": total_billed,
            "total_collected": total_collected,
            "total_outstanding": total_outstanding,
            "collection_rate": float(total_collected / total_billed) if total_billed else None,
            "invoice_count": invoices.count(),
            "payment_count": payments.count(),
            "by_payment_mode": by_mode,
            "daily": daily,
        })


class BillingSummaryView(APIView):
    """
    GET /api/v1/billing/summary/?patient_id=
    GET /api/v1/billing/summary/?appointment_id=  (resolves patient off the
         appointment — Appointment.patient_id is a UUID mirror of
         Patient.uuid, not the same key space as Invoice.patient_id, so this
         is the path the front-desk Bill screen actually uses)

    Combined read-only view of what a patient owes/has paid across three
    still-separate systems: billing.Invoice (front-desk billed items —
    consultation, procedures, whatever's on the price catalog), lab
    (LabRequest, priced off the LabTest catalog, own payment_status), and
    pharmacy (Dispense, which has no sale-price field yet — estimated off
    the stock's unit_cost, flagged as such). Nothing here is merged into a
    single Invoice; lab and pharmacy keep their own payment tracking. This
    just puts the three totals side by side so front desk isn't hunting
    across three screens to see what a patient owes in total.
    """
    permission_classes = [IsAuthenticated, IsHospitalStaff]

    def get(self, request):
        db = request.tenant_db
        patient_id = request.query_params.get("patient_id")

        if not patient_id and request.query_params.get("appointment_id"):
            from apps.opd.models import Appointment
            from apps.patients.models import Patient
            try:
                appt = Appointment.objects.using(db).get(pk=request.query_params["appointment_id"])
                patient_id = Patient.objects.using(db).get(uuid=appt.patient_id).id
            except (Appointment.DoesNotExist, Patient.DoesNotExist):
                return error("Appointment/patient not found.")

        if not patient_id:
            return error("patient_id or appointment_id is required.")

        # ── Billing (front-desk invoices) ───────────────────────────────
        invoices = Invoice.objects.using(db).filter(patient_id=patient_id)
        billing_total  = sum((i.total_amount for i in invoices), Decimal("0"))
        billing_paid   = sum((i.paid_amount for i in invoices), Decimal("0"))
        billing_count  = invoices.count()

        # ── Lab charges (own payment_status, never becomes an Invoice) ──
        from apps.lab.models import LabRequest
        lab_requests = (
            LabRequest.objects.using(db)
            .filter(patient_id=patient_id)
            .exclude(status="cancelled")
            .select_related("test")
        )
        lab_total = sum((lr.test.price or Decimal("0") for lr in lab_requests), Decimal("0"))
        lab_paid  = sum(
            (lr.test.price or Decimal("0") for lr in lab_requests if lr.payment_status == "paid"),
            Decimal("0"),
        )
        lab_count = lab_requests.count()

        # ── Pharmacy charges — ESTIMATED. Dispense has no sale-price field
        # today (only Stock.unit_cost, the hospital's own purchase cost), so
        # this is flagged as an estimate rather than a real charge — see
        # billing backlog item for adding real pharmacy pricing.
        from apps.pharmacy.models import Dispense
        dispenses = (
            Dispense.objects.using(db)
            .filter(prescription_item__prescription__patient_id=patient_id)
            .select_related("stock")
        )
        pharmacy_estimated_total = sum(
            ((d.stock.unit_cost or Decimal("0")) * d.quantity for d in dispenses), Decimal("0")
        )
        pharmacy_count = dispenses.count()

        grand_total = billing_total + lab_total + pharmacy_estimated_total
        grand_paid  = billing_paid + lab_paid  # pharmacy has no payment tracking to add here

        return success(data={
            "patient_id": patient_id,
            "billing":  {"invoice_count": billing_count, "total": str(billing_total), "paid": str(billing_paid)},
            "lab":      {"request_count": lab_count, "total": str(lab_total), "paid": str(lab_paid)},
            "pharmacy": {"dispense_count": pharmacy_count, "estimated_total": str(pharmacy_estimated_total),
                         "note": "Estimated from stock cost — pharmacy doesn't capture a separate sale price yet."},
            "grand_total": str(grand_total),
            "grand_paid":  str(grand_paid),
            "grand_outstanding": str(grand_total - grand_paid),
        })
