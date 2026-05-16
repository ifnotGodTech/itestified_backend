from django.conf import settings
from django.db import models
from django.db.models.signals import pre_save
from django.dispatch import receiver
from django.utils.text import slugify


class TestimonyCategory(models.Model):
    name = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(max_length=140, unique=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return self.name


@receiver(pre_save, sender=TestimonyCategory)
def ensure_testimony_category_slug(sender, instance: TestimonyCategory, **kwargs):
    if not instance.slug:
        instance.slug = slugify(instance.name)


class TestimonyStatus(models.TextChoices):
    PENDING_REVIEW = "pending_review", "Pending Review"
    SCHEDULED = "scheduled", "Scheduled"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"
    ARCHIVED = "archived", "Archived"


class TestimonyType(models.TextChoices):
    WRITTEN = "written", "Written"
    VIDEO = "video", "Video"


class Testimony(models.Model):
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="testimonies",
    )
    category = models.ForeignKey(
        "testimonies.TestimonyCategory",
        on_delete=models.PROTECT,
        related_name="testimonies",
    )
    title = models.CharField(max_length=255)
    body = models.TextField(blank=True)
    testimony_type = models.CharField(
        max_length=20,
        choices=TestimonyType.choices,
        default=TestimonyType.WRITTEN,
    )
    status = models.CharField(
        max_length=20,
        choices=TestimonyStatus.choices,
        default=TestimonyStatus.PENDING_REVIEW,
    )
    video_url = models.URLField(blank=True)
    thumbnail_url = models.URLField(blank=True)
    rejection_reason = models.TextField(blank=True)
    publish_at = models.DateTimeField(null=True, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)
    view_count = models.PositiveIntegerField(default=0)
    comment_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.title} ({self.status})"


class TestimonyFavorite(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="testimony_favorites",
    )
    testimony = models.ForeignKey(
        "testimonies.Testimony",
        on_delete=models.CASCADE,
        related_name="favorited_by",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "testimony"],
                name="uniq_testimony_favorite_user_testimony",
            ),
        ]

    def __str__(self) -> str:
        return f"Favorite<{self.user_id}:{self.testimony_id}>"


class TestimonyComment(models.Model):
    testimony = models.ForeignKey(
        "testimonies.Testimony",
        on_delete=models.CASCADE,
        related_name="comments",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="testimony_comments",
    )
    parent_comment = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="replies",
    )
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Comment<{self.id}:{self.author_id}:{self.testimony_id}>"


class ModerationAction(models.TextChoices):
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"
    SCHEDULED = "scheduled", "Scheduled"
    ARCHIVED = "archived", "Archived"
    AUTO_PUBLISHED = "auto_published", "Auto Published"


class TestimonyModerationHistory(models.Model):
    testimony = models.ForeignKey(
        "testimonies.Testimony",
        on_delete=models.CASCADE,
        related_name="moderation_history",
    )
    action = models.CharField(max_length=32, choices=ModerationAction.choices)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="testimony_moderation_actions",
    )
    from_status = models.CharField(max_length=20, choices=TestimonyStatus.choices)
    to_status = models.CharField(max_length=20, choices=TestimonyStatus.choices)
    reason = models.TextField(blank=True)
    publish_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return f"Moderation<{self.testimony_id}:{self.action}:{self.from_status}->{self.to_status}>"
