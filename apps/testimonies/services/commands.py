from __future__ import annotations

from datetime import datetime

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.testimonies.exceptions import TestimonyTransitionNotAllowedError
from apps.testimonies.models import (
    ModerationAction,
    Testimony,
    TestimonyModerationHistory,
    TestimonyReaction,
    TestimonyReactionType,
    TestimonyStatus,
    TestimonyType,
)
from apps.notifications.services import (
    notify_new_video_testimony_published,
    notify_testimony_approved,
    notify_testimony_rejected,
)


def _record_history(
    *,
    testimony: Testimony,
    action: str,
    from_status: str,
    to_status: str,
    actor,
    reason: str = "",
    publish_at=None,
) -> None:
    TestimonyModerationHistory.objects.create(
        testimony=testimony,
        action=action,
        actor=actor,
        from_status=from_status,
        to_status=to_status,
        reason=reason,
        publish_at=publish_at,
    )


@transaction.atomic
def approve_testimony(*, testimony: Testimony, actor) -> Testimony:
    if testimony.status != TestimonyStatus.PENDING_REVIEW:
        raise TestimonyTransitionNotAllowedError("Only pending testimonies can be approved.")
    from_status = testimony.status
    testimony.status = TestimonyStatus.APPROVED
    testimony.rejection_reason = ""
    testimony.publish_at = None
    testimony.archived_at = None
    testimony.save(update_fields=["status", "rejection_reason", "publish_at", "archived_at", "updated_at"])
    _record_history(
        testimony=testimony,
        action=ModerationAction.APPROVED,
        from_status=from_status,
        to_status=TestimonyStatus.APPROVED,
        actor=actor,
    )
    notify_testimony_approved(
        recipient=testimony.author,
        actor=actor,
        testimony_title=testimony.title,
    )
    return testimony


@transaction.atomic
def reject_testimony(*, testimony: Testimony, actor, reason: str) -> Testimony:
    if testimony.status != TestimonyStatus.PENDING_REVIEW:
        raise TestimonyTransitionNotAllowedError("Only pending testimonies can be rejected.")
    from_status = testimony.status
    testimony.status = TestimonyStatus.REJECTED
    testimony.rejection_reason = reason
    testimony.publish_at = None
    testimony.save(update_fields=["status", "rejection_reason", "publish_at", "updated_at"])
    _record_history(
        testimony=testimony,
        action=ModerationAction.REJECTED,
        from_status=from_status,
        to_status=TestimonyStatus.REJECTED,
        actor=actor,
        reason=reason,
    )
    notify_testimony_rejected(
        recipient=testimony.author,
        actor=actor,
        testimony_title=testimony.title,
        reason=reason,
    )
    return testimony


@transaction.atomic
def schedule_testimony(*, testimony: Testimony, actor, publish_at: datetime) -> Testimony:
    if testimony.status != TestimonyStatus.PENDING_REVIEW:
        raise TestimonyTransitionNotAllowedError("Only pending testimonies can be scheduled.")
    from_status = testimony.status
    testimony.status = TestimonyStatus.SCHEDULED
    testimony.publish_at = publish_at
    testimony.rejection_reason = ""
    testimony.archived_at = None
    testimony.save(update_fields=["status", "publish_at", "rejection_reason", "archived_at", "updated_at"])
    _record_history(
        testimony=testimony,
        action=ModerationAction.SCHEDULED,
        from_status=from_status,
        to_status=TestimonyStatus.SCHEDULED,
        actor=actor,
        publish_at=publish_at,
    )
    return testimony


@transaction.atomic
def archive_testimony(*, testimony: Testimony, actor, reason: str = "") -> Testimony:
    if testimony.status not in (TestimonyStatus.APPROVED, TestimonyStatus.SCHEDULED):
        raise TestimonyTransitionNotAllowedError("Only approved or scheduled testimonies can be archived.")
    from_status = testimony.status
    testimony.status = TestimonyStatus.ARCHIVED
    testimony.archived_at = timezone.now()
    testimony.publish_at = None
    testimony.save(update_fields=["status", "archived_at", "publish_at", "updated_at"])
    _record_history(
        testimony=testimony,
        action=ModerationAction.ARCHIVED,
        from_status=from_status,
        to_status=TestimonyStatus.ARCHIVED,
        actor=actor,
        reason=reason,
    )
    return testimony


