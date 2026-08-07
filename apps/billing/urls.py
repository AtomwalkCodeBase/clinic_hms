from django.urls import path
from .views import (
    BillingServiceListView, InvoiceListCreateView, InvoiceDetailView,
    InvoiceItemCreateView, PaymentCreateView,
)

urlpatterns = [
    path("services/",              BillingServiceListView.as_view(), name="billing-services"),
    path("invoices/",              InvoiceListCreateView.as_view(),  name="invoice-list"),
    path("invoices/<int:pk>/",     InvoiceDetailView.as_view(),      name="invoice-detail"),
    path("invoices/<int:pk>/items/", InvoiceItemCreateView.as_view(), name="invoice-item-create"),
    path("payments/",              PaymentCreateView.as_view(),      name="payment-create"),
]
