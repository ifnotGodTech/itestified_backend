import re

from django.core.validators import validate_email
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from apps.profile_content.choices import ProfileContentKey
from apps.profile_content.models import HelpFaqEntry, ProfileContentBlock

# Deliberately permissive -- this only guards against obvious garbage
# (empty of any digits), not a strict E.164 check, since support numbers
# are entered by hand and may include spaces/dashes/parens.
PHONE_PATTERN = re.compile(r"^[\d+][\d+\s\-()]*$")


class ProfileContentBlockSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProfileContentBlock
        fields = ("key", "body", "updated_at")
        read_only_fields = ("key", "updated_at")

    def validate_body(self, value: str) -> str:
        # The key isn't part of the payload (it's read-only, supplied by the
        # view via the URL) -- the view passes it through context so this
        # can apply key-specific format rules to a field the model itself
        # just stores as freeform text.
        key = self.context.get("key")
        value = value.strip()
        if key == ProfileContentKey.SUPPORT_EMAIL and value:
            try:
                validate_email(value)
            except DjangoValidationError:
                raise serializers.ValidationError("Enter a valid support email address.")
        if key == ProfileContentKey.SUPPORT_PHONE and value and not PHONE_PATTERN.match(value):
            raise serializers.ValidationError("Enter a valid support phone number.")
        return value


class HelpFaqEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = HelpFaqEntry
        fields = ("id", "question", "answer", "display_order", "is_active", "updated_at")
        read_only_fields = ("id", "display_order", "updated_at")

    def validate_question(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Question cannot be blank.")
        return value

    def validate_answer(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Answer cannot be blank.")
        return value


class HelpFaqReorderSerializer(serializers.Serializer):
    ordered_ids = serializers.ListField(child=serializers.IntegerField(min_value=1), allow_empty=False)

    def validate_ordered_ids(self, value: list[int]) -> list[int]:
        existing_ids = set(HelpFaqEntry.objects.values_list("id", flat=True))
        submitted_ids = set(value)
        if submitted_ids != existing_ids:
            raise serializers.ValidationError("ordered_ids must include every existing FAQ entry exactly once.")
        return value
