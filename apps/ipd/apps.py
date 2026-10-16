from django.apps import AppConfig


class IpdConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.ipd"
    label = "ipd"
    verbose_name = "IPD"
    database = "hospital"    # which database the tables of this app live in (read by core/db_router.py)
