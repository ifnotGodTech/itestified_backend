from rest_framework import serializers

from apps.live_broadcasts.models import (
    LiveBroadcast,
    LiveBroadcastApprovalRequest,
    LiveMinutePurchase,
)
from apps.testimonies.models import TestimonyCategory


class PublicLiveBroadcastSerializer(serializers.ModelSerializer):
    """Phase 27 Slice 2 -- what a viewer (including a guest) sees browsing
    live-now/upcoming broadcasts. Mirrors TestimonyListSerializer's own
    author_name/author_avatar fallback chain (Phase 23 Slice 10) exactly:
    every LiveBroadcast creator is already a verified Ministry by
    construction, but the same defensive fallback is kept for
    consistency. Callers must select_related "creator__creator_profile",
    "creator__profile" to stay free of N+1 queries."""

    ministry_id = serializers.CharField(source="creator_id", read_only=True)
    ministry_name = serializers.SerializerMethodField()
    ministry_avatar = serializers.SerializerMethodField()

    class Meta:
        model = LiveBroadcast
        fields = [
            "id",
            "title",
            "status",
            "scheduled_at",
            "started_at",
            "ministry_id",
            "ministry_name",
            "ministry_avatar",
        ]
        read_only_fields = fields

    def get_ministry_name(self, obj: LiveBroadcast) -> str:
        creator_profile = getattr(obj.creator, "creator_profile", None)
        if creator_profile and creator_profile.display_name.strip():
            return creator_profile.display_name
        profile = getattr(obj.creator, "profile", None)
        if profile and profile.full_name.strip():
            return profile.full_name
        return obj.creator.email

    def get_ministry_avatar(self, obj: LiveBroadcast) -> str:
        creator_profile = getattr(obj.creator, "creator_profile", None)
        if creator_profile and creator_profile.avatar_url:
            return creator_profile.avatar_url
        profile = getattr(obj.creator, "profile", None)
        return profile.avatar if profile else ""


class ViewerJoinCredentialSerializer(serializers.Serializer):
    app_id = serializers.CharField()
    channel_name = serializers.CharField()
    uid = serializers.IntegerField()
    token = serializers.CharField()
    expires_at_unix = serializers.IntegerField()
    ministry_name = serializers.CharField()
    ministry_avatar = serializers.CharField()
    title = serializers.CharField()


class LiveBroadcastSerializer(serializers.ModelSerializer):
    class Meta:
        model = LiveBroadcast
        fields = [
            "id",
            "title",
            "category",
            "status",
            "scheduled_at",
            "started_at",
            "ended_at",
            "ended_reason",
            "agora_channel_name",
            "max_viewers_applied",
            "max_duration_minutes_applied",
            "recording_status",
            "archived_testimony",
            "created_at",
        ]
        read_only_fields = fields


class CreateLiveBroadcastSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=255)
    category_id = serializers.PrimaryKeyRelatedField(
        source="category",
        queryset=TestimonyCategory.objects.filter(is_active=True),
    )
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
