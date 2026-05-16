from rest_framework import serializers

from apps.users.models import Profile


class ProfileSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(source="user.email", read_only=True)

    class Meta:
        model = Profile
        fields = ("full_name", "email", "phone_number", "avatar")
