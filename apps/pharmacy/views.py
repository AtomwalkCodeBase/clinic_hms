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
        page_items, meta = paginate_queryset(request, qs)
        return success(data={
            "results": StockSerializer(page_items, many=True).data,
            "pagination": meta,
        })


class DispenseView(APIView):
    permission_classes = [IsAuthenticated, IsPharmacist, RequireFeature("feat_pharmacy")]

    def post(self, request):
        s = DispenseSerializer(data=request.data)
        if not s.is_valid():
            return error("Validation error.", errors=s.errors)

        stock = s.validated_data["stock"]
        qty   = s.validated_data["quantity"]

        if stock.quantity < qty:
            return error(f"Insufficient stock. Available: {stock.quantity}")

        qty_before = stock.quantity
        stock.quantity -= qty
        stock.save(using=request.tenant_db, update_fields=["quantity"])

        StockTransaction.objects.using(request.tenant_db).create(
            stock=stock,
            txn_type="dispense",
            quantity_change=-qty,
            quantity_before=qty_before,
            quantity_after=stock.quantity,
            reference_type="Dispense",
            recorded_by=request.user,
        )

        dispense = Dispense.objects.using(request.tenant_db).create(
            dispensed_by=request.user, **s.validated_data
        )
        return created(data=DispenseSerializer(dispense).data)
