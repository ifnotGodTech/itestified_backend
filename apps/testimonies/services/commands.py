from __future__ import annotations

import uuid
import logging
from datetime import datetime, timedelta

from django.db import transaction
from django.db.models import Count, F, OuterRef, Q, Subquery
from django.db.models.functions import Coalesce, Greatest
from django.utils import timezone
from django.utils.text import slugify

from apps.testimonies.exceptions import (
    AIJobNotRetryableError,
    CommentNotFoundError,
    CommentNotOwnedError,
    CommentReplyDepthError,
    CommentTestimonyNotFoundError,
    ParentCommentNotFoundError,
    ReactionAdminError,
    ReactionNotOfferedError,
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
    TestimonyComment,
    TestimonyModerationHistory,
    REACTION_SET_MAX,
    CategoryReaction,
    Reaction,
    ReactionChangeAction,
    ReactionChangeLog,
    ReactionIcon,
    TestimonyCategory,
    TestimonyReaction,
    TestimonyReactionCount,
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
from apps.testimonies.services.queries import offered_reactions
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
    notify_testimony_comment,
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


def _adjust_reaction_count(*, testimony_id: int, reaction_id: int, delta: int) -> None:
    # The row is created at zero first (a no-op if it's there) and then
    # moved with F(), so two people reacting at once can't both create it.
    TestimonyReactionCount.objects.bulk_create(
        [TestimonyReactionCount(testimony_id=testimony_id, reaction_id=reaction_id, count=0)],
        ignore_conflicts=True,
    )
    TestimonyReactionCount.objects.filter(testimony_id=testimony_id, reaction_id=reaction_id).update(
        count=Greatest(F("count") + delta, 0)
    )


@transaction.atomic
def set_testimony_reaction(*, testimony: Testimony, user, reaction_key: str) -> Testimony:
    """Sets the user's reaction on a testimony, switching it if they already
    reacted differently. One reaction per user per testimony (unique
    constraint on TestimonyReaction) -- tapping the same reaction again is a
    no-op, tapping a different one moves the count from the old reaction to
    the new one, tapping for the first time just adds to the new one.

    Phase 35 Slice 6: only a reaction the testimony's category offers is
    accepted (its own set, or the default set if it has none)."""
    reaction = next(
        (option for option in offered_reactions(testimony.category_id) if option.key == reaction_key),
        None,
    )
    if reaction is None:
        raise ReactionNotOfferedError("That response isn't available on this testimony.")

    existing = (
        TestimonyReaction.objects.select_for_update()
        .filter(user=user, testimony=testimony)
        .select_related("reaction")
        .first()
    )
    if existing is not None:
        if existing.reaction_id == reaction.key:
            return testimony
        _adjust_reaction_count(testimony_id=testimony.id, reaction_id=existing.reaction.id, delta=-1)
        existing.reaction = reaction
        existing.save(update_fields=["reaction"])
    else:
        TestimonyReaction.objects.create(user=user, testimony=testimony, reaction=reaction)
    _adjust_reaction_count(testimony_id=testimony.id, reaction_id=reaction.id, delta=1)
    return testimony


@transaction.atomic
def remove_testimony_reaction(*, testimony: Testimony, user) -> Testimony:
    existing = (
        TestimonyReaction.objects.select_for_update()
        .filter(user=user, testimony=testimony)
        .select_related("reaction")
        .first()
    )
    if existing is not None:
        _adjust_reaction_count(testimony_id=testimony.id, reaction_id=existing.reaction.id, delta=-1)
        existing.delete()
    return testimony


def _adjust_comment_count(*, testimony_id: int, delta: int) -> None:
    Testimony.objects.filter(id=testimony_id).update(comment_count=Greatest(F("comment_count") + delta, 0))


def recount_testimony_counters(*, testimony_ids=None) -> int:
    """Resets comment_count and the reaction counts from the rows themselves,
    for the given testimonies (all when None). The counters are normally
    kept by the commands above; this repairs them after rows went away
    without those commands -- a user deleted outright (Django admin, shell)
    takes their reactions and comments with them. Returns how many
    testimonies were changed."""
    testimonies = Testimony.objects.all()
    if testimony_ids is not None:
        testimonies = testimonies.filter(id__in=list(testimony_ids))

    actual_comments = Coalesce(
        Subquery(
            TestimonyComment.objects.filter(testimony_id=OuterRef("pk"))
            .values("testimony_id")
            .annotate(n=Count("id"))
            .values("n")
        ),
        0,
    )
    comment_drift = set(
        testimonies.annotate(actual=actual_comments)
        .exclude(comment_count=F("actual"))
        .values_list("id", flat=True)
    )
    if comment_drift:
        Testimony.objects.filter(id__in=comment_drift).update(comment_count=actual_comments)

    reaction_ids = dict(Reaction.objects.values_list("key", "id"))
    actual = {
        (row["testimony_id"], reaction_ids[row["reaction_id"]]): row["n"]
        for row in TestimonyReaction.objects.filter(testimony__in=testimonies)
        .values("testimony_id", "reaction_id")
        .annotate(n=Count("id"))
        .order_by()
    }
    stored = {
        (row.testimony_id, row.reaction_id): row
        for row in TestimonyReactionCount.objects.filter(testimony__in=testimonies)
    }
    reaction_drift: set[int] = set()
    to_create, to_update = [], []
    for key, row in stored.items():
        if row.count != actual.get(key, 0):
            row.count = actual.get(key, 0)
            to_update.append(row)
            reaction_drift.add(key[0])
    for (testimony_id, reaction_id), count in actual.items():
        if (testimony_id, reaction_id) not in stored:
            to_create.append(TestimonyReactionCount(testimony_id=testimony_id, reaction_id=reaction_id, count=count))
            reaction_drift.add(testimony_id)
    TestimonyReactionCount.objects.bulk_update(to_update, ["count"], batch_size=1000)
    TestimonyReactionCount.objects.bulk_create(to_create, batch_size=1000)
    return len(comment_drift | reaction_drift)


def _notify_testimony_comment_safely(*, testimony: Testimony, actor) -> None:
    # A push/notification hiccup must never fail a comment that's already saved.
    try:
        notify_testimony_comment(recipient=testimony.author, actor=actor, testimony_title=testimony.title)
    except Exception:  # noqa: BLE001 - notification delivery is best-effort.
        logger.exception("testimonies.create_testimony_comment: notification failed for testimony %s", testimony.id)


@transaction.atomic
def create_testimony_comment(
    *, testimony_id: int, author, body: str, parent_comment_id: int | None = None
) -> TestimonyComment:
    """Adds a comment (or a one-level-deep reply) to an approved testimony,
    bumps its comment_count in the same transaction, and notifies the
    testimony's author once the write has committed."""
    testimony = (
        Testimony.objects.select_related("author")
        .filter(id=testimony_id, status=TestimonyStatus.APPROVED, category__is_active=True)
        .first()
    )
    if testimony is None:
        raise CommentTestimonyNotFoundError("Testimony not found.")

    parent_comment = None
    if parent_comment_id is not None:
        parent_comment = TestimonyComment.objects.filter(id=parent_comment_id, testimony_id=testimony.id).first()
        if parent_comment is None:
            raise ParentCommentNotFoundError("Parent comment not found.")
        if parent_comment.parent_comment_id is not None:
            raise CommentReplyDepthError("Only one reply level is allowed.")

    comment = TestimonyComment.objects.create(
        testimony=testimony, author=author, parent_comment=parent_comment, body=body
    )
    _adjust_comment_count(testimony_id=testimony.id, delta=1)

    if testimony.author_id != author.id:
        transaction.on_commit(lambda: _notify_testimony_comment_safely(testimony=testimony, actor=author))
    return comment


@transaction.atomic
def delete_testimony_comment(*, comment_id: int, actor) -> None:
    """Deletes the actor's own comment together with its replies (cascade)
    and lowers comment_count by all of them. The comment row is locked so
    two concurrent deletes can't both decrement the count."""
    comment = TestimonyComment.objects.select_for_update().filter(id=comment_id).first()
    if comment is None:
        raise CommentNotFoundError("Comment not found.")
    if comment.author_id != actor.id:
        raise CommentNotOwnedError("You can only delete your own comment.")

    deleted_count = TestimonyComment.objects.filter(Q(id=comment.id) | Q(parent_comment_id=comment.id)).count()
    comment.delete()
    _adjust_comment_count(testimony_id=comment.testimony_id, delta=-deleted_count)


# --- Phase 35 Slice 6: the admin's reaction catalogue and category sets ---


def _log_reaction_change(*, actor, action: str, summary: str, reaction=None, category=None) -> None:
    ReactionChangeLog.objects.create(
        actor=actor, action=action, reaction=reaction, category=category, summary=summary[:200]
    )


def _clean_reaction_label(label: str, *, exclude_id: int | None = None) -> str:
    label = " ".join((label or "").split())
    if not label:
        raise ReactionAdminError("Give the reaction a label.")
    if len(label) > 24:
        raise ReactionAdminError("Keep the label to 24 characters or fewer.")
    clash = Reaction.objects.filter(label__iexact=label)
    if exclude_id is not None:
        clash = clash.exclude(id=exclude_id)
    if clash.exists():
        raise ReactionAdminError(f"There's already a reaction called “{label}”.")
    return label


def _clean_reaction_icon(icon: str) -> str:
    if icon not in ReactionIcon.values:
        raise ReactionAdminError("Choose one of the icons.")
    return icon


def _new_reaction_key(label: str) -> str:
    base = (slugify(label).replace("-", "_") or "reaction")[:36]
    key, suffix = base, 2
    while Reaction.objects.filter(key=key).exists():
        key, suffix = f"{base}_{suffix}", suffix + 1
    return key


@transaction.atomic
def create_reaction(*, actor, label: str, icon: str) -> Reaction:
    """Adds a reaction to the catalogue. It isn't offered anywhere until it
    is put in a category's set (or the default set)."""
    label = _clean_reaction_label(label)
    reaction = Reaction.objects.create(key=_new_reaction_key(label), label=label, icon=_clean_reaction_icon(icon))
    _log_reaction_change(actor=actor, action=ReactionChangeAction.CREATED, reaction=reaction, summary=f"Created “{label}”")
    return reaction


@transaction.atomic
def update_reaction(*, actor, reaction_id: int, label: str | None = None, icon: str | None = None) -> Reaction:
    """Renames a reaction or changes its icon. Its key -- what stored
    responses point at -- never changes."""
    reaction = Reaction.objects.select_for_update().filter(id=reaction_id).first()
    if reaction is None:
        raise ReactionAdminError("That reaction no longer exists.")
    changes = []
    if label is not None:
        label = _clean_reaction_label(label, exclude_id=reaction.id)
        if label != reaction.label:
            changes.append(f"renamed “{reaction.label}” to “{label}”")
            reaction.label = label
    if icon is not None and _clean_reaction_icon(icon) != reaction.icon:
        changes.append(f"icon of “{reaction.label}” changed")
        reaction.icon = icon
    if changes:
        reaction.save(update_fields=["label", "icon", "updated_at"])
        _log_reaction_change(
            actor=actor, action=ReactionChangeAction.EDITED, reaction=reaction, summary="; ".join(changes).capitalize()
        )
    return reaction


@transaction.atomic
def retire_reaction(*, actor, reaction_id: int) -> Reaction:
    """Stops offering a reaction anywhere: it comes off every category's set
    and the default set. Its past responses and counts stay. The default
    set can't be left empty, since every category without a set uses it."""
    reaction = Reaction.objects.select_for_update().filter(id=reaction_id).first()
    if reaction is None:
        raise ReactionAdminError("That reaction no longer exists.")
    if not reaction.is_active:
        return reaction
    if reaction.default_position is not None and not Reaction.objects.filter(
        is_active=True, default_position__isnull=False
    ).exclude(id=reaction.id).exists():
        raise ReactionAdminError(
            f"“{reaction.label}” is the only reaction in the default set. Add another to the default set first."
        )

    category_names = list(
        CategoryReaction.objects.filter(reaction=reaction).values_list("category__name", flat=True)
    )
    for category_id in CategoryReaction.objects.filter(reaction=reaction).values_list("category_id", flat=True):
        CategoryReaction.objects.filter(category_id=category_id, reaction=reaction).delete()
        _renumber_category_set(category_id)
    if reaction.default_position is not None:
        reaction.default_position = None
        _renumber_default_set(exclude_id=reaction.id)
    reaction.is_active = False
    reaction.save(update_fields=["is_active", "default_position", "updated_at"])

    taken_off = ", ".join(category_names)
    _log_reaction_change(
        actor=actor,
        action=ReactionChangeAction.RETIRED,
        reaction=reaction,
        summary=f"Retired “{reaction.label}”" + (f" (taken off {taken_off})" if taken_off else ""),
    )
    return reaction


@transaction.atomic
def restore_reaction(*, actor, reaction_id: int) -> Reaction:
    """Brings a retired reaction back into the catalogue. It isn't put back
    in any set; the admin chooses where it appears."""
    reaction = Reaction.objects.select_for_update().filter(id=reaction_id).first()
    if reaction is None:
        raise ReactionAdminError("That reaction no longer exists.")
    if not reaction.is_active:
        reaction.is_active = True
        reaction.save(update_fields=["is_active", "updated_at"])
        _log_reaction_change(
            actor=actor, action=ReactionChangeAction.RESTORED, reaction=reaction, summary=f"Brought back “{reaction.label}”"
        )
    return reaction


def _renumber_category_set(category_id: int) -> None:
    rows = list(CategoryReaction.objects.filter(category_id=category_id).order_by("position"))
    CategoryReaction.objects.filter(category_id=category_id).delete()
    CategoryReaction.objects.bulk_create(
        [CategoryReaction(category_id=category_id, reaction_id=row.reaction_id, position=i) for i, row in enumerate(rows, start=1)]
    )


def _renumber_default_set(*, exclude_id: int | None = None) -> None:
    members = list(
        Reaction.objects.filter(default_position__isnull=False).exclude(id=exclude_id).order_by("default_position")
    )
    Reaction.objects.filter(default_position__isnull=False).update(default_position=None)
    for position, member in enumerate(members, start=1):
        Reaction.objects.filter(id=member.id).update(default_position=position)


def _clean_reaction_set(reaction_ids) -> list[Reaction]:
    reaction_ids = list(reaction_ids)
    if len(reaction_ids) != len(set(reaction_ids)):
        raise ReactionAdminError("Each reaction can only appear once in a set.")
    if len(reaction_ids) > REACTION_SET_MAX:
        raise ReactionAdminError(f"A set can have at most {REACTION_SET_MAX} reactions.")
    found = {reaction.id: reaction for reaction in Reaction.objects.filter(id__in=reaction_ids)}
    if len(found) != len(reaction_ids):
        raise ReactionAdminError("One of those reactions no longer exists.")
    if any(not found[reaction_id].is_active for reaction_id in reaction_ids):
        raise ReactionAdminError("A retired reaction can't be added to a set. Bring it back first.")
    return [found[reaction_id] for reaction_id in reaction_ids]


@transaction.atomic
def set_category_reactions(*, actor, category_id: int, reaction_ids) -> None:
    """Replaces a category's ordered set. An empty list puts the category
    back on the default set. Testimonies keep the responses they already
    have; only what's offered changes."""
    category = TestimonyCategory.objects.select_for_update().filter(id=category_id).first()
    if category is None:
        raise ReactionAdminError("That category no longer exists.")
    reactions = _clean_reaction_set(reaction_ids)
    CategoryReaction.objects.filter(category=category).delete()
    CategoryReaction.objects.bulk_create(
        [CategoryReaction(category=category, reaction=reaction, position=i) for i, reaction in enumerate(reactions, start=1)]
    )
    summary = (
        f"{category.name}: " + ", ".join(reaction.label for reaction in reactions)
        if reactions
        else f"{category.name}: back to the default set"
    )
    _log_reaction_change(actor=actor, action=ReactionChangeAction.SET_CHANGED, category=category, summary=summary)


@transaction.atomic
def set_default_reactions(*, actor, reaction_ids) -> None:
    """Replaces the default set, used by every category without its own.
    It can't be empty."""
    reactions = _clean_reaction_set(reaction_ids)
    if not reactions:
        raise ReactionAdminError("The default set needs at least one reaction.")
    list(Reaction.objects.select_for_update().filter(default_position__isnull=False))
    Reaction.objects.filter(default_position__isnull=False).update(default_position=None)
    for position, reaction in enumerate(reactions, start=1):
        Reaction.objects.filter(id=reaction.id).update(default_position=position)
    _log_reaction_change(
        actor=actor,
        action=ReactionChangeAction.SET_CHANGED,
        summary="Default set: " + ", ".join(reaction.label for reaction in reactions),
    )
