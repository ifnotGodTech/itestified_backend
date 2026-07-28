from django.conf import settings
from django.db import models

from apps.profile_content.choices import ProfileContentKey


class ProfileContentBlock(models.Model):
    """A single long-text block shown on a static profile screen (About Us,
    Terms of Use, Privacy Policy). The key set is fixed -- these are not
    admin-creatable documents, just editable text for three known screens."""

    key = models.CharField(max_length=30, choices=ProfileContentKey.choices, unique=True)
    body = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    def __str__(self) -> str:
        return self.key
