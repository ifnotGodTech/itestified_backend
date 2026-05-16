from __future__ import annotations

from datetime import datetime

from django.db import transaction
from django.utils import timezone

from apps.testimonies.models import (
    ModerationAction,
    Testimony,
    TestimonyModerationHistory,
    TestimonyStatus,
)
from apps.notifications.services import (
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
    return len(testimonies)
