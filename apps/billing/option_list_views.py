"""
apps/billing/option_list_views.py
---------------------------------
Generic CRUD views over billing.OptionList (the merged configurable-dropdown table).
Shared by billing (service categories, payment modes, invoice statuses, room types),
ipd (admission types/sources) and opd (appointment types) — each subclass just points
at its own list_type / serializer.
"""

from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from core.permissions import IsHospitalAdmin, IsHospitalStaff
from core.response import created, error, not_found, success

from .models import OptionList


# ── Configurable dropdown lists ──────────────────────────────────────────────
# Replace what used to be hardcoded `choices=` lists on BillingService.category,
# Payment.payment_mode, and Invoice.status — plus apps.prescriptions.DrugFormType
# for drug forms. v7: these four used to be four near-identical tables; now
# they're one OptionList table with a list_type discriminator, so the CRUD
# logic lives once in these base classes — each subclass just points at its
# own list_type/serializer.

class DropdownListCreateView(APIView):
    list_type = None
    serializer_class = None
    identity_field = "label"  # request JSON key that must be unique / can't change on a system row
    model_field = "label"     # the OptionList column identity_field actually maps to

    def get_permissions(self):
        if self.request.method == "GET":
            return [IsAuthenticated(), IsHospitalStaff()]
        return [IsAuthenticated(), IsHospitalAdmin()]

    def get(self, request):
        qs = OptionList.objects.using(request.tenant_db).filter(list_type=self.list_type)
        # ?all=1 — used by the hospital-admin Billing Setup screen so it can
        # render a toggle for entries that are currently switched off (the
        # normal is_active=True filter below is what every other caller,
        # e.g. the front-desk "record a payment" dropdown, should keep
        # seeing — an admin-only escape hatch, not a behavior change).
        if request.query_params.get("all") == "1":
            from core.permissions import IsHospitalAdmin as _IsHospitalAdmin
            if not _IsHospitalAdmin().has_permission(request, self):
                return error("Only hospital admins can view inactive entries.", status=403)
        else:
            qs = qs.filter(is_active=True)
        return success(data=self.serializer_class(qs, many=True).data)

    def post(self, request):
        s = self.serializer_class(data=request.data)
        if not s.is_valid():
            return error("Validation error.", errors=s.errors)
        data = dict(s.validated_data)
        # For the three list types with no distinct "value" concept
        # (service_category, payment_mode, drug_form), value mirrors label —
        # only invoice_status's serializer supplies "value" explicitly.
        if "value" not in data:
            data["value"] = data.get("label", "")
        lookup = {self.model_field: data.get(self.model_field), "list_type": self.list_type}
        if OptionList.objects.using(request.tenant_db).filter(**lookup).exists():
            return error("This value already exists.", errors={self.identity_field: "Already in use."})
        obj = OptionList(is_system=False, list_type=self.list_type, **data)
        obj.save(using=request.tenant_db)
        return created(data=self.serializer_class(obj).data, message="Added.")


class DropdownDetailView(APIView):
    permission_classes = [IsAuthenticated, IsHospitalAdmin]
    list_type = None
    serializer_class = None
    identity_field = "label"
    model_field = "label"
    # InvoiceStatusOption's system rows have real backend logic tied to
    # their stored value (see PaymentCreateView / InvoiceItemCreateView) —
    # deactivating "paid", say, would break invoice state transitions, so
    # those stay locked. PaymentModeOption has no such coupling (a payment
    # mode is just a label a staff member picks), so it opts back in below —
    # a hospital genuinely may not want to offer "Credit" or "Online".
    system_can_deactivate = False

    def _get(self, request, pk):
        try:
            return OptionList.objects.using(request.tenant_db).get(pk=pk, list_type=self.list_type)
        except OptionList.DoesNotExist:
            return None

    def patch(self, request, pk):
        obj = self._get(request, pk)
        if not obj:
            return not_found("Not found.")
        if obj.is_system and self.identity_field in request.data \
                and request.data[self.identity_field] != getattr(obj, self.model_field):
            return error(f"This is a system value — its {self.identity_field} can't be changed, only its label/active state.")
        if obj.is_system and request.data.get("is_active") is False and not self.system_can_deactivate:
            return error("System values can't be deactivated — the backend relies on them.")
        s = self.serializer_class(obj, data=request.data, partial=True)
        if not s.is_valid():
            return error("Validation error.", errors=s.errors)
        for attr, val in s.validated_data.items():
            setattr(obj, attr, val)
        # Keep value in sync with label for the three list types that have
        # no independent "value" concept — only invoice_status's value and
        # label are allowed to diverge (and its value is separately locked
        # above via the is_system check when model_field == "value").
        if self.model_field == "label" and "label" in s.validated_data:
            obj.value = s.validated_data["label"]
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
