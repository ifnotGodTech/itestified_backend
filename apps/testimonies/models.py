import uuid

from django.conf import settings
from django.db import models
from django.db.models.signals import pre_save
from django.dispatch import receiver
from django.utils.text import slugify


def normalize_testimony_category_name(value: str) -> str:
    stripped = value.strip()
    return f"{stripped[:1].upper()}{stripped[1:].lower()}"


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
    instance.name = normalize_testimony_category_name(instance.name)
    if not instance.slug:
        instance.slug = slugify(instance.name)


class UserFollowedCategory(models.Model):
    # Explicit "I want to see more of this" signal (Phase 16), distinct from
    # TestimonyFavorite/TestimonyReaction which are about a single testimony,
    # not a topic going forward. Kept as its own table for the same reason
    # Favorite is its own table rather than a boolean column.
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="followed_categories",
    )
    category = models.ForeignKey(
        "testimonies.TestimonyCategory",
        on_delete=models.CASCADE,
        related_name="followed_by",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "category"],
                name="uniq_user_followed_category",
            ),
        ]

    def __str__(self) -> str:
        return f"FollowedCategory<{self.user_id}:{self.category_id}>"


class TestimonyStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    PENDING_REVIEW = "pending_review", "Pending Review"
    SCHEDULED = "scheduled", "Scheduled"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"
    ARCHIVED = "archived", "Archived"


class TestimonyType(models.TextChoices):
    WRITTEN = "written", "Written"
    VIDEO = "video", "Video"
    AUDIO = "audio", "Audio"


def default_audio_content_types():
    return ["audio/aac", "audio/mp4", "audio/x-m4a", "audio/mpeg", "audio/mp3"]


class AudioUploadPolicy(models.Model):
    """Admin-managed limits shared by mobile audio submission clients."""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    max_file_size_bytes = models.PositiveBigIntegerField(default=50 * 1024 * 1024)
    max_duration_ms = models.PositiveIntegerField(default=15 * 60 * 1000)
    allowed_content_types = models.JSONField(default=default_audio_content_types)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="updated_audio_policies",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return "Audio upload policy"


