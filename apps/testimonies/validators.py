from datetime import datetime

from django.utils import timezone


def parse_future_publish_at(raw_value: str) -> datetime:
    """Parse and validate a `publish_at` value for scheduling a testimony.

    Raises ValueError with a user-facing message on any invalid input.
    """
    raw_value = str(raw_value or "").strip()
    if not raw_value:
        raise ValueError("publish_at is required.")
    try:
        publish_at = datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("publish_at must be a valid ISO datetime.")
    if timezone.is_naive(publish_at):
        publish_at = timezone.make_aware(publish_at, timezone.get_current_timezone())
    if publish_at <= timezone.now():
        raise ValueError("publish_at must be in the future.")
    return publish_at
