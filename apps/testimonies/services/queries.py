from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass

from django.core.cache import cache
from django.db.models import OuterRef, Subquery, Sum
from django.db.models.functions import Coalesce

from apps.testimonies.models import (
    CategoryReaction,
    Reaction,
    Testimony,
    TestimonyFavorite,
    TestimonyReaction,
    TestimonyReactionCount,
    TestimonyReactionType,
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
# see a genuinely different starting mix each time. Phase 35 Slice 2: the
# shuffle now runs *within* each ranking tier (see _ranked_feed), so a
# fresh session still varies without undoing the ranking -- someone who
# follows Grace Chapel sees Grace Chapel's testimonies first every time,
# just not always in the same order. Only the first
# HOME_FEED_SHUFFLE_WINDOW items of each tier are shuffled, so the
# in-memory shuffle stays bounded regardless of catalog size.
HOME_FEED_SHUFFLE_WINDOW = 200

# A testimony with at least this many responses (reactions + comments)
# counts as popular for viewers with no closer signal -- the cold-start
# "recent plus popular" mix, and the "Popular in Healing" reason.
HOME_FEED_POPULAR_MIN_RESPONSES = 5

# How long one session's ranked list stays cached (keyed by user + seed) so
# that scrolling through several pages of the same session only ranks the
# eligible catalog once, not once per page -- mobile mints a fresh seed on
# every fresh load/refresh, so a new session always gets a genuinely fresh
# ranking regardless of this TTL; it only bounds how long a single very-
# long-lived scroll session goes before picking up newly approved content.
# LocMemCache (Django's default, no CACHES setting configured) is
# per-process, so on a multi-worker deployment this is a best-effort hit
# rate, not a guarantee -- a miss just ranks again, so it's safe either way.
HOME_FEED_ID_CACHE_TTL_SECONDS = 900


@dataclass(frozen=True)
class RankedFeedItem:
    testimony_id: int
    reason: str | None


# Tiers, best first. Within a tier, testimonies the viewer hasn't watched
# yet come before ones they have.
_TIER_FOLLOWED_CREATOR = 0
_TIER_FOLLOWED_CATEGORY = 1
_TIER_ENGAGED_CATEGORY = 2
_TIER_POPULAR = 3
_TIER_EVERYTHING_ELSE = 4


def _display_names(user_ids: set[int]) -> dict[int, str]:
    """The public name for each user -- a Ministry's display name first,
    then the person's full name, then email, matching
    TestimonyListSerializer.get_author_name."""
    from django.contrib.auth import get_user_model

    names = {}
    for user in get_user_model().objects.filter(id__in=user_ids).select_related(
        "profile", "creator_profile"
    ):
        creator_profile = getattr(user, "creator_profile", None)
        profile = getattr(user, "profile", None)
        if creator_profile and creator_profile.display_name.strip():
            names[user.id] = creator_profile.display_name
        elif profile and profile.full_name.strip():
            names[user.id] = profile.full_name
        else:
            names[user.id] = user.email
    return names


def _ranked_feed(user, seed: str | None) -> list[RankedFeedItem]:
    """Phase 35 Slice 2 -- the For you ranking, best first, each with the
    short reason the viewer sees ("You follow Grace Chapel").

    Worked example: Ada follows Grace Chapel and the Healing category, and
    has reacted to a Faith testimony. Her feed reads Grace Chapel's
    testimonies first, then Healing, then Faith, then anything with 5+
    responses ("Popular in Provision"), then the rest, newest first. In
    each of those groups, whatever she has already watched drops to the
    end of the group. A guest gets the last two groups only.
    """
    from apps.creators.models import CreatorFollow

    rows = list(
        Testimony.objects.filter(
            status=TestimonyStatus.APPROVED,
            category__is_active=True,
        )
        .order_by("-created_at", "-id")
        .annotate(
            reaction_total=Coalesce(
                Subquery(
                    TestimonyReactionCount.objects.filter(testimony_id=OuterRef("pk"))
                    .values("testimony_id")
                    .annotate(total=Sum("count"))
                    .values("total")
                ),
                0,
            )
        )
        .values(
            "id",
            "author_id",
            "category_id",
            "category__name",
            "comment_count",
            "reaction_total",
        )
    )
    if not rows:
        return []

    followed_creator_ids: set[int] = set()
    followed_category_ids: set[int] = set()
    engaged_category_ids: set[int] = set()
    watched_ids: set[int] = set()
    if user is not None and getattr(user, "is_authenticated", False):
        followed_creator_ids = set(
            CreatorFollow.objects.filter(follower=user).values_list("creator_id", flat=True)
        )
        followed_category_ids = set(
            user.followed_categories.values_list("category_id", flat=True)
        )
        engaged_category_ids = set(
            TestimonyFavorite.objects.filter(user=user).values_list(
                "testimony__category_id", flat=True
            )
        ) | set(
            TestimonyReaction.objects.filter(user=user).values_list(
                "testimony__category_id", flat=True
            )
        )
        watched_ids = set(
            TestimonyWatch.objects.filter(user=user).values_list("testimony_id", flat=True)
        )
    creator_names = _display_names(followed_creator_ids) if followed_creator_ids else {}

    groups: dict[tuple[int, bool], list[RankedFeedItem]] = {}
    for row in rows:
        category = row["category__name"]
        responses = row["comment_count"] + row["reaction_total"]
        if row["author_id"] in followed_creator_ids:
            tier = _TIER_FOLLOWED_CREATOR
            reason = f"You follow {creator_names.get(row['author_id'], 'this ministry')}"
        elif row["category_id"] in followed_category_ids:
            tier, reason = _TIER_FOLLOWED_CATEGORY, f"You follow {category}"
        elif row["category_id"] in engaged_category_ids:
            tier, reason = _TIER_ENGAGED_CATEGORY, f"Because you liked {category} testimonies"
        elif responses >= HOME_FEED_POPULAR_MIN_RESPONSES:
            tier, reason = _TIER_POPULAR, f"Popular in {category}"
        else:
            tier, reason = _TIER_EVERYTHING_ELSE, None
        watched = row["id"] in watched_ids
        groups.setdefault((tier, watched), []).append(RankedFeedItem(row["id"], reason))

    ranked: list[RankedFeedItem] = []
    for key in sorted(groups):
        items = groups[key]
        if seed:
            window = items[:HOME_FEED_SHUFFLE_WINDOW]
            random.Random(f"{seed}:{key[0]}:{key[1]}").shuffle(window)
            items = window + items[HOME_FEED_SHUFFLE_WINDOW:]
        ranked.extend(items)
    return ranked


def _cached_ranked_feed(user, seed: str | None) -> list[RankedFeedItem]:
    if not seed:
        return _ranked_feed(user, None)
    is_authenticated = user is not None and getattr(user, "is_authenticated", False)
    user_key = user.pk if is_authenticated else "guest"
    cache_key = f"home_feed_ranked:{user_key}:{seed}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    ranked = _ranked_feed(user, seed)
    cache.set(cache_key, ranked, HOME_FEED_ID_CACHE_TTL_SECONDS)
    return ranked


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


def home_feed_page(
    *, user, page: int, page_size: int, seed: str | None = None
) -> dict:
    """One page of the immersive Home feed's For you -- never truly ends:
    once `page` reads past the real ranked list, it wraps around (rotated
    per loop, see HOME_FEED_ROTATION_STEP) instead of returning an empty
    page.

    Results are ranked by _ranked_feed, and each one comes back paired
    with its reason in `reasons` (same order), for the "why shown" line.
    With a `seed` (minted by mobile once per feed session, reused across
    that session's pagination), each tier is shuffled so two sessions see a
    different mix, and the ranked list is cached per (user, seed) so later
    pages of the same session don't rank the catalog again.
    """
    start = (page - 1) * page_size
    ranked = _cached_ranked_feed(user, seed)
    total = len(ranked)
    if total == 0:
        return {"results": [], "reasons": [], "next_page": page + 1}

    reason_by_id = {item.testimony_id: item.reason for item in ranked}
    window_ids = _rotated_window_ids(
        [item.testimony_id for item in ranked], start, page_size, total
    )
    results = _testimonies_for_ids(window_ids)
    return {
        "results": results,
        "reasons": [reason_by_id.get(testimony.id) for testimony in results],
        "next_page": page + 1,
    }


def following_feed_queryset(user):
    """Phase 35 Slice 2 -- the Following chip: approved testimonies from the
    creators this viewer follows, newest first. Unlike For you it ends."""
    return (
        Testimony.objects.filter(
            status=TestimonyStatus.APPROVED,
            category__is_active=True,
            author__followers__follower=user,
        )
        .select_related("author", "author__profile", "author__creator_profile", "category")
        .order_by("-created_at", "-id")
    )


FOLLOWING_SUGGESTION_LIMIT = 6


def suggested_creators_to_follow(user) -> list[dict]:
    """For an empty Following feed: Ministries with approved testimonies the
    viewer doesn't follow yet, most-followed first."""
    from django.db.models import Count, Q

    from apps.creators.models import CreatorProfile

    profiles = (
        CreatorProfile.objects.exclude(user=user)
        .exclude(user__followers__follower=user)
        .annotate(
            approved_count=Count(
                "user__testimonies",
                filter=Q(user__testimonies__status=TestimonyStatus.APPROVED),
                distinct=True,
            ),
            follower_count=Count("user__followers", distinct=True),
        )
        .filter(approved_count__gt=0)
        .order_by("-follower_count", "-approved_count", "id")[:FOLLOWING_SUGGESTION_LIMIT]
    )
    return [
        {
            "user_id": profile.user_id,
            "display_name": profile.display_name,
            "avatar_url": profile.avatar_url,
            "testimony_count": profile.approved_count,
        }
        for profile in profiles
    ]


def apply_testimony_search(queryset, text: str):
    """Phase 35 Slice 3 -- narrows `queryset` to testimonies matching `text`
    and orders them best match first.

    Matches the story's words via full-text search over title and body
    ("healed" finds "healing"), plus a plain substring match on the title
    and on the ministry, author and category names -- so "Grace Chapel" or
    "Provision" finds their testimonies even if neither word is in the
    story. Ranked by SearchRank, with a boost when the title itself
    contains the text, then newest first.

    Worked example: searching "healing" finds a written testimony whose
    story says "I was healed of cancer" (full-text), every testimony in the
    Healing category (category name), and "Healing Streams Fellowship"'s
    testimonies (ministry name) -- with "Healing after the accident"
    (title contains it) ranked above the rest.
    """
    from django.contrib.postgres.search import SearchQuery, SearchRank
    from django.db.models import Case, FloatField, Q, Value, When

    from apps.testimonies.models import TESTIMONY_SEARCH_VECTOR

    query = SearchQuery(text, search_type="websearch", config="english")
    return (
        queryset.annotate(search=TESTIMONY_SEARCH_VECTOR)
        .filter(
            Q(search=query)
            | Q(title__icontains=text)
            | Q(author__creator_profile__display_name__icontains=text)
            | Q(author__profile__full_name__icontains=text)
            | Q(category__name__icontains=text)
        )
        .annotate(
            rank=SearchRank(TESTIMONY_SEARCH_VECTOR, query)
            + Case(
                When(title__icontains=text, then=Value(1.0)),
                default=Value(0.0),
                output_field=FloatField(),
            )
        )
        .order_by("-rank", "-created_at", "-id")
    )


MINISTRY_SEARCH_LIMIT = 5


def search_ministries(text: str, user) -> list[dict]:
    """Phase 35 Slice 3 -- churches and ministries whose name matches, shown
    above the testimony results. Only Ministries with approved testimonies,
    most-followed first."""
    from django.db.models import Count, Q

    from apps.creators.models import CreatorFollow, CreatorProfile

    profiles = list(
        CreatorProfile.objects.filter(display_name__icontains=text)
        .annotate(
            approved_count=Count(
                "user__testimonies",
                filter=Q(user__testimonies__status=TestimonyStatus.APPROVED),
                distinct=True,
            ),
            follower_count=Count("user__followers", distinct=True),
        )
        .filter(approved_count__gt=0)
        .order_by("-follower_count", "display_name", "id")[:MINISTRY_SEARCH_LIMIT]
    )
    followed_ids = set()
    if user is not None and getattr(user, "is_authenticated", False):
        followed_ids = set(
            CreatorFollow.objects.filter(
                follower=user, creator_id__in=[profile.user_id for profile in profiles]
            ).values_list("creator_id", flat=True)
        )
    return [
        {
            "user_id": profile.user_id,
            "display_name": profile.display_name,
            "avatar_url": profile.avatar_url,
            "testimony_count": profile.approved_count,
            "is_followed": profile.user_id in followed_ids,
        }
        for profile in profiles
    ]


@dataclass(frozen=True)
class ReactionSets:
    """Phase 35 Slice 6: which reactions each category offers, loaded once
    per request (the tables are tiny). `reactions` holds every reaction,
    retired ones too, so a stored count can always be named."""

    default: list[Reaction]
    by_category: dict[int, list[Reaction]]
    reactions: dict[int, Reaction]

    def for_category(self, category_id: int | None) -> list[Reaction]:
        return self.by_category.get(category_id) or self.default


def load_reaction_sets() -> ReactionSets:
    reactions = {reaction.id: reaction for reaction in Reaction.objects.all()}
    default = sorted(
        (r for r in reactions.values() if r.is_active and r.default_position is not None),
        key=lambda r: r.default_position,
    )
    by_category: dict[int, list[Reaction]] = {}
    for category_id, reaction_id in CategoryReaction.objects.order_by("category_id", "position").values_list(
        "category_id", "reaction_id"
    ):
        if reactions[reaction_id].is_active:
            by_category.setdefault(category_id, []).append(reactions[reaction_id])
    return ReactionSets(default=default, by_category=by_category, reactions=reactions)


def offered_reactions(category_id: int | None) -> list[Reaction]:
    """The reactions people can choose on a testimony in this category:
    its own set, or the default set if it has none (or none still active)."""
    own = list(
        Reaction.objects.filter(category_sets__category_id=category_id, is_active=True).order_by(
            "category_sets__position"
        )
    )
    if own:
        return own
    return list(Reaction.objects.filter(is_active=True, default_position__isnull=False).order_by("default_position"))


def reaction_counts_by_testimony(testimony_ids) -> dict[int, dict[int, int]]:
    """{testimony id: {reaction id: count}} in one query."""
    counts: dict[int, dict[int, int]] = {}
    for testimony_id, reaction_id, count in TestimonyReactionCount.objects.filter(
        testimony_id__in=list(testimony_ids), count__gt=0
    ).values_list("testimony_id", "reaction_id", "count"):
        counts.setdefault(testimony_id, {})[reaction_id] = count
    return counts


def testimony_reaction_options(testimony, *, sets: ReactionSets | None = None, counts: dict[int, int] | None = None) -> list[dict]:
    """Phase 35 Slices 4 and 6 -- the reactions offered on a testimony, in
    order, with their labels, icons and counts. Pass `sets` and `counts`
    when serializing many testimonies so this adds no queries per item."""
    sets = sets or load_reaction_sets()
    if counts is None:
        counts = reaction_counts_by_testimony([testimony.id]).get(testimony.id, {})
    return [
        {"key": reaction.key, "label": reaction.label, "icon": reaction.icon, "count": counts.get(reaction.id, 0)}
        for reaction in sets.for_category(testimony.category_id)
    ]


def legacy_reaction_counts(*, sets: ReactionSets, counts: dict[int, int]) -> dict[str, int]:
    """The original three counts, for app builds older than Phase 35."""
    by_key = {sets.reactions[reaction_id].key: count for reaction_id, count in counts.items() if reaction_id in sets.reactions}
    return {choice.value: by_key.get(choice.value, 0) for choice in TestimonyReactionType}


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


def admin_reaction_overview() -> dict:
    """Phase 35 Slice 6: everything the dashboard's Reactions page shows --
    the catalogue (with where each reaction is offered and how many
    responses it has), the default set, and every category's own set."""
    from django.db.models import Count

    from apps.testimonies.models import REACTION_SET_MAX, ReactionIcon, TestimonyCategory

    categories = list(TestimonyCategory.objects.order_by("name").values("id", "name", "is_active"))
    category_names = {category["id"]: category["name"] for category in categories}
    sets: dict[int, list[int]] = {}
    for category_id, reaction_id in CategoryReaction.objects.order_by("category_id", "position").values_list(
        "category_id", "reaction_id"
    ):
        sets.setdefault(category_id, []).append(reaction_id)
    shown_on: dict[int, list[str]] = {}
    for category_id, reaction_ids in sets.items():
        for reaction_id in reaction_ids:
            shown_on.setdefault(reaction_id, []).append(category_names[category_id])

    reactions = list(Reaction.objects.annotate(response_count=Count("responses")).order_by("id"))
    emoji = dict(ReactionIcon.choices)
    default_ids = [r.id for r in sorted((r for r in reactions if r.default_position is not None), key=lambda r: r.default_position)]
    return {
        "max_per_set": REACTION_SET_MAX,
        "icons": [{"key": key, "emoji": label} for key, label in ReactionIcon.choices],
        "reactions": [
            {
                "id": reaction.id,
                "key": reaction.key,
                "label": reaction.label,
                "icon": reaction.icon,
                "emoji": emoji.get(reaction.icon, ""),
                "is_active": reaction.is_active,
                "in_default_set": reaction.default_position is not None,
                "categories": sorted(shown_on.get(reaction.id, [])),
                "response_count": reaction.response_count,
            }
            for reaction in reactions
        ],
        "default_set": default_ids,
        "categories": [
            {**category, "reaction_ids": sets.get(category["id"], [])} for category in categories
        ],
    }
