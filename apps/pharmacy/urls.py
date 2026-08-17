from django.urls import path
from .views import StockListView, DispenseView, PendingPrescriptionsView, PrescriptionLookupView

urlpatterns = [
    path("stock/",              StockListView.as_view(),           name="stock-list"),
    path("dispense/",           DispenseView.as_view(),            name="dispense"),
    path("prescriptions/",      PendingPrescriptionsView.as_view(), name="pharmacy-prescriptions"),
    path("prescriptions/lookup/", PrescriptionLookupView.as_view(), name="pharmacy-prescription-lookup"),
]
