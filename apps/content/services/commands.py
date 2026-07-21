from django.utils import timezone

from apps.content.models import InspirationalPicture, InspirationalPictureStatus, ScriptureOfTheDay, ScriptureStatus


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


def publish_due_scheduled_inspirational_pictures() -> int:
    now = timezone.now()

    published_count = InspirationalPicture.objects.filter(
        status=InspirationalPictureStatus.SCHEDULED,
        publish_at__isnull=False,
        publish_at__lte=now,
    ).update(
        status=InspirationalPictureStatus.PUBLISHED,
        updated_at=now,
    )

    return published_count
