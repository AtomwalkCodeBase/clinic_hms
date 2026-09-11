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
DATA_UPLOAD_MAX_MEMORY_SIZE = config("DATA_UPLOAD_MAX_MEMORY_SIZE", default=20 * 1024 * 1024, cast=int)

# ── Object storage (S3) ──────────────────────────────────────────────────────
# Every user-uploaded file — staff/patient profile photos, hospital logos,
# doctor signatures, lab reports, patient-uploaded documents, vaccination
# certificates — lives in S3, not as base64 in a Postgres TextField (the old
# convention; see core/storage.py's module docstring for the full rationale
# and core/file_validation.py for the magic-byte check every upload still
# goes through before it reaches here).
#
# Bucket must be PRIVATE. Nothing is ever served via a public bucket URL —
# core.storage.signed_url() mints a short-lived presigned URL per request
# instead. This matters because several of these fields hold PHI (lab
# reports, vaccination certificates, discharge summaries).
#
# Left blank by default rather than required-at-boot: unlike SECRET_KEY/
# JWT_SIGNING_KEY, a missing bucket shouldn't crash the whole process on
# startup (most of the app works fine without it) — core.storage raises a
# clear, catchable error only at the point a file is actually uploaded, and
# reads degrade to "no file" instead of a 500.
AWS_S3_BUCKET         = config("AWS_S3_BUCKET", default="")
AWS_S3_REGION         = config("AWS_S3_REGION", default="ap-south-1")
AWS_ACCESS_KEY_ID     = config("AWS_ACCESS_KEY_ID", default="")
AWS_SECRET_ACCESS_KEY = config("AWS_SECRET_ACCESS_KEY", default="")
# How long a presigned URL stays valid, in seconds. Short enough that a
# leaked/cached link (browser history, a forwarded screenshot's link, etc.)
# stops working soon; long enough that a slow page load doesn't race it.
AWS_S3_URL_EXPIRY     = config("AWS_S3_URL_EXPIRY", default=3600, cast=int)

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
    "apps.ipd",  # Phase 1 — admission intake only. See apps/ipd/models.py module docstring.
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
        # OTP request/verify endpoints — tighter than login since these are
        # what a brute-force/SMS-bombing attempt would target. The per-
        # identifier resend cooldown (core.otp.RESEND_COOLDOWN_SECONDS) and
        # per-code attempt cap (core.otp.MAX_VERIFY_ATTEMPTS) are the real
        # defenses; this is a per-IP backstop on top of them.
        "otp": "6/min",
        # Emergency QR summary view (apps/patients/emergency_views.py) — public,
        # unauthenticated, reachable by anyone with the token. The token itself
        # is an unguessable signed JWT and expires in ~20 minutes, so this is a
        # per-IP backstop against scripted enumeration, not the primary defense.
        "emergency": "20/min",
        # Consultation-scratchpad pad (apps/patients/consult_pad_views.py) —
        # public, unauthenticated, reached by scanning a permanent per-patient
        # QR. The 43-char random token is the real gate; this is a per-IP
        # backstop against someone scripting note spam against a leaked code.
        "consult_pad": "20/min",
        # "Records Access" break-glass sharing (apps/patients/records_share_views.py)
        # — public, unauthenticated, token-gated. Higher than the others
        # because the doctor's laptop polls the status endpoint every few
        # seconds while it waits for the patient to approve. The 32-char
        # random token is the real gate; this is a per-IP backstop.
        "records_share": "90/min",
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
from corsheaders.defaults import default_headers as _cors_default_headers

CORS_ALLOWED_ORIGINS = config(
    "CORS_ALLOWED_ORIGINS",
    default="http://localhost:3000,http://localhost:5173",
).split(",")
CORS_ALLOW_CREDENTIALS = True
# "Share Records" doctor pages send the per-browser session token as a custom
# header — must be allow-listed or the browser blocks the request post-preflight.
CORS_ALLOW_HEADERS = (*_cors_default_headers, "x-share-device")

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

# ── Email (core/email.py) ────────────────────────────────────────────────────
# No email transport existed before OTP-based auth needed one. DEBUG defaults
# to Django's console backend (prints to the server log, zero setup, fully
# usable for local dev/demo). Production requires real SMTP credentials —
# same "customer supplies their own account" pattern as the payment gateway
# (see task history) — Atomwalk cannot provision a mail relay on their behalf.
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

