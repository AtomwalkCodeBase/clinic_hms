from django.conf import settings
from decimal import Decimal
from datetime import timedelta

from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone
from django.db import transaction
from django.db.models import Sum

from core.api.response import success, created, error, not_found
from core.api.permissions import IsHospitalStaff, IsHospitalAdmin
from core.api.pagination import paginate_queryset
from core.utils.nntm import get_next_number
from apps.billing.serializers import (
    InvoiceSerializer,
    InvoiceItemSerializer,
    PaymentSerializer,
    BillingServiceSerializer,
    ServiceCategorySerializer,
    PaymentModeOptionSerializer,
    InvoiceStatusOptionSerializer,
    RoomTypeOptionSerializer,
)
from apps.billing.option_list_views import DropdownListCreateView, DropdownDetailView
from apps.billing.services import recompute_invoice_totals
from apps.billing.models import (
    Invoice,
    InvoiceItem,
    Payment,
    BillingService,
    OptionList,
)


class BillingServiceListView(APIView):
    """GET  /api/v1/billing/services/  — list the active price catalog (any staff)"""
    def get_permissions(self):
        if self.request.method == "GET":
            return [IsAuthenticated(), IsHospitalStaff()]
        return [IsAuthenticated(), IsHospitalAdmin()]

    def get(self, request):
        services = BillingService.objects.using(request.hospital_db).filter(is_active=True)
        return success(data=BillingServiceSerializer(services, many=True).data)

    def post(self, request):
        s = BillingServiceSerializer(data=request.data)
        if not s.is_valid():
            return error("Validation error.", errors=s.errors)
        svc = BillingService(**s.validated_data)
        svc.save(using=request.hospital_db)
        return created(data=BillingServiceSerializer(svc).data, message="Service added.")


class BillingServiceDetailView(APIView):
    """PATCH  /api/v1/billing/services/{id}/ — edit name/price/tax/category"""
    permission_classes = [IsAuthenticated, IsHospitalAdmin]

    def _get(self, request, pk):
        try:
            return BillingService.objects.using(request.hospital_db).get(pk=pk)
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
        svc.save(using=request.hospital_db)
        return success(data=BillingServiceSerializer(svc).data, message="Service updated.")

    def delete(self, request, pk):
        svc = self._get(request, pk)
        if not svc:
            return not_found("Service not found.")
        svc.is_active = False
        svc.save(using=request.hospital_db, update_fields=["is_active"])
        return success(message="Service deactivated.")


class ServiceCategoryListCreateView(DropdownListCreateView):
    """GET/POST /api/v1/billing/service-categories/"""
    list_type = OptionList.LIST_SERVICE_CATEGORY
    serializer_class = ServiceCategorySerializer
    identity_field = "name"
    model_field = "label"


class ServiceCategoryDetailView(DropdownDetailView):
    """PATCH/DELETE /api/v1/billing/service-categories/{id}/"""
    list_type = OptionList.LIST_SERVICE_CATEGORY
    serializer_class = ServiceCategorySerializer
    identity_field = "name"
    model_field = "label"


class PaymentModeListCreateView(DropdownListCreateView):
    """GET/POST /api/v1/billing/payment-modes/"""
    list_type = OptionList.LIST_PAYMENT_MODE
    serializer_class = PaymentModeOptionSerializer
    identity_field = "name"
    model_field = "label"


class PaymentModeDetailView(DropdownDetailView):
    """PATCH/DELETE /api/v1/billing/payment-modes/{id}/"""
    list_type = OptionList.LIST_PAYMENT_MODE
    serializer_class = PaymentModeOptionSerializer
    identity_field = "name"
    model_field = "label"
    # A hospital can genuinely not want to offer e.g. "Credit" or "Online" —
    system_can_deactivate = True


class InvoiceStatusListCreateView(DropdownListCreateView):
    """GET/POST /api/v1/billing/invoice-statuses/"""
    list_type = OptionList.LIST_INVOICE_STATUS
    serializer_class = InvoiceStatusOptionSerializer
    identity_field = "value"
    model_field = "value"


class InvoiceStatusDetailView(DropdownDetailView):
    """PATCH/DELETE /api/v1/billing/invoice-statuses/{id}/"""
    list_type = OptionList.LIST_INVOICE_STATUS
    serializer_class = InvoiceStatusOptionSerializer
    identity_field = "value"
    model_field = "value"


