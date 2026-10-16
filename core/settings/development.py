from .base import *  # noqa
from decouple import config

DEBUG = True

ALLOWED_HOSTS = ["*"]

# Vite dev server. Override via .env (FRONTEND_URL=http://<lan-ip>:3000) when
FRONTEND_URL = config("FRONTEND_URL", default="http://localhost:3000")

# Looser CORS for local dev
CORS_ALLOW_ALL_ORIGINS = True

# The threaded dev server runs every request on a new thread, so a connection kept for CONN_MAX_AGE seconds is left open by
DATABASES["default"]["CONN_MAX_AGE"] = 0
HOSPITAL_DB_CONFIG_TEMPLATE["CONN_MAX_AGE"] = 0

# Show SQL queries in shell
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {"class": "logging.StreamHandler"},
    },
    "loggers": {
        "django.db.backends": {
            "handlers": ["console"],
            "level": "DEBUG" if DEBUG else "WARNING",
        },
        "apps": {
            "handlers": ["console"],
            "level": "DEBUG",
            "propagate": False,
        },
    },
}
