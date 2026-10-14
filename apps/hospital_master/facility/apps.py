from django.apps import AppConfig


class FacilityConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.hospital_master.facility"
    label = "facility"
    verbose_name = "Facility"
    database = "hospital"    # which database the tables of this app live in (read by core/db_router.py)
