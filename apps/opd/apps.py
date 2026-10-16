from django.apps import AppConfig


class OpdConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.opd"
    label = "opd"
    verbose_name = "OPD"
    database = "hospital"    # which database the tables of this app live in (read by core/db_router.py)
