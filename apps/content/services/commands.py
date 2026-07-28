from django.utils import timezone

from apps.content.models import InspirationalPicture, InspirationalPictureStatus, ScriptureOfTheDay, ScriptureStatus
from apps.notifications.services import notify_all_users_of_scripture_published


def publish_due_scheduled_scriptures() -> int:
    now = timezone.now()
    today = timezone.localdate()

    # Captured before the bulk update so we know exactly which rows the
    # flip actually touched, and can notify once per entry afterward
    # (normally just today's entry, but a missed cron run could catch up
    # several at once, each with its own bible_text).
    due_ids = list(
        ScriptureOfTheDay.objects.filter(
            status=ScriptureStatus.SCHEDULED,
            date__lte=today,
        ).values_list("id", flat=True)
    )

    published_count = ScriptureOfTheDay.objects.filter(id__in=due_ids).update(
        status=ScriptureStatus.PUBLISHED,
        published_at=now,
    )

    # Backfill legacy rows that are already published but still missing published_at.
    ScriptureOfTheDay.objects.filter(
        status=ScriptureStatus.PUBLISHED,
        published_at__isnull=True,
    ).update(published_at=now)

    for entry in ScriptureOfTheDay.objects.filter(id__in=due_ids):
        notify_all_users_of_scripture_published(scripture=entry)

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
