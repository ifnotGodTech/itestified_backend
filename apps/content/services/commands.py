from django.utils import timezone

from apps.content.models import ScriptureOfTheDay, ScriptureStatus


def publish_due_scheduled_scriptures() -> int:
    now = timezone.now()
    today = timezone.localdate()

    published_count = ScriptureOfTheDay.objects.filter(
        status=ScriptureStatus.SCHEDULED,
        date__lte=today,
    ).update(
        status=ScriptureStatus.PUBLISHED,
        published_at=now,
    )

    # Backfill legacy rows that are already published but still missing published_at.
    ScriptureOfTheDay.objects.filter(
        status=ScriptureStatus.PUBLISHED,
        published_at__isnull=True,
    ).update(published_at=now)

    return published_count
