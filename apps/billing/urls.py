from django.urls import path
from .views import (
    BillingServiceListView, BillingServiceDetailView,
    InvoiceListCreateView, InvoiceDetailView, InvoicePDFView,
    InvoiceItemCreateView, PaymentCreateView, BillingSummaryView, RevenueReportView,
    ServiceCategoryListCreateView, ServiceCategoryDetailView,
    PaymentModeListCreateView, PaymentModeDetailView,
    InvoiceStatusListCreateView, InvoiceStatusDetailView,
)

urlpatterns = [
    path("services/",              BillingServiceListView.as_view(), name="billing-services"),
    path("services/<int:pk>/",     BillingServiceDetailView.as_view(), name="billing-service-detail"),

    path("service-categories/",         ServiceCategoryListCreateView.as_view(), name="billing-service-category-list"),
    path("service-categories/<int:pk>/", ServiceCategoryDetailView.as_view(),    name="billing-service-category-detail"),
    path("payment-modes/",              PaymentModeListCreateView.as_view(),     name="billing-payment-mode-list"),
    path("payment-modes/<int:pk>/",     PaymentModeDetailView.as_view(),         name="billing-payment-mode-detail"),
    path("invoice-statuses/",           InvoiceStatusListCreateView.as_view(),   name="billing-invoice-status-list"),
    path("invoice-statuses/<int:pk>/",  InvoiceStatusDetailView.as_view(),       name="billing-invoice-status-detail"),

    path("invoices/",              InvoiceListCreateView.as_view(),  name="invoice-list"),
    path("invoices/<int:pk>/",     InvoiceDetailView.as_view(),      name="invoice-detail"),
    path("invoices/<int:pk>/pdf/", InvoicePDFView.as_view(),         name="invoice-pdf"),
    path("invoices/<int:pk>/items/", InvoiceItemCreateView.as_view(), name="invoice-item-create"),
    path("payments/",              PaymentCreateView.as_view(),      name="payment-create"),
    path("summary/",               BillingSummaryView.as_view(),     name="billing-summary"),
    path("reports/revenue/",       RevenueReportView.as_view(),      name="billing-revenue-report"),
]
