"""Settings for Atomwalk Healthcare Platform: ENVIRONMENT=development (default) or production; manage.py test adds a test database and in-memory storage."""

import os
import sys
from pathlib import Path
from datetime import timedelta
from decouple import config

BASE_DIR = Path(__file__).resolve().parent.parent

ENVIRONMENT = config("ENVIRONMENT", default="development")
PRODUCTION = ENVIRONMENT == "production"
TESTING = sys.argv[1:2] == ["test"]
DEBUG = not PRODUCTION

if DEBUG:
    SECRET_KEY = config("SECRET_KEY", default="dev-only-insecure-secret-key")
    ALLOWED_HOSTS = ["*"]
else:
    SECRET_KEY = config("SECRET_KEY")
    ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="app.atomwalk.com").split(",")

FRONTEND_URL = config("FRONTEND_URL", default="http://localhost:3000")

if DEBUG:
    JWT_SIGNING_KEY = config("JWT_SIGNING_KEY", default=SECRET_KEY)
else:
    JWT_SIGNING_KEY = config("JWT_SIGNING_KEY")

DATA_UPLOAD_MAX_MEMORY_SIZE = config("DATA_UPLOAD_MAX_MEMORY_SIZE", default=20 * 1024 * 1024, cast=int)

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
    "corsheaders",
    "django_filters",
    "drf_spectacular",
    "django_celery_beat",
]

LOCAL_APPS = [
    "apps.patients",
    "apps.documents",
    "apps.hospital_master",
    "apps.hospital_setup",
    "apps.ipd",
    "apps.opd",
    "apps.billing",
    "apps.lab",
    "apps.pharmacy",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "core.utils.logging_context.RequestIdMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "core.api.middleware.JWTHospitalMiddleware",
]

ROOT_URLCONF = "core.urls"

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

WSGI_APPLICATION = "core.wsgi.application"
ASGI_APPLICATION = "core.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": config("ATOMWALK_DB_NAME", default="atomwalk"),
        "USER": config("ATOMWALK_DB_USER", default="postgres"),
        "PASSWORD": config("ATOMWALK_DB_PASSWORD", default="password"),
        "HOST": config("ATOMWALK_DB_HOST", default="localhost"),
        "PORT": config("ATOMWALK_DB_PORT", default="5432"),
        "OPTIONS": {"options": "-c search_path=public"},
        "CONN_MAX_AGE": 60,
    }
}

HOSPITAL_DB_CONFIG_TEMPLATE = {
    "ENGINE": "django.db.backends.postgresql",
    "NAME": "",
    "USER": config("HOSPITAL_DB_USER", default="postgres"),
    "PASSWORD": config("HOSPITAL_DB_PASSWORD", default="password"),
    "HOST": config("HOSPITAL_DB_HOST", default="localhost"),
    "PORT": config("HOSPITAL_DB_PORT", default="5432"),
    "CONN_MAX_AGE": 60,
    "TIME_ZONE": None,
    "OPTIONS": {},
    "TEST": {"MIRROR": None},
    "AUTOCOMMIT": True,
    "ATOMIC_REQUESTS": False,
}

DATABASE_ROUTERS = ["core.db_router.HospitalDatabaseRouter"]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'static/')

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
CORS_ORIGIN_ALLOW_ALL = True

STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

LOCAL_OR_AWS_S3_MEDIA = 'S3'
if LOCAL_OR_AWS_S3_MEDIA == "S3":
    AWS_ACCESS_KEY_ID = config("AWS_ACCESS_KEY_ID", default="")
    AWS_SECRET_ACCESS_KEY = config("AWS_SECRET_ACCESS_KEY", default="")
    AWS_STORAGE_BUCKET_NAME = config("AWS_S3_BUCKET", default="")
    AWS_S3_FILE_OVERWRITE = False
    AWS_DEFAULT_ACL = None
    DEFAULT_FILE_STORAGE = 'core.storage_backend.mediaStorage'
    AWS_S3_REGION_NAME = config("AWS_S3_REGION", default="ap-south-1")
    AWS_S3_SIGNATURE_VERSION = "s3v4"
    AWS_S3_URL_EXPIRY = config("AWS_S3_URL_EXPIRY", default=3600, cast=int)
    AWS_S3_OBJECT_PARAMETERS = {
        'CacheControl': 'max-age=86400',
    }
