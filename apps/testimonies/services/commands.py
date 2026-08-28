from __future__ import annotations

import uuid
import logging
from datetime import datetime, timedelta

from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from apps.testimonies.exceptions import (
    AIJobNotRetryableError,
    AudioDailyLimitReachedError,
    AudioPremiumRequiredError,
    AudioUploadAssetVerificationError,
    AudioUploadIntentConsumedError,
    AudioUploadIntentExpiredError,
    AudioUploadIntentNotFoundError,
    TestimonyTransitionNotAllowedError,
    TestimonyTranslationNotReadyError,
    VideoDailyLimitReachedError,
    VideoPremiumRequiredError,
    VideoUploadAssetVerificationError,
    VideoUploadIntentConsumedError,
    VideoUploadIntentExpiredError,
    VideoUploadIntentNotFoundError,
)
from apps.testimonies.models import (
    AudioUploadIntent,
    AudioUploadPolicy,
    AudioUploadPolicyHistory,
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
    VideoUploadIntent,
    VideoUploadPolicy,
    VideoUploadPolicyHistory,
)
from apps.subscriptions.selectors import is_user_premium
from apps.testimonies.services.media_uploads import (
    CloudinaryUploadError,
    CloudinaryUploadSignature,
    build_cloudinary_video_thumbnail_url,
    create_direct_upload_signature,
    delete_cloudinary_asset,
    get_cloudinary_audio_asset,
    get_cloudinary_video_asset,
)
from apps.notifications.services import (
    notify_new_video_testimony_published,
    notify_testimony_approved,
    notify_testimony_rejected,
    notify_testimony_submitted_to_admins,
)
from apps.testimonies.tasks import run_transcription_job, run_translation_job


logger = logging.getLogger(__name__)


AUDIO_UPLOAD_INTENT_LIFETIME = timedelta(minutes=15)
AUDIO_FORMAT_CONTENT_TYPES = {
    "aac": {"audio/aac"},
    "m4a": {"audio/mp4", "audio/x-m4a"},
    "mp3": {"audio/mpeg", "audio/mp3"},
    "mp4": {"audio/mp4"},
}
# Videos take longer to upload than audio (200MB default cap vs. 50MB), so
# the intent gets a longer window before it expires on a slow connection.
VIDEO_UPLOAD_INTENT_LIFETIME = timedelta(minutes=30)
VIDEO_FORMAT_CONTENT_TYPES = {
    "mp4": {"video/mp4"},
    "mov": {"video/quicktime"},
    "m4v": {"video/mp4", "video/x-m4v"},
}


def _count_todays_submissions(*, user, testimony_type: str) -> int:
    """Calendar-day count (not a rolling 24h window) of a user's own
    testimonies of one media type, used for Phase 32's daily submission
    caps. Counts every submission regardless of moderation outcome -- a
    rejected submission still consumed a slot, which is what stops someone
    retry-spamming the queue."""
    return Testimony.objects.filter(
        author=user,
        testimony_type=testimony_type,
        created_at__date=timezone.localdate(),
    ).count()


def issue_audio_upload_intent(*, user) -> tuple[AudioUploadIntent, CloudinaryUploadSignature]:
    if not is_user_premium(user):
        raise AudioPremiumRequiredError("Premium is required to submit an audio testimony.")

    policy, _ = AudioUploadPolicy.objects.get_or_create(pk=1)
    if _count_todays_submissions(user=user, testimony_type=TestimonyType.AUDIO) >= policy.daily_limit:
        raise AudioDailyLimitReachedError(
            f"You've reached today's limit of {policy.daily_limit} audio submissions. Try again tomorrow."
        )
    upload_public_id = f"audio_{uuid.uuid4().hex}"
    signature = create_direct_upload_signature(
        resource_type="audio",
        public_id=upload_public_id,
    )
    intent = AudioUploadIntent.objects.create(
        user=user,
        folder=signature.folder,
        public_id=upload_public_id,
        max_file_size_bytes=policy.max_file_size_bytes,
        max_duration_ms=policy.max_duration_ms,
        allowed_content_types=list(policy.allowed_content_types),
        expires_at=timezone.now() + AUDIO_UPLOAD_INTENT_LIFETIME,
    )
    return intent, signature


def _verified_audio_content_type(*, asset_format: str, allowed_content_types: list[str]) -> str:
    candidates = AUDIO_FORMAT_CONTENT_TYPES.get(asset_format, set())
    allowed = {str(value).strip().lower() for value in allowed_content_types}
    matches = sorted(candidates & allowed)
    if not matches:
        raise AudioUploadAssetVerificationError("This audio format is not accepted.")
    return matches[0]


