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

# Tests call tasks synchronously in-process -- no broker/worker needed, and a
# task's exceptions surface directly in the test instead of failing silently.
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
