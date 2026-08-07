from django.apps import AppConfig


class TenantsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.tenants"
    label = "tenants"
    verbose_name = "Tenants"

    def ready(self):
        """
        Auto-register all tenant DBs at startup so they're available everywhere:
        shell, management commands, Celery workers — not just HTTP requests.
        The JWT middleware still handles on-demand registration for any tenant
        added after the process started.
        """
        self._register_tenant_databases()

    @staticmethod
    def _register_tenant_databases():
        try:
            from django.conf import settings
            from apps.tenants.utils import _make_db_config
            from apps.tenants.models import Tenant

            tenants = Tenant.objects.using("default").filter(is_active=True).values("db_name")
            for row in tenants:
                db_name = row["db_name"]
                if db_name and db_name not in settings.DATABASES:
                    settings.DATABASES[db_name] = _make_db_config(db_name)
        except Exception:
            # Table may not exist yet during first migrate — silently skip
            pass
