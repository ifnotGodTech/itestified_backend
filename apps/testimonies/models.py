from django.conf import settings
from django.db import models
from django.utils.text import slugify


class TestimonyCategory(models.Model):
    name = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(max_length=140, unique=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.name


class TestimonyStatus(models.TextChoices):
    PENDING_REVIEW = "pending_review", "Pending Review"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"


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
