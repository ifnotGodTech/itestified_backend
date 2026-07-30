from collections import Counter

from apps.testimonies.models import TestimonyFavorite, TestimonyReaction, TestimonyWatch


# Matches the engagement mockup's bar chart, which compares the user's top
# 4 categories (Healing / Faith / Deliv. / Salv. in the mockup's example).
THEME_DISTRIBUTION_LIMIT = 4


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
