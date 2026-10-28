import csv
import io
import logging

from django.conf import settings
from decimal import Decimal
from datetime import timedelta

from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone
from django.db import transaction
from django.db.models import Sum
from django.utils.dateparse import parse_datetime

from core.api.response import success, created, error, not_found
from core.api.permissions import IsHospitalStaff, IsHospitalAdmin
from core.api.pagination import paginate_list, paginate_queryset
from apps.hospital_setup.models import NextNumber
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
from apps.billing.services import add_payment, line_from_request, money, recompute_invoice_totals
from apps.billing.models import Invoice, BillingItem
from apps.hospital_setup.models import OptionList


logger = logging.getLogger(__name__)


class BillingServiceListView(APIView):
    """GET  /api/v1/billing/services/  — list the active price catalog (any staff)"""
    def get_permissions(self):
        if self.request.method == "GET":
            return [IsAuthenticated(), IsHospitalStaff()]
        return [IsAuthenticated(), IsHospitalAdmin()]

    def get(self, request):
        services = BillingItem.objects.using(request.hospital_db).filter(is_active=True)
        return success(data=BillingServiceSerializer(services, many=True).data)

    def post(self, request):
        s = BillingServiceSerializer(data=request.data)
        if not s.is_valid():
            return error("Validation error.", errors=s.errors)
        svc = BillingItem(**s.validated_data)
        svc.save(using=request.hospital_db)
        return created(data=BillingServiceSerializer(svc).data, message="Service added.")


class BillingServiceUploadView(APIView):
    """POST /api/v1/billing/services/upload/ — add or update the price list in one go.

    Send a CSV file (field "file") with the columns code, name, category, unit_price, tax_rate, tax_inclusive, is_price_editable, is_active,
    or JSON {"services": [...]} with the same keys. A row whose code already exists updates that service. Nothing is saved if any row is wrong."""
    permission_classes = [IsAuthenticated, IsHospitalAdmin]

    @staticmethod
    def _rows(request):
        upload = request.FILES.get("file")
        if upload is None:
            return request.data.get("services") or []
        text = upload.read().decode("utf-8-sig")
        return [{k.strip(): (v or "").strip() for k, v in row.items() if k} for row in csv.DictReader(io.StringIO(text))]

    def post(self, request):
        rows = self._rows(request)
        if not rows:
            return error("No price-list rows were sent.")
        db = request.hospital_db
        problems, parsed = {}, []
        for number, row in enumerate(rows, start=1):
            row = {k: v for k, v in row.items() if v != ""}
            for flag in ("tax_inclusive", "is_price_editable", "is_active"):
                if flag in row:
                    row[flag] = str(row[flag]).lower() in ("true", "1", "yes", "y")
            known = BillingItem.objects.using(db).filter(code=row["code"]).first() if row.get("code") else None
            s = BillingServiceSerializer(known, data=row, partial=known is not None)
            if not s.is_valid():
                problems[number] = s.errors
            elif not s.validated_data.get("code"):
                problems[number] = {"code": ["Every row needs a code."]}
            else:
                parsed.append(s.validated_data)
        if len({p["code"] for p in parsed}) != len(parsed):
            problems["file"] = {"code": ["A code appears more than once."]}
        if problems:
            return error("The price list was not saved.", errors=problems)
        added = updated = 0
        with transaction.atomic(using=db):
            for data in parsed:
                _, was_added = BillingItem.objects.using(db).update_or_create(code=data["code"], defaults=data)
                added, updated = added + was_added, updated + (not was_added)
        return success(data={"added": added, "updated": updated}, message="Price list saved.")


