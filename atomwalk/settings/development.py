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
