from django.utils import timezone
from rest_framework import serializers

from apps.content.models import (
    FeaturedHomeTestimony,
    HomeSectionKey,
    HomeSectionOrder,
    InspirationalPicture,
    InspirationalPictureCategory,
    InspirationalPictureStatus,
    ScriptureOfTheDay,
    ScriptureStatus,
    normalize_inspirational_picture_category_name,
)
from apps.testimonies.models import Testimony, TestimonyStatus
from apps.testimonies.services.media_uploads import build_cloudinary_video_thumbnail_url


class InspirationalPictureCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = InspirationalPictureCategory
        fields = ("id", "name", "slug", "description", "is_active", "created_at", "updated_at")
        read_only_fields = ("id", "slug", "created_at", "updated_at")

    def validate_name(self, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise serializers.ValidationError("Name is required.")
        normalized = normalize_inspirational_picture_category_name(trimmed)
        queryset = InspirationalPictureCategory.objects.all()
        if self.instance is not None:
            queryset = queryset.exclude(id=self.instance.id)
        if queryset.filter(name__iexact=normalized).exists():
            raise serializers.ValidationError("Category name already exists.")
        return normalized


class InspirationalPictureSerializer(serializers.ModelSerializer):
    category = serializers.SerializerMethodField()
    category_id = serializers.PrimaryKeyRelatedField(
        source="category",
        queryset=InspirationalPictureCategory.objects.filter(is_active=True),
        required=False,
        allow_null=True,
    )

    class Meta:
        model = InspirationalPicture
        fields = (
            "id",
            "title",
            "caption",
            "category",
            "category_id",
            "source",
            "image_url",
            "status",
            "publish_at",
            "expires_at",
            "created_at",
            "updated_at",
        )

    def get_category(self, obj: InspirationalPicture) -> str:
        return obj.category.name if obj.category_id else ""

    def validate(self, attrs):
        status = attrs.get("status", getattr(self.instance, "status", InspirationalPictureStatus.DRAFT))
        publish_at = attrs.get("publish_at", getattr(self.instance, "publish_at", None))
        expires_at = attrs.get("expires_at", getattr(self.instance, "expires_at", None))
        if status == InspirationalPictureStatus.SCHEDULED and not publish_at:
            raise serializers.ValidationError("publish_at is required when status is scheduled.")
        if publish_at and expires_at and expires_at <= publish_at:
            raise serializers.ValidationError("expires_at must be after publish_at.")
        return attrs


class ScriptureSerializer(serializers.ModelSerializer):
    class Meta:
        model = ScriptureOfTheDay
        fields = (
            "id",
            "date",
            "bible_text",
            "scripture",
            "prayer",
            "bible_version",
            "status",
            "published_at",
            "created_at",
            "updated_at",
        )

    def validate_date(self, value):
        existing = ScriptureOfTheDay.objects.filter(date=value)
        if self.instance is not None:
            existing = existing.exclude(pk=self.instance.pk)
        if existing.exists():
            raise serializers.ValidationError("A scripture entry already exists for this date.")
        return value

    def validate(self, attrs):
        instance = self.instance
        if instance is not None and instance.status == ScriptureStatus.PUBLISHED and instance.date <= timezone.localdate():
            if "bible_text" in attrs or "scripture" in attrs or "prayer" in attrs or "bible_version" in attrs:
                raise serializers.ValidationError("Published scripture entries cannot be edited after publish date.")
        return attrs


class HomeSectionOrderSerializer(serializers.ModelSerializer):
    class Meta:
        model = HomeSectionOrder
        fields = ("section", "position")


class FeaturedHomeTestimonySerializer(serializers.ModelSerializer):
    testimony_id = serializers.IntegerField(source="testimony.id", read_only=True)
    title = serializers.CharField(source="testimony.title", read_only=True)
    category = serializers.CharField(source="testimony.category.name", read_only=True)
    testimony_type = serializers.CharField(source="testimony.testimony_type", read_only=True)
    body = serializers.CharField(source="testimony.body", read_only=True)
    thumbnail_url = serializers.SerializerMethodField()
    video_url = serializers.CharField(source="testimony.video_url", read_only=True)
    created_at = serializers.DateTimeField(source="testimony.created_at", read_only=True)

    class Meta:
        model = FeaturedHomeTestimony
        fields = (
            "id",
            "testimony_id",
            "position",
            "title",
            "category",
            "testimony_type",
            "body",
            "thumbnail_url",
            "video_url",
            "created_at",
        )

    def get_thumbnail_url(self, obj: FeaturedHomeTestimony) -> str:
        if obj.testimony.thumbnail_url.strip():
            return obj.testimony.thumbnail_url
        return build_cloudinary_video_thumbnail_url(obj.testimony.video_url)


class HomeCurationUpdateSerializer(serializers.Serializer):
    section_order = serializers.ListField(
        child=serializers.ChoiceField(choices=HomeSectionKey.values),
        allow_empty=False,
    )
    featured_testimony_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        allow_empty=True,
    )

    def validate_section_order(self, value):
        required = set(HomeSectionKey.values)
        incoming = set(value)
        if incoming != required or len(value) != len(required):
            raise serializers.ValidationError(
                f"section_order must contain each section exactly once: {', '.join(HomeSectionKey.values)}."
            )
        return value

    def validate_featured_testimony_ids(self, value):
        if not value:
            return value
        testimonies = Testimony.objects.filter(id__in=value, status=TestimonyStatus.APPROVED)
        found_ids = {item.id for item in testimonies}
        missing = [item_id for item_id in value if item_id not in found_ids]
        if missing:
            raise serializers.ValidationError("All featured testimonies must exist and be approved.")
        return value
