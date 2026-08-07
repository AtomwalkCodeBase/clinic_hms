from django.urls import path
from .views import StockListView, DispenseView

urlpatterns = [
    path("stock/",    StockListView.as_view(), name="stock-list"),
    path("dispense/", DispenseView.as_view(),  name="dispense"),
]
