from django.apps import AppConfig


class HospitalPatientsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.hospital_master.patients"
    label = "hospital_patients"
    verbose_name = "Patients (hospital)"
    database = "hospital"    # which database the tables of this app live in (read by core/db_router.py)

    def ready(self):
        import apps.hospital_master.patients.signals  # noqa: F401 — registers signal handlers
