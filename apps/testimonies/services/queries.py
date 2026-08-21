from __future__ import annotations

import random
from collections import Counter

from django.core.cache import cache
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

# A per-session seed (minted by mobile once per fresh load / pull-to-
# refresh, reused across pagination within that session) lets the reader
# see a genuinely different, truly shuffled starting mix each time, not
# just a different rotation of the same fixed order. Only the first
# HOME_FEED_SHUFFLE_WINDOW ranked items are actually shuffled -- realistic
# sessions rarely scroll past that, so the in-memory shuffle itself stays
# O(window) regardless of catalog size. The ordered id list still has to
# come from somewhere for that shuffle to run against, though -- see
# _cached_base_ids for how the DB query behind it is kept off the hot path
# for repeat pages within one session. This is the "seeded Fisher-Yates
# over a bounded window" approach agreed after discussing scale: cheap
# now, and migrates cleanly later (same seed param, same response shape)
# to a precomputed random-rank column with a periodic reshuffle job if
# traffic ever outgrows it.
HOME_FEED_SHUFFLE_WINDOW = 200

# How long one session's ordered id list stays cached (keyed by user +
# seed) so that scrolling through several pages of the same session only
# re-queries the eligible catalog once, not once per page -- mobile mints
# a fresh seed on every fresh load/refresh, so a new session always gets a
# genuinely fresh query regardless of this TTL; it only bounds how long a
# single very-long-lived scroll session goes before picking up newly
# approved content. LocMemCache (Django's default, no CACHES setting
# configured) is per-process, so on a multi-worker deployment this is a
# best-effort hit rate, not a guarantee -- a miss just falls back to the
# same query that always ran before this cache existed, so it's safe
# either way.
HOME_FEED_ID_CACHE_TTL_SECONDS = 900


def _cached_base_ids(user, seed: str) -> list[int]:
    is_authenticated = user is not None and getattr(user, "is_authenticated", False)
    user_key = user.pk if is_authenticated else "guest"
    cache_key = f"home_feed_ids:{user_key}:{seed}"
    cached_ids = cache.get(cache_key)
    if cached_ids is not None:
        return cached_ids
    ids = list(_home_feed_base_queryset(user).values_list("id", flat=True))
    cache.set(cache_key, ids, HOME_FEED_ID_CACHE_TTL_SECONDS)
    return ids


def _seeded_shuffle_ids(base_ids: list[int], seed: str) -> list[int]:
    window = base_ids[:HOME_FEED_SHUFFLE_WINDOW]
    rest = base_ids[HOME_FEED_SHUFFLE_WINDOW:]
    shuffled_window = window[:]
    random.Random(seed).shuffle(shuffled_window)
    return shuffled_window + rest


def _rotated_window_ids(
    ordered_ids: list[int], start: int, page_size: int, total: int
) -> list[int]:
    """The wraparound-safe slice of `ordered_ids` for one page, rotated by
    a deterministic per-loop offset once `start` has read past `total` --
    shared by the seeded and un-seeded loop-back paths below."""
    loop_number = start // total
    rotation = (loop_number * HOME_FEED_ROTATION_STEP) % total
    rotated_ids = ordered_ids[rotation:] + ordered_ids[:rotation]

    window_ids = []
    remaining = page_size
    cursor = start % total
    while remaining > 0:
        take = min(remaining, total - cursor)
        window_ids.extend(rotated_ids[cursor : cursor + take])
        remaining -= take
        cursor = (cursor + take) % total
    return window_ids


def _testimonies_for_ids(window_ids: list[int]) -> list[Testimony]:
    testimonies_by_id = Testimony.objects.select_related(
        "author", "author__profile", "author__creator_profile", "category"
    ).in_bulk(window_ids)
    return [
        testimonies_by_id[testimony_id]
        for testimony_id in window_ids
        if testimony_id in testimonies_by_id
    ]


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


def home_feed_page(
    *, user, page: int, page_size: int, seed: str | None = None
) -> dict:
    """One page of the immersive Home feed (Phase 20 Slice 3) -- never
    truly ends: once `page` reads past the real ordered list, it wraps
    around (rotated per loop, see HOME_FEED_ROTATION_STEP) instead of
    returning an empty page.

    With a `seed` (minted by mobile once per feed session, reused across
    that session's pagination -- see HOME_FEED_SHUFFLE_WINDOW), the first
    page of items is a genuine shuffle rather than the plain ranked order,
    so two different sessions -- or the same user's next pull-to-refresh
    -- see a different mix, not just a different rotation of the same
    fixed order. Without a seed, behavior is unchanged from before this
    was added (backward compatible for any caller that doesn't send one).

    Optimized for the common no-seed case: as long as the requested
    window still fits inside the real, un-looped content, this is a
    single indexed COUNT plus a plain DB-level OFFSET/LIMIT slice --
    select_related covers the serializer's needs, no extra queries. A
    seeded request always needs the ordered ID list up front instead,
    since a shuffle can't be expressed as a DB-level slice; that list is
    fetched without select_related (only `id` is ever read off it, so the
    joins select_related would add are pure waste here) and cached per
    (user, seed) via _cached_base_ids so repeat pages within one session
    don't re-run that query -- only the id-list fetch is cached, the
    shuffle and the final select_related testimony fetch still run fresh
    every call, same as before.
    """
    start = (page - 1) * page_size

    if seed:
        base_ids = _cached_base_ids(user, seed)
        total = len(base_ids)
        if total == 0:
            return {"results": [], "next_page": page + 1}
        ordered_ids = _seeded_shuffle_ids(base_ids, seed)
        window_ids = _rotated_window_ids(ordered_ids, start, page_size, total)
        return {"results": _testimonies_for_ids(window_ids), "next_page": page + 1}

    base_queryset = _home_feed_base_queryset(user).select_related(
        "author", "author__profile", "author__creator_profile", "category"
    )
    total = base_queryset.count()
    if total == 0:
        return {"results": [], "next_page": page + 1}

    if start + page_size <= total:
        return {
            "results": list(base_queryset[start : start + page_size]),
            "next_page": page + 1,
        }

    base_ids = list(base_queryset.values_list("id", flat=True))
    window_ids = _rotated_window_ids(base_ids, start, page_size, total)
    return {"results": _testimonies_for_ids(window_ids), "next_page": page + 1}


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
