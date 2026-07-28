from rest_framework import serializers

from apps.social_links.models import SocialLink


class SocialLinkSerializer(serializers.ModelSerializer):
    class Meta:
        model = SocialLink
        fields = ("platform", "url", "is_active", "display_order", "updated_at")
        read_only_fields = ("platform", "updated_at")
