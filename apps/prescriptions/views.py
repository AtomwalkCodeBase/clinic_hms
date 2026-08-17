from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from core.response import success, created, error, not_found
from core.permissions import IsPharmacist, IsHospitalStaff, RequireFeature
from core.utils.nntm import get_next_number
from core.pagination import paginate_queryset
from .serializers import DrugSerializer, DrugFormTypeSerializer
from .models import Drug, DrugFormType


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


class DrugCatalogView(APIView):
    """
    GET  /api/v1/prescriptions/drugs/  — active catalog entries, for the
                                          doctor's prescription dropdown (and
                                          pharmacy's "receive stock" picker).
                                          Pass ?include_inactive=1 (pharmacist
                                          catalog management screen) to also
                                          see deactivated ones. Pass ?page=
                                          (pharmacist's Drug Catalog Setup
                                          list) for a paginated {results,
                                          pagination} shape instead — the
                                          doctor dropdown and stock picker
                                          never pass ?page=, so they keep
                                          getting the plain full list.
    POST /api/v1/prescriptions/drugs/  — pharmacist adds a new drug to the
                                          catalog. Doctors/nurses/etc. only
                                          get read access — the catalog is
                                          pharmacist-maintained by design.
    """
    def get_permissions(self):
        if self.request.method == "POST":
            return [IsAuthenticated(), IsPharmacist(), RequireFeature("feat_pharmacy")()]
        return [IsAuthenticated(), IsHospitalStaff(), RequireFeature("feat_pharmacy")()]

    def get(self, request):
        drugs = Drug.objects.using(request.tenant_db)
        if request.query_params.get("include_inactive") != "1":
            drugs = drugs.filter(is_active=True)

        if "page" in request.query_params:
            page_items, meta = paginate_queryset(request, drugs)
            return success(data={
                "results": DrugSerializer(page_items, many=True).data,
                "pagination": meta,
            })

        return success(data=DrugSerializer(drugs, many=True).data)

    def post(self, request):
        s = DrugSerializer(data=request.data)
        if not s.is_valid():
            return error("Validation error.", errors=s.errors)

        db = request.tenant_db
        validated = dict(s.validated_data)
        # Code is never typed by hand — NNTM assigns it, same as the lab
        # catalog's test codes, so codes stay unique and consistently formatted.
        if not validated.get("drug_code"):
            validated["drug_code"] = self._next_drug_code(request, db)

        drug = Drug.objects.using(db).create(**validated)
        return created(data=DrugSerializer(drug).data, message="Drug added to catalog.")

    def _next_drug_code(self, request, db):
        from apps.org.models import NextNumber, Branch

        branch_id = getattr(request.user, "branch_id", None)
        if not branch_id:
            branch = Branch.objects.using(db).filter(is_active=True).order_by("id").first()
            branch_id = branch.id if branch else None
        if not branch_id:
            return ""

        # Idempotent — covers branches created before "drug" existed as an
        # NNTM entity, so older tenants don't hit a missing-row DoesNotExist.
        NextNumber.objects.using(db).get_or_create(
            branch_id=branch_id, entity="drug",
            defaults={"prefix": "DRG-", "pad_length": 4, "last_number": 0},
        )
        code, _ = get_next_number(branch_id=branch_id, entity="drug", using=db)
        return code


class DrugFormTypeListCreateView(APIView):
    """
    GET  /api/v1/prescriptions/drug-forms/  — active list, for the Drug
                                               Catalog's "Drug Form" dropdown.
                                               Pass ?include_inactive=1 (Drug
                                               Form Setup screen) to also see
                                               deactivated ones.
    POST /api/v1/prescriptions/drug-forms/  — pharmacist adds a new drug
                                               form (e.g. "Suppository").
    """
    def get_permissions(self):
        if self.request.method == "POST":
            return [IsAuthenticated(), IsPharmacist(), RequireFeature("feat_pharmacy")()]
        return [IsAuthenticated(), IsHospitalStaff(), RequireFeature("feat_pharmacy")()]

    def get(self, request):
        forms = DrugFormType.objects.using(request.tenant_db)
        if request.query_params.get("include_inactive") != "1":
            forms = forms.filter(is_active=True)
        return success(data=DrugFormTypeSerializer(forms, many=True).data)

    def post(self, request):
        s = DrugFormTypeSerializer(data=request.data)
        if not s.is_valid():
            return error("Validation error.", errors=s.errors)
        form = DrugFormType.objects.using(request.tenant_db).create(**s.validated_data)
        return created(data=DrugFormTypeSerializer(form).data, message="Drug form added.")


class DrugFormTypeDetailView(APIView):
    """PATCH /api/v1/prescriptions/drug-forms/{id}/ — edit or deactivate a drug form."""
    permission_classes = [IsAuthenticated, IsPharmacist, RequireFeature("feat_pharmacy")]

    def patch(self, request, pk):
        try:
            form = DrugFormType.objects.using(request.tenant_db).get(pk=pk)
        except DrugFormType.DoesNotExist:
            return not_found("Drug form not found.")
        s = DrugFormTypeSerializer(form, data=request.data, partial=True)
        if not s.is_valid():
            return error("Validation error.", errors=s.errors)
        s.save()
        return success(data=DrugFormTypeSerializer(form).data, message="Drug form updated.")


class DrugCatalogDetailView(APIView):
    """PATCH /api/v1/prescriptions/drugs/{id}/ — edit or deactivate a catalog entry."""
    permission_classes = [IsAuthenticated, IsPharmacist, RequireFeature("feat_pharmacy")]

    def patch(self, request, pk):
        try:
            drug = Drug.objects.using(request.tenant_db).get(pk=pk)
        except Drug.DoesNotExist:
            return not_found("Drug not found.")
        s = DrugSerializer(drug, data=request.data, partial=True)
        if not s.is_valid():
            return error("Validation error.", errors=s.errors)
        s.save()
        return success(data=DrugSerializer(drug).data, message="Drug updated.")

# PrescriptionListCreateView / PrescriptionFinalizeView (and the
# Prescription/PrescriptionItem models they served) were retired as dead
# code (HMS-07c-1) — the live doctor-consultation flow has only ever
# written prescriptions to apps.opd.Prescription/PrescriptionItem (see
# apps/opd/views.py PrescriptionCreateView), never to these.
