"""
Base settings for Atomwalk Healthcare Platform.

Architecture:
  - 'default' DB  → Registry DB (shared: tenants, users, subscriptions)
  - Tenant DBs    → one PostgreSQL DB per hospital, resolved at request time
                    via TenantDatabaseRouter using thread-local context
"""

import os
from pathlib import Path
from datetime import timedelta
from decouple import config

BASE_DIR = Path(__file__).resolve().parent.parent.parent

DEBUG = config("DEBUG", default=False, cast=bool)

# SECRET_KEY / ALLOWED_HOSTS: the old hardcoded/"*" fallbacks meant a missing
# .env would silently boot an insecure server instead of failing loudly. Now
# that's only tolerated in DEBUG (local dev); anywhere DEBUG=False, both are
# required and the process refuses to start without them.
if DEBUG:
    SECRET_KEY = config("SECRET_KEY", default="dev-only-insecure-secret-key")
    ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="*").split(",")
else:
    SECRET_KEY = config("SECRET_KEY")           # raises if unset — no insecure fallback in prod
    ALLOWED_HOSTS = config("ALLOWED_HOSTS").split(",")  # raises if unset — no wildcard in prod

FRONTEND_URL = config("FRONTEND_URL", default="http://localhost:3000")

# JWT_SIGNING_KEY: deliberately separate from SECRET_KEY. SECRET_KEY also
# backs Django's own session cookies, CSRF tokens, and password-reset token
# hashing — sharing it with the auth JWTs (used for every API request via
# core/middleware.py + apps/auth_app/views.py's jwt.encode/decode calls)
# means a leak of either compromises both, and neither can be rotated
# independently. Falls back to SECRET_KEY only in DEBUG so local dev doesn't
# need a second env var; production must set it explicitly.
if DEBUG:
    JWT_SIGNING_KEY = config("JWT_SIGNING_KEY", default=SECRET_KEY)
else:
    JWT_SIGNING_KEY = config("JWT_SIGNING_KEY")  # raises if unset — no fallback to SECRET_KEY in prod

# Django's default (2.5MB) is too small for base64-encoded document uploads
# (patient-attached lab reports / scans as data URIs run larger than raw
# binary). Raised to comfortably fit a few-MB PDF/photo; the view layer adds
# its own explicit size guard on top of this so oversized uploads still get
# a clean validation error instead of a hard 400 from Django itself.
DATA_UPLOAD_MAX_MEMORY_SIZE = config("DATA_UPLOAD_MAX_MEMORY_SIZE", default=10 * 1024 * 1024, cast=int)

# ── Installed Apps ──────────────────────────────────────────────────────────
DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "rest_framework_simplejwt",
    "corsheaders",
    "django_filters",
    "drf_spectacular",
]

LOCAL_APPS = [
    # Registry DB apps (live in 'default' DB)
    "apps.tenants",
    "apps.registry",
    # Per-tenant apps
    "apps.auth_app",
    "apps.org",
    "apps.patients",
    "apps.opd",
    # apps.scheduling removed — duplicate of apps.opd's Appointment/queue models,
    # confirmed zero external references before deletion.
    "apps.clinical",
    "apps.prescriptions",
    "apps.lab",
    "apps.billing",
    "apps.pharmacy",
    "apps.ai_pipeline",
    "apps.notifications",
    "apps.compliance",
    "apps.tasks",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# ── Middleware ───────────────────────────────────────────────────────────────
MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    # Serves STATIC_ROOT directly from the app process (compressed +
    # cache-busted via manifest hashing) — with DEBUG=False Django doesn't
    # serve static files itself, and nothing else was configured to. Fine at
    # this app's scale; swap for S3+CloudFront later if static traffic
    # volume ever justifies it. Must sit right after SecurityMiddleware.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # Atomwalk: JWT decode + tenant DB routing (must be after Django's auth middleware)
    "core.middleware.JWTTenantMiddleware",
]

ROOT_URLCONF = "atomwalk.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "atomwalk.wsgi.application"
ASGI_APPLICATION = "atomwalk.asgi.application"

# ── Databases ────────────────────────────────────────────────────────────────
# 'default' is always the Registry DB.
# Tenant DBs are added dynamically at runtime via TenantDatabaseRouter.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": config("REGISTRY_DB_NAME", default="atomwalk_registry"),
        "USER": config("REGISTRY_DB_USER", default="postgres"),
        "PASSWORD": config("REGISTRY_DB_PASSWORD", default="password"),
        "HOST": config("REGISTRY_DB_HOST", default="localhost"),
        "PORT": config("REGISTRY_DB_PORT", default="5432"),
        "OPTIONS": {"options": "-c search_path=public"},
        "CONN_MAX_AGE": 60,
    }
}