@transaction.atomic
def upload_now_video_testimony(*, testimony: Testimony, actor) -> Testimony:
    if testimony.testimony_type != TestimonyType.VIDEO:
        raise TestimonyTransitionNotAllowedError("Only video testimonies can be uploaded now.")
    if testimony.status not in (TestimonyStatus.DRAFT, TestimonyStatus.SCHEDULED):
        raise TestimonyTransitionNotAllowedError("Only draft or scheduled video testimonies can be uploaded now.")
    from_status = testimony.status
    testimony.status = TestimonyStatus.APPROVED
    testimony.publish_at = None
    testimony.save(update_fields=["status", "publish_at", "updated_at"])
    _record_history(
        testimony=testimony,
        action=ModerationAction.APPROVED,
        from_status=from_status,
        to_status=TestimonyStatus.APPROVED,
        actor=actor,
        reason="Uploaded now from draft/scheduled via admin modal.",
    )
    return testimony


@transaction.atomic
def auto_publish_due_scheduled_testimonies() -> int:
    now = timezone.now()
    testimonies = list(
        Testimony.objects.filter(
            status=TestimonyStatus.SCHEDULED,
            publish_at__isnull=False,
            publish_at__lte=now,
        )
    )
    for testimony in testimonies:
        from_status = testimony.status
        testimony.status = TestimonyStatus.APPROVED
        testimony.publish_at = None
        testimony.save(update_fields=["status", "publish_at", "updated_at"])
        _record_history(
            testimony=testimony,
            action=ModerationAction.AUTO_PUBLISHED,
            from_status=from_status,
            to_status=TestimonyStatus.APPROVED,
            actor=None,
        )
        if testimony.testimony_type == TestimonyType.VIDEO:
            notify_new_video_testimony_published(testimony=testimony, actor=None)
    return len(testimonies)


_REACTION_COUNT_FIELDS = {
    TestimonyReactionType.PRAYING_FOR_YOU: "praying_for_you_count",
    TestimonyReactionType.AMEN: "amen_count",
    TestimonyReactionType.GIVES_ME_HOPE: "gives_me_hope_count",
}


def _adjust_reaction_count(*, testimony_id: int, reaction_type: str, delta: int) -> None:
    field = _REACTION_COUNT_FIELDS[reaction_type]
    Testimony.objects.filter(id=testimony_id).update(**{field: F(field) + delta})


@transaction.atomic
def set_testimony_reaction(*, testimony: Testimony, user, reaction_type: str) -> Testimony:
    """Sets the user's reaction on a testimony, switching it if they already
    reacted differently. One reaction per user per testimony (unique
    constraint on TestimonyReaction) -- tapping the same reaction again is a
    no-op, tapping a different one moves the count from the old type to the
    new one, tapping for the first time just increments the new type."""
    existing = (
        TestimonyReaction.objects.select_for_update()
        .filter(user=user, testimony=testimony)
        .first()
    )
    if existing is not None:
        if existing.reaction_type == reaction_type:
            return testimony
        _adjust_reaction_count(testimony_id=testimony.id, reaction_type=existing.reaction_type, delta=-1)
        existing.reaction_type = reaction_type
        existing.save(update_fields=["reaction_type"])
    else:
        TestimonyReaction.objects.get_or_create(
            user=user, testimony=testimony, defaults={"reaction_type": reaction_type}
        )
    _adjust_reaction_count(testimony_id=testimony.id, reaction_type=reaction_type, delta=1)
    testimony.refresh_from_db(fields=["praying_for_you_count", "amen_count", "gives_me_hope_count"])
    return testimony


@transaction.atomic
def remove_testimony_reaction(*, testimony: Testimony, user) -> Testimony:
    existing = (
        TestimonyReaction.objects.select_for_update()
        .filter(user=user, testimony=testimony)
        .first()
    )
    if existing is not None:
        _adjust_reaction_count(testimony_id=testimony.id, reaction_type=existing.reaction_type, delta=-1)
        existing.delete()
    testimony.refresh_from_db(fields=["praying_for_you_count", "amen_count", "gives_me_hope_count"])
    return testimony
