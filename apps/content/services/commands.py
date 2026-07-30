from datetime import date

from django.db import transaction
from django.utils import timezone

from apps.content.exceptions import ContentError
from apps.content.models import (
    InspirationalPicture,
    InspirationalPictureStatus,
    ScriptureOfTheDay,
    ScriptureReadReceipt,
    ScriptureStatus,
)
from apps.notifications.services import notify_all_users_of_scripture_published, send_push_to_users
from apps.users.choices import UserAccountStatus
from apps.users.models import Profile

# Automatic, non-punitive: covers exactly one missed day per calendar month,
# consumed without any user action (Duolingo Streak Freeze framing -- see
# Phase 17 background). Resets when Profile.scripture_streak_freeze_month
# no longer matches the current read's month.
MAX_MONTHLY_SCRIPTURE_STREAK_FREEZES = 2


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


def mark_scripture_read(*, user, read_date: date) -> Profile:
    """Records that `user` read the Scripture of the Day on `read_date` --
    the user's own local calendar date, passed in by the client rather than
    computed server-side, so a read right after local midnight isn't
    robbed of credit by the server's day rolling over first.

    Idempotent: reading again the same read_date is a no-op that just
    returns current state. Otherwise extends the streak by one day,
    consumes an automatic monthly freeze if exactly one day was missed, or
    resets to 1 if the gap is longer (today's read still counts -- streaks
    reset to 1, never to 0, on a genuine read)."""
    today = timezone.localdate()
    if abs((read_date - today).days) > 1:
        raise ContentError("That doesn't look like today's date.")

    if ScriptureReadReceipt.objects.filter(user=user, read_date=read_date).exists():
        # Not user.profile -- that's Django's cached reverse-relation object
        # and can be stale (e.g. from before an earlier call in the same
        # request/test updated a separately-queried Profile instance with
        # the same PK). Fetch fresh so the no-op path can't return old state.
        return Profile.objects.get(user=user)

    with transaction.atomic():
        ScriptureReadReceipt.objects.create(user=user, read_date=read_date)
        profile = Profile.objects.select_for_update().get(user=user)
        last = profile.scripture_last_read_date

        if last is None:
            new_streak = 1
        else:
            gap_days = (read_date - last).days
            if gap_days <= 1:
                # Same day (shouldn't reach here given the receipt check
                # above) or the very next day -- either way, extend.
                new_streak = profile.scripture_streak_count + 1
            elif gap_days == 2:
                month_start = read_date.replace(day=1)
                if profile.scripture_streak_freeze_month != month_start:
                    profile.scripture_streak_freezes_used = 0
                    profile.scripture_streak_freeze_month = month_start
                if profile.scripture_streak_freezes_used < MAX_MONTHLY_SCRIPTURE_STREAK_FREEZES:
                    profile.scripture_streak_freezes_used += 1
                    new_streak = profile.scripture_streak_count + 1
                else:
                    new_streak = 1
            else:
                new_streak = 1

        profile.scripture_streak_count = new_streak
        profile.scripture_last_read_date = read_date
        profile.save(
            update_fields=[
                "scripture_streak_count",
                "scripture_last_read_date",
                "scripture_streak_freezes_used",
                "scripture_streak_freeze_month",
            ]
        )
    return profile


def scripture_streak_freezes_remaining(profile: Profile) -> int:
    today = timezone.localdate()
    month_start = today.replace(day=1)
    used = (
        profile.scripture_streak_freezes_used
        if profile.scripture_streak_freeze_month == month_start
        else 0
    )
    return max(0, MAX_MONTHLY_SCRIPTURE_STREAK_FREEZES - used)


def send_scripture_streak_reminders() -> int:
    """Pushes a once-daily nudge to every active user who hasn't read
    today's scripture yet (Phase 17 Slice 3). Deliberately push-only -- no
    UserNotification row, unlike every other notify_* helper -- since a
    once-a-day broadcast to every unread user would flood the in-app
    notification list; this is the one place in the system that
    intentionally skips it.

    Must run from its own once-daily cron entry, never from the existing
    */5 * * * * publish_due_scriptures job -- appending it there (as an
    earlier draft of this phase's background suggested) would fire this up
    to 288 times a day instead of once. All opt-out and device-token
    filtering is delegated to send_push_to_users; this function only
    decides *who* is still owed today's reminder.
    """
    today = timezone.localdate()
    target_user_ids = list(
        Profile.objects.filter(user__account_status=UserAccountStatus.ACTIVE)
        .exclude(scripture_last_read_date=today)
        .values_list("user_id", flat=True)
    )
    if not target_user_ids:
        return 0

    send_push_to_users(
        user_ids=target_user_ids,
        title="Keep your streak going",
        body="You haven't read today's Scripture yet -- read it now to keep your streak alive.",
    )
    return len(target_user_ids)
