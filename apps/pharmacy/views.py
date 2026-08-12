from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from core.response import success, created, error
from core.permissions import IsPharmacist, RequireFeature
from core.pagination import paginate_queryset
from .serializers import StockSerializer, StockTransactionSerializer, DispenseSerializer
from .models import Stock, StockTransaction, Dispense


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
        from apps.prescriptions.models import Prescription, PrescriptionItem
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
            Prescription.objects.using(db).filter(pk=prescription_id).update(status="dispensed")

        return created(data=DispenseSerializer(dispense).data)


class PendingPrescriptionsView(APIView):
    """
    GET /api/v1/pharmacy/prescriptions/
    The pharmacist's working queue — finalized prescriptions (doctor has
    signed off) grouped with their items and how much of each has already
    been dispensed. ?status=dispensed shows completed ones instead.

    Deliberately not reusing prescriptions.PrescriptionListCreateView — that
    endpoint is IsDoctor-only and returns doctor/patient as bare ids with no
    patient/doctor name resolution, which the pharmacist screen needs.
    """
    permission_classes = [IsAuthenticated, IsPharmacist, RequireFeature("feat_pharmacy")]

    def get(self, request):
        from apps.prescriptions.models import Prescription
        from apps.patients.models import Patient
        from apps.org.models import StaffUser

        db = request.tenant_db
        status_filter = request.query_params.get("status", "finalized")
        qs = (Prescription.objects.using(db)
              .filter(status=status_filter)
              .prefetch_related("items")
              .order_by("-finalized_at", "-created_at"))
        page_items, meta = paginate_queryset(request, qs)

        # Batch-resolve patient/doctor names in two queries instead of one
        # each per row.
        patient_ids = {p.patient_id for p in page_items}
        doctor_ids  = {p.prescribed_by_id for p in page_items}
        patients = {p.id: p for p in Patient.objects.using(db).filter(pk__in=patient_ids)}
        doctors  = {d.id: d for d in StaffUser.objects.using(db).filter(pk__in=doctor_ids)}

        # Per-item dispensed quantity, in one query for the whole page.
        item_ids = [it.id for p in page_items for it in p.items.all()]
        dispensed_by_item = {}
        for row in (Dispense.objects.using(db).filter(prescription_item_id__in=item_ids)
                    .values("prescription_item_id")
                    .annotate(total=__import__("django.db.models", fromlist=["Sum"]).Sum("quantity"))):
            dispensed_by_item[row["prescription_item_id"]] = row["total"]

        results = []
        for rx in page_items:
            patient = patients.get(rx.patient_id)
            doctor  = doctors.get(rx.prescribed_by_id)
            results.append({
                "id": rx.id, "rx_number": rx.rx_number, "status": rx.status,
                "notes": rx.notes, "finalized_at": rx.finalized_at, "created_at": rx.created_at,
                "patient_id": rx.patient_id,
                "patient": rx.patient_id,
                "patient_name": patient.full_name if patient else "",
                "patient_uhid": patient.uhid if patient else "",
                "doctor_name": (f"{doctor.first_name} {doctor.last_name}".strip() or doctor.email or "") if doctor else "",
                "items": [{
                    "id": it.id, "drug": it.drug_id, "drug_name": it.drug_name,
                    "dose": it.dose, "unit": it.unit, "frequency": it.frequency,
                    "route": it.route, "duration_days": it.duration_days,
                    "instructions": it.instructions,
                    "dispensed_qty": dispensed_by_item.get(it.id, 0),
                } for it in rx.items.all()],
            })

        return success(data={"results": results, "pagination": meta})
