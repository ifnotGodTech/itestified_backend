from django.conf import settings
from django.db import models
from django.db.models import Q


class CreatorProfile(models.Model):
    """Phase 23 Slice 1 -- a Ministry/Creator account. OneToOne to User (not
    Profile) to stay consistent with Testimony.author already being a User
    FK. Creation is entitlement-checked in services/commands.py via
    apps.subscriptions.selectors.is_user_premium, not a DB constraint --
    premium status changes over time and a schema constraint can't
    reference another table's live state. Losing Premium never deletes
    this row (same "never claw back what's already there" rule as Phase 21
    cancellation and Phase 32's own upload gating) -- it only blocks
    Ministry-specific writes until resubscribed, enforced in commands.py."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="creator_profile",
    )
    display_name = models.CharField(max_length=255)
    bio = models.TextField(blank=True)
    # Deliberately separate from Profile.avatar (the personal account
    # photo) -- a Ministry can have a distinct public-facing photo from
    # whoever operates it. Same signed-direct-to-Cloudinary pattern as
    # the personal avatar (apps.common.services.media_uploads), its own
    # "creator_avatar" resource_type/folder.
    avatar_url = models.URLField(blank=True)
    # Admin-granted trust signal, layered on top of the Premium gate above
    # rather than replacing it -- see Phase 23's Background note. Never
    # gates followability, analytics, or the prayer inbox; only whether the
    # verified badge itself renders.
    is_verified = models.BooleanField(default=False)
    verified_at = models.DateTimeField(null=True, blank=True)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="verified_creator_profiles",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"CreatorProfile<{self.user_id}:{self.display_name}>"


class CreatorFollow(models.Model):
    """Phase 23 Slice 2 -- mirrors UserFollowedCategory's shape exactly
    (Phase 16 precedent for a simple follow join table). `creator` points
    at the User being followed (the one with a CreatorProfile), consistent
    with Testimony.author -- not at CreatorProfile itself, so this table
    doesn't need to change shape if a creator's profile is ever deleted
    and later recreated."""

    follower = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="creator_follows",
    )
    creator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="followers",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["follower", "creator"],
                name="uniq_creator_follow_follower_creator",
            ),
            models.CheckConstraint(
                check=~Q(follower=models.F("creator")),
                name="creator_follow_no_self_follow",
            ),
        ]

    def __str__(self) -> str:
        return f"CreatorFollow<{self.follower_id}->{self.creator_id}>"


class PrayerResponse(models.Model):
    """Phase 23 Slice 4 -- OneToOne to the specific TestimonyReaction being
    responded to (not a loose testimony+user pair), so "already responded
    to this exact reaction" is a real, DB-enforced state rather than
    something services/commands.py has to re-derive. Scoped to
    praying_for_you reactions only -- enforced in commands.py, not here,
    since it's a business rule about which reactions are eligible, not a
    property of a response row once it exists."""

    reaction = models.OneToOneField(
        "testimonies.TestimonyReaction",
        on_delete=models.CASCADE,
        related_name="prayer_response",
    )
    responded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="prayer_responses_sent",
    )
    response_text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"PrayerResponse<{self.reaction_id}>"
