import logging
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from core.response import success, created, error, not_found
from core.permissions import IsPharmacist, RequireFeature
from core.pagination import paginate_queryset
from .serializers import StockSerializer, StockTransactionSerializer, DispenseSerializer
from .models import Stock, StockTransaction, Dispense

logger = logging.getLogger(__name__)


class StockListView(APIView):
    permission_classes = [IsAuthenticated, IsPharmacist, RequireFeature("feat_pharmacy")]

    def get(self, request):
        qs = Stock.objects.using(request.tenant_db).select_related("drug").order_by("drug__name")
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
        """
        Receive stock — creates a new batch, or tops up an existing one for
        the same (drug, branch, batch_number), and logs a "purchase"
        StockTransaction either way so the ledger always explains how the
        quantity got there.
        """
        s = StockSerializer(data=request.data)
        if not s.is_valid():
            return error("Validation error.", errors=s.errors)
        db = request.tenant_db
        d = s.validated_data
        added = d["quantity"]
        if added <= 0:
            return error("Quantity received must be greater than zero.")

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
        qty_before = stock.quantity
        stock.quantity += added
        # An existing batch being topped up can still have its price/expiry
        # corrected in the same call rather than needing a second edit step.
        if not made:
            if d.get("expiry_date"):  stock.expiry_date = d["expiry_date"]
            if d.get("unit_cost") is not None: stock.unit_cost = d["unit_cost"]
            if d.get("mrp") is not None:       stock.mrp = d["mrp"]
        stock.save(using=db)

        StockTransaction.objects.using(db).create(
            stock=stock, txn_type="purchase", quantity_change=added,
            quantity_before=qty_before, quantity_after=stock.quantity,
            reference_type="Purchase", recorded_by=request.user,
        )
        return created(data=StockSerializer(stock).data, message="Stock received.")


class DispenseView(APIView):
    permission_classes = [IsAuthenticated, IsPharmacist, RequireFeature("feat_pharmacy")]

    def post(self, request):
        s = DispenseSerializer(data=request.data)
        if not s.is_valid():
            return error("Validation error.", errors=s.errors)

        db    = request.tenant_db
        stock = s.validated_data["stock"]
        qty   = s.validated_data["quantity"]

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
            recorded_by=request.user,
        )

        dispense = Dispense.objects.using(db).create(
            dispensed_by=request.user, **s.validated_data
        )

        # If every item on this prescription now has at least one dispense
        # record against it, treat the whole prescription as fulfilled so it
        # drops off the pending queue. This checks "touched at least once"
        # rather than "fully dispensed to the prescribed quantity" — there's
        # no quantity-prescribed field on PrescriptionItem to compare
        # against, only what's actually been dispensed, so a same-item
        # top-up dispense (e.g. partial fill now, rest later) won't
        # re-open a prescription already marked dispensed. Good enough for
        # the common case; a pharmacist can still dispense against an
        # already-"dispensed" prescription's item if more is needed.
        #
        # apps.opd.Prescription/PrescriptionItem — the live model doctors
        # actually write to (see apps/pharmacy/models.py header note; this
        # used to point at the old apps.prescriptions models, which the
        # live OPD flow never wrote to, so nothing ever reached this queue).
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
        # (actual sale price) rather than Stock.unit_cost (purchase cost) —
        # this is the gap BillingSummaryView flags explicitly as "no
        # sale-price field yet, estimate only." One Invoice per Prescription:
        # created on the first dispense against it, every later dispense of
        # another item on the same Rx appends an InvoiceItem to that same
        # invoice instead of creating a duplicate. Never blocks the dispense
        # itself — stock is already deducted and recorded above; a billing
        # hiccup shouldn't strand a drug that's physically left the shelf.
        try:
            from decimal import Decimal
            from apps.billing.models import Invoice, InvoiceItem
            from apps.billing.views import _recompute_invoice_totals
            from apps.opd.views import _tenant_default_tax_rate
            from apps.patients.models import Patient
            from core.utils.nntm import get_next_number

            rx = Prescription.objects.using(db).get(pk=prescription_id)
            # Batch MRP wins (real price this batch was received at); fall
            # back to unit_cost, then to the drug's catalog reference price
            # (Drug.default_mrp) rather than silently billing ₹0 just
            # because whoever received this particular batch left the price
            # fields blank.
            unit_price = (
                stock.mrp if stock.mrp is not None
                else stock.unit_cost if stock.unit_cost is not None
                else getattr(stock.drug, "default_mrp", None) or Decimal("0")
            )
            tax_rate = _tenant_default_tax_rate(request.tenant_id)

            if rx.invoice_id:
                invoice = Invoice.objects.using(db).get(pk=rx.invoice_id)
            else:
                patient = Patient.objects.using(db).get(uuid=rx.patient_id)
                invoice_number, _ = get_next_number(branch_id=patient.branch_id or 1, entity="invoice", using=db)
                invoice = Invoice.objects.using(db).create(
                    patient=patient, branch=patient.branch, invoice_number=invoice_number,
                    status="draft", created_by_id=request.user.id,
                    notes=f"Auto-generated for prescription {rx.rx_number or rx.id}",
                )
                rx.invoice = invoice
                rx.save(using=db, update_fields=["invoice"])

            InvoiceItem.objects.using(db).create(
                invoice=invoice, description=item.drug_name, quantity=qty,
                unit_price=unit_price, tax_rate=tax_rate, total=unit_price * qty,
            )
            _recompute_invoice_totals(invoice, db)
            logger.info("Billed dispense: prescription=%s invoice=%s drug=%s qty=%s unit_price=%s",
                        prescription_id, invoice.invoice_number, item.drug_name, qty, unit_price)
        except Exception as e:
            logger.warning("Could not bill dispense for prescription %s: %s", prescription_id, e)

        return created(data=DispenseSerializer(dispense).data)