@transaction.atomic
def create_audio_testimony_from_upload(
    *,
    user,
    upload_intent_id,
    title: str,
    category,
    body: str = "",
) -> Testimony:
    if not is_user_premium(user):
        raise AudioPremiumRequiredError("Premium is required to submit an audio testimony.")

    try:
        intent = AudioUploadIntent.objects.select_for_update().get(id=upload_intent_id)
    except (AudioUploadIntent.DoesNotExist, ValueError, TypeError):
        raise AudioUploadIntentNotFoundError("Audio upload authorization was not found.") from None

    if intent.user_id != user.id:
        raise AudioUploadIntentNotFoundError("Audio upload authorization was not found.")
    if intent.consumed_at is not None:
        raise AudioUploadIntentConsumedError("This audio upload has already been submitted.")
    if intent.expires_at <= timezone.now():
        raise AudioUploadIntentExpiredError("This audio upload authorization has expired.")

    try:
        asset = get_cloudinary_audio_asset(public_id=intent.asset_public_id)
    except CloudinaryUploadError as exc:
        raise AudioUploadAssetVerificationError(str(exc)) from exc

    if asset.public_id != intent.asset_public_id:
        raise AudioUploadAssetVerificationError("The uploaded audio does not match this authorization.")
    if asset.resource_type != "video" or not asset.is_audio_only:
        raise AudioUploadAssetVerificationError("The uploaded asset is not an audio-only file.")
    if asset.file_size_bytes <= 0 or asset.file_size_bytes > intent.max_file_size_bytes:
        raise AudioUploadAssetVerificationError("Audio exceeds the configured file-size limit.")
    if asset.duration_ms <= 0 or asset.duration_ms > intent.max_duration_ms:
        raise AudioUploadAssetVerificationError("Audio exceeds the configured duration limit.")
    _verified_audio_content_type(
        asset_format=asset.format,
        allowed_content_types=intent.allowed_content_types,
    )

    testimony = Testimony.objects.create(
        author=user,
        category=category,
        title=title,
        body=body,
        testimony_type=TestimonyType.AUDIO,
        status=TestimonyStatus.PENDING_REVIEW,
        audio_url=asset.secure_url,
        duration_ms=asset.duration_ms,
    )
    intent.consumed_at = timezone.now()
    intent.testimony = testimony
    intent.save(update_fields=("consumed_at", "testimony"))
    enqueue_transcription_job(testimony=testimony)
    notify_testimony_submitted_to_admins(
        testimony_title=testimony.title,
        testimony_type=testimony.testimony_type,
        actor=user,
        testimony_id=testimony.id,
    )
    return testimony


def issue_video_upload_intent(*, user) -> tuple[VideoUploadIntent, CloudinaryUploadSignature]:
    """Phase 32 -- parallel to `issue_audio_upload_intent`."""
    if not is_user_premium(user):
        raise VideoPremiumRequiredError("Premium is required to submit a video testimony.")

    policy, _ = VideoUploadPolicy.objects.get_or_create(pk=1)
    if _count_todays_submissions(user=user, testimony_type=TestimonyType.VIDEO) >= policy.daily_limit:
        raise VideoDailyLimitReachedError(
            f"You've reached today's limit of {policy.daily_limit} video submissions. Try again tomorrow."
        )
    upload_public_id = f"video_{uuid.uuid4().hex}"
    signature = create_direct_upload_signature(
        resource_type="video",
        public_id=upload_public_id,
    )
    intent = VideoUploadIntent.objects.create(
        user=user,
        folder=signature.folder,
        public_id=upload_public_id,
        max_file_size_bytes=policy.max_file_size_bytes,
        max_duration_ms=policy.max_duration_ms,
        allowed_content_types=list(policy.allowed_content_types),
        expires_at=timezone.now() + VIDEO_UPLOAD_INTENT_LIFETIME,
    )
    return intent, signature


def _verified_video_content_type(*, asset_format: str, allowed_content_types: list[str]) -> str:
    candidates = VIDEO_FORMAT_CONTENT_TYPES.get(asset_format, set())
    allowed = {str(value).strip().lower() for value in allowed_content_types}
    matches = sorted(candidates & allowed)
    if not matches:
        raise VideoUploadAssetVerificationError("This video format is not accepted.")
    return matches[0]