class RoomTypeListCreateView(DropdownListCreateView):
    """GET/POST /api/v1/billing/room-types/"""
    list_type = OptionList.LIST_ROOM_TYPE
    serializer_class = RoomTypeOptionSerializer
    identity_field = "value"
    model_field = "value"


class RoomTypeDetailView(DropdownDetailView):
    """PATCH/DELETE /api/v1/billing/room-types/{id}/"""
    list_type = OptionList.LIST_ROOM_TYPE
    serializer_class = RoomTypeOptionSerializer
    identity_field = "value"
    model_field = "value"
    # Nothing in the backend branches on a specific room type value (unlike
    system_can_deactivate = True


class InvoiceListCreateView(APIView):
    """GET  /api/v1/billing/invoices/  — list invoices (optionally filter by"""
    permission_classes = [IsAuthenticated, IsHospitalStaff]

    def get(self, request):
        qs = Invoice.objects.using(request.hospital_db).select_related("patient").order_by("-created_at")
        if pid := request.query_params.get("patient_id"):
            qs = qs.filter(patient_id=pid)
        if status_filter := request.query_params.get("status"):
            qs = qs.filter(status=status_filter)
        page_items, meta = paginate_queryset(request, qs)
        patients = [i.patient for i in page_items]
        for p in patients[:1]:
            p.get_patient_details(batch=patients)             # the whole page at once
        return success(data={
            "results": InvoiceSerializer(page_items, many=True).data,
            "pagination": meta,
        })

    def post(self, request):
        db = request.hospital_db
        patient_pk = request.data.get("patient")
        branch_id = request.data.get("branch")

        # Resolve patient/branch from an appointment when one is given —
        appointment_id = request.data.get("appointment_id")
        if appointment_id:
            from apps.opd.models import Appointment
            try:
                appt = Appointment.objects.using(db).select_related("branch_department").get(pk=appointment_id)
            except Appointment.DoesNotExist:
                return error("Appointment not found.")
            patient_pk = appt.patient_id
            branch_id = branch_id or appt.branch_department.branch_id

        if not patient_pk:
            return error("patient (or appointment_id) is required.", errors={"patient": "Required."})

        # No appointment_id (billing without a visit — e.g. a registration
        if not branch_id:
            branch_id = getattr(request.user, "branch_id", None)
        if not branch_id:
            return error(
                "Could not determine which branch to bill this invoice to — pass branch explicitly.",
                errors={"branch": "Required."},
            )

        inv_number, _ = get_next_number(branch_id=branch_id, entity="invoice", using=db)
        inv = Invoice.objects.using(db).create(
            patient_id=patient_pk,
            branch_id=branch_id,
            invoice_number=inv_number,
            notes=request.data.get("notes", ""),
            created_by_id=request.user.id,
        )

        # Optional line items in the same call — [{description, unit_price,
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
            recompute_invoice_totals(inv, db)
            inv.refresh_from_db(using=db)

        return created(data=InvoiceSerializer(inv).data)


