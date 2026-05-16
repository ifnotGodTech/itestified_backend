from rest_framework import serializers

from apps.testimonies.models import (
    Testimony,
    TestimonyCategory,
    TestimonyFavorite,
    TestimonyStatus,
    TestimonyType,
)


class TestimonyCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = TestimonyCategory
        fields = ("id", "name", "slug", "description")


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
            "view_count",
            "comment_count",
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
        )


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
        return Testimony.objects.create(
            author=user,
            category=validated_data["category"],
            title=validated_data["title"],
            body=validated_data["body"],
            testimony_type=TestimonyType.WRITTEN,
            status=TestimonyStatus.PENDING_REVIEW,
        )


class TestimonyVideoCreateSerializer(serializers.ModelSerializer):
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
        return value.strip()

    def create(self, validated_data):
        user = self.context["request"].user
        return Testimony.objects.create(
            author=user,
            category=validated_data["category"],
            title=validated_data["title"],
            video_url=validated_data["video_url"],
            thumbnail_url=validated_data.get("thumbnail_url", ""),
            testimony_type=TestimonyType.VIDEO,
            status=TestimonyStatus.PENDING_REVIEW,
        )


class FavoriteSerializer(serializers.ModelSerializer):
    testimony_id = serializers.IntegerField(source="testimony_id", read_only=True)

    class Meta:
        model = TestimonyFavorite
        fields = ("testimony_id", "created_at")
