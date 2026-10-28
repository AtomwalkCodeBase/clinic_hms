from django.apps import AppConfig


class HospitalPatientsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.hospital_patients"
    label = "hospital_patients"
    verbose_name = "Hospital patients"
    database = "hospital"

    def ready(self):
        from apps.hospital_patients import hospital_log
        hospital_log.connect(self.apps)
