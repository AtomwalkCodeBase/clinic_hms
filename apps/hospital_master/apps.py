import logging
import os

from django.apps import AppConfig

logger = logging.getLogger(__name__)


class HospitalMasterConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.hospital_master"
    label = "hospital_master"
    verbose_name = "Hospital master"
    database = "atomwalk"

    def ready(self):
        from django.db.models.signals import post_migrate
        post_migrate.connect(_bootstrap_platform_admin, sender=self)
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
            from apps.hospital_master.services import ensure_hospital_db
            from apps.hospital_master.models import Hospital

            hospitals = Hospital.objects.using("default").filter(is_active=True).values("db_name")
            for row in hospitals:
                db_name = row["db_name"]
                if db_name:
                    ensure_hospital_db(db_name)
        except Exception:
            # Table may not exist yet during first migrate — silently skip
            pass


def _bootstrap_platform_admin(sender, **kwargs):
    """After migrations run, ensure a Django superuser exists for the admin panel."""
    try:
        username = os.environ.get("DJANGO_SUPERUSER_USERNAME", "admin").strip()
        email = os.environ.get("DJANGO_SUPERUSER_EMAIL", "").strip()
        password = os.environ.get("DJANGO_SUPERUSER_PASSWORD", "").strip()

        if not password:
            return  # Not configured — skip silently

        from django.contrib.auth import get_user_model
        User = get_user_model()

        if User.objects.filter(is_superuser=True).exists():
            return  # Already have a superuser

        User.objects.create_superuser(
            username=username,
            email=email,
            password=password,
        )
        logger.info("Platform superuser bootstrapped: %s", username)

    except Exception as e:
        logger.warning("Platform admin bootstrap skipped: %s", e)
