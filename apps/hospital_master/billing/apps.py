from django.apps import AppConfig


class BillingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.hospital_master.billing"
    label = "billing"
    verbose_name = "Billing"
    database = "hospital"    # which database the tables of this app live in (read by core/db_router.py)
