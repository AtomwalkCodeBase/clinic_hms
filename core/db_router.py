"""
core/db_router.py
-----------------
HospitalDatabaseRouter — routes every ORM query to the correct database.

Database alias convention (configured in settings.DATABASES):
  "default"       → Atomwalk DB (shared: patient, hospital, subscription, shared_* HIE tables)
  "<db_name>"     → Per-hospital PostgreSQL DB (e.g. "apollo_delhi", "max_mumbai")

The hospital's db_name is injected into the request by JWTHospitalMiddleware and
stored on the thread-local _thread_local.db_alias.

Rules:
  1. Atomwalk models → always "default"
  2. All other models → thread-local hospital alias or "default" as fallback

Each app declares its database in its AppConfig. Any model belonging to an Atomwalk app
goes to "default". Everything else goes to the current hospital DB.
"""

import threading

_thread_local = threading.local()

def is_atomwalk_app(app_label: str) -> bool:
    """
    True when the app's tables live in the shared Atomwalk database. Every app of ours says so itself, in its AppConfig
    (`database = "atomwalk"` or `"hospital"`); an app that says nothing (Django's own auth, sessions, admin, content types and
    the Celery beat tables) lives in Atomwalk.
    """
    from django.apps import apps
    return getattr(apps.get_app_config(app_label), "database", "atomwalk") == "atomwalk"


def set_hospital_db(db_alias: str | None) -> None:
    """
    Called by JWTHospitalMiddleware after JWT decode.
    Sets the DB alias for the current thread.
    """
    _thread_local.db_alias = db_alias


def get_hospital_db() -> str:
    """Returns the current thread's hospital DB alias, defaulting to 'default'."""
    return getattr(_thread_local, "db_alias", "default") or "default"


class HospitalDatabaseRouter:
    """
    A database router that separates atomwalk data from hospital data.
    Register in settings.py:
        DATABASE_ROUTERS = ["core.db_router.HospitalDatabaseRouter"]
    """

    # Tables that must always live on "default" even though their model's app
    # isn't a atomwalk app — e.g. the DatabaseCache backend's dynamic model.
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
        """
        Allow relations only within the same database.
        Cross-DB relations (atomwalk ↔ hospital) are intentionally prohibited
        at the ORM level — use IDs and separate queries instead.
        """
        db1 = "default" if is_atomwalk_app(obj1._meta.app_label) else get_hospital_db()
        db2 = "default" if is_atomwalk_app(obj2._meta.app_label) else get_hospital_db()
        return db1 == db2

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        """
        Atomwalk apps only migrate on "default".
        Hospital apps only migrate on non-default aliases.
        The DatabaseCache table (createcachetable) lives on "default".
        """
        model = hints.get("model")
        if (app_label == "django_cache"
                or (model is not None
                    and getattr(model._meta, "db_table", "") in self._DEFAULT_ONLY_TABLES)):
            return db == "default"
        if is_atomwalk_app(app_label):
            return db == "default"
        return db != "default"