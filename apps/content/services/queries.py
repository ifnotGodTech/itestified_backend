from datetime import timedelta

from django.utils import timezone

from apps.users.models import Profile


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