class PendingPrescriptionsView(APIView):
    """
    GET /api/v1/pharmacy/prescriptions/
    The pharmacist's working queue — prescriptions a doctor has written
    (apps.opd.Prescription, created the moment a doctor saves one during a
    consultation — see opd.views.PrescriptionCreateView) grouped with their
    items and how much of each has already been dispensed.
    ?status=dispensed shows completed ones instead of the default "active".

    Only shows prescriptions the patient has actually chosen to fill
    in-house (patient_choice="in_house") — a doctor finalizing a
    prescription does NOT put it in front of the pharmacist by itself;
    the patient has to opt in via the portal (or have front desk record
    that choice for them) first. Without this filter every prescription
    ever written would show up here the moment it's saved, regardless of
    whether the patient even intends to fill it at this pharmacy.

    Deliberately not reusing opd.PrescriptionDetailView — that's shaped for
    the doctor/clinical view (IsTenantStaff, bare ids), not the pharmacist
    screen, which needs patient/doctor names resolved and per-item
    dispensed quantity.
    """
    permission_classes = [IsAuthenticated, IsPharmacist, RequireFeature("feat_pharmacy")]

    def get(self, request):
        from django.db.models import Sum
        from apps.opd.models import Prescription
        from apps.patients.models import Patient
        from apps.org.models import StaffUser

        db = request.tenant_db
        status_filter = request.query_params.get("status", Prescription.STATUS_ACTIVE)
        qs = (Prescription.objects.using(db)
              .filter(status=status_filter, patient_choice=Prescription.CHOICE_IN_HOUSE)
              .prefetch_related("items")
              .order_by("-created_at"))
        page_items, meta = paginate_queryset(request, qs)

        # Batch-resolve patient/doctor names in two queries instead of one
        # each per row. patient_id/doctor_user_id are UUIDs on Prescription
        # (patient_id mirrors Patient.uuid; doctor_user_id is the StaffUser
        # pk wrapped via uuid.UUID(int=staff_id) — see
        # apps.opd.views._resolve_doctor_consultation_fee for the same
        # unwrap trick applied there).
        patient_uuids = {p.patient_id for p in page_items}
        doctor_pks = {(d.int if hasattr(d, "int") else d) for d in {p.doctor_user_id for p in page_items}}
        patients = {p.uuid: p for p in Patient.objects.using(db).filter(uuid__in=patient_uuids)}
        doctors  = {d.id: d for d in StaffUser.objects.using(db).filter(pk__in=doctor_pks)}

        # Per-item dispensed quantity, in one query for the whole page.
        item_ids = [it.id for p in page_items for it in p.items.all()]
        dispensed_by_item = {}
        for row in (Dispense.objects.using(db).filter(prescription_item_id__in=item_ids)
                    .values("prescription_item_id")
                    .annotate(total=Sum("quantity"))):
            dispensed_by_item[row["prescription_item_id"]] = row["total"]

        results = []
        for rx in page_items:
            patient = patients.get(rx.patient_id)
            doctor_pk = rx.doctor_user_id.int if hasattr(rx.doctor_user_id, "int") else rx.doctor_user_id
            doctor = doctors.get(doctor_pk)
            results.append({
                # rx_number: the real NNTM-generated token (e.g. "RX-000123")
                # patients can quote at the counter — previously this was
                # just the first 8 chars of the internal UUID, which was
                # never shown to the patient anywhere and wasn't a real
                # sequential/quotable reference. Falls back to the old
                # truncated-UUID form only for pre-existing rows that
                # predate the rx_number field.
                "id": str(rx.id), "rx_number": rx.rx_number or str(rx.id)[:8].upper(), "status": rx.status,
                "patient_choice": rx.patient_choice, "payment_status": rx.payment_status,
                "notes": rx.notes, "finalized_at": rx.created_at, "created_at": rx.created_at,
                "patient_id": str(patient.id) if patient else None,
                "patient": str(patient.id) if patient else None,
                "patient_name": patient.full_name if patient else "",
                "patient_uhid": patient.uhid if patient else "",
                "doctor_name": (f"{doctor.first_name} {doctor.last_name}".strip() or doctor.email or "") if doctor else "",
                "items": [{
                    "id": str(it.id), "drug": it.drug_id, "drug_name": it.drug_name,
                    "dose": it.dosage, "unit": "", "frequency": it.frequency,
                    "route": it.route, "duration_days": it.duration_days,
                    "instructions": it.instructions,
                    "dispensed_qty": dispensed_by_item.get(it.id, 0),
                } for it in rx.items.all()],
            })

        return success(data={"results": results, "pagination": meta})


