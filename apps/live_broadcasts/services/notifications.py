from __future__ import annotations

from apps.live_broadcasts.models import LiveBroadcastApprovalRequest, LiveBroadcastApprovalStatus
from apps.notifications.models import NotificationType, UserNotification
from apps.notifications.services import send_push_to_users
from apps.users.choices import AdminAssignmentStatus
from apps.users.models import AdminAssignment


def notify_admins_of_approval_request(approval_request: LiveBroadcastApprovalRequest) -> int:
    """Mirrors `notify_admins_of_new_donation`'s shape (apps.notifications) --
    this is the fallback path's whole point: if a Ministry can't self-serve
    a top-up, an admin needs to actually see the request, not just have it
    sit in a queue nobody's told to check."""
    admin_user_ids = list(
        AdminAssignment.objects.filter(status=AdminAssignmentStatus.ACTIVE)
        .values_list("user_id", flat=True)
        .distinct()
    )
    if not admin_user_ids:
        return 0
    title = "Live streaming minute request"
    message = (
        f"{approval_request.creator.email} requested {approval_request.requested_minutes} extra "
        f"streaming minutes for broadcast #{approval_request.broadcast_id}."
    )
    rows = [
        UserNotification(
            recipient_id=user_id,
            actor=approval_request.creator,
            notification_type=NotificationType.LIVE_BROADCAST_APPROVAL_REQUESTED,
            title=title,
            message=message,
            metadata={"broadcast_id": approval_request.broadcast_id, "approval_request_id": approval_request.id},
        )
        for user_id in admin_user_ids
    ]
    UserNotification.objects.bulk_create(rows)
    send_push_to_users(user_ids=admin_user_ids, title=title, body=message)
    return len(rows)


def notify_creator_of_approval_decision(approval_request: LiveBroadcastApprovalRequest) -> UserNotification:
    approved = approval_request.status == LiveBroadcastApprovalStatus.APPROVED
    title = "Extra streaming minutes approved" if approved else "Extra streaming minutes request declined"
    message = (
        f"Your request for {approval_request.requested_minutes} extra minutes was approved."
        if approved
        else f"Your request for {approval_request.requested_minutes} extra minutes was declined."
    )
    note = approval_request.review_note.strip()
    if note:
        message += f" Note: {note}"
    notification = UserNotification.objects.create(
        recipient=approval_request.creator,
        actor=approval_request.reviewed_by,
        notification_type=NotificationType.LIVE_BROADCAST_APPROVAL_DECIDED,
        title=title,
        message=message,
        metadata={"broadcast_id": approval_request.broadcast_id, "approval_request_id": approval_request.id},
    )
    send_push_to_users(user_ids=[approval_request.creator_id], title=title, body=message)
    return notification
