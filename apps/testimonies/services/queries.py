from collections import Counter

from apps.testimonies.models import TestimonyFavorite, TestimonyReaction, TestimonyWatch


def user_engagement_journey(user) -> dict:
    """Live-computed "Your Journey" signals for a single authenticated
    user (Phase 18 Slice 3) -- watched/favorited counts and a most-visited
    category, blended from the same three signals Phase 16's For You feed
    already uses (favorites, reactions, watches). No new aggregation
    table: this is one user's own request, not a cross-user report, so a
    live group-by is cheap."""
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
    most_visited_theme = (
        Counter(category_names).most_common(1)[0][0] if category_names else None
    )

    return {
        "watched_count": watched_count,
        "favorited_count": favorited_count,
        "most_visited_theme": most_visited_theme,
    }