# ── SMS (core/sms.py) ────────────────────────────────────────────────────────
# "log" (default) writes the message to the app log instead of sending it —
# there is no SMS gateway account configured for this deployment. Set to
# "msg91" (and MSG91_AUTH_KEY/MSG91_TEMPLATE_ID below) once the hospital has
# its own MSG91 account with a DLT-approved template, or "android_gateway"
# (and SMS_GATEWAY_* below) to relay through a self-hosted phone+SIM instead
# of a paid aggregator.
SMS_BACKEND = config("SMS_BACKEND", default="log")
MSG91_AUTH_KEY     = config("MSG91_AUTH_KEY", default="")
MSG91_TEMPLATE_ID  = config("MSG91_TEMPLATE_ID", default="")
# Must match the variable name used in the DLT-approved template on the
# MSG91 dashboard (commonly "VAR1" for a single-variable template, e.g.
# "Your Atomwalk verification code is ##VAR1##.").
MSG91_OTP_VAR_NAME = config("MSG91_OTP_VAR_NAME", default="VAR1")
# "SMS Gateway for Android" (github.com/capcom6/android-sms-gateway) app
# credentials — shown on the app's Home screen. BASE_URL is the phone's own
# address in Local mode (e.g. "http://192.168.1.50:8080", requires the
# Django server on the same network) or a Private/Cloud server URL.
SMS_GATEWAY_BASE_URL = config("SMS_GATEWAY_BASE_URL", default="")
SMS_GATEWAY_USERNAME = config("SMS_GATEWAY_USERNAME", default="")
SMS_GATEWAY_PASSWORD = config("SMS_GATEWAY_PASSWORD", default="")
# Optional one-hop fallback: tried automatically if SMS_BACKEND's actual
# send attempt fails (not just "unconfigured"). E.g. SMS_BACKEND=
# android_gateway + SMS_FALLBACK_BACKEND=msg91 means a gateway outage
# falls through to MSG91 instead of silently failing. See core/sms.py.
SMS_FALLBACK_BACKEND = config("SMS_FALLBACK_BACKEND", default="")

# ── OTP (core/otp.py) ────────────────────────────────────────────────────────
# Separate from JWT_SIGNING_KEY so it can be rotated independently — falls
# back to JWT_SIGNING_KEY only in DEBUG, same pattern as JWT_SIGNING_KEY's
# own fallback to SECRET_KEY above.
if DEBUG:
    OTP_HASH_PEPPER = config("OTP_HASH_PEPPER", default=JWT_SIGNING_KEY)
else:
    OTP_HASH_PEPPER = config("OTP_HASH_PEPPER")

# ── Platform Admin ───────────────────────────────────────────────────────────
PLATFORM_ADMIN_SECRET = config("PLATFORM_ADMIN_SECRET", default="change-this")

# ── My Reports document QR (core/qr_token.py) ────────────────────────────────
# HMAC secret for the QR codes printed on prescriptions / lab reports.
# RECOMMENDED to set a dedicated value in production: it can then be rotated
# independently of SECRET_KEY (rotating SECRET_KEY would otherwise silently
# invalidate every printed QR, sending re-uploads down the slower OCR path).
# Falls back to SECRET_KEY when unset so a deploy never breaks on a missing
# value — this feature is new, so there are no live QRs to invalidate yet.
DOC_QR_SECRET = config("DOC_QR_SECRET", default="") or SECRET_KEY

# OCR engine for no-QR document classification (core/ocr.py):
#   "auto" (default) — RapidOCR (PaddleOCR's PP-OCR models on ONNX Runtime;
#     pip-only, CPU, no system package) when installed, else Tesseract.
#   "rapidocr" | "paddleocr" | "tesseract" — force one.  "none" — disable OCR.
DOC_OCR_ENGINE = config("DOC_OCR_ENGINE", default="auto")

# Path to the tesseract binary — only used when DOC_OCR_ENGINE falls back to
# Tesseract. Leave blank on Linux where `tesseract` is on PATH (apt install
# tesseract-ocr); set it only if the binary lives somewhere non-standard
# (some Windows dev machines) — core/ocr.py also auto-probes the usual paths.
TESSERACT_CMD = config("TESSERACT_CMD", default="")

