import logging
from django.db import transaction
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from core.api.response import success, created, error, not_found
from core.api.permissions import IsPharmacist, RequireFeature
from core.api.pagination import paginate_queryset
from apps.pharmacy.serializers import StockSerializer, DispenseSerializer
from apps.pharmacy.models import Stock, StockTransaction, Dispense

logger = logging.getLogger(__name__)


class StockListView(APIView):
    permission_classes = [IsAuthenticated, IsPharmacist, RequireFeature("feat_pharmacy")]

    def get(self, request):
        qs = Stock.objects.using(request.hospital_db).select_related("drug").order_by("drug__name")
        if bid := request.query_params.get("branch_id"):
            qs = qs.filter(branch_id=bid)
        if request.query_params.get("low_only") == "1":
            from django.db.models import F
            qs = qs.filter(quantity__lte=F("reorder_level"))
        page_items, meta = paginate_queryset(request, qs)
        return success(data={
            "results": StockSerializer(page_items, many=True).data,
            "pagination": meta,
        })

    def post(self, request):
        """Receive stock — creates a new batch, or tops up an existing one for"""
        s = StockSerializer(data=request.data)
        if not s.is_valid():
            return error("Validation error.", errors=s.errors)
        db = request.hospital_db
        d = s.validated_data
        added = d["quantity"]
        if added <= 0:
            return error("Quantity received must be greater than zero.")

        with transaction.atomic(using=db):
            stock, made = Stock.objects.using(db).get_or_create(
                drug=d["drug"], branch=d["branch"], batch_number=d.get("batch_number", ""),
                defaults={
                    "expiry_date":   d.get("expiry_date"),
                    "quantity":      0,
                    "reorder_level": d.get("reorder_level", 10),
                    "unit_cost":     d.get("unit_cost"),
                    "mrp":           d.get("mrp"),
                },
            )
            # Lock the batch and read its current quantity, so this can't overwrite a
            stock = Stock.objects.using(db).select_for_update().get(pk=stock.pk)
            qty_before = stock.quantity
            stock.quantity += added
            # An existing batch being topped up can still have its price/expiry
            if not made:
                if d.get("expiry_date"):  stock.expiry_date = d["expiry_date"]
                if d.get("unit_cost") is not None: stock.unit_cost = d["unit_cost"]
                if d.get("mrp") is not None:       stock.mrp = d["mrp"]
            stock.save(using=db)

            StockTransaction.objects.using(db).create(
                stock=stock, txn_type="purchase", quantity_change=added,
                quantity_before=qty_before, quantity_after=stock.quantity,
                reference_type="Purchase", recorded_by_id=request.user.id,
            )
        return created(data=StockSerializer(stock).data, message="Stock received.")


class DispenseView(APIView):
    permission_classes = [IsAuthenticated, IsPharmacist, RequireFeature("feat_pharmacy")]

    def post(self, request):
        s = DispenseSerializer(data=request.data)
        if not s.is_valid():
            return error("Validation error.", errors=s.errors)

        db    = request.hospital_db
        qty   = s.validated_data["quantity"]

        # One transaction for the whole stock movement, holding a row lock on the batch:
        with transaction.atomic(using=db):
            stock = Stock.objects.using(db).select_for_update().get(pk=s.validated_data["stock"].pk)

            if stock.quantity < qty:
                return error(f"Insufficient stock. Available: {stock.quantity}")

            qty_before = stock.quantity
            stock.quantity -= qty
            stock.save(using=db, update_fields=["quantity"])

            StockTransaction.objects.using(db).create(
                stock=stock,
                txn_type="dispense",
                quantity_change=-qty,
                quantity_before=qty_before,
                quantity_after=stock.quantity,
                reference_type="Dispense",
                recorded_by_id=request.user.id,
            )

            dispense = Dispense.objects.using(db).create(
                dispensed_by_id=request.user.id, **s.validated_data
            )

            # If every item on this prescription now has at least one dispense
            from apps.opd.models import Prescription, PrescriptionItem
            item = s.validated_data["prescription_item"]
            prescription_id = item.prescription_id
            still_pending = PrescriptionItem.objects.using(db).filter(
                prescription_id=prescription_id
            ).exclude(
                id__in=Dispense.objects.using(db)
                    .filter(prescription_item__prescription_id=prescription_id)
                    .values_list("prescription_item_id", flat=True)
            ).exists()
            if not still_pending:
                Prescription.objects.using(db).filter(pk=prescription_id).update(status=Prescription.STATUS_DISPENSED)

        # ── Billing: create/append to a real Invoice, priced from Stock.mrp
        try:
            from decimal import Decimal
            from apps.billing.models import Invoice, InvoiceItem
            from apps.billing.services import recompute_invoice_totals, hospital_default_tax_rate
            from apps.opd.models import HospitalPatient
            from core.utils.nntm import get_next_number

            # Its own savepoint: a failure half-way (invoice created, line item not) rolls the
            with transaction.atomic(using=db):
                # Locked so two concurrent dispenses on one Rx can't each create its invoice.
                rx = Prescription.objects.using(db).select_for_update().get(pk=prescription_id)
                # Batch MRP wins (real price this batch was received at); fall
                unit_price = (
                    stock.mrp if stock.mrp is not None
                    else stock.unit_cost if stock.unit_cost is not None
                    else getattr(stock.drug, "default_mrp", None) or Decimal("0")
                )
                tax_rate = hospital_default_tax_rate(request.hospital_id)

                if rx.invoice_id:
                    invoice = Invoice.objects.using(db).get(pk=rx.invoice_id)
                else:
                    appointment = rx.encounter.appointment
                    branch = appointment.branch_department.branch
                    invoice_number, _ = get_next_number(branch_id=branch.id, entity="invoice", using=db)
                    invoice = Invoice.objects.using(db).create(
                        patient=appointment.patient, branch=branch, invoice_number=invoice_number,
                        status="draft", created_by_id=request.user.id,
                        notes=f"Auto-generated for prescription {rx.rx_number or rx.id}",
                    )
                    rx.invoice = invoice
                    rx.save(using=db, update_fields=["invoice"])

                InvoiceItem.objects.using(db).create(
                    invoice=invoice, description=item.drug_name, quantity=qty,
                    unit_price=unit_price, tax_rate=tax_rate, total=unit_price * qty,
                )
                recompute_invoice_totals(invoice, db)
                logger.info("Billed dispense: prescription=%s invoice=%s drug=%s qty=%s unit_price=%s",
                            prescription_id, invoice.invoice_number, item.drug_name, qty, unit_price)
        except Exception as e:
            logger.warning("Could not bill dispense for prescription %s: %s", prescription_id, e)

        return created(data=DispenseSerializer(dispense).data)


