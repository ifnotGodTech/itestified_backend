import re

from rest_framework import serializers

from apps.app_versions.models import AppVersionConfig

VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+(\+\d+)?$")


def _version_tuple(value: str) -> tuple[int, int, int, int]:
    # Build number is an optional tie-breaker: apps that ship multiple
    # builds under the same MAJOR.MINOR.PATCH (e.g. a Play Store metadata
    # resubmission) can still be gated on a specific build. Omitted on
    # either side defaults to 0, so bare "1.2.0" entries keep working
    # exactly as before.
    version_part, _, build_part = value.partition("+")
    major, minor, patch = version_part.split(".")
    build = int(build_part) if build_part else 0
    return (int(major), int(minor), int(patch), build)


class AppVersionConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = AppVersionConfig
        fields = ("platform", "minimum_version", "latest_version", "updated_at")
        read_only_fields = ("platform", "updated_at")

    def _validate_version_format(self, value: str) -> str:
        value = value.strip()
        if not VERSION_PATTERN.match(value):
            raise serializers.ValidationError(
                "Version must be in the form MAJOR.MINOR.PATCH, e.g. 1.2.0 "
                "(optionally with a build number, e.g. 1.2.0+40)."
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
        # A row must never exist without a real minimum -- "no minimum
        # required" is represented by having no row at all, not by a row
        # with a blank minimum_version. partial=True otherwise lets this
        # slip through on first-time creation when only latest_version is
        # submitted.
        if self.instance is None and not minimum:
            raise serializers.ValidationError(
                {"minimum_version": "Minimum version is required when configuring a platform for the first time."}
            )
        if minimum and latest and _version_tuple(latest) < _version_tuple(minimum):
            raise serializers.ValidationError(
                "Latest version cannot be lower than the minimum version."
            )
        return attrs
