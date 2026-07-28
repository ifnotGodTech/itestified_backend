from rest_framework import serializers

from apps.profile_content.models import ProfileContentBlock


class ProfileContentBlockSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProfileContentBlock
        fields = ("key", "body", "updated_at")
        read_only_fields = ("key", "updated_at")
