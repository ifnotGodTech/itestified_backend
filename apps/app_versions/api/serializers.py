import re

from rest_framework import serializers

from apps.app_versions.models import AppVersionConfig

VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")


class AppVersionConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = AppVersionConfig
        fields = ("platform", "minimum_version", "updated_at")
        read_only_fields = ("platform", "updated_at")

    def validate_minimum_version(self, value: str) -> str:
        value = value.strip()
        if not VERSION_PATTERN.match(value):
            raise serializers.ValidationError(
                "Version must be in the form MAJOR.MINOR.PATCH, e.g. 1.2.0."
            )
        return value
