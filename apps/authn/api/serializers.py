from rest_framework import serializers


class StartRegistrationSerializer(serializers.Serializer):
    full_name = serializers.CharField(max_length=255)
    email = serializers.EmailField()


class VerifyCodeSerializer(serializers.Serializer):
    email = serializers.EmailField()
    otp = serializers.CharField(max_length=12)


class CompleteRegistrationSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField()


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField()


class MobileGoogleSignInSerializer(serializers.Serializer):
    id_token = serializers.CharField()
    platform = serializers.ChoiceField(choices=("android", "ios"), required=False)


class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()


class CompletePasswordResetSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField()


class AdminCreatePasswordSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField()
    confirm_password = serializers.CharField()
    entry_code = serializers.CharField(max_length=64)

    def validate(self, attrs):
        if attrs["password"] != attrs["confirm_password"]:
            raise serializers.ValidationError({"confirm_password": "Passwords do not match."})
        return attrs


class AdminInviteSerializer(serializers.Serializer):
    email = serializers.EmailField()
    role_code = serializers.ChoiceField(
        choices=("moderator", "content_admin", "finance_admin"),
    )


class AdminInviteVerifySerializer(serializers.Serializer):
    email = serializers.EmailField()
    otp = serializers.CharField(max_length=12)


class AdminInviteCompleteSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField()


class ChangeTemporaryPasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField()
    new_password = serializers.CharField()
    confirm_new_password = serializers.CharField()

    def validate(self, attrs):
        if attrs["new_password"] != attrs["confirm_new_password"]:
            raise serializers.ValidationError({"confirm_new_password": "Passwords do not match."})
        return attrs
