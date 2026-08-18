from datetime import datetime

from rest_framework import serializers
from django.utils import timezone

from apps.notifications.services import notify_testimony_submitted_to_admins
from apps.subscriptions.selectors import is_user_premium
from apps.testimonies.models import (
    Testimony,
    TestimonyCategory,
    TestimonyComment,
    TestimonyFavorite,
    TestimonyModerationHistory,
    TestimonyReaction,
    TestimonyReactionType,
    TestimonyStatus,
    TestimonyType,
    TranscriptionJob,
    TranscriptionJobStatus,
    TranslationJob,
    normalize_testimony_category_name,
)
from apps.testimonies.services.media_uploads import (
    CloudinaryUploadError,
    build_cloudinary_video_thumbnail_url,
    upload_testimony_media,
)

SOURCE_PREFIX = "source:"
SOURCE_CANONICAL_NAMES = {
    "youtube": "YouTube",
    "you tube": "YouTube",
    "you-tube": "YouTube",
    "instagram": "Instagram",
    "tiktok": "TikTok",
    "tik tok": "TikTok",
    "facebook": "Facebook",
}


def normalize_video_source(value: str) -> str:
    trimmed = value.strip()
    if not trimmed:
        return ""
    key = " ".join(trimmed.replace("_", " ").split()).lower()
    return SOURCE_CANONICAL_NAMES.get(key, trimmed[:1].upper() + trimmed[1:])


def extract_video_source(body: str) -> str:
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith(SOURCE_PREFIX):
            return normalize_video_source(stripped[len(SOURCE_PREFIX) :])
    return ""


def normalize_video_source_lines(body: str) -> str:
    lines = []
    source_seen = False
    for line in body.strip().splitlines():
        stripped = line.strip()
        if stripped.lower().startswith(SOURCE_PREFIX):
            source = normalize_video_source(stripped[len(SOURCE_PREFIX) :])
            if source and not source_seen:
                lines.append(f"Source: {source}")
                source_seen = True
            continue
        lines.append(line.rstrip())
    return "\n".join(lines).strip()


class TestimonyCategorySerializer(serializers.ModelSerializer):
    is_followed = serializers.SerializerMethodField()

    class Meta:
        model = TestimonyCategory
        fields = ("id", "name", "slug", "description", "is_followed")

    def get_is_followed(self, obj: TestimonyCategory) -> bool:
        # Prefetched once per request by PublicCategoryListView (a single
        # query for the whole list) rather than one .exists() query per
        # category row here -- see get_serializer_context there.
        followed_ids = self.context.get("followed_category_ids")
        if followed_ids is not None:
            return obj.id in followed_ids
        request = self.context.get("request")
        if request is None or not request.user.is_authenticated:
            return False
        return request.user.followed_categories.filter(category=obj).exists()


