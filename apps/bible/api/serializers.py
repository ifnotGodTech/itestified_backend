from rest_framework import serializers

from apps.bible.models import BiblePack


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
