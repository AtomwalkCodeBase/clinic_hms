from django.apps import AppConfig


class ComplianceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.hospital_master.compliance"
    label = "compliance"
    verbose_name = "Compliance"
    database = "hospital"    # which database the tables of this app live in (read by core/db_router.py)
