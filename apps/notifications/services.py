from apps.notifications.models import NotificationType, UserNotification
from apps.users.choices import AdminAssignmentStatus
from apps.users.models import AdminAssignment


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


def notify_testimony_comment(*, recipient, actor, testimony_title: str) -> UserNotification:
    actor_name = getattr(actor, "full_name", "") or actor.email
    return UserNotification.objects.create(
        recipient=recipient,
        actor=actor,
        notification_type=NotificationType.TESTIMONY_COMMENT,
        title="New comment on your testimony",
        message=f"{actor_name} commented on your testimony \"{testimony_title}\".",
    )
