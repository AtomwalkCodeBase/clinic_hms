from django.apps import AppConfig


class HospitalSetupConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.hospital_setup"
    label = "hospital_setup"
    verbose_name = "Hospital set-up"
    database = "hospital"
