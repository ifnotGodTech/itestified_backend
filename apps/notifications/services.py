from apps.notifications.models import NotificationType, UserNotification, UserNotificationPreference
from apps.users.choices import AdminAssignmentStatus, UserAccountStatus
from apps.users.models import AdminAssignment
from apps.users.models import User


def notify_testimony_approved(*, recipient, actor, testimony_title: str) -> UserNotification:
    return UserNotification.objects.create(
        recipient=recipient,
        actor=actor,
        notification_type=NotificationType.TESTIMONY_APPROVED,
        title="Your testimony was approved",
        message=f'"{testimony_title}" has been approved and is now visible to others.',
    )


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

    label = "Video" if testimony_type == "video" else "Text"
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

    rows = [
        UserNotification(
            recipient_id=user_id,
            actor=actor,
            notification_type=NotificationType.NEW_VIDEO_TESTIMONY,
            title="New video testimony",
            message=f'New video testimony published: "{testimony.title}".',
        )
        for user_id in recipient_ids
    ]
    UserNotification.objects.bulk_create(rows)
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


def notify_testimony_comment(*, recipient, actor, testimony_title: str) -> UserNotification:
    actor_name = getattr(actor, "full_name", "") or actor.email
    return UserNotification.objects.create(
        recipient=recipient,
        actor=actor,
        notification_type=NotificationType.TESTIMONY_COMMENT,
        title="New comment on your testimony",
        message=f"{actor_name} commented on your testimony \"{testimony_title}\".",
    )
