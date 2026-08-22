from rest_framework import serializers

from ..models import BrandedVideoExport, MediaExportBrandingConfig
from ..services import build_share_caption, default_logo_url, testimony_share_url


class BrandedVideoExportSerializer(serializers.ModelSerializer):
    testimony_id = serializers.IntegerField(source="testimony.id", read_only=True)
    testimony_title = serializers.CharField(source="testimony.title", read_only=True)
    share_url = serializers.SerializerMethodField()
    share_caption = serializers.SerializerMethodField()

    class Meta:
        model = BrandedVideoExport
        fields = (
            "id", "testimony_id", "testimony_title", "branding_version", "status",
            "branded_video_url", "share_url", "share_caption", "error_message",
            "retry_count", "created_at", "updated_at",
        )

    def get_share_url(self, obj):
        return testimony_share_url(obj.testimony_id)

    def get_share_caption(self, obj):
        return build_share_caption(title=obj.testimony.title, testimony_id=obj.testimony_id)


class MediaExportBrandingConfigSerializer(serializers.ModelSerializer):
    # The permanent fallback mark, always present regardless of whether an
    # admin has uploaded a custom one -- lets the dashboard show it as a
    # real option instead of hardcoding the Cloudinary cloud name itself.
    default_logo_url = serializers.SerializerMethodField()

    class Meta:
        model = MediaExportBrandingConfig
        fields = (
            "id", "logo_url", "default_logo_url", "watermark_text", "call_to_action", "end_card_url",
            "is_enabled", "version", "updated_by", "created_at", "updated_at",
        )
        read_only_fields = ("id", "version", "updated_by", "created_at", "updated_at")

    def get_default_logo_url(self, obj):
        return default_logo_url()

    def validate_watermark_text(self, value):
        return value.strip()

    def validate_call_to_action(self, value):
        return value.strip()