# ── Handwriting recognition (consultation scratchpad) ───────────────────────
# The consult-pad QR flow photographs a handwritten SOAP note; a vision model
# transcribes it and splits it into S/O/A/P. Any OpenAI-compatible chat
# endpoint works — OpenAI, Groq, OpenRouter, Together, a local vLLM/Ollama —
# just point BASE + MODEL + KEY at it. A BLANK key is fine: recognition is
# skipped, the handwritten PDF still saves, and the doctor types the note in.
#   OpenAI  : BASE=https://api.openai.com/v1        MODEL=gpt-4o-mini
#   Groq    : BASE=https://api.groq.com/openai/v1   MODEL=meta-llama/llama-4-scout-17b-16e-instruct
#   OpenRouter: BASE=https://openrouter.ai/api/v1   MODEL=google/gemini-2.0-flash-001
CONSULT_PAD_LLM_BASE  = config("CONSULT_PAD_LLM_BASE", default="https://api.groq.com/openai/v1")
CONSULT_PAD_LLM_MODEL = config("CONSULT_PAD_LLM_MODEL", default="qwen/qwen3.8-27b")
# Falls back to GROQ_API_KEY so an existing Groq key already in .env just works.
CONSULT_PAD_LLM_KEY   = config("CONSULT_PAD_LLM_KEY", default="") or config("GROQ_API_KEY", default="")

# ── Document classifier — LLM / vision fallback for the uncertain tail ──────
# The pipeline (core.doc_classifier) runs three layers, cheapest first:
#   1. deterministic keyword pass       — free, instant, handles the bulk
#   2. TEXT LLM on the OCR text          — resolves garbled / sparse text
#   3. VISION LLM on the page image      — resolves bad OCR / odd layouts / disagreement
# Each layer only runs on what the previous one wasn't sure about. Every layer
# is a labeller: kind / panel / date only, NEVER test values. Any layer with a
# blank KEY (and no GROQ_API_KEY) is skipped and the deterministic result +
# review tray stand. A confident keyword verdict is never overridden by an LLM;
# genuine cross-layer disagreement goes to the patient.
DOC_CLASSIFIER_LLM       = config("DOC_CLASSIFIER_LLM", default="core.doc_classifier_llm.classify")
DOC_CLASSIFIER_LLM_BASE  = config("DOC_CLASSIFIER_LLM_BASE", default="https://api.groq.com/openai/v1")
DOC_CLASSIFIER_LLM_MODEL = config("DOC_CLASSIFIER_LLM_MODEL", default="openai/gpt-oss-20b")
DOC_CLASSIFIER_LLM_KEY   = config("DOC_CLASSIFIER_LLM_KEY", default="") or config("GROQ_API_KEY", default="")

# Vision layer — OFF unless a MODEL is set (Groq currently has no VLM; point
# this at a local vLLM/Ollama VLM, or OpenRouter gemini-2.0-flash / gpt-4o).
DOC_CLASSIFIER_VISION_BASE  = config("DOC_CLASSIFIER_VISION_BASE", default="https://api.groq.com/openai/v1")
DOC_CLASSIFIER_VISION_MODEL = config("DOC_CLASSIFIER_VISION_MODEL", default="")
DOC_CLASSIFIER_VISION_KEY   = (config("DOC_CLASSIFIER_VISION_KEY", default="")
                               or config("DOC_CLASSIFIER_LLM_KEY", default="")
                               or config("GROQ_API_KEY", default=""))

# Persistent, worker-shared cache for the classifier's LLM/vision answers —
# a given OCR text (or image) always classifies the same, so we store it once
# and never pay Groq / the VLM again for a re-upload, a backfill, or a retry.
# Needs `manage.py createcachetable` (migration 0032 runs it). The app's other
# uses of the cache framework keep the default local-memory backend.
CACHES = {
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
    "doc_classify": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "doc_classify_cache",
        "TIMEOUT": 60 * 60 * 24 * 60,   # 60 days
        "OPTIONS": {"MAX_ENTRIES": 100_000, "CULL_FREQUENCY": 4},
    },
}

# ── License tier constants ───────────────────────────────────────────────────
class LicenseTier:
    TRIAL = "trial"
    ESSENTIAL = "essential"
    OPD_AI = "opd_ai"
    HOSPITAL = "hospital"

LICENSE_TIER = LicenseTier
