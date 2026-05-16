import os

from .base import *

DEBUG = True
SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "itestified"),
        "USER": os.environ.get("POSTGRES_USER", "itestified"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "itestified"),
        "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
    }
}

EMAIL_BACKEND = os.environ.get("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
ADMIN_ENTRY_CODE = os.environ.get("ADMIN_ENTRY_CODE", "ITESTIFIED-ADMIN")
OTP_HINT_IN_RESPONSE = get_bool("OTP_HINT_IN_RESPONSE", True)