class AudioUploadIntent(models.Model):
    """A short-lived, single-use authorization for one direct audio upload."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="audio_upload_intents",
    )
    folder = models.CharField(max_length=255)
    public_id = models.CharField(max_length=255, unique=True)
    max_file_size_bytes = models.PositiveBigIntegerField()
    max_duration_ms = models.PositiveIntegerField()
    allowed_content_types = models.JSONField()
    expires_at = models.DateTimeField(db_index=True)
    consumed_at = models.DateTimeField(null=True, blank=True)
    testimony = models.OneToOneField(
        "testimonies.Testimony",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audio_upload_intent",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(
                fields=("user", "consumed_at", "expires_at"),
                name="audio_intent_user_state_idx",
            ),
        ]

    @property
    def asset_public_id(self) -> str:
        return f"{self.folder.rstrip('/')}/{self.public_id}" if self.folder else self.public_id

    def __str__(self) -> str:
        return f"AudioUploadIntent<{self.id}:{self.user_id}>"


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
    audio_url = models.URLField(blank=True)
    duration_ms = models.PositiveIntegerField(null=True, blank=True)
    thumbnail_url = models.URLField(blank=True)
    rejection_reason = models.TextField(blank=True)
    # Moderator-curated only (Phase 19) -- deliberately no automatic
    # sentence-extraction fallback, see the phase background. Settable any
    # time via its own small admin endpoint, independent of
    # approve_testimony/reject_testimony. Blank means the detail screen's
    # pull-quote block simply doesn't render -- not required to publish.
    pull_quote = models.CharField(max_length=280, blank=True)
    publish_at = models.DateTimeField(null=True, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)
    view_count = models.PositiveIntegerField(default=0)
    comment_count = models.PositiveIntegerField(default=0)
    # Denormalized per-reaction-type counters, kept in sync by
    # services/commands.py's set_testimony_reaction/remove_testimony_reaction
    # (F() updates) -- same pattern as comment_count, so list/detail
    # responses never need a live aggregate query per testimony.
    praying_for_you_count = models.PositiveIntegerField(default=0)
    amen_count = models.PositiveIntegerField(default=0)
    gives_me_hope_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["testimony_type", "status", "-created_at"], name="testim_type_status_created_idx"),
            models.Index(fields=["category", "status", "-created_at"], name="testim_cat_status_created_idx"),
            models.Index(fields=["-created_at", "id"], name="testim_created_id_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.title} ({self.status})"


class TranscriptionJobStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    PROCESSING = "processing", "Processing"
    DONE = "done", "Done"
    FAILED = "failed", "Failed"


class TranscriptionJob(models.Model):
    """One durable transcription record per video or audio testimony.

    The row is created transactionally with the testimony and dispatched to
    Celery only after commit. It remains PENDING if broker publication fails,
    allowing the operator redispatch command to recover it safely.
    """

    testimony = models.OneToOneField(
        "testimonies.Testimony",
        on_delete=models.CASCADE,
        related_name="transcription_job",
    )
    status = models.CharField(
        max_length=20,
        choices=TranscriptionJobStatus.choices,
        default=TranscriptionJobStatus.PENDING,
    )
    transcript = models.TextField(blank=True)
    error_message = models.TextField(blank=True)
    retry_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"TranscriptionJob<{self.testimony_id}:{self.status}>"


class TranslationJobStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    PROCESSING = "processing", "Processing"
    DONE = "done", "Done"
    FAILED = "failed", "Failed"


class TranslationJob(models.Model):
    """Phase 22 Slice 2 -- one row per (testimony, language), created
    on-demand the first time a premium user requests that language
    (services/commands.py's request_testimony_translation), never upfront
    for every language. A second request for an already-DONE pair reuses
    this row instead of calling the paid API again -- the caching behavior
    Phase 22's own Build note requires."""

    testimony = models.ForeignKey(
        "testimonies.Testimony",
        on_delete=models.CASCADE,
        related_name="translation_jobs",
    )
    # ISO 639-1 code (e.g. "fr", "yo", "ig", "ha", "sw") -- short and
    # unambiguous, matches what the translation prompt and mobile's
    # language-chip row both key off of.
    language = models.CharField(max_length=10)
    status = models.CharField(
        max_length=20,
        choices=TranslationJobStatus.choices,
        default=TranslationJobStatus.PENDING,
    )
    translated_text = models.TextField(blank=True)
    error_message = models.TextField(blank=True)
    retry_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["testimony", "language"],
                name="uniq_translation_job_per_language",
            ),
        ]

    def __str__(self) -> str:
        return f"TranslationJob<{self.testimony_id}:{self.language}:{self.status}>"


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


class TestimonyWatch(models.Model):
    # Recorded once per distinct testimony an authenticated user opens (Phase
    # 18 Slice 1) -- backs the "Watched" count on Profile's Your Journey
    # card, so "48 Watched" reads as 48 different testimonies, not 48
    # playback events. Written by PublicTestimonyViewIncrementView, which
    # already increments the global view_count on every open regardless of
    # auth; this is the per-user complement to that, authenticated-only.
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="testimony_watches",
    )
    testimony = models.ForeignKey(
        "testimonies.Testimony",
        on_delete=models.CASCADE,
        related_name="watched_by",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "testimony"],
                name="uniq_testimony_watch_user_testimony",
            ),
        ]

    def __str__(self) -> str:
        return f"Watch<{self.user_id}:{self.testimony_id}>"


class TestimonyReactionType(models.TextChoices):
    # Deliberately no negative/critical option -- a testimony is a personal
    # hardship-to-breakthrough story, not generic social content. See the
    # Phase 15 engagement review for the reasoning (LinkedIn cut "Curious"
    # for being ambiguous; a testimony has even less room for one).
    PRAYING_FOR_YOU = "praying_for_you", "Praying for you"
    AMEN = "amen", "Amen"
    GIVES_ME_HOPE = "gives_me_hope", "Gives me hope"


class TestimonyReaction(models.Model):
    # One reaction per user per testimony -- setting a different type
    # switches it rather than adding a second row (same single-reaction-slot
    # model as Facebook's original 2016 reactions), enforced here and in
    # services/commands.py's set_testimony_reaction.
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="testimony_reactions",
    )
    testimony = models.ForeignKey(
        "testimonies.Testimony",
        on_delete=models.CASCADE,
        related_name="reactions",
    )
    reaction_type = models.CharField(max_length=20, choices=TestimonyReactionType.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "testimony"],
                name="uniq_testimony_reaction_user_testimony",
            ),
        ]

    def __str__(self) -> str:
        return f"Reaction<{self.user_id}:{self.testimony_id}:{self.reaction_type}>"


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
