from __future__ import annotations

from django.utils import timezone

from apps.creators.exceptions import (
    CannotFollowSelfError,
    CreatorProfileAlreadyExistsError,
    CreatorProfileNotEligibleError,
    CreatorProfileNotFoundError,
    PrayerReactionAlreadyRespondedError,
    PrayerReactionNotFoundError,
    PrayerReactionNotOwnedByCreatorError,
    PrayerReactionWrongTypeError,
)
from apps.creators.models import CreatorFollow, CreatorProfile, PrayerResponse
from apps.notifications.services import notify_prayer_response
from apps.subscriptions.selectors import is_user_premium
from apps.testimonies.models import TestimonyReaction, TestimonyReactionType


def create_creator_profile(*, user, display_name: str, bio: str = "", avatar_url: str = "") -> CreatorProfile:
    """Phase 23 Slice 1. Premium-gated regardless of content type (see
    Phase 23's Background note) -- not a DB constraint, since premium
    status changes over time and a schema constraint can't reference
    another table's live state."""
    if not is_user_premium(user):
        raise CreatorProfileNotEligibleError("A Premium subscription is required to create a Ministry profile.")
    if CreatorProfile.objects.filter(user=user).exists():
        raise CreatorProfileAlreadyExistsError("This account already has a Ministry profile.")

    return CreatorProfile.objects.create(user=user, display_name=display_name, bio=bio, avatar_url=avatar_url)


def update_creator_profile(
    *, user, display_name: str | None = None, bio: str | None = None, avatar_url: str | None = None
) -> CreatorProfile:
    """A lapsed-Premium creator keeps their existing profile fully intact
    (never clawed back) but can't edit it until resubscribed -- same rule
    Phase 21 applies to cancellation and Phase 32 applies to upload."""
    if not is_user_premium(user):
        raise CreatorProfileNotEligibleError("A Premium subscription is required to edit your Ministry profile.")
    try:
        profile = CreatorProfile.objects.get(user=user)
    except CreatorProfile.DoesNotExist as exc:
        raise CreatorProfileNotFoundError("No Ministry profile exists for this account.") from exc

    update_fields = []
    if display_name is not None:
        profile.display_name = display_name
        update_fields.append("display_name")
    if avatar_url is not None:
        profile.avatar_url = avatar_url
        update_fields.append("avatar_url")
    if bio is not None:
        profile.bio = bio
        update_fields.append("bio")
    if update_fields:
        update_fields.append("updated_at")
        profile.save(update_fields=update_fields)
    return profile


def follow_creator(*, follower, creator_user_id: int) -> CreatorFollow:
    """Idempotent -- a repeat follow call reuses the existing row rather
    than erroring or duplicating it (get_or_create), matching Phase 23's
    own test requirement. Works regardless of the target's verified
    status -- verification is a trust badge, never a follow-gate."""
    if follower.id == creator_user_id:
        raise CannotFollowSelfError("You can't follow yourself.")
    if not CreatorProfile.objects.filter(user_id=creator_user_id).exists():
        raise CreatorProfileNotFoundError("This account doesn't have a Ministry profile.")

    follow, _ = CreatorFollow.objects.get_or_create(follower=follower, creator_id=creator_user_id)
    return follow


def unfollow_creator(*, follower, creator_user_id: int) -> None:
    """Idempotent -- unfollowing a creator you don't follow is a safe no-op,
    never a 404/error."""
    CreatorFollow.objects.filter(follower=follower, creator_id=creator_user_id).delete()


def respond_to_prayer_reaction(*, creator, reaction_id: int, response_text: str) -> PrayerResponse:
    """Phase 23 Slice 4. Scoped to praying_for_you reactions on the
    creator's own testimonies only -- see the individual exceptions below
    for each rejected case. Response reaches the original reactor as a
    real notification (notify_prayer_response), not just a
    dashboard-visible log row, per Phase 23's own test requirement."""
    try:
        reaction = TestimonyReaction.objects.select_related("testimony", "user").get(id=reaction_id)
    except TestimonyReaction.DoesNotExist as exc:
        raise PrayerReactionNotFoundError("Reaction not found.") from exc

    if reaction.testimony.author_id != creator.id:
        raise PrayerReactionNotOwnedByCreatorError("You can only respond to reactions on your own testimonies.")
    if reaction.reaction_type != TestimonyReactionType.PRAYING_FOR_YOU:
        raise PrayerReactionWrongTypeError("Only 'Praying for you' reactions can be responded to.")
    if PrayerResponse.objects.filter(reaction=reaction).exists():
        raise PrayerReactionAlreadyRespondedError("This reaction has already been responded to.")

    try:
        creator_profile = CreatorProfile.objects.get(user=creator)
    except CreatorProfile.DoesNotExist as exc:
        raise CreatorProfileNotFoundError("Only Ministry accounts can respond to prayer reactions.") from exc

    response = PrayerResponse.objects.create(reaction=reaction, responded_by=creator, response_text=response_text)
    notify_prayer_response(
        recipient=reaction.user,
        actor=creator,
        creator_display_name=creator_profile.display_name,
        testimony_title=reaction.testimony.title,
        response_text=response_text,
    )
    return response


def request_creator_verification(*, user) -> CreatorProfile:
    """Phase 23 Slice 14 -- owner-initiated, idempotent: a repeat call once
    already requested or already verified is a no-op, not an error,
    matching this app's established follow/unfollow idempotency
    convention rather than raising on a harmless double-tap."""
    try:
        profile = CreatorProfile.objects.get(user=user)
    except CreatorProfile.DoesNotExist as exc:
        raise CreatorProfileNotFoundError("No Ministry profile exists for this account.") from exc

    if profile.verification_requested_at is None and not profile.is_verified:
        profile.verification_requested_at = timezone.now()
        profile.save(update_fields=["verification_requested_at", "updated_at"])
    return profile


def verify_creator_profile(*, creator_profile: CreatorProfile, admin_user, is_verified: bool) -> CreatorProfile:
    """Phase 23 Slice 5 (admin). Never touches moderation status or
    visibility of the creator's testimonies -- verification and moderation
    are fully independent systems, by design (see Phase 23's Background
    note on not mixing identity trust with content trust)."""
    creator_profile.is_verified = is_verified
    creator_profile.verified_at = timezone.now() if is_verified else None
    creator_profile.verified_by = admin_user if is_verified else None
    creator_profile.save(update_fields=["is_verified", "verified_at", "verified_by", "updated_at"])
    return creator_profile