@transaction.atomic
def create_video_testimony_from_upload(
    *,
    user,
    upload_intent_id,
    title: str,
    category,
    body: str = "",
) -> Testimony:
    """Phase 32 -- parallel to `create_audio_testimony_from_upload`, with
    one addition: an asset that fails the post-upload policy check is
    deleted from Cloudinary immediately rather than left orphaned (the
    2026-08-26 product decision on abuse resistance -- see the Phase 32
    plan section)."""
    if not is_user_premium(user):
        raise VideoPremiumRequiredError("Premium is required to submit a video testimony.")

    try:
        intent = VideoUploadIntent.objects.select_for_update().get(id=upload_intent_id)
    except (VideoUploadIntent.DoesNotExist, ValueError, TypeError):
        raise VideoUploadIntentNotFoundError("Video upload authorization was not found.") from None

    if intent.user_id != user.id:
        raise VideoUploadIntentNotFoundError("Video upload authorization was not found.")
    if intent.consumed_at is not None:
        raise VideoUploadIntentConsumedError("This video upload has already been submitted.")
    if intent.expires_at <= timezone.now():
        raise VideoUploadIntentExpiredError("This video upload authorization has expired.")

    try:
        asset = get_cloudinary_video_asset(public_id=intent.asset_public_id)
    except CloudinaryUploadError as exc:
        raise VideoUploadAssetVerificationError(str(exc)) from exc

    if asset.public_id != intent.asset_public_id:
        raise VideoUploadAssetVerificationError("The uploaded video does not match this authorization.")
    if asset.resource_type != "video" or not asset.has_visual_track:
        delete_cloudinary_asset(public_id=intent.asset_public_id)
        raise VideoUploadAssetVerificationError("The uploaded asset is not a video file.")
    if asset.file_size_bytes <= 0 or asset.file_size_bytes > intent.max_file_size_bytes:
        delete_cloudinary_asset(public_id=intent.asset_public_id)
        raise VideoUploadAssetVerificationError("Video exceeds the configured file-size limit.")
    if asset.duration_ms <= 0 or asset.duration_ms > intent.max_duration_ms:
        delete_cloudinary_asset(public_id=intent.asset_public_id)
        raise VideoUploadAssetVerificationError("Video exceeds the configured duration limit.")
    try:
        _verified_video_content_type(
            asset_format=asset.format,
            allowed_content_types=intent.allowed_content_types,
        )
    except VideoUploadAssetVerificationError:
        delete_cloudinary_asset(public_id=intent.asset_public_id)
        raise

    testimony = Testimony.objects.create(
        author=user,
        category=category,
        title=title,
        body=body,
        testimony_type=TestimonyType.VIDEO,
        status=TestimonyStatus.PENDING_REVIEW,
        video_url=asset.secure_url,
        thumbnail_url=build_cloudinary_video_thumbnail_url(asset.secure_url),
        duration_ms=asset.duration_ms,
    )
    intent.consumed_at = timezone.now()
    intent.testimony = testimony
    intent.save(update_fields=("consumed_at", "testimony"))
    enqueue_transcription_job(testimony=testimony)
    notify_testimony_submitted_to_admins(
        testimony_title=testimony.title,
        testimony_type=testimony.testimony_type,
        actor=user,
        testimony_id=testimony.id,
    )
    return testimony


def _update_media_upload_policy(
    *,
    policy,
    history_model,
    actor,
    new_values: dict,
):
    """Shared one-row-per-changed-field update, mirroring
    `update_live_streaming_policy` -- factored out since `AudioUploadPolicy`
    and `VideoUploadPolicy` need the identical update shape."""
    changed_fields = []
    history_rows = []
    for field_name, new_value in new_values.items():
        old_value = getattr(policy, field_name)
        if old_value == new_value:
            continue
        changed_fields.append(field_name)
        history_rows.append(
            history_model(
                policy=policy,
                field_name=field_name,
                from_value=str(old_value),
                to_value=str(new_value),
                actor=actor,
            )
        )
        setattr(policy, field_name, new_value)

    if changed_fields:
        policy.updated_by = actor
        policy.save(update_fields=[*changed_fields, "updated_by", "updated_at"])
        history_model.objects.bulk_create(history_rows)
    return policy


