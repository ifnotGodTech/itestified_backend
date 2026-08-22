from django.conf import settings
from django.db import models


class MediaExportBrandingConfig(models.Model):
    """The active server-side branding policy for externally shared media.

    There is intentionally one row. ``version`` changes when the branding
    inputs change, allowing old exported files to remain immutable while new
    requests receive the new branding.
    """

    logo_url = models.URLField(blank=True)
    watermark_text = models.CharField(max_length=120, default="From iTestified")
    call_to_action = models.CharField(
        max_length=255,
        default="Get the iTestified app for more inspiring testimonies.",
    )
    end_card_url = models.URLField(blank=True)
    is_enabled = models.BooleanField(default=True)
    version = models.PositiveIntegerField(default=1)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="updated_media_export_branding_configs",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "media export branding configuration"
        verbose_name_plural = "media export branding configuration"

    def save(self, *args, **kwargs):
        if self.pk:
            previous = type(self).objects.filter(pk=self.pk).values(
                "logo_url", "watermark_text", "call_to_action", "end_card_url", "is_enabled"
            ).first()
            if previous and any(previous[field] != getattr(self, field) for field in previous):
                self.version = self.version + 1
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"MediaExportBrandingConfig<v{self.version}>"


class BrandedVideoExportStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    PROCESSING = "processing", "Processing"
    DONE = "done", "Done"
    FAILED = "failed", "Failed"


class BrandedVideoExport(models.Model):
    testimony = models.ForeignKey(
        "testimonies.Testimony",
        on_delete=models.CASCADE,
        related_name="branded_exports",
    )
    branding_version = models.PositiveIntegerField()
    source_video_url = models.URLField(max_length=2048)
    branded_video_url = models.URLField(max_length=2048, blank=True)
    status = models.CharField(
        max_length=20,
        choices=BrandedVideoExportStatus.choices,
        default=BrandedVideoExportStatus.PENDING,
    )
    error_message = models.TextField(blank=True)
    retry_count = models.PositiveIntegerField(default=0)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="requested_branded_video_exports",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["testimony", "branding_version"],
                name="uniq_branded_export_testimony_branding",
            ),
        ]
        indexes = [models.Index(fields=["status", "-updated_at"], name="media_export_status_idx")]

    def __str__(self) -> str:
        return f"BrandedVideoExport<{self.testimony_id}:v{self.branding_version}:{self.status}>"
