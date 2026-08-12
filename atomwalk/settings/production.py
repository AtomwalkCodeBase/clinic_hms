from .base import *  # noqa
from decouple import config

DEBUG = False

# ── Error tracking (optional — only activates if SENTRY_DSN is set) ─────────
SENTRY_DSN = config("SENTRY_DSN", default="")
if SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.django import DjangoIntegration
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[DjangoIntegration()],
        traces_sample_rate=config("SENTRY_TRACES_SAMPLE_RATE", default=0.1, cast=float),
        send_default_pii=False,
        environment=config("ENVIRONMENT", default="production"),
    )

ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="app.atomwalk.com").split(",")

# Any real cloud deployment (AWS ALB, Nginx, Cloudflare, ...) terminates TLS
# at the proxy/load balancer and talks plain HTTP to this app internally.
# Without telling Django which header to trust for "was this HTTPS?", every
# request looks insecure to Django, and SECURE_SSL_REDIRECT below causes an
# infinite redirect loop the instant this goes live behind a real LB — the
# proxy forwards HTTP, Django redirects to HTTPS, the LB terminates that and
# forwards HTTP again. Must match whatever header your specific proxy sets
# (ALB and most others use X-Forwarded-Proto by default).
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

SECURE_SSL_REDIRECT = config("SECURE_SSL_REDIRECT", default=True, cast=bool)
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

# Needed because the frontend SPA is served from a different origin than the
# API (e.g. app.atomwalk.com vs api.atomwalk.com) — only actually exercised
# by session/cookie-based requests (Django admin login), since the API
# itself uses JWT bearer auth and isn't CSRF-protected the same way. Empty
# by default so a misconfigured/missing env var fails safe (no origins
# trusted) rather than accidentally trusting everything.
CSRF_TRUSTED_ORIGINS = [o for o in config("CSRF_TRUSTED_ORIGINS", default="").split(",") if o]

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "()": "pythonjsonlogger.jsonlogger.JsonFormatter",
            "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
        }
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json",
        },
    },
    "root": {"handlers": ["console"], "level": "WARNING"},
    "loggers": {
        "apps": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}