@transaction.atomic
def update_audio_upload_policy(
    *,
    actor,
    max_file_size_bytes: int,
    max_duration_ms: int,
    allowed_content_types: list,
    daily_limit: int,
) -> AudioUploadPolicy:
    policy, _ = AudioUploadPolicy.objects.select_for_update().get_or_create(pk=1)
    return _update_media_upload_policy(
        policy=policy,
        history_model=AudioUploadPolicyHistory,
        actor=actor,
        new_values={
            "max_file_size_bytes": max_file_size_bytes,
            "max_duration_ms": max_duration_ms,
            "allowed_content_types": allowed_content_types,
            "daily_limit": daily_limit,
        },
    )


@transaction.atomic
def update_video_upload_policy(
    *,
    actor,
    max_file_size_bytes: int,
    max_duration_ms: int,
    allowed_content_types: list,
    daily_limit: int,
) -> VideoUploadPolicy:
    policy, _ = VideoUploadPolicy.objects.select_for_update().get_or_create(pk=1)
    return _update_media_upload_policy(
        policy=policy,
        history_model=VideoUploadPolicyHistory,
        actor=actor,
        new_values={
            "max_file_size_bytes": max_file_size_bytes,
            "max_duration_ms": max_duration_ms,
            "allowed_content_types": allowed_content_types,
            "daily_limit": daily_limit,
        },
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
    if testimony.testimony_type not in (TestimonyType.VIDEO, TestimonyType.AUDIO):
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
    """Create and dispatch one durable transcript job for video or audio.

    The row is created inside the caller's transaction; broker dispatch is
    deferred until commit. A broker outage is logged without escaping into
    the request, leaving the durable PENDING row available for redispatch.
    """
    if testimony.testimony_type not in (TestimonyType.VIDEO, TestimonyType.AUDIO):
        return None
    job, created = TranscriptionJob.objects.get_or_create(testimony=testimony)
    if not created:
        return job
    transaction.on_commit(lambda: dispatch_transcription_job(job_id=job.id))
    return job


def dispatch_transcription_job(*, job_id: int) -> bool:
    """Best-effort Celery publication that never breaks the domain action."""
    try:
        run_transcription_job.delay(job_id)
    except Exception:  # noqa: BLE001 - broker/client exception classes vary.
        logger.exception(
            "transcription.dispatch_failed job_id=%s; job remains pending for redispatch",
            job_id,
        )
        return False
    return True


def redispatch_stranded_transcription_jobs(
    *,
    pending_older_than: timedelta = timedelta(minutes=1),
    processing_older_than: timedelta = timedelta(minutes=30),
    limit: int = 100,
) -> tuple[int, int]:
    """Redispatch old PENDING jobs and recover stale PROCESSING jobs.

    Duplicate Celery deliveries are safe because the task atomically claims
    only a PENDING row. PROCESSING rows are reset only after the explicit
    stale threshold, covering a worker that died after claiming a job.
    Returns ``(attempted, published)`` for operator visibility.
    """
    if limit <= 0:
        return 0, 0
    now = timezone.now()
    pending_cutoff = now - pending_older_than
    processing_cutoff = now - processing_older_than
    with transaction.atomic():
        jobs = list(
            TranscriptionJob.objects.select_for_update()
            .filter(
                Q(status=TranscriptionJobStatus.PENDING, updated_at__lte=pending_cutoff)
                | Q(
                    status=TranscriptionJobStatus.PROCESSING,
                    updated_at__lte=processing_cutoff,
                )
            )
            .order_by("updated_at", "id")[:limit]
        )
        stale_processing_ids = [
            job.id for job in jobs if job.status == TranscriptionJobStatus.PROCESSING
        ]
        if stale_processing_ids:
            TranscriptionJob.objects.filter(id__in=stale_processing_ids).update(
                status=TranscriptionJobStatus.PENDING,
                error_message="",
                updated_at=now,
            )
        job_ids = [job.id for job in jobs]

    published = sum(
        dispatch_transcription_job(job_id=job_id) for job_id in job_ids
    )
    return len(job_ids), published


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
    TranscriptionJob. Only a FAILED job may be retried here; old PENDING or
    stale PROCESSING jobs use the operator redispatch command instead."""
    job = TranscriptionJob.objects.select_related("testimony").get(id=job_id)
    if job.status != TranscriptionJobStatus.FAILED:
        raise AIJobNotRetryableError(f"Job is '{job.status}', not 'failed' -- nothing to retry.")

    job.status = TranscriptionJobStatus.PENDING
    job.error_message = ""
    job.save(update_fields=["status", "error_message", "updated_at"])
    transaction.on_commit(lambda: dispatch_transcription_job(job_id=job.id))
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
