import logging
from typing import Iterable, Optional

from django.db import transaction

from apps.common.exceptions import PushProviderNotConfiguredError
from apps.common.services.push import chunked, send_push_to_tokens
from apps.notifications.models import DeviceToken, NotificationType, UserNotification, UserNotificationPreference
from apps.users.choices import AdminAssignmentStatus, UserAccountStatus
from apps.users.models import AdminAssignment
from apps.users.models import User

logger = logging.getLogger(__name__)


def send_push_to_users(
    *,
    user_ids: Iterable[int],
    title: str,
    body: str,
    data: Optional[dict[str, str]] = None,
    platform: Optional[str] = None,
) -> None:
    """Sends a push to every device of every user in `user_ids`, honoring each
    user's own allow_push_notifications preference (default opted-in). Pass
    `platform` to only push to that platform's device tokens (e.g. an
    Android-only release shouldn't nudge someone's iOS device). The actual
    send is deferred to transaction.on_commit -- if called from inside
    an atomic block, the push only fires once the underlying write (the
    testimony approval, the comment, etc.) actually commits, and never at all
    if it rolls back. Outside a transaction, on_commit runs immediately, so
    this is safe to call unconditionally regardless of caller context.

    Failures (no credentials configured, FCM error) are logged, never raised
    -- a broken push integration must never affect the notification-worthy
    action that triggered it.
    """
    user_id_list = list(dict.fromkeys(user_ids))
    if not user_id_list:
        return

    opted_out_user_ids = set(
        UserNotificationPreference.objects.filter(
            user_id__in=user_id_list, allow_push_notifications=False
        ).values_list("user_id", flat=True)
    )
    eligible_user_ids = [uid for uid in user_id_list if uid not in opted_out_user_ids]
    if not eligible_user_ids:
        logger.info(
            "notifications.push.skipped_all_opted_out user_ids=%s", user_id_list
        )
        return

    tokens_qs = DeviceToken.objects.filter(user_id__in=eligible_user_ids)
    if platform is not None:
        tokens_qs = tokens_qs.filter(platform=platform)
    tokens = list(tokens_qs.values_list("token", flat=True))
    if not tokens:
        logger.info(
            "notifications.push.skipped_no_device_tokens user_ids=%s", eligible_user_ids
        )
        return

    logger.info(
        "notifications.push.scheduled user_ids=%s token_count=%s",
        eligible_user_ids,
        len(tokens),
    )
    transaction.on_commit(
        lambda: _dispatch_push(tokens=tokens, title=title, body=body, data=data)
    )


def deregister_all_devices_for_user(*, user) -> int:
    """Removes every device token registered to `user`. Called on account
    deletion so a deleted (soft-deleted/anonymized, not row-deleted) user's
    device can never receive a push -- send_push_to_users has no
    account_status filter of its own, so a stale token left behind would
    otherwise still be included in future sends. The mobile client also
    tries to deregister its own device on logout/deletion, but that call
    needs a still-valid auth token; by the time account deletion has run,
    the token is already gone, so that best-effort client call always fails
    for this specific flow -- this is the guaranteed cleanup path."""
    deleted_count, _ = DeviceToken.objects.filter(user=user).delete()
    return deleted_count


def _dispatch_push(
    *, tokens: list[str], title: str, body: str, data: Optional[dict[str, str]]
) -> None:
    try:
        invalid_tokens: list[str] = []
        for chunk in chunked(tokens, 500):
            invalid_tokens.extend(
                send_push_to_tokens(tokens=chunk, title=title, body=body, data=data)
            )
    except PushProviderNotConfiguredError:
        logger.warning("notifications.push.provider_not_configured")
        return
    except Exception:
        logger.exception("notifications.push.send_failed")
        return

    logger.info(
        "notifications.push.sent token_count=%s invalid_count=%s",
        len(tokens),
        len(invalid_tokens),
    )
    if invalid_tokens:
        DeviceToken.objects.filter(token__in=invalid_tokens).delete()


# Phase 6 Slice 10 domain decision: only testimony-approved, testimony-comment,
# and new-video-testimony push. Rejections, submissions, and donation-received
# stay in-app-only -- see notify_testimony_rejected / notify_testimony_submitted_to_admins
# / notify_admins_of_new_donation below, none of which call send_push_to_users.
def notify_testimony_approved(*, recipient, actor, testimony_title: str) -> UserNotification:
    title = "Your testimony was approved"
    message = f'"{testimony_title}" has been approved and is now visible to others.'
    notification = UserNotification.objects.create(
        recipient=recipient,
        actor=actor,
        notification_type=NotificationType.TESTIMONY_APPROVED,
        title=title,
        message=message,
    )
    send_push_to_users(user_ids=[recipient.id], title=title, body=message)
    return notification


