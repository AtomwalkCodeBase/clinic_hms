"""core/db_router.py"""

import threading

_thread_local = threading.local()

def is_atomwalk_app(app_label: str) -> bool:
    """True when the app's tables live in the shared Atomwalk database. Every app of ours says so itself, in its AppConfig"""
    from django.apps import apps
    return getattr(apps.get_app_config(app_label), "database", "atomwalk") == "atomwalk"


def set_hospital_db(db_alias: str | None) -> None:
    """Called by JWTHospitalMiddleware after JWT decode."""
    _thread_local.db_alias = db_alias


def get_hospital_db() -> str:
    """Returns the current thread's hospital DB alias, defaulting to 'default'."""
    return getattr(_thread_local, "db_alias", "default") or "default"


class HospitalDatabaseRouter:
    """A database router that separates atomwalk data from hospital data."""

    # Tables that must always live on "default" even though their model's app
    _DEFAULT_ONLY_TABLES = frozenset({"doc_classify_cache"})

    def _is_atomwalk_model(self, model) -> bool:
        if is_atomwalk_app(model._meta.app_label):
            return True
        return getattr(model._meta, "db_table", "") in self._DEFAULT_ONLY_TABLES

    def db_for_read(self, model, **hints):
        if self._is_atomwalk_model(model):
            return "default"
        return get_hospital_db()

    def db_for_write(self, model, **hints):
        if self._is_atomwalk_model(model):
            return "default"
        return get_hospital_db()

    def allow_relation(self, obj1, obj2, **hints):
        """Allow relations only within the same database."""
        db1 = "default" if is_atomwalk_app(obj1._meta.app_label) else get_hospital_db()
        db2 = "default" if is_atomwalk_app(obj2._meta.app_label) else get_hospital_db()
        return db1 == db2

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        """Atomwalk apps only migrate on "default"."""
        model = hints.get("model")
        if (app_label == "django_cache"
                or (model is not None
                    and getattr(model._meta, "db_table", "") in self._DEFAULT_ONLY_TABLES)):
            return db == "default"
        if is_atomwalk_app(app_label):
            return db == "default"
        return db != "default"