class AdminTestimonyCategorySerializer(serializers.ModelSerializer):
    follower_count = serializers.SerializerMethodField()

    class Meta:
        model = TestimonyCategory
        fields = (
            "id",
            "name",
            "slug",
            "description",
            "is_active",
            "follower_count",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "slug", "created_at", "updated_at")

    def get_follower_count(self, obj: TestimonyCategory) -> int:
        # AdminCategoryListCreateView/AdminCategoryDetailView annotate this
        # (one query for the whole list, not one .count() per row); fall
        # back to a live count for any call site that doesn't bother
        # annotating (e.g. AdminCategoryActivationView, a single row).
        annotated = getattr(obj, "follower_count", None)
        if annotated is not None:
            return annotated
        return obj.followed_by.count()

    def validate_name(self, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise serializers.ValidationError("Name is required.")
        normalized = normalize_testimony_category_name(trimmed)
        queryset = TestimonyCategory.objects.all()
        if self.instance is not None:
            queryset = queryset.exclude(id=self.instance.id)
        if queryset.filter(name__iexact=normalized).exists():
            raise serializers.ValidationError("Category name already exists.")
        return normalized

    def validate_description(self, value: str) -> str:
        return value.strip()


class TestimonyListSerializer(serializers.ModelSerializer):
    author_name = serializers.SerializerMethodField()
    author_avatar = serializers.SerializerMethodField()
    category = serializers.CharField(source="category.name", read_only=True)
    category_slug = serializers.CharField(source="category.slug", read_only=True)
    thumbnail_url = serializers.SerializerMethodField()
    reaction_counts = serializers.SerializerMethodField()

    class Meta:
        model = Testimony
        fields = (
            "id",
            "title",
            "testimony_type",
            "author_name",
            "author_avatar",
            "category",
            "category_slug",
            "body",
            "video_url",
            "thumbnail_url",
            "view_count",
            "comment_count",
            "reaction_counts",
            "publish_at",
            "created_at",
        )

    def get_author_name(self, obj: Testimony) -> str:
        profile = getattr(obj.author, "profile", None)
        if profile and profile.full_name.strip():
            return profile.full_name
        return obj.author.email

    def get_author_avatar(self, obj: Testimony) -> str:
        profile = getattr(obj.author, "profile", None)
        return profile.avatar if profile else ""

    def get_thumbnail_url(self, obj: Testimony) -> str:
        if obj.thumbnail_url.strip():
            return obj.thumbnail_url
        return build_cloudinary_video_thumbnail_url(obj.video_url)

    def get_reaction_counts(self, obj: Testimony) -> dict:
        # Reads the three denormalized counters directly -- no per-row
        # query, so this is free on list views with many testimonies.
        return {
            "praying_for_you": obj.praying_for_you_count,
            "amen": obj.amen_count,
            "gives_me_hope": obj.gives_me_hope_count,
        }


class TestimonyDetailSerializer(TestimonyListSerializer):
    # Phase 23 Slice 7 -- the only place a testimony exposes its author's
    # real user id (list payloads stay author_name/author_avatar-only,
    # unchanged, to avoid widening an already-widely-consumed shape).
    # Mobile uses this to link "Follow" from a testimony's author row to
    # apps.creators' public profile endpoint -- a 404 there just means
    # this particular author isn't a Ministry account, handled gracefully
    # client-side, not something this field needs to pre-filter.
    author_id = serializers.IntegerField(source="author.id", read_only=True)
    my_reaction = serializers.SerializerMethodField()
    transcript_status = serializers.SerializerMethodField()
    transcript = serializers.SerializerMethodField()

    class Meta(TestimonyListSerializer.Meta):
        fields = TestimonyListSerializer.Meta.fields + (
            "author_id",
            "body",
            "video_url",
            "thumbnail_url",
            "status",
            "rejection_reason",
            "my_reaction",
            "pull_quote",
            "transcript_status",
            "transcript",
        )

    def get_my_reaction(self, obj: Testimony):
        # Unlike reaction_counts, this needs a query -- scoped to the
        # single-object detail serializer only, kept off the list
        # serializer deliberately to avoid an N+1 across a testimony list.
        request = self.context.get("request")
        if request is None or not request.user.is_authenticated:
            return None
        return (
            TestimonyReaction.objects.filter(user=request.user, testimony=obj)
            .values_list("reaction_type", flat=True)
            .first()
        )

    def get_transcript_status(self, obj: Testimony) -> str:
        # Metadata, not content -- safe to return regardless of the
        # viewer's premium status, same "gate the content, not its
        # existence" split the mockup's locked state relies on.
        job = getattr(obj, "transcription_job", None)
        if job is None:
            return "not_available"
        return job.status

    def get_transcript(self, obj: Testimony):
        # Phase 22 Slice 1: gated at both the entitlement layer (here) and
        # the presentation layer (mobile never renders it for a non-premium
        # viewer either) -- see the phase's own Test note.
        job = getattr(obj, "transcription_job", None)
        if job is None or job.status != TranscriptionJobStatus.DONE:
            return None
        request = self.context.get("request")
        if request is None or not is_user_premium(request.user):
            return None
        return job.transcript


class TestimonyTranslationRequestSerializer(serializers.Serializer):
    language = serializers.CharField(max_length=10)


class TestimonyTranslationSerializer(serializers.ModelSerializer):
    class Meta:
        model = TranslationJob
        fields = ("language", "status", "translated_text")


class AdminTranscriptionJobSerializer(serializers.ModelSerializer):
    testimony_id = serializers.IntegerField(source="testimony.id", read_only=True)
    testimony_title = serializers.CharField(source="testimony.title", read_only=True)

    class Meta:
        model = TranscriptionJob
        fields = (
            "id",
            "testimony_id",
            "testimony_title",
            "status",
            "error_message",
            "retry_count",
            "created_at",
            "updated_at",
        )


class AdminTranslationJobSerializer(serializers.ModelSerializer):
    testimony_id = serializers.IntegerField(source="testimony.id", read_only=True)
    testimony_title = serializers.CharField(source="testimony.title", read_only=True)

    class Meta:
        model = TranslationJob
        fields = (
            "id",
            "testimony_id",
            "testimony_title",
            "language",
            "status",
            "error_message",
            "retry_count",
            "created_at",
            "updated_at",
        )


class PublicTestimonyShareSerializer(serializers.ModelSerializer):
    """Phase 11 Slice 1's public, unauthenticated share page -- deliberately
    a standalone serializer, not built on TestimonyListSerializer, so there
    is no author_name/author_avatar field to ever expose here at all (not
    even by omitting it downstream). TestimonyListSerializer.get_author_name
    falls back to the author's email when no profile full_name is set --
    fine for the in-app experience, not something a public, crawler-indexed
    page (search engines, WhatsApp/Facebook/Twitter link-preview caches)
    should ever be able to render. Attribution on the public page is always
    the fixed "iTestified" branding, decided at the frontend template level,
    not derived per-testimony -- so this serializer carries no author field
    for that to read in the first place."""

    category = serializers.CharField(source="category.name", read_only=True)
    thumbnail_url = serializers.SerializerMethodField()

    class Meta:
        model = Testimony
        fields = (
            "id",
            "title",
            "testimony_type",
            "category",
            "body",
            "pull_quote",
            "video_url",
            "thumbnail_url",
        )

    def get_thumbnail_url(self, obj: Testimony) -> str:
        if obj.thumbnail_url.strip():
            return obj.thumbnail_url
        return build_cloudinary_video_thumbnail_url(obj.video_url)


class AdminTestimonyListSerializer(serializers.ModelSerializer):
    author_name = serializers.SerializerMethodField()
    author_email = serializers.CharField(source="author.email", read_only=True)
    category = serializers.CharField(source="category.name", read_only=True)
    category_slug = serializers.CharField(source="category.slug", read_only=True)
    comment_count = serializers.SerializerMethodField()
    thumbnail_url = serializers.SerializerMethodField()
    source = serializers.SerializerMethodField()

    class Meta:
        model = Testimony
        fields = (
            "id",
            "title",
            "testimony_type",
            "status",
            "author_name",
            "author_email",
            "category",
            "category_slug",
            "source",
            "thumbnail_url",
            "view_count",
            "comment_count",
            "created_at",
            "updated_at",
        )

    def get_author_name(self, obj: Testimony) -> str:
        profile = getattr(obj.author, "profile", None)
        if profile and profile.full_name.strip():
            return profile.full_name
        return obj.author.email

    def get_comment_count(self, obj: Testimony) -> int:
        return int(getattr(obj, "comment_count_total", obj.comment_count))

    def get_thumbnail_url(self, obj: Testimony) -> str:
        if obj.thumbnail_url.strip():
            return obj.thumbnail_url
        return build_cloudinary_video_thumbnail_url(obj.video_url)

    def get_source(self, obj: Testimony) -> str:
        return extract_video_source(obj.body)


class AdminTestimonyDetailSerializer(AdminTestimonyListSerializer):
    moderation_history = serializers.SerializerMethodField()

    class Meta(AdminTestimonyListSerializer.Meta):
        fields = AdminTestimonyListSerializer.Meta.fields + (
            "body",
            "video_url",
            "thumbnail_url",
            "rejection_reason",
            "publish_at",
            "archived_at",
            "moderation_history",
            "pull_quote",
        )

    def get_moderation_history(self, obj: Testimony):
        history = obj.moderation_history.select_related("actor").all()
        payload = []
        for item in history:
            payload.append(
                {
                    "id": item.id,
                    "action": item.action,
                    "from_status": item.from_status,
                    "to_status": item.to_status,
                    "reason": item.reason,
                    "publish_at": item.publish_at,
                    "created_at": item.created_at,
                    "actor_email": item.actor.email if item.actor else None,
                    "actor_name": (
                        item.actor.profile.full_name
                        if item.actor and hasattr(item.actor, "profile") and item.actor.profile.full_name
                        else (item.actor.email if item.actor else "System")
                    ),
                }
            )
        return payload


class TestimonyModerationHistorySerializer(serializers.ModelSerializer):
    actor_email = serializers.SerializerMethodField()
    actor_name = serializers.SerializerMethodField()

    class Meta:
        model = TestimonyModerationHistory
        fields = (
            "id",
            "action",
            "from_status",
            "to_status",
            "reason",
            "publish_at",
            "created_at",
            "actor_email",
            "actor_name",
        )

    def get_actor_email(self, obj: TestimonyModerationHistory):
        return obj.actor.email if obj.actor else None

    def get_actor_name(self, obj: TestimonyModerationHistory):
        if obj.actor is None:
            return "System"
        profile = getattr(obj.actor, "profile", None)
        if profile and profile.full_name.strip():
            return profile.full_name
        return obj.actor.email


class TestimonyCreateSerializer(serializers.ModelSerializer):
    category_id = serializers.PrimaryKeyRelatedField(
        source="category",
        queryset=TestimonyCategory.objects.filter(is_active=True),
        write_only=True,
    )

    class Meta:
        model = Testimony
        fields = ("title", "body", "category_id")

    def validate_title(self, value: str) -> str:
        if not value or not value.strip():
            raise serializers.ValidationError("Title is required.")
        return value.strip()

    def validate_body(self, value: str) -> str:
        if not value or not value.strip():
            raise serializers.ValidationError("Body is required for written testimony.")
        return value.strip()

    def create(self, validated_data):
        user = self.context["request"].user
        testimony = Testimony.objects.create(
            author=user,
            category=validated_data["category"],
            title=validated_data["title"],
            body=validated_data["body"],
            testimony_type=TestimonyType.WRITTEN,
            status=TestimonyStatus.PENDING_REVIEW,
        )
        notify_testimony_submitted_to_admins(
            testimony_title=testimony.title,
            testimony_type=testimony.testimony_type,
            actor=user,
        )
        return testimony


class RejectedTestimonyResubmitSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=255)
    body = serializers.CharField()
    category_id = serializers.PrimaryKeyRelatedField(
        source="category",
        queryset=TestimonyCategory.objects.filter(is_active=True),
    )

    def validate_title(self, value: str) -> str:
        if not value or not value.strip():
            raise serializers.ValidationError("Title is required.")
        return value.strip()

    def validate_body(self, value: str) -> str:
        if not value or not value.strip():
            raise serializers.ValidationError("Body is required for written testimony.")
        return value.strip()


