from django.db import models


class AppPlatform(models.TextChoices):
    ANDROID = "android", "Android"
    IOS = "ios", "iOS"
