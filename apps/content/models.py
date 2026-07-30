from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.signals import pre_save
from django.dispatch import receiver
from django.utils import timezone
from django.utils.text import slugify

from apps.testimonies.models import Testimony, TestimonyStatus


def normalize_inspirational_picture_category_name(value: str) -> str:
    stripped = value.strip()
    return f"{stripped[:1].upper()}{stripped[1:].lower()}"


class InspirationalPictureCategory(models.Model):
    name = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(max_length=140, unique=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return self.name


@receiver(pre_save, sender=InspirationalPictureCategory)
def ensure_inspirational_picture_category_slug(sender, instance: InspirationalPictureCategory, **kwargs):
    instance.name = normalize_inspirational_picture_category_name(instance.name)
    if not instance.slug:
        instance.slug = slugify(instance.name)


class InspirationalPictureStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    SCHEDULED = "scheduled", "Scheduled"
    PUBLISHED = "published", "Published"
    UNPUBLISHED = "unpublished", "Unpublished"


class InspirationalPicture(models.Model):
    title = models.CharField(max_length=160)
    caption = models.TextField(blank=True)
    category = models.ForeignKey(
        "content.InspirationalPictureCategory",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="pictures",
    )
    # A short attribution label (e.g. "Instagram", "Southern Living"), not a
    # clickable link -- matches how testimonies' "source" is a platform name,
    # not a URL. Was a URLField until an admin's first real upload hit "Enter
    # a valid URL" typing exactly this kind of label.
    source = models.CharField(max_length=255, blank=True)
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


class ScriptureReadReceipt(models.Model):
    # One row per user per calendar day they marked a read -- read_date is
    # the user's own local date (sent by the client), not necessarily the
    # server's date, since that's precisely the ambiguity this model exists
    # to resolve correctly (see Profile.scripture_streak_count). Not tied to
    # a specific ScriptureOfTheDay row: the streak is about the daily
    # practice, not which exact entry was read.
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="scripture_read_receipts",
    )
    read_date = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-read_date"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "read_date"],
                name="uniq_scripture_read_receipt_user_date",
            ),
        ]

    def __str__(self) -> str:
        return f"ScriptureReadReceipt<{self.user_id}:{self.read_date}>"


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


class FeaturedHomePicture(models.Model):
    picture = models.ForeignKey(
        InspirationalPicture,
        on_delete=models.CASCADE,
        related_name="home_featured_entries",
    )
    position = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="home_featured_pictures_created",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="home_featured_pictures_updated",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["position", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["picture"],
                name="uniq_home_featured_picture",
            ),
        ]

    def clean(self):
        if self.picture.status != InspirationalPictureStatus.PUBLISHED:
            raise ValidationError("Only published pictures can be featured on home feed.")

    def __str__(self) -> str:
        return f"FeaturedHomePicture<{self.picture_id}:{self.position}>"
