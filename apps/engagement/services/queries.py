from __future__ import annotations

from datetime import date, timedelta

from django.db.models import Aggregate, Count, FloatField, Q
from django.utils import timezone

from apps.engagement.choices import HomeEventType
from apps.engagement.models import HomeEngagementDay, HomeEvent

# Raw events are kept this long; their days live on in HomeEngagementDay.
HOME_EVENT_RETENTION_DAYS = 90
SUMMARY_PERIODS = (7, 30, 90)


class _Median(Aggregate):
    function = "PERCENTILE_CONT"
    template = "%(function)s(0.5) WITHIN GROUP (ORDER BY %(expressions)s)"
    output_field = FloatField()


def _day_metrics(events) -> dict:
    """The day-level numbers for a set of events -- in the database, one
    query, however many events there are."""
    totals = events.aggregate(
        items_viewed=Count("id", filter=Q(event_type=HomeEventType.ITEM_VIEWED)),
        swipes=Count("id", filter=Q(event_type=HomeEventType.SWIPED)),
        sessions=Count("session_id", distinct=True),
        searches=Count("id", filter=Q(event_type=HomeEventType.SEARCH_RUN)),
        results_opened=Count("id", filter=Q(event_type=HomeEventType.RESULT_OPENED)),
        responses=Count("id", filter=Q(event_type=HomeEventType.RESPONDED)),
    )
    median = events.filter(event_type=HomeEventType.ITEM_VIEWED).aggregate(
        median=_Median("duration_ms")
    )["median"]
    totals["median_view_ms"] = round(median or 0)
    return totals


def _events_on(day: date):
    return HomeEvent.objects.filter(occurred_at__date=day)


def roll_up_and_prune(today: date | None = None) -> None:
    """Rolls every finished day that has events but no HomeEngagementDay
    yet, then drops raw events older than the retention window. Runs when
    the dashboard asks for the summary, so it needs no scheduled job."""
    today = today or timezone.localdate()
    rolled = set(HomeEngagementDay.objects.values_list("day", flat=True))
    pending_days = {
        day
        for day in HomeEvent.objects.filter(occurred_at__date__lt=today)
        .dates("occurred_at", "day")
        if day not in rolled
    }
    HomeEngagementDay.objects.bulk_create(
        [HomeEngagementDay(day=day, **_day_metrics(_events_on(day))) for day in sorted(pending_days)],
        ignore_conflicts=True,
    )
    cutoff = today - timedelta(days=HOME_EVENT_RETENTION_DAYS)
    HomeEvent.objects.filter(occurred_at__date__lt=cutoff).delete()


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 3) if denominator else None


def home_engagement_summary(*, days: int, today: date | None = None) -> dict:
    """Phase 35 Slice 5 -- the dashboard's "Home engagement" card for the
    last `days` days, today included (today live, earlier days rolled up).

    Worked example over 7 days: 1,200 items viewed with a median of 41s,
    300 sessions with 2,100 swipes (7.0 swipes per session), 140 searches
    (20 a day) and 96 responses (8% of items viewed got a response).
    """
    today = today or timezone.localdate()
    roll_up_and_prune(today)
    start = today - timedelta(days=days - 1)

    series = []
    rolled = {row.day: row for row in HomeEngagementDay.objects.filter(day__gte=start, day__lt=today)}
    for offset in range(days):
        day = start + timedelta(days=offset)
        if day == today:
            metrics = _day_metrics(_events_on(today))
        elif day in rolled:
            row = rolled[day]
            metrics = {
                "items_viewed": row.items_viewed,
                "median_view_ms": row.median_view_ms,
                "swipes": row.swipes,
                "sessions": row.sessions,
                "searches": row.searches,
                "results_opened": row.results_opened,
                "responses": row.responses,
            }
        else:
            metrics = {
                "items_viewed": 0,
                "median_view_ms": 0,
                "swipes": 0,
                "sessions": 0,
                "searches": 0,
                "results_opened": 0,
                "responses": 0,
            }
        series.append({"day": day.isoformat(), **metrics})

    def total(key: str) -> int:
        return sum(entry[key] for entry in series)

    # The period's median comes straight from the raw events (kept for the
    # longest period offered), not from averaging daily medians.
    period_median = HomeEvent.objects.filter(
        event_type=HomeEventType.ITEM_VIEWED, occurred_at__date__gte=start
    ).aggregate(median=_Median("duration_ms"))["median"]

    return {
        "days": days,
        "median_view_ms": round(period_median or 0),
        "swipes_per_session": _rate(total("swipes"), total("sessions")),
        "searches_per_day": round(total("searches") / days, 1),
        # How often a search led to a result being played.
        "search_play_rate": _rate(total("results_opened"), total("searches")),
        "response_rate": _rate(total("responses"), total("items_viewed")),
        "items_viewed": total("items_viewed"),
        "sessions": total("sessions"),
        "series": series,
    }