else:
    AWS_ACCESS_KEY_ID = ""
    AWS_SECRET_ACCESS_KEY = ""
    AWS_STORAGE_BUCKET_NAME = ""
    AWS_S3_REGION_NAME = ""
    AWS_S3_URL_EXPIRY = 3600
    MEDIA_URL = '/media/'
    MEDIA_ROOT = os.path.join(BASE_DIR, 'media/')

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "core.api.authentication.JWTHospitalAuthentication",
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
    "EXCEPTION_HANDLER": "core.api.exceptions.custom_exception_handler",
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
        "rest_framework.throttling.ScopedRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "100/min",
        "user": "300/min",
        "login": "10/min",
        "otp": "6/min",
        "emergency": "20/min",
        "consult_pad": "20/min",
        "records_share": "90/min",
        "view_report": "20/min",
        "preview": "600/min",
    },
}

JWT_ACCESS_TOKEN_LIFETIME = timedelta(
    minutes=config("JWT_ACCESS_TOKEN_LIFETIME_MINUTES", default=60, cast=int)
)
JWT_REFRESH_TOKEN_LIFETIME = timedelta(
    days=config("JWT_REFRESH_TOKEN_LIFETIME_DAYS", default=7, cast=int)
)

from corsheaders.defaults import default_headers as _cors_default_headers

CORS_ALLOWED_ORIGINS = config(
    "CORS_ALLOWED_ORIGINS",
    default="http://localhost:3000,http://localhost:5173",
).split(",")
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_HEADERS = (*_cors_default_headers, "x-share-device")

SPECTACULAR_SETTINGS = {
    "TITLE": "Atomwalk Healthcare Platform API",
    "DESCRIPTION": "Multi-hospital hospital management system API",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
}

if DEBUG:
    EMAIL_BACKEND = config("EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend")
else:
    EMAIL_BACKEND = config("EMAIL_BACKEND", default="django.core.mail.backends.smtp.EmailBackend")
