from rest_framework import serializers

from apps.notifications.models import UserNotification, UserNotificationPreference


class UserNotificationSerializer(serializers.ModelSerializer):
    actor_email = serializers.EmailField(source="actor.email", read_only=True, allow_null=True)
    recipient_email = serializers.EmailField(source="recipient.email", read_only=True)

    class Meta:
        model = UserNotification
        fields = (
            "id",
            "notification_type",
            "title",
            "message",
            "is_read",
            "actor_email",
            "recipient_email",
            "created_at",
        )


class NotificationMarkReadSerializer(serializers.Serializer):
    notification_id = serializers.IntegerField(required=False)


class UserNotificationPreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserNotificationPreference
        fields = (
            "allow_email_notifications",
            "notify_new_donation_received",
            "send_donation_thank_you_email",
            "updated_at",
        )
        read_only_fields = ("updated_at",)
