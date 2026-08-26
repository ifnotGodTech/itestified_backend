import os
from pathlib import Path

from .env import get_bool, get_list, load_env_file

BASE_DIR = Path(__file__).resolve().parents[2]
PROJECT_DIR = BASE_DIR.parent

load_env_file(PROJECT_DIR / ".env")
load_env_file(BASE_DIR / ".env")

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
DEBUG = False
ALLOWED_HOSTS = get_list("DJANGO_ALLOWED_HOSTS", ["localhost", "127.0.0.1"])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework.authtoken",
    "apps.common",
    "apps.users",
    "apps.authn",
    "apps.testimonies",
    "apps.donations",
    "apps.subscriptions",
    "apps.creators",
    "apps.notifications",
    "apps.content",
    "apps.app_versions",
    "apps.social_links",
    "apps.profile_content",
    "apps.media_exports",
    "apps.referrals",
    "apps.live_broadcasts",
    "apps.playlists",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
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

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "users.User"

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
        "rest_framework.authentication.TokenAuthentication",
    ],
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "structured": {
            "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "structured",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
}

SECURE_PROXY_SSL_HEADER = None
USE_X_FORWARDED_HOST = False
CSRF_TRUSTED_ORIGINS = get_list("DJANGO_CSRF_TRUSTED_ORIGINS")

APPEND_SLASH = True

# Security default: never expose OTP hints unless explicitly enabled by env.
OTP_HINT_IN_RESPONSE = get_bool("OTP_HINT_IN_RESPONSE", False)

EMAIL_BACKEND = os.environ.get("EMAIL_BACKEND", "django.core.mail.backends.smtp.EmailBackend")
EMAIL_HOST = os.environ.get("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = get_bool("EMAIL_USE_TLS", True)
EMAIL_USE_SSL = get_bool("EMAIL_USE_SSL", False)
EMAIL_TIMEOUT = int(os.environ.get("EMAIL_TIMEOUT", "10"))
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "iTestified <no-reply@itestified.app>")
SUPPORT_EMAIL = os.environ.get("SUPPORT_EMAIL", "support@itestified.app")
EMAIL_PROVIDER = os.environ.get("EMAIL_PROVIDER", "smtp")
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
RESEND_FROM_EMAIL = os.environ.get("RESEND_FROM_EMAIL", DEFAULT_FROM_EMAIL)
BREVO_API_KEY = os.environ.get("BREVO_API_KEY", "")
BREVO_FROM_EMAIL = os.environ.get("BREVO_FROM_EMAIL", DEFAULT_FROM_EMAIL)

# Raw JSON content of a Firebase service account key (Firebase Console ->
# Project Settings -> Service Accounts -> Generate new private key), used to
# send push notifications via the Admin SDK. Not SMTP/APNs -- this is a
# separate credential from the client-side google-services.json /
# GoogleService-Info.plist already in the mobile app. Left unset until
# provided; push sending fails closed (logged, not raised) until then.
FIREBASE_CREDENTIALS_JSON = os.environ.get("FIREBASE_CREDENTIALS_JSON", "")

GOOGLE_OAUTH_CLIENT_IDS = get_list("GOOGLE_OAUTH_CLIENT_IDS")
GOOGLE_OAUTH_ALLOWED_ISSUERS = get_list(
    "GOOGLE_OAUTH_ALLOWED_ISSUERS",
    ["https://accounts.google.com", "accounts.google.com"],
)

FLUTTERWAVE_PUBLIC_KEY = os.environ.get("FLUTTERWAVE_PUBLIC_KEY", "")
FLUTTERWAVE_SECRET_KEY = os.environ.get("FLUTTERWAVE_SECRET_KEY", "")
FLUTTERWAVE_SECRET_HASH = os.environ.get("FLUTTERWAVE_SECRET_HASH", "")
FLUTTERWAVE_BASE_URL = os.environ.get("FLUTTERWAVE_BASE_URL", "https://api.flutterwave.com")
FLUTTERWAVE_REDIRECT_URL = os.environ.get("FLUTTERWAVE_REDIRECT_URL", "")

