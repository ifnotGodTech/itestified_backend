from __future__ import annotations

from rest_framework import serializers

from apps.creators.models import CreatorProfile
from apps.testimonies.models import TestimonyReaction


class CreatorProfileSerializer(serializers.ModelSerializer):
    """Own-profile create/update/read shape (Slice 1). `user_id` lets
    mobile open this same account's public profile in preview (Slice 13's
    "View public profile" action) without a second lookup."""

    user_id = serializers.IntegerField(source="user.id", read_only=True)

    class Meta:
        model = CreatorProfile
        fields = (
            "id",
            "user_id",
            "display_name",
            "bio",
            "avatar_url",
            "is_verified",
            "verified_at",
            "verification_requested_at",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "user_id",
            "is_verified",
            "verified_at",
            "verification_requested_at",
            "created_at",
            "updated_at",
        )

    def validate_display_name(self, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise serializers.ValidationError("Display name can't be blank.")
        return stripped


class PublicCreatorProfileSerializer(serializers.ModelSerializer):
    """Public-facing shape (Slice 1 read + Slice 2 follow-state) -- what a
    follower sees, per the reviewed Phase 23 mockup. follower_count and
    is_following are annotated onto the instance by the view rather than
    computed here, since they need the requesting user's id."""

    user_id = serializers.IntegerField(source="user.id", read_only=True)
    follower_count = serializers.IntegerField(read_only=True)
    is_following = serializers.BooleanField(read_only=True)

    class Meta:
        model = CreatorProfile
        fields = (
            "user_id",
            "display_name",
            "bio",
            "avatar_url",
            "is_verified",
            "follower_count",
            "is_following",
        )


class PrayerReactionInboxSerializer(serializers.ModelSerializer):
    """Phase 23 Slice 4 -- one row per praying_for_you reaction on the
    creator's own testimonies. `response` is null until responded, matching
    the reviewed mockup's "Respond" vs "Responded" row states."""

    reactor_id = serializers.IntegerField(source="user.id", read_only=True)
    reactor_name = serializers.SerializerMethodField()
    testimony_id = serializers.IntegerField(source="testimony.id", read_only=True)
    testimony_title = serializers.CharField(source="testimony.title", read_only=True)
    response = serializers.SerializerMethodField()

    class Meta:
        model = TestimonyReaction
        fields = ("id", "reactor_id", "reactor_name", "testimony_id", "testimony_title", "created_at", "response")

    def get_reactor_name(self, obj: TestimonyReaction) -> str:
        profile = getattr(obj.user, "profile", None)
        if profile and profile.full_name.strip():
            return profile.full_name
        return obj.user.email

    def get_response(self, obj: TestimonyReaction) -> dict | None:
        response = getattr(obj, "prayer_response", None)
        if response is None:
            return None
        return {"response_text": response.response_text, "created_at": response.created_at}


class PrayerResponseCreateSerializer(serializers.Serializer):
    response_text = serializers.CharField()

    def validate_response_text(self, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise serializers.ValidationError("Response can't be blank.")
        return stripped


class AdminCreatorProfileSerializer(serializers.ModelSerializer):
    """Phase 23 Slice 5 (admin)."""

    user_id = serializers.IntegerField(source="user.id", read_only=True)
    user_email = serializers.CharField(source="user.email", read_only=True)
    verified_by_email = serializers.CharField(source="verified_by.email", read_only=True, default=None)

    class Meta:
        model = CreatorProfile
        fields = (
            "id",
            "user_id",
            "user_email",
            "display_name",
            "bio",
            "avatar_url",
            "is_verified",
            "verified_at",
            "verification_requested_at",
            "verified_by_email",
            "created_at",
        )
