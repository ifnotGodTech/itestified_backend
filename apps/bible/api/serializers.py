from rest_framework import serializers

from apps.bible.models import BiblePack, BiblePackChange


class BiblePackSerializer(serializers.ModelSerializer):
    class Meta:
        model = BiblePack
        fields = (
            "code",
            "kind",
            "name",
            "abbreviation",
            "description",
            "attribution",
            "supports_word_study",
            "is_online_only",
            "file_url",
            "size_bytes",
            "sha256",
            "data_version",
            "is_default",
        )
        read_only_fields = fields


def _person(user) -> str:
    if user is None:
        return ""
    profile = getattr(user, "profile", None)
    if profile and profile.full_name.strip():
        return profile.full_name
    return user.email


class AdminBiblePackSerializer(serializers.ModelSerializer):
    """Phase 34 Slice 8: everything the admin's Bible settings show, hidden
    packs included."""

    class Meta:
        model = BiblePack
        fields = (
            "code",
            "kind",
            "name",
            "abbreviation",
            "description",
            "attribution",
            "supports_word_study",
            "is_online_only",
            "file_url",
            "size_bytes",
            "sha256",
            "data_version",
            "is_enabled",
            "is_default",
            "updated_at",
        )
        read_only_fields = fields


class AdminBiblePackChangeSerializer(serializers.ModelSerializer):
    pack_code = serializers.CharField(source="pack.code", read_only=True)
    pack_name = serializers.CharField(source="pack.name", read_only=True)
    actor_name = serializers.SerializerMethodField()

    class Meta:
        model = BiblePackChange
        fields = ("pack_code", "pack_name", "action", "actor_name", "created_at")
        read_only_fields = fields

    def get_actor_name(self, obj: BiblePackChange) -> str:
        return _person(obj.actor)
