from urllib.parse import urlparse

from rest_framework import serializers

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


class TestimonyVideoCreateSerializer(serializers.ModelSerializer):
    _DISALLOWED_VIDEO_PAGE_HOSTS = {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "youtu.be",
        "vimeo.com",
        "www.vimeo.com",
    }

    category_id = serializers.PrimaryKeyRelatedField(
        source="category",
        queryset=TestimonyCategory.objects.filter(is_active=True),
        write_only=True,
    )
    thumbnail_url = serializers.URLField(required=False, allow_blank=True)

    class Meta:
        model = Testimony
        fields = ("title", "category_id", "video_url", "thumbnail_url")

    def validate_title(self, value: str) -> str:
        if not value or not value.strip():
            raise serializers.ValidationError("Title is required.")
        return value.strip()

    def validate_video_url(self, value: str) -> str:
        if not value or not value.strip():
            raise serializers.ValidationError("Video URL is required.")
        trimmed = value.strip()
        parsed = urlparse(trimmed)
        if parsed.scheme not in {"http", "https"}:
            raise serializers.ValidationError("Video URL must start with http:// or https://.")
        if not parsed.netloc:
            raise serializers.ValidationError("Video URL must include a valid host.")
        host = parsed.netloc.lower()
        if host in self._DISALLOWED_VIDEO_PAGE_HOSTS:
            raise serializers.ValidationError(
                "Direct video stream/file URL is required (watch-page links are not supported)."
            )
        return trimmed

    def create(self, validated_data):
        user = self.context["request"].user
        testimony = Testimony.objects.create(
            author=user,
            category=validated_data["category"],
            title=validated_data["title"],
            video_url=validated_data["video_url"],
            thumbnail_url=validated_data.get("thumbnail_url", ""),
            testimony_type=TestimonyType.VIDEO,
            status=TestimonyStatus.PENDING_REVIEW,
        )
        notify_testimony_submitted_to_admins(
            testimony_title=testimony.title,
            testimony_type=testimony.testimony_type,
            actor=user,
        )
        return testimony


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
