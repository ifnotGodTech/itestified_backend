from datetime import datetime

from rest_framework import serializers
from django.utils import timezone

from apps.notifications.services import notify_testimony_submitted_to_admins
from apps.testimonies.models import (
    Testimony,
    TestimonyCategory,
    TestimonyComment,
    TestimonyFavorite,
    TestimonyModerationHistory,
    TestimonyStatus,
    TestimonyType,
)
from apps.testimonies.services.media_uploads import CloudinaryUploadError, upload_testimony_media


class TestimonyCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = TestimonyCategory
        fields = ("id", "name", "slug", "description")


class AdminTestimonyCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = TestimonyCategory
        fields = ("id", "name", "slug", "description", "is_active", "created_at", "updated_at")
        read_only_fields = ("id", "slug", "created_at", "updated_at")

    def validate_name(self, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise serializers.ValidationError("Name is required.")
        queryset = TestimonyCategory.objects.all()
        if self.instance is not None:
            queryset = queryset.exclude(id=self.instance.id)
        if queryset.filter(name__iexact=trimmed).exists():
            raise serializers.ValidationError("Category name already exists.")
        return trimmed

    def validate_description(self, value: str) -> str:
        return value.strip()


class TestimonyListSerializer(serializers.ModelSerializer):
    author_name = serializers.SerializerMethodField()
    category = serializers.CharField(source="category.name", read_only=True)
    category_slug = serializers.CharField(source="category.slug", read_only=True)

    class Meta:
        model = Testimony
        fields = (
            "id",
            "title",
            "testimony_type",
            "author_name",
            "category",
            "category_slug",
            "body",
            "video_url",
            "thumbnail_url",
            "view_count",
            "comment_count",
            "publish_at",
            "created_at",
        )

    def get_author_name(self, obj: Testimony) -> str:
        profile = getattr(obj.author, "profile", None)
        if profile and profile.full_name.strip():
            return profile.full_name
        return obj.author.email


class TestimonyDetailSerializer(TestimonyListSerializer):
    class Meta(TestimonyListSerializer.Meta):
        fields = TestimonyListSerializer.Meta.fields + (
            "body",
            "video_url",
            "thumbnail_url",
            "status",
            "rejection_reason",
        )


class AdminTestimonyListSerializer(serializers.ModelSerializer):
    author_name = serializers.SerializerMethodField()
    author_email = serializers.CharField(source="author.email", read_only=True)
    category = serializers.CharField(source="category.name", read_only=True)
    category_slug = serializers.CharField(source="category.slug", read_only=True)
    comment_count = serializers.SerializerMethodField()

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
        return value.strip()

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
        return value.strip()

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
            thumbnail_url=validated_data.get("thumbnail_url", ""),
            testimony_type=TestimonyType.VIDEO,
            status=status_value,
            publish_at=publish_at,
        )


class FavoriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = TestimonyFavorite
        fields = ("testimony_id", "created_at")


class FavoriteTestimonySerializer(TestimonyListSerializer):
    class Meta(TestimonyListSerializer.Meta):
        fields = TestimonyListSerializer.Meta.fields + (
            "body",
            "video_url",
            "thumbnail_url",
        )


class TestimonyCommentSerializer(serializers.ModelSerializer):
    author_name = serializers.SerializerMethodField()
    is_owner = serializers.SerializerMethodField()
    replies_count = serializers.SerializerMethodField()

    class Meta:
        model = TestimonyComment
        fields = (
            "id",
            "author_name",
            "body",
            "created_at",
            "is_owner",
            "parent_comment_id",
            "replies_count",
        )

    def get_author_name(self, obj: TestimonyComment) -> str:
        profile = getattr(obj.author, "profile", None)
        if profile and profile.full_name.strip():
            return profile.full_name
        return obj.author.email

    def get_is_owner(self, obj: TestimonyComment) -> bool:
        request = self.context.get("request")
        if request is None or not request.user.is_authenticated:
            return False
        return obj.author_id == request.user.id

    def get_replies_count(self, obj: TestimonyComment) -> int:
        return obj.replies.count()


class TestimonyCommentCreateSerializer(serializers.ModelSerializer):
    parent_comment_id = serializers.IntegerField(required=False, allow_null=True)

    class Meta:
        model = TestimonyComment
        fields = ("body", "parent_comment_id")

    def validate_body(self, value: str) -> str:
        if not value or not value.strip():
            raise serializers.ValidationError("Comment body is required.")
        return value.strip()
