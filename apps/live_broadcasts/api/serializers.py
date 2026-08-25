from rest_framework import serializers

from apps.live_broadcasts.models import (
    LiveBroadcast,
    LiveBroadcastApprovalRequest,
    LiveMinutePurchase,
)


class LiveBroadcastSerializer(serializers.ModelSerializer):
    class Meta:
        model = LiveBroadcast
        fields = [
            "id",
            "title",
            "status",
            "scheduled_at",
            "started_at",
            "ended_at",
            "agora_channel_name",
            "max_viewers_applied",
            "max_duration_minutes_applied",
            "created_at",
        ]
        read_only_fields = fields


class CreateLiveBroadcastSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=255)
    scheduled_at = serializers.DateTimeField(required=False, allow_null=True, default=None)

    def validate_title(self, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise serializers.ValidationError("Title is required.")
        return trimmed


class PublisherCredentialSerializer(serializers.Serializer):
    app_id = serializers.CharField()
    channel_name = serializers.CharField()
    uid = serializers.IntegerField()
    token = serializers.CharField()
    expires_at_unix = serializers.IntegerField()


class AllowanceSerializer(serializers.Serializer):
    year = serializers.IntegerField()
    month = serializers.IntegerField()
    base_allowance_minutes = serializers.IntegerField()
    purchased_minutes = serializers.IntegerField()
    total_allowance_minutes = serializers.IntegerField()
    reserved_minutes = serializers.IntegerField()
    remaining_minutes = serializers.IntegerField()


class InitiateMinutePurchaseSerializer(serializers.Serializer):
    minutes = serializers.IntegerField(min_value=1)
    currency = serializers.CharField(max_length=3)


class LiveMinutePurchaseSerializer(serializers.ModelSerializer):
    class Meta:
        model = LiveMinutePurchase
        fields = [
            "id",
            "minutes",
            "amount",
            "currency",
            "status",
            "payment_reference",
            "checkout_url",
            "created_at",
        ]
        read_only_fields = fields


class VerifyMinutePurchaseSerializer(serializers.Serializer):
    transaction_id = serializers.CharField()


class RequestBroadcastApprovalSerializer(serializers.Serializer):
    requested_minutes = serializers.IntegerField(min_value=1)


class LiveBroadcastApprovalRequestSerializer(serializers.ModelSerializer):
    creator_email = serializers.EmailField(source="creator.email", read_only=True)

    class Meta:
        model = LiveBroadcastApprovalRequest
        fields = [
            "id",
            "broadcast",
            "creator_email",
            "requested_minutes",
            "status",
            "reviewed_at",
            "review_note",
            "created_at",
        ]
        read_only_fields = fields


class DecideBroadcastApprovalSerializer(serializers.Serializer):
    approve = serializers.BooleanField()
    note = serializers.CharField(required=False, allow_blank=True, default="")
