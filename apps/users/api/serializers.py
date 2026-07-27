from rest_framework import serializers

from apps.users.choices import UserAccountStatus
from apps.users.models import Profile
from apps.users.validators import normalize_full_name


class ProfileSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(source="user.email", read_only=True)

    class Meta:
        model = Profile
        fields = ("full_name", "email", "phone_number", "avatar")

    def validate_full_name(self, value: str) -> str:
        return normalize_full_name(value)


class AdminUserSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    email = serializers.EmailField(read_only=True)
    full_name = serializers.CharField(read_only=True)
    account_status = serializers.ChoiceField(choices=UserAccountStatus.choices, read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