def notify_testimony_rejected(*, recipient, actor, testimony_title: str, reason: str) -> UserNotification:
    reason_text = reason.strip() or "No reason provided."
    return UserNotification.objects.create(
        recipient=recipient,
        actor=actor,
        notification_type=NotificationType.TESTIMONY_REJECTED,
        title="Your testimony was rejected",
        message=f'"{testimony_title}" was rejected. Reason: {reason_text}',
    )


def notify_testimony_submitted_to_admins(*, testimony_title: str, testimony_type: str, actor) -> None:
    admin_user_ids = list(
        AdminAssignment.objects.filter(status=AdminAssignmentStatus.ACTIVE)
        .exclude(user_id=actor.id)
        .values_list("user_id", flat=True)
        .distinct()
    )
    if not admin_user_ids:
        return

    label = {"video": "Video", "audio": "Audio"}.get(testimony_type, "Text")
    title = f"New {label} Testimony Submitted"
    message = f'{actor.email} submitted "{testimony_title}" for moderation review.'
    rows = [
        UserNotification(
            recipient_id=user_id,
            actor=actor,
            notification_type=NotificationType.TESTIMONY_SUBMITTED,
            title=title,
            message=message,
        )
        for user_id in admin_user_ids
    ]
    UserNotification.objects.bulk_create(rows)


def notify_new_video_testimony_published(*, testimony, actor=None) -> int:
    recipient_qs = User.objects.filter(account_status=UserAccountStatus.ACTIVE)
    active_admin_user_ids = AdminAssignment.objects.filter(
        status=AdminAssignmentStatus.ACTIVE
    ).values_list("user_id", flat=True)
    recipient_qs = recipient_qs.exclude(id__in=active_admin_user_ids)
    if actor is not None:
        recipient_qs = recipient_qs.exclude(id=actor.id)

    recipient_ids = list(recipient_qs.values_list("id", flat=True))
    if not recipient_ids:
        return 0

    title = "New video testimony"
    message = f'New video testimony published: "{testimony.title}".'
    rows = [
        UserNotification(
            recipient_id=user_id,
            actor=actor,
            notification_type=NotificationType.NEW_VIDEO_TESTIMONY,
            title=title,
            message=message,
        )
        for user_id in recipient_ids
    ]
    UserNotification.objects.bulk_create(rows)
    send_push_to_users(user_ids=recipient_ids, title=title, body=message)
    return len(rows)


def notify_admins_of_new_donation(*, donor, donor_label: str, amount_label: str) -> int:
    """Notify each active admin that a donation was submitted, honoring each
    admin's own notify_new_donation_received preference (default: opted in,
    matching the model default for admins with no preference row yet)."""
    admin_assignments = (
        AdminAssignment.objects.filter(status=AdminAssignmentStatus.ACTIVE)
        .exclude(user_id=donor.id)
        .select_related("user")
    )
    admin_users = [assignment.user for assignment in admin_assignments]
    if not admin_users:
        return 0

    preferences = {
        preference.user_id: preference
        for preference in UserNotificationPreference.objects.filter(user__in=admin_users)
    }
    title = "New donation received"
    message = f"{donor_label} submitted a donation of {amount_label} for verification."
    rows = [
        UserNotification(
            recipient=user,
            actor=donor,
            notification_type=NotificationType.DONATION_RECEIVED,
            title=title,
            message=message,
        )
        for user in admin_users
        if (preference := preferences.get(user.id)) is None or preference.notify_new_donation_received
    ]
    if not rows:
        return 0
    UserNotification.objects.bulk_create(rows)
    return len(rows)


def notify_all_users_of_app_update(*, actor, platform: str) -> int:
    """Broadcasts an in-app + push notification to every active user with a
    registered device on `platform`. Admin-triggered explicitly via a
    dedicated "Notify users" action -- deliberately decoupled from saving the
    version config itself, so correcting a typo or tweaking a version number
    doesn't mass-notify everyone. Scoped to `platform` because an Android-only
    release shouldn't nudge iOS users (and vice versa)."""
    recipient_ids = list(
        User.objects.filter(
            account_status=UserAccountStatus.ACTIVE,
            device_tokens__platform=platform,
        )
        .values_list("id", flat=True)
        .distinct()
    )
    if not recipient_ids:
        return 0

    title = "New version available"
    message = "A new version of iTestified is available. Update now to get the latest experience."
    rows = [
        UserNotification(
            recipient_id=user_id,
            actor=actor,
            notification_type=NotificationType.APP_UPDATE_AVAILABLE,
            title=title,
            message=message,
        )
        for user_id in recipient_ids
    ]
    UserNotification.objects.bulk_create(rows)
    send_push_to_users(user_ids=recipient_ids, title=title, body=message, platform=platform)
    return len(rows)


