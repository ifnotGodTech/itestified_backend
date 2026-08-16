from django.utils import timezone
from rest_framework import serializers

from apps.content.models import (
    FeaturedHomePicture,
    FeaturedHomeTestimony,
    HomePromoCard,
    HomePromoCtaDestination,
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


class ScriptureReadInputSerializer(serializers.Serializer):
    # Required, not defaulted server-side -- the whole point is trusting the
    # client's own local calendar date over the server's (see
    # mark_scripture_read's docstring).
    read_date = serializers.DateField()


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


class FeaturedHomePictureSerializer(serializers.ModelSerializer):
    picture_id = serializers.IntegerField(source="picture.id", read_only=True)
    title = serializers.CharField(source="picture.title", read_only=True)
    caption = serializers.CharField(source="picture.caption", read_only=True)
    category = serializers.SerializerMethodField()
    source = serializers.CharField(source="picture.source", read_only=True)
    image_url = serializers.CharField(source="picture.image_url", read_only=True)
    created_at = serializers.DateTimeField(source="picture.created_at", read_only=True)

    class Meta:
        model = FeaturedHomePicture
        fields = (
            "id",
            "picture_id",
            "position",
            "title",
            "caption",
            "category",
            "source",
            "image_url",
            "created_at",
        )

    def get_category(self, obj: FeaturedHomePicture) -> str:
        return obj.picture.category.name if obj.picture.category_id else ""


class HomeCurationUpdateSerializer(serializers.Serializer):
    section_order = serializers.ListField(
        child=serializers.ChoiceField(choices=HomeSectionKey.values),
        allow_empty=False,
    )
    featured_testimony_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        allow_empty=True,
    )
    featured_picture_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        allow_empty=True,
        required=False,
        default=list,
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

    def validate_featured_picture_ids(self, value):
        if not value:
            return value
        pictures = InspirationalPicture.objects.filter(id__in=value, status=InspirationalPictureStatus.PUBLISHED)
        found_ids = {item.id for item in pictures}
        missing = [item_id for item_id in value if item_id not in found_ids]
        if missing:
            raise serializers.ValidationError("All featured pictures must exist and be published.")
        return value


class HomePromoCardSerializer(serializers.ModelSerializer):
    status = serializers.SerializerMethodField()
    updated_by_email = serializers.EmailField(source="updated_by.email", read_only=True, default="")

    class Meta:
        model = HomePromoCard
        fields = (
            "id",
            "title",
            "body",
            "image_url",
            "cta_label",
            "cta_destination",
            "cta_url",
            "starts_at",
            "ends_at",
            "is_active",
            "status",
            "updated_by_email",
            "created_at",
            "updated_at",
        )

    def get_status(self, obj: HomePromoCard) -> str:
        return obj.computed_status()

    def validate(self, attrs):
        starts_at = attrs.get("starts_at", getattr(self.instance, "starts_at", None))
        ends_at = attrs.get("ends_at", getattr(self.instance, "ends_at", None))
        if starts_at and ends_at and ends_at <= starts_at:
            raise serializers.ValidationError({"ends_at": "Must be after the start date."})

        cta_label = attrs.get("cta_label", getattr(self.instance, "cta_label", "")) or ""
        cta_destination = attrs.get("cta_destination", getattr(self.instance, "cta_destination", "")) or ""
        has_cta = bool(cta_label or cta_destination)
        if has_cta and not (cta_label and cta_destination):
            raise serializers.ValidationError("A CTA needs both a label and a destination, or neither.")
        if cta_destination == HomePromoCtaDestination.EXTERNAL_URL:
            cta_url = attrs.get("cta_url", getattr(self.instance, "cta_url", "")) or ""
            if not cta_url:
                raise serializers.ValidationError({"cta_url": "Required when the CTA destination is an external URL."})
        return attrs