EMAIL_HOST          = config("EMAIL_HOST", default="")
EMAIL_PORT          = config("EMAIL_PORT", default=587, cast=int)
EMAIL_HOST_USER     = config("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = config("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS       = config("EMAIL_USE_TLS", default=True, cast=bool)
DEFAULT_FROM_EMAIL  = config("DEFAULT_FROM_EMAIL", default="Atomwalk HMS <no-reply@atomwalk.local>")

SMS_BACKEND = config("SMS_BACKEND", default="log")
MSG91_AUTH_KEY     = config("MSG91_AUTH_KEY", default="")
MSG91_TEMPLATE_ID  = config("MSG91_TEMPLATE_ID", default="")
MSG91_OTP_VAR_NAME = config("MSG91_OTP_VAR_NAME", default="VAR1")
SMS_GATEWAY_BASE_URL = config("SMS_GATEWAY_BASE_URL", default="")
SMS_GATEWAY_USERNAME = config("SMS_GATEWAY_USERNAME", default="")
SMS_GATEWAY_PASSWORD = config("SMS_GATEWAY_PASSWORD", default="")
SMS_FALLBACK_BACKEND = config("SMS_FALLBACK_BACKEND", default="")

if DEBUG:
    OTP_HASH_PEPPER = config("OTP_HASH_PEPPER", default=JWT_SIGNING_KEY)
else:
    OTP_HASH_PEPPER = config("OTP_HASH_PEPPER")

DOC_QR_SECRET = config("DOC_QR_SECRET", default="") or SECRET_KEY

CONSULT_PAD_LLM_BASE  = config("CONSULT_PAD_LLM_BASE", default="https://api.groq.com/openai/v1")
CONSULT_PAD_LLM_MODEL = config("CONSULT_PAD_LLM_MODEL", default="qwen/qwen3.8-27b")
CONSULT_PAD_LLM_KEY   = config("CONSULT_PAD_LLM_KEY", default="") or config("GROQ_API_KEY", default="")

LLM_API_URL = config("LLM_API_URL", default="https://atomwalk.com/llm_api/ask/")
LLM_API_TOKEN = config("LLM_API_TOKEN", default="")
LLM_API_STYLE = config("LLM_API_STYLE", default="company")
LLM_API_MODEL = config("LLM_API_MODEL", default="")
PEDIATRIC_HEALTH_CONFIG = config("PEDIATRIC_HEALTH_CONFIG", default="") or None

CELERY_BROKER_URL = config("CELERY_BROKER_URL", default="redis://localhost:6379/0")
CELERY_RESULT_BACKEND = config("CELERY_RESULT_BACKEND", default="redis://localhost:6379/0")
CELERY_TASK_ALWAYS_EAGER = config("CELERY_TASK_ALWAYS_EAGER", default=False, cast=bool)
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_WORKER_SEND_TASK_EVENTS = True       # Flower lists tasks from these events
CELERY_TASK_SEND_SENT_EVENT = True
CELERY_TASK_TRACK_STARTED = True
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_BROKER_TRANSPORT_OPTIONS = {"visibility_timeout": 600}
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"

RECORDS_REVIEW_FROM = config("RECORDS_REVIEW_FROM", default="")

CACHES = {
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
}

class LicenseTier:
    TRIAL = "trial"
    ESSENTIAL = "essential"
    OPD_AI = "opd_ai"
    HOSPITAL = "hospital"

LICENSE_TIER = LicenseTier

if PRODUCTION:
    SENTRY_DSN = config("SENTRY_DSN", default="")
    if SENTRY_DSN:
        import sentry_sdk
        from sentry_sdk.integrations.django import DjangoIntegration
        sentry_sdk.init(
            dsn=SENTRY_DSN,
            integrations=[DjangoIntegration()],
            traces_sample_rate=config("SENTRY_TRACES_SAMPLE_RATE", default=0.1, cast=float),
            send_default_pii=False,
            environment=ENVIRONMENT,
        )
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = config("SECURE_SSL_REDIRECT", default=True, cast=bool)
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    CSRF_TRUSTED_ORIGINS = [o for o in config("CSRF_TRUSTED_ORIGINS", default="").split(",") if o]
    LOGGING = {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {"request_context": {"()": "core.utils.logging_context.RequestContextFilter"}},
        "formatters": {
            "json": {
                "()": "pythonjsonlogger.jsonlogger.JsonFormatter",
                "format": "%(asctime)s %(levelname)s %(name)s %(request_id)s %(hospital_id)s %(user_id)s %(message)s",
            }
        },
        "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "json", "filters": ["request_context"]}},
        "root": {"handlers": ["console"], "level": "WARNING"},
        "loggers": {"apps": {"handlers": ["console"], "level": "INFO", "propagate": False}},
    }
else:
    CORS_ALLOW_ALL_ORIGINS = True
    DATABASES["default"]["CONN_MAX_AGE"] = 0
    HOSPITAL_DB_CONFIG_TEMPLATE["CONN_MAX_AGE"] = 0
    LOGGING = {
        "version": 1,
        "disable_existing_loggers": False,
        "handlers": {"console": {"class": "logging.StreamHandler"}},
        "loggers": {
            "django.db.backends": {"handlers": ["console"], "level": "DEBUG" if DEBUG else "WARNING"},
            "apps": {"handlers": ["console"], "level": "DEBUG", "propagate": False},
        },
    }

if TESTING:
    DATABASES["hospital_test"] = {
        **HOSPITAL_DB_CONFIG_TEMPLATE,
        "NAME": "aw_hospital_test",
        "TEST": {"NAME": "test_aw_hospital_test"},
    }
    DEFAULT_FILE_STORAGE = "django.core.files.storage.InMemoryStorage"