# Phase 21: one Flutterwave payment plan per supported currency (a Payment
# Plan is tied to a single currency at creation time on Flutterwave's side,
# so "Premium in USD" needs its own plan id, distinct from the NGN one).
# Created once per currency via `manage.py create_premium_payment_plan
# --currency=NGN` / `--currency=USD` (writes the plan id to stdout); there is
# deliberately no code path that creates these automatically at request
# time, since a plan id is meant to live for the lifetime of the product,
# not get recreated per-deploy. Mirrors Giving's existing NGN/USD choice
# (Phase 5) rather than introducing a new currency-selection pattern.
FLUTTERWAVE_PREMIUM_PLAN_IDS = {
    "NGN": os.environ.get("FLUTTERWAVE_PREMIUM_PLAN_ID_NGN", ""),
    "USD": os.environ.get("FLUTTERWAVE_PREMIUM_PLAN_ID_USD", ""),
}
# Minor currency units (kobo/cents). NGN matches the illustrative price
# already shown on the mobile Plans screen mock and the business blueprint's
# own referral-commission example; USD is an illustrative placeholder
# pending a real pricing decision, same caveat as the NGN figure.
PREMIUM_PLAN_PRICING_MINOR_UNITS = {
    "NGN": 300000,
    "USD": 499,
}

# Phase 27 Slice 4: Agora Live Broadcasting. AGORA_APP_ID/AGORA_APP_CERTIFICATE
# come from the Agora Console project and are used only to sign RTC tokens
# locally (agora-token-builder) -- no network call needed to issue a token.
# AGORA_CUSTOMER_ID/AGORA_CUSTOMER_SECRET are a *separate* credential pair
# Agora issues for its RESTful APIs (Usage API for cost-cap enforcement,
# Channel Management API for Slice 8's kill switch) -- Basic-Auth'd, distinct
# from the App ID/Certificate pair above. All blank by default until a real
# Agora project exists; services/agora.py fails clearly rather than silently
# no-opping when a call is attempted with nothing configured.
AGORA_APP_ID = os.environ.get("AGORA_APP_ID", "")
AGORA_APP_CERTIFICATE = os.environ.get("AGORA_APP_CERTIFICATE", "")
AGORA_CUSTOMER_ID = os.environ.get("AGORA_CUSTOMER_ID", "")
AGORA_CUSTOMER_SECRET = os.environ.get("AGORA_CUSTOMER_SECRET", "")
AGORA_REST_BASE_URL = os.environ.get("AGORA_REST_BASE_URL", "https://api.agora.io")

# Phase 27 Slice 5: Agora Cloud Recording doesn't host files itself -- it
# pushes the finished composite (mix-mode) recording to a third-party
# bucket you configure. VENDOR/REGION are Agora's own numeric codes for
# that bucket (confirm the exact codes for your chosen provider/region
# against Agora's console at setup time -- default below, 1/0, is a
# best-effort AWS S3/first-region guess, not vendor-verified). This is a
# new integration for the app -- everything else here is Cloudinary-only.
# AGORA_RECORDING_PUBLIC_URL_BASE is deliberately separate from the numeric
# codes above: it's the bucket's own known public base URL, used only to
# build a playable link from the filename Agora's query API returns, and
# requires the bucket to serve public-read objects (same "every video URL
# in this app is a plain public HTTPS URL" expectation Cloudinary already
# meets).
AGORA_RECORDING_STORAGE_VENDOR = int(os.environ.get("AGORA_RECORDING_STORAGE_VENDOR", "1"))
AGORA_RECORDING_STORAGE_REGION = int(os.environ.get("AGORA_RECORDING_STORAGE_REGION", "0"))
AGORA_RECORDING_STORAGE_BUCKET = os.environ.get("AGORA_RECORDING_STORAGE_BUCKET", "")
AGORA_RECORDING_STORAGE_ACCESS_KEY = os.environ.get("AGORA_RECORDING_STORAGE_ACCESS_KEY", "")
AGORA_RECORDING_STORAGE_SECRET_KEY = os.environ.get("AGORA_RECORDING_STORAGE_SECRET_KEY", "")
AGORA_RECORDING_PUBLIC_URL_BASE = os.environ.get("AGORA_RECORDING_PUBLIC_URL_BASE", "")

# Phase 22 groundwork: shared Celery/Redis task queue for async work (AI
# transcription/translation now; any future off-request-path job routes
# through the same broker rather than a bespoke polling command per feature).
# REDIS_URL is the single source of truth so Render's managed Redis
# connection string (broker + result backend) only needs setting once;
# CELERY_BROKER_URL/CELERY_RESULT_BACKEND can still override independently
# if a deployment ever needs to split them.
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", REDIS_URL)
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", REDIS_URL)
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TRACK_STARTED = True
# Belt-and-suspenders alongside each task's own retry policy: a worker that
# dies mid-task (deploy, OOM) shouldn't silently drop a transcription job.
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
