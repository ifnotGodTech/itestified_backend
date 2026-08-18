from __future__ import annotations

from django.db.models import Count, QuerySet, Sum

from apps.creators.models import CreatorFollow, CreatorProfile
from apps.testimonies.models import Testimony, TestimonyReaction, TestimonyReactionType, TestimonyStatus


def get_creator_profile(user) -> CreatorProfile | None:
    return CreatorProfile.objects.filter(user=user).first()


def follower_count(*, creator_user_id: int) -> int:
    return CreatorFollow.objects.filter(creator_id=creator_user_id).count()


def is_following(*, follower_user_id: int, creator_user_id: int) -> bool:
    return CreatorFollow.objects.filter(
        follower_id=follower_user_id, creator_id=creator_user_id
    ).exists()


def get_creator_analytics(*, creator_user_id: int) -> dict:
    """Phase 23 Slice 3 -- pure read-side aggregation over Testimony.view_count
    and TestimonyReaction, both already stored per-testimony (Phase 3,
    Phase 15). No new data collection, no write path. Scoped to APPROVED
    testimonies only -- a pending/rejected/draft testimony isn't public
    yet, so it shouldn't inflate a creator's visible stats."""
    approved_testimonies = Testimony.objects.filter(
        author_id=creator_user_id, status=TestimonyStatus.APPROVED
    )
    testimony_count = approved_testimonies.count()
    total_views = approved_testimonies.aggregate(total=Sum("view_count"))["total"] or 0

    reaction_rows = (
        TestimonyReaction.objects.filter(testimony__in=approved_testimonies)
        .values("reaction_type")
        .annotate(count=Count("id"))
    )
    reaction_counts = {choice.value: 0 for choice in TestimonyReactionType}
    total_reactions = 0
    for row in reaction_rows:
        reaction_counts[row["reaction_type"]] = row["count"]
        total_reactions += row["count"]

    return {
        "follower_count": follower_count(creator_user_id=creator_user_id),
        "testimony_count": testimony_count,
        "total_views": total_views,
        "total_reactions": total_reactions,
        "reaction_counts": reaction_counts,
    }


def list_prayer_reactions_for_creator(*, creator_user_id: int) -> QuerySet[TestimonyReaction]:
    """Phase 23 Slice 4 -- the creator's own inbox. Scoped to
    praying_for_you specifically (see Phase 23's Background note);
    select_related/prefetch keeps this a fixed number of queries
    regardless of inbox size. select_related("prayer_response") is safe
    even though it's a reverse OneToOne with no guaranteed row -- Django
    returns None for reaction.prayer_response when none exists, which is
    exactly the "not yet responded" state the API needs to expose."""
    return (
        TestimonyReaction.objects.filter(
            testimony__author_id=creator_user_id,
            reaction_type=TestimonyReactionType.PRAYING_FOR_YOU,
        )
        .select_related("user", "user__profile", "testimony", "prayer_response")
        .order_by("-created_at")
    )
