from __future__ import annotations

from datetime import datetime, timedelta

from django.utils import timezone

from apps.engagement.models import HomeEvent

# A phone's clock can drift, and a batch can sit in a queue while offline --
# but anything claiming to be from the future, or older than this, is
# dropped rather than skewing a day that has already been rolled up.
MAX_CLOCK_SKEW = timedelta(minutes=5)
MAX_EVENT_AGE = timedelta(days=2)


def record_home_events(
    *, user, device_id: str, session_id: str, events: list[dict]
) -> int:
    """Phase 35 Slice 5 -- stores one batch of Home events from the app.
    `events` are already validated (type, ids, duration, time). Returns how
    many were kept."""
    now = timezone.now()
    owner = user if user is not None and getattr(user, "is_authenticated", False) else None
    rows = []
    for event in events:
        occurred_at: datetime = event["at"]
        if occurred_at > now + MAX_CLOCK_SKEW or occurred_at < now - MAX_EVENT_AGE:
            continue
        rows.append(
            HomeEvent(
                user=owner,
                device_id=device_id,
                session_id=session_id,
                event_type=event["type"],
                testimony_id=event.get("testimony_id"),
                duration_ms=event.get("duration_ms"),
                occurred_at=occurred_at,
            )
        )
    HomeEvent.objects.bulk_create(rows)
    return len(rows)
