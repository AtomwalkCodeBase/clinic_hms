from django.apps import AppConfig


class OpdConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.opd"
    label = "opd"
    verbose_name = "OPD"
    database = "hospital"    # which database the tables of this app live in (read by core/db_router.py)

    def ready(self):
        import apps.opd.patient_signals  # noqa: F401 — registers signal handlers