def notify_all_users_of_scripture_published(*, scripture, actor=None) -> int:
    """Broadcasts an in-app + push notification to every active, non-admin
    user when a Scripture of the Day goes live -- whether that happens
    immediately (an admin creates or edits an entry dated today) or later,
    when the daily publish_due_scriptures cron catches a scheduled entry up.
    `actor` is None for the cron path (nobody to exclude); admins are always
    excluded since they already see the change in the dashboard."""
    recipient_qs = User.objects.filter(account_status=UserAccountStatus.ACTIVE)
    active_admin_user_ids = AdminAssignment.objects.filter(
        status=AdminAssignmentStatus.ACTIVE
    ).values_list("user_id", flat=True)
    recipient_qs = recipient_qs.exclude(id__in=active_admin_user_ids)
    if actor is not None:
        recipient_qs = recipient_qs.exclude(id=actor.id)

    recipient_ids = list(recipient_qs.values_list("id", flat=True))
    if not recipient_ids:
        return 0

    title = "Today's scripture is here"
    message = f"A new Scripture of the Day is ready: {scripture.bible_text}."
    rows = [
        UserNotification(
            recipient_id=user_id,
            actor=actor,
            notification_type=NotificationType.SCRIPTURE_PUBLISHED,
            title=title,
            message=message,
        )
        for user_id in recipient_ids
    ]
    UserNotification.objects.bulk_create(rows)
    send_push_to_users(user_ids=recipient_ids, title=title, body=message)
    return len(rows)


def notify_creator_digest(*, follower_ids: Iterable[int], creator_display_name: str, new_testimony_count: int) -> None:
    """Phase 23 Slice 2 -- one notification per follower per creator per
    run, never one per testimony (see Phase 23's Background note on why
    follower notifications must batch). Called from
    apps.creators.tasks.send_creator_follower_digests, a daily Celery
    beat task -- actor is None since this isn't triggered by any single
    user's action."""
    follower_id_list = list(dict.fromkeys(follower_ids))
    if not follower_id_list:
        return

    count_label = "testimony" if new_testimony_count == 1 else "testimonies"
    title = f"New from {creator_display_name}"
    message = f"{creator_display_name} shared {new_testimony_count} new {count_label}."
    rows = [
        UserNotification(
            recipient_id=follower_id,
            actor=None,
            notification_type=NotificationType.CREATOR_DIGEST,
            title=title,
            message=message,
        )
        for follower_id in follower_id_list
    ]
    UserNotification.objects.bulk_create(rows)
    send_push_to_users(user_ids=follower_id_list, title=title, body=message)


def notify_prayer_response(
    *, recipient, actor, creator_display_name: str, testimony_title: str, response_text: str
) -> UserNotification:
    """Phase 23 Slice 4 -- reaches the original reactor as a real
    notification, not just a dashboard-visible log row (Phase 23's own
    test requirement). `actor` is the creator who responded; their
    Ministry display name (not email) is what the reactor actually
    recognizes, same reasoning as notify_creator_digest."""
    title = f"{creator_display_name} responded to your prayer"
    message = f'On "{testimony_title}": {response_text}'
    notification = UserNotification.objects.create(
        recipient=recipient,
        actor=actor,
        notification_type=NotificationType.PRAYER_RESPONSE,
        title=title,
        message=message,
    )
    send_push_to_users(user_ids=[recipient.id], title=title, body=message)
    return notification


def notify_testimony_comment(*, recipient, actor, testimony_title: str) -> UserNotification:
    actor_name = getattr(actor, "full_name", "") or actor.email
    title = "New comment on your testimony"
    message = f"{actor_name} commented on your testimony \"{testimony_title}\"."
    notification = UserNotification.objects.create(
        recipient=recipient,
        actor=actor,
        notification_type=NotificationType.TESTIMONY_COMMENT,
        title=title,
        message=message,
    )
    send_push_to_users(user_ids=[recipient.id], title=title, body=message)
    return notification
