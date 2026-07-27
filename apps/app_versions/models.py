from django.conf import settings
from django.db import models

from apps.app_versions.choices import AppPlatform


class AppVersionConfig(models.Model):
    platform = models.CharField(max_length=10, choices=AppPlatform.choices, unique=True)
    minimum_version = models.CharField(max_length=32)
    # Blank until an admin sets it -- distinct from "no latest tracked yet",
    # not the same as "no minimum required" (that's simply no row at all).
    latest_version = models.CharField(max_length=32, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    def __str__(self) -> str:
        return f"{self.platform}: min {self.minimum_version}, latest {self.latest_version or '(unset)'}"
