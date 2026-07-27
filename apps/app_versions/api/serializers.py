import re

from rest_framework import serializers

from apps.app_versions.models import AppVersionConfig

VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")


def _version_tuple(value: str) -> tuple[int, int, int]:
    major, minor, patch = value.split(".")
    return (int(major), int(minor), int(patch))


class AppVersionConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = AppVersionConfig
        fields = ("platform", "minimum_version", "latest_version", "updated_at")
        read_only_fields = ("platform", "updated_at")

    def _validate_version_format(self, value: str) -> str:
        value = value.strip()
        if not VERSION_PATTERN.match(value):
            raise serializers.ValidationError(
                "Version must be in the form MAJOR.MINOR.PATCH, e.g. 1.2.0."
            )
        return value

    def validate_minimum_version(self, value: str) -> str:
        return self._validate_version_format(value)

    def validate_latest_version(self, value: str) -> str:
        value = value.strip()
        if not value:
            return value
        return self._validate_version_format(value)

    def validate(self, attrs):
        minimum = attrs.get(
            "minimum_version", getattr(self.instance, "minimum_version", "") if self.instance else ""
        )
        latest = attrs.get(
            "latest_version", getattr(self.instance, "latest_version", "") if self.instance else ""
        )
        if minimum and latest and _version_tuple(latest) < _version_tuple(minimum):
            raise serializers.ValidationError(
                "Latest version cannot be lower than the minimum version."
            )
        return attrs