class InvoiceDetailView(APIView):
    """GET   /api/v1/billing/invoices/{id}/ — invoice with items + payments"""
    permission_classes = [IsAuthenticated, IsHospitalStaff]

    def _get(self, request, pk):
        try:
            return Invoice.objects.using(request.hospital_db).get(pk=pk)
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
        db = request.hospital_db

        if "discount_amount" in request.data:
            inv.discount_amount = Decimal(str(request.data["discount_amount"]))
            inv.save(using=db, update_fields=["discount_amount"])
            recompute_invoice_totals(inv, db)
            inv.refresh_from_db(using=db)

        if "notes" in request.data:
            inv.notes = request.data["notes"]
            inv.save(using=db, update_fields=["notes"])

        status_val = request.data.get("status")
        if status_val:
            valid_statuses = set(
                OptionList.objects.using(db)
                .filter(list_type=OptionList.LIST_INVOICE_STATUS, is_active=True)
                .values_list("value", flat=True)
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
    """GET /api/v1/billing/invoices/{id}/pdf/"""
    permission_classes = [IsAuthenticated, IsHospitalStaff]

    def get(self, request, pk):
        import base64
        from apps.opd.models import HospitalPatient
        from apps.hospital_setup.models import Branch
        from apps.hospital_master.models import Hospital
        from apps.billing.pdf import generate_invoice_pdf

        db = request.hospital_db
        try:
            inv = Invoice.objects.using(db).prefetch_related("i_items", "i_payments").get(pk=pk)
        except Invoice.DoesNotExist:
            return not_found("Invoice not found.")

        patient = HospitalPatient.objects.using(db).filter(pk=inv.patient_id).first()
        branch = Branch.objects.using(db).filter(pk=inv.branch_id).first()
        hospital = Hospital.objects.using("default").filter(pk=request.hospital_id).first()
        hospital_name = hospital.name if hospital else "Hospital"

        pdf_bytes = generate_invoice_pdf(
            invoice=inv,
            items=list(inv.i_items.all()),
            payments=list(inv.i_payments.all().order_by("paid_at")),
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
        db = request.hospital_db
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
        InvoiceItem.objects.using(db).create(
            invoice=inv,
            service=d.get("service"),
            description=d["description"],
            quantity=d.get("quantity", 1),
            unit_price=d["unit_price"],
            tax_rate=d.get("tax_rate", 0),
            total=d["unit_price"] * d.get("quantity", 1),
        )
        recompute_invoice_totals(inv, db)
        return created(data=InvoiceSerializer(inv.__class__.objects.using(db).get(pk=inv.pk)).data,
                       message="Item added.")


class PaymentCreateView(APIView):
    """POST /api/v1/billing/payments/  — record a payment against an invoice."""
    permission_classes = [IsAuthenticated, IsHospitalStaff]

    def get(self, request):
        from apps.opd.models import HospitalPatient
        from apps.hospital_setup.models import StaffUser

        db = request.hospital_db
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
        rows = list(HospitalPatient.objects.using(db).filter(pk__in=patient_ids))
        for p in rows[:1]:
            p.get_patient_details(batch=rows)
        patients = {p.id: p for p in rows}
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
                "patient_name": patient.get_patient_details()["full_name"] if patient else "",
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
        db = request.hospital_db
        # Payment + the invoice's running total in one transaction, with the invoice row
        with transaction.atomic(using=db):
            inv = Invoice.objects.using(db).select_for_update().get(pk=s.validated_data["invoice"].pk)
            outstanding = inv.total_amount - inv.paid_amount
            if s.validated_data["amount"] > outstanding:
                return error("That is more than the invoice still owes.",
                             errors={"amount": f"At most {outstanding} is outstanding."})
            ref = s.validated_data.get("transaction_ref") or ""
            if ref and Payment.objects.using(db).filter(invoice=inv, transaction_ref=ref).exists():
                return error("That payment reference is already recorded for this invoice.",
                             errors={"transaction_ref": "Already used on this invoice."})
            payment = Payment.objects.using(db).create(recorded_by_id=request.user.id, **s.validated_data)
            inv.paid_amount += payment.amount
            inv.status = "paid" if inv.paid_amount >= inv.total_amount else "partially_paid"
            inv.save(using=db, update_fields=["paid_amount", "status"])
        return created(data=PaymentSerializer(payment).data)


class RevenueReportView(APIView):
    """GET /api/v1/billing/reports/revenue/?date_from=&date_to=  (HMS-09d-2)"""
    permission_classes = [IsAuthenticated, IsHospitalAdmin]

    def get(self, request):
        from django.db.models.functions import TruncDate

        db = request.hospital_db
        date_to = request.query_params.get("date_to") or timezone.localdate().isoformat()
        date_from = request.query_params.get("date_from") or (
            timezone.localdate() - timedelta(days=settings.BILLING_REPORT_DAYS - 1)
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
    """GET /api/v1/billing/summary/?patient_id="""
    permission_classes = [IsAuthenticated, IsHospitalStaff]

    def get(self, request):
        db = request.hospital_db
        patient_id = request.query_params.get("patient_id")

        if not patient_id and request.query_params.get("appointment_id"):
            from apps.opd.models import Appointment
            try:
                patient_id = Appointment.objects.using(db).get(pk=request.query_params["appointment_id"]).patient_id
            except Appointment.DoesNotExist:
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
        from apps.pharmacy.models import Dispense
        dispenses = (
            Dispense.objects.using(db)
            .filter(prescription_item__prescription__encounter__appointment__patient_id=patient_id)
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
