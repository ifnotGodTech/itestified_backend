from django.db import models


class ProfileContentKey(models.TextChoices):
    ABOUT_US = "about_us", "About Us"
    TERMS_OF_USE = "terms_of_use", "Terms of Use"
    PRIVACY_POLICY = "privacy_policy", "Privacy Policy"
