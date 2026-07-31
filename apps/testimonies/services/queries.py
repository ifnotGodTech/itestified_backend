from collections import Counter

from django.db.models import Case, IntegerField, When

from apps.testimonies.models import (
    Testimony,
    TestimonyFavorite,
    TestimonyReaction,
    TestimonyStatus,
    TestimonyWatch,
)


# Matches the engagement mockup's bar chart, which compares the user's top
# 4 categories (Healing / Faith / Deliv. / Salv. in the mockup's example).
THEME_DISTRIBUTION_LIMIT = 4

# Phase 20 Slice 3: once the real, unseen feed is exhausted, the home feed
# loops back through already-seen testimonies rather than dead-ending.
# Each loop starts reading from a rotated point in the ordered list instead
# of literally index 0 again, so consecutive loops don't read back in the
# exact same order (the phase's own "reshuffled" decision) -- a full random
# shuffle per request would make pagination inconsistent (the same item
# could appear on two different "pages" within one loop), so this rotates
# the whole ordering deterministically instead.
HOME_FEED_ROTATION_STEP = 7


def _home_feed_base_queryset(user):
    """The ranked, un-evaluated queryset behind one user's home feed --
    signal-category testimonies first (most recent within), then
    everything else (most recent within) for a user with real signal
    (follows/favorites/reactions, same blend as Phase 16's for-you feed);
    plain most-recent-first for a guest or a signal-less user."""
    base_queryset = Testimony.objects.filter(
        status=TestimonyStatus.APPROVED,
        category__is_active=True,
    )
    category_ids = set()
    if user is not None and getattr(user, "is_authenticated", False):
        category_ids = (
            set(user.followed_categories.values_list("category_id", flat=True))
            | set(
                TestimonyFavorite.objects.filter(user=user).values_list(
                    "testimony__category_id", flat=True
                )
            )
            | set(
                TestimonyReaction.objects.filter(user=user).values_list(
                    "testimony__category_id", flat=True
                )
            )
        )
    if category_ids:
        return base_queryset.annotate(
            is_signal=Case(
                When(category_id__in=category_ids, then=0),
                default=1,
                output_field=IntegerField(),
            )
        ).order_by("is_signal", "-created_at", "id")
    return base_queryset.order_by("-created_at", "id")


def home_feed_page(*, user, page: int, page_size: int) -> dict:
    """One page of the immersive Home feed (Phase 20 Slice 3) -- never
    truly ends: once `page` reads past the real ordered list, it wraps
    around (rotated per loop, see HOME_FEED_ROTATION_STEP) instead of
    returning an empty page.

    Optimized for the common case: as long as the requested window still
    fits inside the real, un-looped content, this is a single indexed
    COUNT plus a plain DB-level OFFSET/LIMIT slice -- select_related
    covers the serializer's needs, no extra queries. The full ordered-ID
    list (and the O(total) rotation math) is only ever materialized once
    a request actually reads past the end of the real content, which is a
    small fraction of traffic for any catalog bigger than a page or two.
    """
    base_queryset = _home_feed_base_queryset(user).select_related(
        "author", "author__profile", "category"
    )
    total = base_queryset.count()
    if total == 0:
        return {"results": [], "next_page": page + 1}

    start = (page - 1) * page_size
    if start + page_size <= total:
        return {
            "results": list(base_queryset[start : start + page_size]),
            "next_page": page + 1,
        }

    base_ids = list(base_queryset.values_list("id", flat=True))
    loop_number = start // total
    rotation = (loop_number * HOME_FEED_ROTATION_STEP) % total
    rotated_ids = base_ids[rotation:] + base_ids[:rotation]

    window_ids = []
    remaining = page_size
    cursor = start % total
    while remaining > 0:
        take = min(remaining, total - cursor)
        window_ids.extend(rotated_ids[cursor : cursor + take])
        remaining -= take
        cursor = (cursor + take) % total

    testimonies_by_id = Testimony.objects.select_related(
        "author", "author__profile", "category"
    ).in_bulk(window_ids)
    ordered_testimonies = [
        testimonies_by_id[testimony_id]
        for testimony_id in window_ids
        if testimony_id in testimonies_by_id
    ]

    return {"results": ordered_testimonies, "next_page": page + 1}


def user_engagement_journey(user) -> dict:
    """Live-computed "Your Journey" signals for a single authenticated
    user (Phase 18 Slice 3) -- watched/favorited counts and a ranked
    category distribution, blended from the same three signals Phase 16's
    For You feed already uses (favorites, reactions, watches). No new
    aggregation table: this is one user's own request, not a cross-user
    report, so a live group-by is cheap.

    theme_distribution is the top THEME_DISTRIBUTION_LIMIT categories by
    combined signal count, most-visited first -- real counts, not a
    fabricated comparison, so mobile can render an honest bar chart
    instead of just naming a single winner."""
    watched_count = TestimonyWatch.objects.filter(user=user).count()
    favorited_count = TestimonyFavorite.objects.filter(user=user).count()

    category_names = (
        list(
            TestimonyFavorite.objects.filter(user=user).values_list(
                "testimony__category__name", flat=True
            )
        )
        + list(
            TestimonyReaction.objects.filter(user=user).values_list(
                "testimony__category__name", flat=True
            )
        )
        + list(
            TestimonyWatch.objects.filter(user=user).values_list(
                "testimony__category__name", flat=True
            )
        )
    )
    ranked = Counter(category_names).most_common(THEME_DISTRIBUTION_LIMIT)
    theme_distribution = [{"theme": name, "count": count} for name, count in ranked]
    most_visited_theme = ranked[0][0] if ranked else None

    return {
        "watched_count": watched_count,
        "favorited_count": favorited_count,
        "most_visited_theme": most_visited_theme,
        "theme_distribution": theme_distribution,
    }
