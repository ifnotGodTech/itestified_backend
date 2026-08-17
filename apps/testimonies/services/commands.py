from __future__ import annotations

from datetime import datetime

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.testimonies.exceptions import (
    AIJobNotRetryableError,
    TestimonyTransitionNotAllowedError,
    TestimonyTranslationNotReadyError,
)
from apps.testimonies.models import (
    ModerationAction,
    Testimony,
    TestimonyModerationHistory,
    TestimonyReaction,
    TestimonyReactionType,
    TestimonyStatus,
    TestimonyType,
    TranscriptionJob,
    TranscriptionJobStatus,
    TranslationJob,
    TranslationJobStatus,
)
from apps.notifications.services import (
    notify_new_video_testimony_published,
    notify_testimony_approved,
    notify_testimony_rejected,
)
from apps.testimonies.tasks import run_transcription_job, run_translation_job


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


def enqueue_transcription_job(*, testimony: Testimony) -> TranscriptionJob | None:
    """Phase 22 Slice 1 -- creates a TranscriptionJob for a newly-created
    video testimony and enqueues the Celery task that runs it, deferred to
    transaction.on_commit (safe to call unconditionally regardless of
    caller context -- runs immediately outside an atomic block, or once the
    enclosing transaction actually commits, same pattern as
    apps/notifications/services.py). Audio isn't supported yet (Phase 28);
    a written testimony returns None. A repeat call for a testimony that
    already has a job is a no-op (returns the existing job, doesn't
    re-enqueue) so this is safe to call more than once."""
    if testimony.testimony_type != TestimonyType.VIDEO:
        return None
    job, created = TranscriptionJob.objects.get_or_create(testimony=testimony)
    if not created:
        return job
    transaction.on_commit(lambda: run_transcription_job.delay(job.id))
    return job


def request_testimony_translation(*, testimony: Testimony, language: str) -> TranslationJob:
    """Phase 22 Slice 2 -- get-or-creates a TranslationJob for (testimony,
    language). A previously DONE job is returned as-is with no new work
    enqueued -- the caching behavior Phase 22's own Build note requires,
    and what makes this endpoint safe for mobile to call repeatedly both to
    request a language and to poll for its result. A previously FAILED job
    is retried by resetting it to pending and re-enqueuing, so a transient
    failure doesn't permanently strand a language behind a dead job.

    Raises TestimonyTranslationNotReadyError if the testimony has no
    completed transcript yet -- translation source text is always the
    transcript (Slice 1), never the raw video, so there's nothing to
    translate until that finishes."""
    transcription_job = getattr(testimony, "transcription_job", None)
    if transcription_job is None or transcription_job.status != TranscriptionJobStatus.DONE:
        raise TestimonyTranslationNotReadyError("Transcript isn't ready yet.")

    job, created = TranslationJob.objects.get_or_create(testimony=testimony, language=language)
    if created or job.status == TranslationJobStatus.FAILED:
        job.status = TranslationJobStatus.PENDING
        job.error_message = ""
        job.save(update_fields=["status", "error_message", "updated_at"])
        transaction.on_commit(lambda: run_translation_job.delay(job.id))
    return job


def retry_transcription_job(*, job_id: int) -> TranscriptionJob:
    """Phase 22 Slice 5 -- admin-triggered retry for a FAILED
    TranscriptionJob. Unlike request_testimony_translation, nothing else
    re-enqueues a transcription job on its own (it's only ever created
    once, at testimony-creation time), so without this a failed job is
    stuck forever. Only a FAILED job may be retried -- pending/processing
    is already in flight, and done is already correct."""
    job = TranscriptionJob.objects.select_related("testimony").get(id=job_id)
    if job.status != TranscriptionJobStatus.FAILED:
        raise AIJobNotRetryableError(f"Job is '{job.status}', not 'failed' -- nothing to retry.")

    job.status = TranscriptionJobStatus.PENDING
    job.error_message = ""
    job.save(update_fields=["status", "error_message", "updated_at"])
    transaction.on_commit(lambda: run_transcription_job.delay(job.id))
    return job


def retry_translation_job(*, job_id: int) -> TranslationJob:
    """Phase 22 Slice 5 -- admin-triggered retry for a FAILED
    TranslationJob, for the case where the admin notices the failure
    before the reader ever re-requests that language (which would also
    retry it, per request_testimony_translation)."""
    job = TranslationJob.objects.select_related("testimony").get(id=job_id)
    if job.status != TranslationJobStatus.FAILED:
        raise AIJobNotRetryableError(f"Job is '{job.status}', not 'failed' -- nothing to retry.")

    job.status = TranslationJobStatus.PENDING
    job.error_message = ""
    job.save(update_fields=["status", "error_message", "updated_at"])
    transaction.on_commit(lambda: run_translation_job.delay(job.id))
    return job


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
