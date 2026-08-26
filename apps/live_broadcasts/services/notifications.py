from __future__ import annotations

from apps.creators.models import CreatorFollow
from apps.live_broadcasts.models import LiveBroadcast, LiveBroadcastApprovalRequest, LiveBroadcastApprovalStatus
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


def notify_creator_broadcast_recording_ready(broadcast: LiveBroadcast) -> UserNotification:
    """Phase 27 Slice 5 -- the creator's recording is archived as a DRAFT
    testimony (services/commands.py's archive_broadcast_recording) and
    waiting on their own Slice 3 decision (submit for review or hold);
    this is what tells them it's there to act on, instead of them having
    to keep checking back."""
    title = "Your broadcast recording is ready"
    message = f'The recording of "{broadcast.title}" is ready for you to review and submit whenever you\'re ready.'
    notification = UserNotification.objects.create(
        recipient=broadcast.creator,
        notification_type=NotificationType.LIVE_BROADCAST_RECORDING_READY,
        title=title,
        message=message,
        metadata={"broadcast_id": broadcast.id, "testimony_id": broadcast.archived_testimony_id},
    )
    send_push_to_users(user_ids=[broadcast.creator_id], title=title, body=message)
    return notification


def notify_admins_of_live_broadcast_started(broadcast: LiveBroadcast) -> int:
    """Phase 27 Slice 7 -- pure polling on the admin monitoring panel
    (Slice 7's own list endpoint) only helps if an admin happens to have
    it open at the right moment; this is what prompts them to check in
    the instant a Ministry actually goes live, since live broadcasting
    has no real-time content moderation otherwise (see Slice 7's own
    plan text). Mirrors `notify_admins_of_approval_request`'s shape
    exactly -- same on-duty-admin audience, same bulk-create-plus-push
    pattern -- just a different trigger and a distinct notification type
    so a follower's "is live now" and an admin's "go check the monitoring
    panel" are never conflated on either client."""
    admin_user_ids = list(
        AdminAssignment.objects.filter(status=AdminAssignmentStatus.ACTIVE)
        .values_list("user_id", flat=True)
        .distinct()
    )
    if not admin_user_ids:
        return 0
    creator_display_name = getattr(broadcast.creator, "email", "A Ministry")
    creator_profile = getattr(broadcast.creator, "creator_profile", None)
    if creator_profile is not None and creator_profile.display_name:
        creator_display_name = creator_profile.display_name

    title = "A Ministry is live -- monitoring needed"
    message = f'{creator_display_name} just started "{broadcast.title}". Open the Live Broadcasts panel to monitor it.'
    rows = [
        UserNotification(
            recipient_id=user_id,
            actor=broadcast.creator,
            notification_type=NotificationType.LIVE_BROADCAST_ADMIN_ALERT,
            title=title,
            message=message,
            metadata={"broadcast_id": broadcast.id},
        )
        for user_id in admin_user_ids
    ]
    UserNotification.objects.bulk_create(rows)
    send_push_to_users(user_ids=admin_user_ids, title=title, body=message)
    return len(rows)


def notify_creator_broadcast_admin_terminated(broadcast: LiveBroadcast) -> UserNotification:
    """Phase 27 Slice 8 -- the creator is told their broadcast was ended
    by an admin and why, matching the same non-generic-error principle
    used everywhere else in this app (e.g. a rejected testimony always
    carries its reason, see apps.testimonies)."""
    title = "Your broadcast was ended by an admin"
    message = f'"{broadcast.title}" was ended by an admin.'
    note = broadcast.admin_termination_note.strip()
    if note:
        message += f" Reason: {note}"
    notification = UserNotification.objects.create(
        recipient=broadcast.creator,
        notification_type=NotificationType.LIVE_BROADCAST_ADMIN_TERMINATED,
        title=title,
        message=message,
        metadata={"broadcast_id": broadcast.id},
    )
    send_push_to_users(user_ids=[broadcast.creator_id], title=title, body=message)
    return notification


def notify_followers_of_live_broadcast(broadcast: LiveBroadcast) -> int:
    """Phase 27 Slice 6 -- one notification per follower per broadcast,
    the moment go_live() (services/commands.py) actually succeeds, not at
    scheduling time (a follower shouldn't be pinged for something that
    hasn't started, and might never start if the Ministry never taps Go
    Live). Mirrors `notify_creator_digest`'s bulk-create shape
    (apps.notifications) -- same "one row per follower, not per event
    fan-out elsewhere" batching principle, just triggered by a single
    broadcast instead of a daily digest window."""
    follower_ids = list(
        CreatorFollow.objects.filter(creator_id=broadcast.creator_id).values_list("follower_id", flat=True)
    )
    if not follower_ids:
        return 0

    creator_display_name = getattr(broadcast.creator, "email", "A Ministry you follow")
    creator_profile = getattr(broadcast.creator, "creator_profile", None)
    if creator_profile is not None and creator_profile.display_name:
        creator_display_name = creator_profile.display_name

    title = f"{creator_display_name} is live now"
    message = f'"{broadcast.title}" just started -- watch now.'
    rows = [
        UserNotification(
            recipient_id=follower_id,
            actor=broadcast.creator,
            notification_type=NotificationType.LIVE_BROADCAST_STARTED,
            title=title,
            message=message,
            metadata={"broadcast_id": broadcast.id},
        )
        for follower_id in follower_ids
    ]
    UserNotification.objects.bulk_create(rows)
    send_push_to_users(user_ids=follower_ids, title=title, body=message)
    return len(rows)