# Tenant DB connection template (populated by TenantDatabaseRouter at runtime)
# Must include all keys Django's DatabaseWrapper accesses directly (not via .get()).
TENANT_DB_CONFIG_TEMPLATE = {
    "ENGINE": "django.db.backends.postgresql",
    "NAME": "",
    "USER": config("TENANT_DB_USER", default="postgres"),
    "PASSWORD": config("TENANT_DB_PASSWORD", default="password"),
    "HOST": config("TENANT_DB_HOST", default="localhost"),
    "PORT": config("TENANT_DB_PORT", default="5432"),
    "CONN_MAX_AGE": 60,
    "TIME_ZONE": None,
    "OPTIONS": {},
    "TEST": {},
    "AUTOCOMMIT": True,
    "ATOMIC_REQUESTS": False,
}

# Custom DB router
DATABASE_ROUTERS = ["core.db_router.TenantDatabaseRouter"]

# ── Password Validation ──────────────────────────────────────────────────────
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ── Internationalisation ─────────────────────────────────────────────────────
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

# ── Static / Media ───────────────────────────────────────────────────────────
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# Compressed + hashed filenames for cache-busting, served by WhiteNoise above.
# manage.py collectstatic must be run on every deploy for this to pick up
# fresh files (see DEPLOYMENT.md).
STORAGES = {
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ── Custom User Model ────────────────────────────────────────────────────────
# Using Django's built-in User for platform admin (Django admin panel).
# Per-tenant staff use apps.org.StaffUser, which extends AbstractUser separately.
# AUTH_USER_MODEL is intentionally NOT overridden — StaffUser is a standalone model.

# ── DRF ─────────────────────────────────────────────────────────────────────
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "core.authentication.JWTTenantAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 25,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    # No rate limiting existed anywhere (including login) before this. Global
    # defaults are a safety net; auth endpoints get a tighter "login" scope
    # via ScopedRateThrottle (see apps/auth_app/views.py).
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
        "rest_framework.throttling.ScopedRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "100/min",
        "user": "300/min",
        "login": "10/min",
    },
}

# ── JWT ──────────────────────────────────────────────────────────────────────
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(
        minutes=config("JWT_ACCESS_TOKEN_LIFETIME_MINUTES", default=60, cast=int)
    ),
    "REFRESH_TOKEN_LIFETIME": timedelta(
        days=config("JWT_REFRESH_TOKEN_LIFETIME_DAYS", default=7, cast=int)
    ),
    "ROTATE_REFRESH_TOKENS": False,
    "UPDATE_LAST_LOGIN": False,
    "ALGORITHM": "HS256",
    "SIGNING_KEY": JWT_SIGNING_KEY,
    "AUTH_HEADER_TYPES": ("Bearer",),
    # Atomwalk uses a custom JWT view (apps/auth_app/views.py) instead of SimpleJWT obtain
}

# ── CORS ─────────────────────────────────────────────────────────────────────
CORS_ALLOWED_ORIGINS = config(
    "CORS_ALLOWED_ORIGINS",
    default="http://localhost:3000,http://localhost:5173",
).split(",")
CORS_ALLOW_CREDENTIALS = True

# ── API Docs (drf-spectacular) ───────────────────────────────────────────────
SPECTACULAR_SETTINGS = {
    "TITLE": "Atomwalk Healthcare Platform API",
    "DESCRIPTION": "Multi-tenant hospital management system — Phase 0 + 1",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
}

# ── Field-level encryption (core/encrypted_fields.py) ───────────────────────
# Not yet applied to any model field — see core/encrypted_fields.py docstring.
# Required once fields start using EncryptedTextField/EncryptedCharField.
FIELD_ENCRYPTION_KEY = config("FIELD_ENCRYPTION_KEY", default="") or None
_fek_fallbacks = config("FIELD_ENCRYPTION_KEY_FALLBACKS", default="")
FIELD_ENCRYPTION_KEY_FALLBACKS = _fek_fallbacks.split(",") if _fek_fallbacks else []

# ── Platform Admin ───────────────────────────────────────────────────────────
PLATFORM_ADMIN_SECRET = config("PLATFORM_ADMIN_SECRET", default="change-this")

# ── License tier constants ───────────────────────────────────────────────────
class LicenseTier:
    TRIAL = "trial"
    ESSENTIAL = "essential"
    OPD_AI = "opd_ai"
    HOSPITAL = "hospital"

LICENSE_TIER = LicenseTier