class PendingPrescriptionsView(APIView):
    """GET /api/v1/pharmacy/prescriptions/"""
    permission_classes = [IsAuthenticated, IsPharmacist, RequireFeature("feat_pharmacy")]

    def get(self, request):
        from django.db.models import Sum
        from apps.opd.models import Prescription

        db = request.hospital_db
        status_filter = request.query_params.get("status", Prescription.STATUS_ACTIVE)
        qs = (Prescription.objects.using(db).select_related("encounter__appointment__patient", "encounter__appointment__doctor")
              .filter(status=status_filter, patient_choice=Prescription.CHOICE_IN_HOUSE)
              .prefetch_related("rx_items")
              .order_by("-created_at"))
        page_items, meta = paginate_queryset(request, qs)
        patients = [rx.encounter.appointment.patient for rx in page_items]
        for p in patients[:1]:
            p.get_patient_details(batch=patients)                 # the patients' names, in one go

        # Per-item dispensed quantity, in one query for the whole page.
        item_ids = [it.id for p in page_items for it in p.rx_items.all()]
        dispensed_by_item = {}
        for row in (Dispense.objects.using(db).filter(prescription_item_id__in=item_ids)
                    .values("prescription_item_id")
                    .annotate(total=Sum("quantity"))):
            dispensed_by_item[row["prescription_item_id"]] = row["total"]

        results = []
        for rx in page_items:
            patient = rx.encounter.appointment.patient
            doctor = rx.encounter.appointment.doctor
            results.append({
                # rx_number: the real NNTM-generated token (e.g. "RX-000123")
                "id": str(rx.id), "rx_number": rx.rx_number or str(rx.id)[:8].upper(), "status": rx.status,
                "patient_choice": rx.patient_choice, "payment_status": rx.payment_status,
                "notes": rx.notes, "finalized_at": rx.created_at, "created_at": rx.created_at,
                "patient_id": str(patient.id),
                "patient": str(patient.id),
                "patient_name": patient.get_patient_details()["full_name"],
                "patient_uhid": patient.uhid,
                "doctor_name": doctor.get_full_name(),
                "items": [{
                    "id": str(it.id), "drug": it.drug_id, "drug_name": it.drug_name,
                    "dose": it.dosage, "unit": "", "frequency": it.frequency,
                    "route": it.route, "duration_days": it.duration_days,
                    "instructions": it.instructions,
                    "dispensed_qty": dispensed_by_item.get(it.id, 0),
                } for it in rx.rx_items.all()],
            })

        return success(data={"results": results, "pagination": meta})


class PrescriptionLookupView(APIView):
    """GET /api/v1/pharmacy/prescriptions/lookup/?rx_number=RX-000123"""
    permission_classes = [IsAuthenticated, IsPharmacist, RequireFeature("feat_pharmacy")]

    def get(self, request):
        from apps.opd.models import Prescription
        from django.db.models import Sum

        rx_number = (request.query_params.get("rx_number") or "").strip()
        if not rx_number:
            return error("rx_number is required.")

        db = request.hospital_db
        try:
            rx = (Prescription.objects.using(db).select_related("encounter__appointment__patient", "encounter__appointment__doctor")
                  .prefetch_related("rx_items").get(rx_number__iexact=rx_number))
        except Prescription.DoesNotExist:
            return not_found("No prescription found for that number.")

        patient = rx.encounter.appointment.patient
        doctor = rx.encounter.appointment.doctor

        item_ids = [it.id for it in rx.rx_items.all()]
        dispensed_by_item = {
            row["prescription_item_id"]: row["total"]
            for row in (Dispense.objects.using(db).filter(prescription_item_id__in=item_ids)
                        .values("prescription_item_id").annotate(total=Sum("quantity")))
        }

        return success(data={
            "id": str(rx.id), "rx_number": rx.rx_number, "status": rx.status,
            "patient_choice": rx.patient_choice, "payment_status": rx.payment_status,
            "notes": rx.notes, "created_at": rx.created_at,
            "patient_id": str(patient.id),
            "patient_name": patient.get_patient_details()["full_name"],
            "patient_uhid": patient.uhid,
            "patient_phone": patient.get_patient_details()["mobile"],
            "doctor_name": doctor.get_full_name(),
            "items": [{
                "id": str(it.id), "drug": it.drug_id, "drug_name": it.drug_name,
                "dose": it.dosage, "unit": "", "frequency": it.frequency,
                "route": it.route, "duration_days": it.duration_days,
                "instructions": it.instructions,
                "dispensed_qty": dispensed_by_item.get(it.id, 0),
            } for it in rx.rx_items.all()],
        })
