import re

from django.core.validators import validate_email
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from apps.profile_content.choices import ProfileContentKey
from apps.profile_content.models import ProfileContentBlock

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
