from django.apps import AppConfig


class PharmacyConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.hospital_master.pharmacy"
    label = "pharmacy"
    verbose_name = "Pharmacy"
    database = "hospital"    # which database the tables of this app live in (read by core/db_router.py)
