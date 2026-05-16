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