class BillingServiceDetailView(APIView):
    """PATCH  /api/v1/billing/services/{id}/ — edit name/price/tax/category"""
    permission_classes = [IsAuthenticated, IsHospitalAdmin]

    def _get(self, request, pk):
        try:
            return BillingItem.objects.using(request.hospital_db).get(pk=pk)
        except BillingItem.DoesNotExist:
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

        inv_number, _ = NextNumber.next(branch_id, "invoice", db)
        inv = Invoice.objects.using(db).create(
            patient_id=patient_pk,
            branch_id=branch_id,
            invoice_number=inv_number,
            notes=request.data.get("notes", ""),
            created_by_id=request.user.pk,
        )

        # Optional lines in the same call — [{description, unit_price, quantity, service}]
        if request.data.get("items"):
            for item in request.data["items"]:
                service = BillingItem.objects.using(db).filter(pk=item["service"]).first() if item.get("service") else None
                inv.lines = [*inv.lines, line_from_request(item, service)]
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
    """GET /api/v1/billing/invoices/{id}/pdf/ — the PDF is also kept as the hospital's document for the invoice (the latest print replaces the last)."""
    permission_classes = [IsAuthenticated, IsHospitalStaff]

    @staticmethod
    def _keep(db, inv, patient, data_uri):
        from core import storage as blob_storage
        from apps.hospital_patients.hospital_log import event_for, record_document
        from apps.hospital_setup.models import hospital_folder

        if patient is None:
            return
        try:
            key = blob_storage.upload_data_uri(data_uri, prefix=f"{hospital_folder(db)}/patients/{patient.uhid}/invoices", mime_type="application/pdf",
                                               category="invoice")
            old = record_document(db, event_for(db, patient.pk, "billing", inv.created_at), key)
            if old:
                blob_storage.delete(old)
        except Exception:
            logger.exception("invoice %s: the PDF was not kept as a hospital document", inv.pk)

    def get(self, request, pk):
        import base64
        from apps.hospital_patients.models import HospitalPatient
        from apps.hospital_setup.models import Branch
        from apps.hospital_master.models import Hospital
        from apps.billing.pdf import generate_invoice_pdf

        db = request.hospital_db
        try:
            inv = Invoice.objects.using(db).get(pk=pk)
        except Invoice.DoesNotExist:
            return not_found("Invoice not found.")

        patient = HospitalPatient.objects.using(db).filter(pk=inv.patient_id).first()
        branch = Branch.objects.using(db).filter(pk=inv.branch_id).first()
        hospital = Hospital.objects.using("default").filter(pk=request.hospital_id).first()
        hospital_name = hospital.name if hospital else "Hospital"

        pdf_bytes = generate_invoice_pdf(
            invoice=inv,
            items=inv.lines,
            payments=sorted(inv.payments, key=lambda p: p["paid_at"]),
            patient=patient,
            branch=branch,
            hospital_name=hospital_name,
        )
        data_uri = "data:application/pdf;base64," + base64.b64encode(pdf_bytes).decode("ascii")
        self._keep(db, inv, patient, data_uri)
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

        s = InvoiceItemSerializer(data=request.data, db=db)
        if not s.is_valid():
            return error("Validation error.", errors=s.errors)
        d = s.validated_data
        inv.lines = [*inv.lines, line_from_request(d, d.get("service"))]
        recompute_invoice_totals(inv, db)
        return created(data=InvoiceSerializer(inv).data, message="Item added.")


