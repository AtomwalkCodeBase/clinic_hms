from django.apps import AppConfig


class PrescriptionsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.prescriptions"

    # ready()'s signal-registration hook was removed along with
    # Prescription/PrescriptionItem (HMS-07c-1) — see signals.py.
