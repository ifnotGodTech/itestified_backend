from django.conf import settings
from django.db import models

from apps.app_versions.choices import AppPlatform


class AppVersionConfig(models.Model):
    platform = models.CharField(max_length=10, choices=AppPlatform.choices, unique=True)
    minimum_version = models.CharField(max_length=32)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    def __str__(self) -> str:
        return f"{self.platform}: min {self.minimum_version}"
