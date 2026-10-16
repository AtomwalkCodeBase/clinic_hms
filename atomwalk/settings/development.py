from .base import *  # noqa
from decouple import config

DEBUG = True

ALLOWED_HOSTS = ["*"]

# Vite dev server. Override via .env (FRONTEND_URL=http://<lan-ip>:3000) when
# testing the consult-pad QR from a phone — the QR encodes this value, and a
# phone can't resolve "localhost".
FRONTEND_URL = config("FRONTEND_URL", default="http://localhost:3000")

# Looser CORS for local dev
CORS_ALLOW_ALL_ORIGINS = True

# The threaded dev server runs every request on a new thread, so a connection kept for CONN_MAX_AGE seconds is left open by
# a thread that is already gone - polling pages (My Reports refreshes every 4 s) then pile up idle connections until Postgres
# refuses new ones ("too many clients"). Close each connection at the end of the request in development.
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