class PrescriptionLookupView(APIView):
    """
    GET /api/v1/pharmacy/prescriptions/lookup/?rx_number=RX-000123
    The counter workflow: a patient walks up and quotes their rx_number
    (shown to them in the portal / on the printed slip). This pulls up the
    full prescription — patient details and items — regardless of status
    filter or pagination, same idea as a lab tech searching by report
    number. Exact match only; rx_number is unique per tenant DB.
    """
    permission_classes = [IsAuthenticated, IsPharmacist, RequireFeature("feat_pharmacy")]

    def get(self, request):
        from apps.opd.models import Prescription
        from apps.patients.models import Patient
        from apps.org.models import StaffUser
        from django.db.models import Sum

        rx_number = (request.query_params.get("rx_number") or "").strip()
        if not rx_number:
            return error("rx_number is required.")

        db = request.tenant_db
        try:
            rx = Prescription.objects.using(db).prefetch_related("items").get(rx_number__iexact=rx_number)
        except Prescription.DoesNotExist:
            return not_found("No prescription found for that number.")

        patient = Patient.objects.using(db).filter(uuid=rx.patient_id).first()
        doctor_pk = rx.doctor_user_id.int if hasattr(rx.doctor_user_id, "int") else rx.doctor_user_id
        doctor = StaffUser.objects.using(db).filter(pk=doctor_pk).first()

        item_ids = [it.id for it in rx.items.all()]
        dispensed_by_item = {
            row["prescription_item_id"]: row["total"]
            for row in (Dispense.objects.using(db).filter(prescription_item_id__in=item_ids)
                        .values("prescription_item_id").annotate(total=Sum("quantity")))
        }

        return success(data={
            "id": str(rx.id), "rx_number": rx.rx_number, "status": rx.status,
            "patient_choice": rx.patient_choice, "payment_status": rx.payment_status,
            "notes": rx.notes, "created_at": rx.created_at,
            "patient_id": str(patient.id) if patient else None,
            "patient_name": patient.full_name if patient else "",
            "patient_uhid": patient.uhid if patient else "",
            "patient_phone": patient.mobile if patient else "",
            "doctor_name": (f"{doctor.first_name} {doctor.last_name}".strip() or doctor.email or "") if doctor else "",
            "items": [{
                "id": str(it.id), "drug": it.drug_id, "drug_name": it.drug_name,
                "dose": it.dosage, "unit": "", "frequency": it.frequency,
                "route": it.route, "duration_days": it.duration_days,
                "instructions": it.instructions,
                "dispensed_qty": dispensed_by_item.get(it.id, 0),
            } for it in rx.items.all()],
        })
