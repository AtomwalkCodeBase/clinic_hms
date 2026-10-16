from django.apps import AppConfig


class OpdConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.opd"
    label = "opd"
    verbose_name = "OPD"
    database = "hospital"

    def ready(self):
        import apps.opd.patient_signals  # noqa: F401 — registers signal handlers
