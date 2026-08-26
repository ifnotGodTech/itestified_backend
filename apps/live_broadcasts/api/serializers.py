import re

from rest_framework import serializers

from apps.live_broadcasts.models import (
    LiveBroadcast,
    LiveBroadcastApprovalRequest,
    LiveMinutePricing,
    LiveMinutePurchase,
    LiveStreamingPolicy,
)
from apps.testimonies.models import TestimonyCategory

_CURRENCY_CODE_RE = re.compile(r"^[A-Za-z]{3}$")


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


class AdminActiveBroadcastSerializer(serializers.ModelSerializer):
    """Phase 27 Slice 7 -- admin monitoring, active-now section. Reads
    `viewer_count`/`elapsed_seconds`/`reserved_minutes_this_month`/
    `total_allowance_minutes`/`remaining_allowance_minutes` as plain
    attributes already attached by `selectors.list_active_broadcasts_for_admin`
    (never computed here -- an external REST call and cross-model
    aggregation are selector/service concerns, not serializer ones)."""

    ministry_id = serializers.CharField(source="creator_id", read_only=True)
    ministry_name = serializers.SerializerMethodField()
    ministry_avatar = serializers.SerializerMethodField()
    elapsed_seconds = serializers.IntegerField(read_only=True)
    viewer_count = serializers.IntegerField(read_only=True, allow_null=True)
    reserved_minutes_this_month = serializers.IntegerField(read_only=True)
    total_allowance_minutes = serializers.IntegerField(read_only=True)
    remaining_allowance_minutes = serializers.IntegerField(read_only=True)

    class Meta:
        model = LiveBroadcast
        fields = [
            "id",
            "title",
            "started_at",
            "elapsed_seconds",
            "ministry_id",
            "ministry_name",
            "ministry_avatar",
            "viewer_count",
            "max_viewers_applied",
            "max_duration_minutes_applied",
            "reserved_minutes_this_month",
            "total_allowance_minutes",
            "remaining_allowance_minutes",
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


class AdminScheduledBroadcastSerializer(serializers.ModelSerializer):
    """Phase 27 Slice 7 -- admin monitoring, scheduled/upcoming section.
    No viewer/usage figures here (nothing to measure yet); the caps that
    *will* apply come from the current `LiveStreamingPolicy`, returned
    once as a sibling `policy` object in `AdminBroadcastMonitorView`'s
    response rather than repeated identically on every row."""

    ministry_id = serializers.CharField(source="creator_id", read_only=True)
    ministry_name = serializers.SerializerMethodField()
    ministry_avatar = serializers.SerializerMethodField()

    class Meta:
        model = LiveBroadcast
        fields = ["id", "title", "scheduled_at", "ministry_id", "ministry_name", "ministry_avatar"]
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


class AdminEndBroadcastSerializer(serializers.Serializer):
    """Phase 27 Slice 8 -- a reason is required every time, mirroring the
    existing reject-with-reason validation shape used elsewhere in this
    codebase (e.g. `apps.donations`' admin reversal reason)."""

    reason = serializers.CharField(min_length=3, max_length=1000)


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


class LiveStreamingPolicySerializer(serializers.ModelSerializer):
    updated_by_email = serializers.EmailField(source="updated_by.email", read_only=True, default="")

    class Meta:
        model = LiveStreamingPolicy
        fields = [
            "is_enabled",
            "max_concurrent_viewers",
            "max_duration_minutes",
            "shared_monthly_ceiling_minutes",
            "default_ministry_monthly_allowance_minutes",
            "updated_by_email",
            "updated_at",
        ]
        read_only_fields = fields


class UpdateLiveStreamingPolicySerializer(serializers.Serializer):
    is_enabled = serializers.BooleanField()
    max_concurrent_viewers = serializers.IntegerField(min_value=1)
    max_duration_minutes = serializers.IntegerField(min_value=1)
    shared_monthly_ceiling_minutes = serializers.IntegerField(min_value=1)
    default_ministry_monthly_allowance_minutes = serializers.IntegerField(min_value=1)


class LiveMinutePricingSerializer(serializers.ModelSerializer):
    updated_by_email = serializers.EmailField(source="updated_by.email", read_only=True, default="")

    class Meta:
        model = LiveMinutePricing
        fields = ["currency", "price_per_1000_minutes", "updated_by_email", "updated_at"]
        read_only_fields = fields


class SetLiveMinutePriceSerializer(serializers.Serializer):
    currency = serializers.CharField(max_length=3)
    price_per_1000_minutes = serializers.IntegerField(min_value=1)

    def validate_currency(self, value: str) -> str:
        currency = value.strip().upper()
        if not _CURRENCY_CODE_RE.fullmatch(currency):
            raise serializers.ValidationError("Currency must be a 3-letter code, e.g. NGN or USD.")
        return currency


class MinistryUsageRowSerializer(serializers.Serializer):
    """Phase 27 Slice 9 -- one row of selectors.list_ministry_usage_for_current_month's
    per-Ministry dicts. Mirrors PublicLiveBroadcastSerializer's own
    ministry display-name/avatar fallback chain."""

    ministry_id = serializers.SerializerMethodField()
    ministry_name = serializers.SerializerMethodField()
    ministry_avatar = serializers.SerializerMethodField()
    base_allowance_minutes = serializers.IntegerField()
    purchased_minutes = serializers.IntegerField()
    total_allowance_minutes = serializers.IntegerField()
    reserved_minutes = serializers.IntegerField()
    remaining_minutes = serializers.IntegerField()

    def get_ministry_id(self, obj: dict) -> int:
        return obj["creator"].id

    def get_ministry_name(self, obj: dict) -> str:
        creator = obj["creator"]
        creator_profile = getattr(creator, "creator_profile", None)
        if creator_profile and creator_profile.display_name.strip():
            return creator_profile.display_name
        profile = getattr(creator, "profile", None)
        if profile and profile.full_name.strip():
            return profile.full_name
        return creator.email

    def get_ministry_avatar(self, obj: dict) -> str:
        creator = obj["creator"]
        creator_profile = getattr(creator, "creator_profile", None)
        if creator_profile and creator_profile.avatar_url:
            return creator_profile.avatar_url
        profile = getattr(creator, "profile", None)
        return profile.avatar if profile else ""


class PlatformUsageSummarySerializer(serializers.Serializer):
    year = serializers.IntegerField()
    month = serializers.IntegerField()
    used_minutes = serializers.IntegerField(allow_null=True)
    shared_monthly_ceiling_minutes = serializers.IntegerField()
