from django.conf import settings
from django.db import models

from apps.social_links.choices import SocialPlatform


class SocialLink(models.Model):
    platform = models.CharField(max_length=20, choices=SocialPlatform.choices, unique=True)
    # Blank until an admin sets it -- mirrors AppVersionConfig's "no row"
    # vs "row with a blank field" distinction being meaningless here since
    # the platform set is fixed; blank simply means "not linked yet".
    url = models.URLField(blank=True)
    # Lets an admin temporarily hide a platform (e.g. account paused) without
    # losing the configured URL.
    is_active = models.BooleanField(default=True)
    display_order = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        ordering = ["display_order", "platform"]

    def __str__(self) -> str:
        return f"{self.platform}: {self.url or '(unset)'}"