class PaymentCreateView(APIView):
    """GET /api/v1/billing/payments/ — every payment, newest first; POST — record a payment against an invoice."""
    permission_classes = [IsAuthenticated, IsHospitalStaff]

    def get(self, request):
        from apps.hospital_patients.models import HospitalPatient
        from apps.hospital_setup.models import StaffUser

        db = request.hospital_db
        invoices = Invoice.objects.using(db).exclude(payments=[]).select_related("patient")
        if patient_id := request.query_params.get("patient_id"):
            invoices = invoices.filter(patient_id=patient_id)
        date_from, date_to = request.query_params.get("date_from"), request.query_params.get("date_to")
        mode = request.query_params.get("payment_mode")

        rows = []
        for inv in invoices:
            for p in inv.payments:
                paid_at = parse_datetime(p["paid_at"])
                if (date_from and paid_at.date().isoformat() < date_from) or (date_to and paid_at.date().isoformat() > date_to) or (mode and p["payment_mode"] != mode):
                    continue
                rows.append((paid_at, inv, p))
        rows.sort(key=lambda r: r[0], reverse=True)
        total_amount = sum((money(p["amount"]) for _, _, p in rows), Decimal("0"))
        page_items, meta = paginate_list(request, rows)

        patients = [inv.patient for _, inv, _ in page_items]
        for p in patients[:1]:
            p.get_patient_details(batch=patients)
        recorders = {s.pk: s for s in StaffUser.objects.using(db).filter(pk__in={p["recorded_by_id"] for _, _, p in page_items if p.get("recorded_by_id")})}

        results = []
        for paid_at, inv, p in page_items:
            recorder = recorders.get(p.get("recorded_by_id"))
            results.append({
                "payment_id": f"{inv.pk}-{p['payment_id']}", "amount": p["amount"], "payment_mode": p["payment_mode"], "transaction_ref": p["transaction_ref"],
                "paid_at": paid_at, "invoice_id": inv.pk, "invoice_number": inv.invoice_number, "invoice_status": inv.status,
                "patient_name": inv.patient.get_patient_details()["full_name"], "patient_uhid": inv.patient.uhid,
                "recorded_by_name": (f"{recorder.first_name} {recorder.last_name}".strip() or recorder.email) if recorder else "",
            })
        return success(data={"results": results, "pagination": meta, "total_amount": total_amount})

    def post(self, request):
        db = request.hospital_db
        s = PaymentSerializer(data=request.data, db=db)
        if not s.is_valid():
            return error("Validation error.", errors=s.errors)
        d = s.validated_data
        # The payment and the invoice's running total in one transaction, with the invoice row locked
        with transaction.atomic(using=db):
            inv = Invoice.objects.using(db).select_for_update().get(pk=d["invoice"].pk)
            outstanding = inv.total_amount - inv.paid_amount
            if d["amount"] > outstanding:
                return error("That is more than the invoice still owes.", errors={"amount": f"At most {outstanding} is outstanding."})
            ref = d.get("transaction_ref") or ""
            if ref and any(p["transaction_ref"] == ref for p in inv.payments):
                return error("That payment reference is already recorded for this invoice.", errors={"transaction_ref": "Already used on this invoice."})
            payment = add_payment(inv, db, d["amount"], d["payment_mode"], ref, request.user.pk)
        return created(data={**payment, "invoice": inv.pk})


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
        # Payments sit on their invoice, so the ones made in the dates asked for are picked out of the invoices that have any
        payments = [(parse_datetime(p["paid_at"]).date(), p) for inv in Invoice.objects.using(db).exclude(payments=[]) for p in inv.payments
                    if date_from <= parse_datetime(p["paid_at"]).date().isoformat() <= date_to]

        total_billed = invoices.aggregate(t=Sum("total_amount"))["t"] or Decimal("0")
        total_collected = sum((money(p["amount"]) for _, p in payments), Decimal("0"))
        # Outstanding is a point-in-time balance (not date-scoped) across every unpaid invoice
        open_invoices = Invoice.objects.using(db).exclude(status__in=[Invoice.STATUS_CANCELLED, Invoice.STATUS_PAID])
        total_outstanding = (open_invoices.aggregate(t=Sum("total_amount"))["t"] or Decimal("0")) - (open_invoices.aggregate(t=Sum("paid_amount"))["t"] or Decimal("0"))

        by_mode = {}
        for _, p in payments:
            by_mode[p["payment_mode"]] = by_mode.get(p["payment_mode"], Decimal("0")) + money(p["amount"])
        daily_billed = {
            row["day"]: row["amount"] for row in
            invoices.annotate(day=TruncDate("created_at")).values("day").annotate(amount=Sum("total_amount")).order_by("day")
        }
        daily_collected = {}
        for day, p in payments:
            daily_collected[day] = daily_collected.get(day, Decimal("0")) + money(p["amount"])
        daily = [
            {"date": str(d), "billed": daily_billed.get(d, Decimal("0")), "collected": daily_collected.get(d, Decimal("0"))}
            for d in sorted(set(daily_billed) | set(daily_collected))
        ]

        return success(data={
            "date_from": date_from,
            "date_to": date_to,
            "total_billed": total_billed,
            "total_collected": total_collected,
            "total_outstanding": total_outstanding,
            "collection_rate": float(total_collected / total_billed) if total_billed else None,
            "invoice_count": invoices.count(),
            "payment_count": len(payments),
            "by_payment_mode": [{"payment_mode": m, "amount": a} for m, a in sorted(by_mode.items(), key=lambda kv: -kv[1])],
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

        invoices = Invoice.objects.using(db).filter(patient_id=patient_id)
        total = sum((i.total_amount for i in invoices), Decimal("0"))
        paid = sum((i.paid_amount for i in invoices), Decimal("0"))
        return success(data={
            "patient_id": patient_id,
            "billing": {"invoice_count": invoices.count(), "total": str(total), "paid": str(paid)},
            "grand_total": str(total),
            "grand_paid": str(paid),
            "grand_outstanding": str(total - paid),
        })
