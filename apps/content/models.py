from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.testimonies.models import Testimony, TestimonyStatus


class InspirationalPictureStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    SCHEDULED = "scheduled", "Scheduled"
    PUBLISHED = "published", "Published"
    UNPUBLISHED = "unpublished", "Unpublished"


class InspirationalPicture(models.Model):
    title = models.CharField(max_length=160)
    caption = models.TextField(blank=True)
    category = models.CharField(max_length=80, blank=True)
    source = models.URLField(blank=True)
    image_url = models.URLField()
    status = models.CharField(
        max_length=20,
        choices=InspirationalPictureStatus.choices,
        default=InspirationalPictureStatus.DRAFT,
    )
    publish_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="inspirational_pictures_created",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="inspirational_pictures_updated",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return f"InspirationalPicture<{self.id}:{self.status}>"


class ScriptureStatus(models.TextChoices):
    SCHEDULED = "scheduled", "Scheduled"
    PUBLISHED = "published", "Published"


class ScriptureOfTheDay(models.Model):
    date = models.DateField(unique=True)
    bible_text = models.CharField(max_length=120)
    scripture = models.TextField()
    prayer = models.TextField(blank=True)
    bible_version = models.CharField(max_length=20, default="KJV")
    status = models.CharField(
        max_length=20,
        choices=ScriptureStatus.choices,
        default=ScriptureStatus.SCHEDULED,
    )
    published_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="scriptures_created",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="scriptures_updated",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date", "-id"]

    def refresh_status_for_today(self) -> None:
        if self.date <= timezone.localdate() and self.status != ScriptureStatus.PUBLISHED:
            self.status = ScriptureStatus.PUBLISHED
            self.published_at = timezone.now()

    def __str__(self) -> str:
        return f"ScriptureOfTheDay<{self.date}:{self.status}>"


class HomeSectionKey(models.TextChoices):
    FEATURED_TESTIMONIES = "featured_testimonies", "Featured Testimonies"
    INSPIRATIONAL_PICTURE = "inspirational_picture", "Inspirational Picture"
    SCRIPTURE = "scripture", "Scripture"


class HomeSectionOrder(models.Model):
    section = models.CharField(max_length=40, choices=HomeSectionKey.choices, unique=True)
    position = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["position", "id"]

    def __str__(self) -> str:
        return f"HomeSectionOrder<{self.section}:{self.position}>"


class FeaturedHomeTestimony(models.Model):
    testimony = models.ForeignKey(
        Testimony,
        on_delete=models.CASCADE,
        related_name="home_featured_entries",
    )
    position = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="home_featured_testimonies_created",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="home_featured_testimonies_updated",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["position", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["testimony"],
                name="uniq_home_featured_testimony",
            ),
        ]

    def clean(self):
        if self.testimony.status != TestimonyStatus.APPROVED:
            raise ValidationError("Only approved testimonies can be featured on home feed.")

    def __str__(self) -> str:
        return f"FeaturedHomeTestimony<{self.testimony_id}:{self.position}>"
