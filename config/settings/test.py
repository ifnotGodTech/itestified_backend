from .base import *

SECRET_KEY = "test-secret-key"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

ADMIN_ENTRY_CODE = "ITESTIFIED-ADMIN"
OTP_HINT_IN_RESPONSE = get_bool("OTP_HINT_IN_RESPONSE", True)

# Never let a developer's real .env credentials reach tests: blank every
# external-provider secret so tests exercise the "not configured" path
# unless they opt in with override_settings (and mock the HTTP call).
AGORA_APP_ID = ""
AGORA_APP_CERTIFICATE = ""
AGORA_CUSTOMER_ID = ""
AGORA_CUSTOMER_SECRET = ""
AGORA_RECORDING_STORAGE_BUCKET = ""
AGORA_RECORDING_STORAGE_ACCESS_KEY = ""
AGORA_RECORDING_STORAGE_SECRET_KEY = ""
AGORA_RECORDING_PUBLIC_URL_BASE = ""
EMAIL_PROVIDER = "smtp"  # with the locmem EMAIL_BACKEND above; never Brevo/Resend.

# Tests call tasks synchronously in-process -- no broker/worker needed, and a
# task's exceptions surface directly in the test instead of failing silently.
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
