from django.apps import AppConfig


class HospitalsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.hospitals"
    label = "hospitals"
    verbose_name = "Hospitals"

    def ready(self):
        """
        Auto-register all hospital DBs at startup so they're available everywhere:
        shell, management commands, Celery workers — not just HTTP requests.
        The JWT middleware still handles on-demand registration for any hospital
        added after the process started.
        """
        self._register_hospital_databases()

    @staticmethod
    def _register_hospital_databases():
        try:
            from apps.hospitals.utils import ensure_hospital_db
            from apps.hospitals.models import Hospital

            hospitals = Hospital.objects.using("default").filter(is_active=True).values("db_name")
            for row in hospitals:
                db_name = row["db_name"]
                if db_name:
                    ensure_hospital_db(db_name)
        except Exception:
            # Table may not exist yet during first migrate — silently skip
            pass
