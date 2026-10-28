from django.urls import path
from core.api.permissions import in_module
from apps.billing.views import (
    BillingServiceListView,
    BillingServiceDetailView,
    BillingServiceUploadView,
    InvoiceListCreateView,
    InvoiceDetailView,
    InvoicePDFView,
    InvoiceItemCreateView,
    PaymentCreateView,
    BillingSummaryView,
    RevenueReportView,
    ServiceCategoryListCreateView,
    ServiceCategoryDetailView,
    PaymentModeListCreateView,
    PaymentModeDetailView,
    InvoiceStatusListCreateView,
    InvoiceStatusDetailView,
    RoomTypeListCreateView,
    RoomTypeDetailView,
)

urlpatterns = [
    path("services/",              in_module(BillingServiceListView, "billing").as_view(), name="billing-services"),
    path("services/upload/",       in_module(BillingServiceUploadView, "billing").as_view(), name="billing-service-upload"),
    path("services/<int:pk>/",     in_module(BillingServiceDetailView, "billing").as_view(), name="billing-service-detail"),

    path("service-categories/",         in_module(ServiceCategoryListCreateView, "billing").as_view(), name="billing-service-category-list"),
    path("service-categories/<int:pk>/", in_module(ServiceCategoryDetailView, "billing").as_view(),    name="billing-service-category-detail"),
    path("payment-modes/",              in_module(PaymentModeListCreateView, "billing").as_view(),     name="billing-payment-mode-list"),
    path("payment-modes/<int:pk>/",     in_module(PaymentModeDetailView, "billing").as_view(),         name="billing-payment-mode-detail"),
    path("invoice-statuses/",           in_module(InvoiceStatusListCreateView, "billing").as_view(),   name="billing-invoice-status-list"),
    path("invoice-statuses/<int:pk>/",  in_module(InvoiceStatusDetailView, "billing").as_view(),       name="billing-invoice-status-detail"),
    # room-types/ now also carries what used to be the separate ward-types/
    path("room-types/",                 in_module(RoomTypeListCreateView, "billing").as_view(),        name="billing-room-type-list"),
    path("room-types/<int:pk>/",        in_module(RoomTypeDetailView, "billing").as_view(),            name="billing-room-type-detail"),

    path("invoices/",              in_module(InvoiceListCreateView, "billing").as_view(),  name="invoice-list"),
    path("invoices/<int:pk>/",     in_module(InvoiceDetailView, "billing").as_view(),      name="invoice-detail"),
    path("invoices/<int:pk>/pdf/", in_module(InvoicePDFView, "billing").as_view(),         name="invoice-pdf"),
    path("invoices/<int:pk>/items/", in_module(InvoiceItemCreateView, "billing").as_view(), name="invoice-item-create"),
    path("payments/",              in_module(PaymentCreateView, "billing").as_view(),      name="payment-create"),
    path("summary/",               in_module(BillingSummaryView, "billing", "reports").as_view(),     name="billing-summary"),
    path("reports/revenue/",       in_module(RevenueReportView, "billing", "reports").as_view(),      name="billing-revenue-report"),
]
