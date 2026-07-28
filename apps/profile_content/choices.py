from django.db import models


class ProfileContentKey(models.TextChoices):
    ABOUT_US = "about_us", "About Us"
    TERMS_OF_USE = "terms_of_use", "Terms of Use"
    PRIVACY_POLICY = "privacy_policy", "Privacy Policy"
    SUPPORT_EMAIL = "support_email", "Support Email"
    SUPPORT_PHONE = "support_phone", "Support Phone"


# Keys whose body is a single-line value (validated below) rather than
# freeform long-form text like About Us/Terms/Privacy.
SINGLE_LINE_KEYS = {ProfileContentKey.SUPPORT_EMAIL, ProfileContentKey.SUPPORT_PHONE}
