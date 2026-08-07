from .base import *  # noqa

DEBUG = True

ALLOWED_HOSTS = ["*"]

FRONTEND_URL = "http://localhost:3000"  # Vite dev server

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
