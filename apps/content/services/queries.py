from datetime import timedelta

from django.db import models
from django.utils import timezone

from apps.users.models import Profile

# Fully automatic (Phase 20 decision) -- no admin curation step for this
# rotation, unlike FeaturedHomePicture/FeaturedHomeTestimony.
HOME_CAROUSEL_PICTURE_LIMIT = 4
HOME_CAROUSEL_QUOTE_LIMIT = 4


def _testimony_speaker_name(testimony) -> str:
    profile = getattr(testimony.author, "profile", None)
    if profile and profile.full_name.strip():
        return profile.full_name
    return testimony.author.email


def home_carousel_slides() -> list[dict]:
    """Slides for the immersive Home carousel (Phase 20 Slice 1): the most
    recent published, non-expired inspirational pictures blended with the
    most recent approved testimonies carrying a moderator-curated
    pull_quote (Phase 19) -- pictures first, then quotes, most recent
    first within each kind.
    """
    from apps.content.models import InspirationalPicture, InspirationalPictureStatus
    from apps.testimonies.models import Testimony, TestimonyStatus

    now = timezone.now()
    pictures = (
        InspirationalPicture.objects.filter(status=InspirationalPictureStatus.PUBLISHED)
        .filter(models.Q(publish_at__isnull=True) | models.Q(publish_at__lte=now))
        .filter(models.Q(expires_at__isnull=True) | models.Q(expires_at__gt=now))
        .order_by("-updated_at")[:HOME_CAROUSEL_PICTURE_LIMIT]
    )
    slides = [
        {
            "kind": "picture",
            "id": picture.id,
            "image_url": picture.image_url,
            "title": picture.title,
            "caption": picture.caption,
        }
        for picture in pictures
    ]

    quoted_testimonies = (
        Testimony.objects.filter(status=TestimonyStatus.APPROVED)
        .exclude(pull_quote="")
        .select_related("category", "author__profile")
        .order_by("-created_at")[:HOME_CAROUSEL_QUOTE_LIMIT]
    )
    slides += [
        {
            "kind": "testimony_quote",
            "id": testimony.id,
            "pull_quote": testimony.pull_quote,
            "speaker": _testimony_speaker_name(testimony),
            "category": testimony.category.name if testimony.category else "",
        }
        for testimony in quoted_testimonies
    ]
    return slides


def scripture_streak_engagement_stats() -> dict:
    """Aggregate view of how the Scripture streak feature (Phase 17) is
    actually being used, for the admin dashboard only -- never exposed to
    mobile.

    "Active" means read today or yesterday. A user who's 2+ days stale
    hasn't necessarily lost their streak yet (a freeze can still save it on
    their next read), but their own scripture_streak_count is itself stale
    until that next read happens either way -- counting them as "active"
    here would overstate genuine, current engagement.
    """
    today = timezone.localdate()
    active_streak_counts = list(
        Profile.objects.filter(
            scripture_streak_count__gte=1,
            scripture_last_read_date__gte=today - timedelta(days=1),
        ).values_list("scripture_streak_count", flat=True)
    )

    distribution = {
        "1_to_3_days": 0,
        "4_to_7_days": 0,
        "8_to_30_days": 0,
        "31_plus_days": 0,
    }
    for count in active_streak_counts:
        if count <= 3:
            distribution["1_to_3_days"] += 1
        elif count <= 7:
            distribution["4_to_7_days"] += 1
        elif count <= 30:
            distribution["8_to_30_days"] += 1
        else:
            distribution["31_plus_days"] += 1

    return {
        "active_streak_user_count": len(active_streak_counts),
        "streak_length_distribution": distribution,
    }
