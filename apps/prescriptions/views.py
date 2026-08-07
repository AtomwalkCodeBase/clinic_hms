from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from core.response import success, created, error, not_found
from core.permissions import IsDoctor, IsPharmacist, IsHospitalStaff
from core.utils.nntm import get_next_number
from core.pagination import paginate_queryset
from .serializers import DrugSerializer, PrescriptionSerializer, PrescriptionItemSerializer
from .models import Drug, Prescription, PrescriptionItem


class DrugSearchView(APIView):
    permission_classes = [IsAuthenticated, IsHospitalStaff]

    def get(self, request):
        q = request.query_params.get("q", "").strip()
        if len(q) < 2:
            return error("Query must be at least 2 characters.")
        drugs = Drug.objects.using(request.tenant_db).filter(
            name__icontains=q, is_active=True
        )[:30]
        return success(data=DrugSerializer(drugs, many=True).data)


class PrescriptionListCreateView(APIView):
    permission_classes = [IsAuthenticated, IsDoctor]

    def get(self, request):
        qs = Prescription.objects.using(request.tenant_db).prefetch_related("items").order_by("-created_at")
        if eid := request.query_params.get("encounter_id"):
            qs = qs.filter(encounter_id=eid)
        page_items, meta = paginate_queryset(request, qs)
        return success(data={
            "results": PrescriptionSerializer(page_items, many=True).data,
            "pagination": meta,
        })

    def post(self, request):
        items_data = request.data.pop("items", [])
        branch_id  = request.data.get("branch_id") or getattr(request, "branch_id", 1)
        rx_number, _ = get_next_number(branch_id=branch_id, entity="RX",
                                       using=request.tenant_db)
        rx = Prescription.objects.using(request.tenant_db).create(
            patient_id=request.data["patient"],
            encounter_id=request.data["encounter"],
            prescribed_by_id=request.user.id,
            rx_number=rx_number,
            notes=request.data.get("notes", ""),
        )
        for item_data in items_data:
            PrescriptionItem.objects.using(request.tenant_db).create(
                prescription=rx, **item_data
            )
        return created(data=PrescriptionSerializer(rx).data)


class PrescriptionFinalizeView(APIView):
    permission_classes = [IsAuthenticated, IsDoctor]

    def post(self, request, pk):
        try:
            rx = Prescription.objects.using(request.tenant_db).get(pk=pk)
        except Prescription.DoesNotExist:
            return not_found("Prescription not found.")
        if rx.status != "draft":
            return error(f"Cannot finalize a prescription in '{rx.status}' status.")
        rx.status       = "finalized"
        rx.finalized_at = timezone.now()
        rx.save(using=request.tenant_db, update_fields=["status", "finalized_at"])
        return success(message="Prescription finalized.")