class AdminVideoTestimonyUploadSerializer(serializers.Serializer):
    MAX_VIDEO_FILE_SIZE_BYTES = 200 * 1024 * 1024  # 200 MB
    MAX_THUMBNAIL_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB
    MAX_VIDEOS_PER_BATCH = 10
    ALLOWED_VIDEO_CONTENT_TYPES = {
        "video/mp4",
    }
    ALLOWED_THUMBNAIL_CONTENT_TYPES = {
        "image/jpeg",
        "image/png",
        "image/webp",
    }

    class UploadStatus:
        UPLOAD_NOW = "upload_now"
        SCHEDULE_FOR_LATER = "schedule_for_later"
        DRAFT = "draft"
        CHOICES = (
            (UPLOAD_NOW, "Upload Now"),
            (SCHEDULE_FOR_LATER, "Schedule for Later"),
            (DRAFT, "Draft"),
        )

    title = serializers.CharField(max_length=255)
    category_id = serializers.PrimaryKeyRelatedField(
        source="category",
        queryset=TestimonyCategory.objects.filter(is_active=True),
    )
    video_file = serializers.FileField()
    thumbnail_file = serializers.FileField(required=False, allow_null=True)
    body = serializers.CharField(required=False, allow_blank=True)
    total_videos_in_batch = serializers.IntegerField(required=False, min_value=1)
    upload_status = serializers.ChoiceField(
        choices=UploadStatus.CHOICES,
        required=False,
        default=UploadStatus.UPLOAD_NOW,
    )
    scheduled_publish_at = serializers.CharField(required=False, allow_blank=True)

    def validate_title(self, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise serializers.ValidationError("Title is required.")
        return trimmed

    def validate_body(self, value: str) -> str:
        return normalize_video_source_lines(value)

    def validate_video_file(self, value):
        content_type = (getattr(value, "content_type", "") or "").lower().strip()
        if content_type not in self.ALLOWED_VIDEO_CONTENT_TYPES:
            raise serializers.ValidationError("Only MP4 video uploads are allowed.")
        size = int(getattr(value, "size", 0) or 0)
        if size <= 0:
            raise serializers.ValidationError("Video file is empty.")
        if size > self.MAX_VIDEO_FILE_SIZE_BYTES:
            raise serializers.ValidationError("Video file exceeds the 200MB limit.")
        return value

    def validate_thumbnail_file(self, value):
        if value is None:
            return value
        content_type = (getattr(value, "content_type", "") or "").lower().strip()
        if content_type and content_type not in self.ALLOWED_THUMBNAIL_CONTENT_TYPES:
            raise serializers.ValidationError("Thumbnail must be JPG, PNG, or WEBP.")
        size = int(getattr(value, "size", 0) or 0)
        if size <= 0:
            raise serializers.ValidationError("Thumbnail file is empty.")
        if size > self.MAX_THUMBNAIL_FILE_SIZE_BYTES:
            raise serializers.ValidationError("Thumbnail file exceeds the 10MB limit.")
        return value

    def validate(self, attrs):
        upload_status = attrs.get("upload_status", self.UploadStatus.UPLOAD_NOW)
        raw_publish_at = str(attrs.get("scheduled_publish_at", "")).strip()
        total_videos = int(attrs.get("total_videos_in_batch") or 1)
        if total_videos > self.MAX_VIDEOS_PER_BATCH:
            raise serializers.ValidationError(
                {
                    "total_videos_in_batch": f"A maximum of {self.MAX_VIDEOS_PER_BATCH} videos is allowed per upload batch."
                }
            )

        if upload_status == self.UploadStatus.SCHEDULE_FOR_LATER:
            if not raw_publish_at:
                raise serializers.ValidationError(
                    {"scheduled_publish_at": "scheduled_publish_at is required when upload_status is schedule_for_later."}
                )
            try:
                publish_at = datetime.fromisoformat(raw_publish_at.replace("Z", "+00:00"))
            except ValueError as exc:
                raise serializers.ValidationError({"scheduled_publish_at": "scheduled_publish_at must be a valid ISO datetime."}) from exc
            if timezone.is_naive(publish_at):
                publish_at = timezone.make_aware(publish_at, timezone.get_current_timezone())
            if publish_at <= timezone.now():
                raise serializers.ValidationError({"scheduled_publish_at": "scheduled_publish_at must be in the future."})
            attrs["parsed_scheduled_publish_at"] = publish_at
        else:
            attrs["parsed_scheduled_publish_at"] = None

        return attrs

    def create(self, validated_data):
        actor = self.context["request"].user
        try:
            upload_result = upload_testimony_media(
                video_file=validated_data["video_file"],
                thumbnail_file=validated_data.get("thumbnail_file"),
            )
        except CloudinaryUploadError as exc:
            raise serializers.ValidationError({"video_file": str(exc)}) from exc

        upload_status = validated_data.get("upload_status", self.UploadStatus.UPLOAD_NOW)
        status_value = TestimonyStatus.PENDING_REVIEW
        publish_at = None
        if upload_status == self.UploadStatus.UPLOAD_NOW:
            status_value = TestimonyStatus.APPROVED
        elif upload_status == self.UploadStatus.SCHEDULE_FOR_LATER:
            status_value = TestimonyStatus.SCHEDULED
            publish_at = validated_data.get("parsed_scheduled_publish_at")
        elif upload_status == self.UploadStatus.DRAFT:
            status_value = TestimonyStatus.DRAFT

        testimony = Testimony.objects.create(
            author=actor,
            category=validated_data["category"],
            title=validated_data["title"],
            body=validated_data.get("body", ""),
            video_url=upload_result.video_url,
            thumbnail_url=upload_result.thumbnail_url,
            testimony_type=TestimonyType.VIDEO,
            status=status_value,
            publish_at=publish_at,
        )
        # Admin-originated uploads should not trigger the mobile/user submission review notification flow.
        return testimony


class AdminVideoTestimonyEditSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=255, required=False)
    category_id = serializers.PrimaryKeyRelatedField(
        source="category",
        queryset=TestimonyCategory.objects.filter(is_active=True),
        required=False,
    )
    scheduled_publish_at = serializers.CharField(required=False, allow_blank=True)

    def validate_title(self, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise serializers.ValidationError("Title is required.")
        return trimmed

    def validate(self, attrs):
        testimony = self.instance
        if testimony is None:
            return attrs

        raw_publish_at = str(attrs.get("scheduled_publish_at", "")).strip()
        if testimony.status == TestimonyStatus.SCHEDULED and raw_publish_at:
            try:
                publish_at = datetime.fromisoformat(raw_publish_at.replace("Z", "+00:00"))
            except ValueError as exc:
                raise serializers.ValidationError(
                    {"scheduled_publish_at": "scheduled_publish_at must be a valid ISO datetime."}
                ) from exc
            if timezone.is_naive(publish_at):
                publish_at = timezone.make_aware(publish_at, timezone.get_current_timezone())
            if publish_at <= timezone.now():
                raise serializers.ValidationError(
                    {"scheduled_publish_at": "scheduled_publish_at must be in the future."}
                )
            attrs["parsed_scheduled_publish_at"] = publish_at
        elif raw_publish_at:
            raise serializers.ValidationError(
                {"scheduled_publish_at": "scheduled_publish_at can only be updated for scheduled testimonies."}
            )
        return attrs

    def update(self, instance: Testimony, validated_data):
        fields_to_update = []

        title = validated_data.get("title")
        if title is not None:
            instance.title = title
            fields_to_update.append("title")

        category = validated_data.get("category")
        if category is not None:
            instance.category = category
            fields_to_update.append("category")

        parsed_publish_at = validated_data.get("parsed_scheduled_publish_at")
        if parsed_publish_at is not None:
            instance.publish_at = parsed_publish_at
            fields_to_update.append("publish_at")

        if fields_to_update:
            instance.save(update_fields=[*fields_to_update, "updated_at"])
        return instance


class AdminTestimonyPullQuoteSerializer(serializers.Serializer):
    # Phase 19: moderator-curated pull-quote, settable independently of the
    # approve/reject decision -- allow_blank so a moderator can clear a
    # quote they've already set, not just add one.
    pull_quote = serializers.CharField(max_length=280, allow_blank=True)

    def validate_pull_quote(self, value: str) -> str:
        return value.strip()

    def update(self, instance: Testimony, validated_data):
        instance.pull_quote = validated_data["pull_quote"]
        instance.save(update_fields=["pull_quote", "updated_at"])
        return instance


class AdminVideoTestimonyCreateFromUrlSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=255)
    category_id = serializers.PrimaryKeyRelatedField(
        source="category",
        queryset=TestimonyCategory.objects.filter(is_active=True),
    )
    video_url = serializers.URLField()
    thumbnail_url = serializers.URLField(required=False, allow_blank=True)
    body = serializers.CharField(required=False, allow_blank=True)
    upload_status = serializers.ChoiceField(
        choices=AdminVideoTestimonyUploadSerializer.UploadStatus.CHOICES,
        required=False,
        default=AdminVideoTestimonyUploadSerializer.UploadStatus.UPLOAD_NOW,
    )
    scheduled_publish_at = serializers.CharField(required=False, allow_blank=True)

    def validate_title(self, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise serializers.ValidationError("Title is required.")
        return trimmed

    def validate_body(self, value: str) -> str:
        return normalize_video_source_lines(value)

    def validate(self, attrs):
        upload_status = attrs.get("upload_status", AdminVideoTestimonyUploadSerializer.UploadStatus.UPLOAD_NOW)
        raw_publish_at = str(attrs.get("scheduled_publish_at", "")).strip()
        if upload_status == AdminVideoTestimonyUploadSerializer.UploadStatus.SCHEDULE_FOR_LATER:
            if not raw_publish_at:
                raise serializers.ValidationError(
                    {"scheduled_publish_at": "scheduled_publish_at is required when upload_status is schedule_for_later."}
                )
            try:
                publish_at = datetime.fromisoformat(raw_publish_at.replace("Z", "+00:00"))
            except ValueError as exc:
                raise serializers.ValidationError({"scheduled_publish_at": "scheduled_publish_at must be a valid ISO datetime."}) from exc
            if timezone.is_naive(publish_at):
                publish_at = timezone.make_aware(publish_at, timezone.get_current_timezone())
            if publish_at <= timezone.now():
                raise serializers.ValidationError({"scheduled_publish_at": "scheduled_publish_at must be in the future."})
            attrs["parsed_scheduled_publish_at"] = publish_at
        else:
            attrs["parsed_scheduled_publish_at"] = None
        return attrs

    def create(self, validated_data):
        actor = self.context["request"].user
        upload_status = validated_data.get("upload_status", AdminVideoTestimonyUploadSerializer.UploadStatus.UPLOAD_NOW)
        status_value = TestimonyStatus.PENDING_REVIEW
        publish_at = None
        if upload_status == AdminVideoTestimonyUploadSerializer.UploadStatus.UPLOAD_NOW:
            status_value = TestimonyStatus.APPROVED
        elif upload_status == AdminVideoTestimonyUploadSerializer.UploadStatus.SCHEDULE_FOR_LATER:
            status_value = TestimonyStatus.SCHEDULED
            publish_at = validated_data.get("parsed_scheduled_publish_at")
        elif upload_status == AdminVideoTestimonyUploadSerializer.UploadStatus.DRAFT:
            status_value = TestimonyStatus.DRAFT

        return Testimony.objects.create(
            author=actor,
            category=validated_data["category"],
            title=validated_data["title"],
            body=validated_data.get("body", ""),
            video_url=validated_data["video_url"],
            thumbnail_url=validated_data.get("thumbnail_url", "")
            or build_cloudinary_video_thumbnail_url(validated_data["video_url"]),
            testimony_type=TestimonyType.VIDEO,
            status=status_value,
            publish_at=publish_at,
        )


class FavoriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = TestimonyFavorite
        fields = ("testimony_id", "created_at")


class TestimonyReactionInputSerializer(serializers.Serializer):
    reaction_type = serializers.ChoiceField(choices=TestimonyReactionType.choices)


class FavoriteTestimonySerializer(TestimonyListSerializer):
    class Meta(TestimonyListSerializer.Meta):
        fields = TestimonyListSerializer.Meta.fields + (
            "body",
            "video_url",
            "thumbnail_url",
        )


class TestimonyCommentSerializer(serializers.ModelSerializer):
    author_name = serializers.SerializerMethodField()
    author_avatar = serializers.SerializerMethodField()
    is_owner = serializers.SerializerMethodField()
    replies_count = serializers.SerializerMethodField()
    replies = serializers.SerializerMethodField()

    class Meta:
        model = TestimonyComment
        fields = (
            "id",
            "author_name",
            "author_avatar",
            "body",
            "created_at",
            "is_owner",
            "parent_comment_id",
            "replies_count",
            "replies",
        )

    def get_author_name(self, obj: TestimonyComment) -> str:
        profile = getattr(obj.author, "profile", None)
        if profile and profile.full_name.strip():
            return profile.full_name
        return obj.author.email

    def get_author_avatar(self, obj: TestimonyComment) -> str:
        profile = getattr(obj.author, "profile", None)
        return profile.avatar if profile else ""

    def get_is_owner(self, obj: TestimonyComment) -> bool:
        request = self.context.get("request")
        if request is None or not request.user.is_authenticated:
            return False
        return obj.author_id == request.user.id

    def get_replies_count(self, obj: TestimonyComment) -> int:
        return obj.replies.count()

    def get_replies(self, obj: TestimonyComment) -> list[dict]:
        if obj.parent_comment_id is not None:
            return []
        replies = obj.replies.select_related("author", "author__profile").order_by("created_at")
        return TestimonyCommentSerializer(replies, many=True, context=self.context).data


class TestimonyCommentCreateSerializer(serializers.ModelSerializer):
    parent_comment_id = serializers.IntegerField(required=False, allow_null=True)

    class Meta:
        model = TestimonyComment
        fields = ("body", "parent_comment_id")

    def validate_body(self, value: str) -> str:
        if not value or not value.strip():
            raise serializers.ValidationError("Comment body is required.")
        return value.strip()
