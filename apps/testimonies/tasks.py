from __future__ import annotations

import logging

from celery import shared_task
from django.utils import timezone

from apps.common.services.ai_text import AITextServiceError, transcribe_video, translate_text
from apps.testimonies.models import (
    TranscriptionJob,
    TranscriptionJobStatus,
    TranslationJob,
    TranslationJobStatus,
    TestimonyType,
)

logger = logging.getLogger(__name__)


@shared_task
def run_transcription_job(job_id: int) -> None:
    claimed = TranscriptionJob.objects.filter(
        id=job_id,
        status=TranscriptionJobStatus.PENDING,
    ).update(
        status=TranscriptionJobStatus.PROCESSING,
        error_message="",
        updated_at=timezone.now(),
    )
    if not claimed:
        status_value = (
            TranscriptionJob.objects.filter(id=job_id)
            .values_list("status", flat=True)
            .first()
        )
        if status_value is None:
            logger.warning("run_transcription_job: job %s no longer exists", job_id)
        else:
            logger.info(
                "run_transcription_job: job %s not claimed because status is %s",
                job_id,
                status_value,
            )
        return
    job = TranscriptionJob.objects.select_related("testimony").get(id=job_id)

    try:
        source_url = (
            job.testimony.audio_url
            if job.testimony.testimony_type == TestimonyType.AUDIO
            else job.testimony.video_url
        )
        transcript = transcribe_video(video_url=source_url)
    except AITextServiceError as exc:
        job.status = TranscriptionJobStatus.FAILED
        job.error_message = str(exc)
        job.retry_count += 1
        job.save(update_fields=["status", "error_message", "retry_count", "updated_at"])
        logger.warning("run_transcription_job: job %s failed: %s", job_id, exc)
        return

    job.status = TranscriptionJobStatus.DONE
    job.transcript = transcript
    job.error_message = ""
    job.save(update_fields=["status", "transcript", "error_message", "updated_at"])


@shared_task
def run_translation_job(job_id: int) -> None:
    try:
        job = TranslationJob.objects.get(id=job_id)
    except TranslationJob.DoesNotExist:
        logger.warning("run_translation_job: job %s no longer exists", job_id)
        return

    # request_testimony_translation already checks the transcript is DONE
    # before creating this row, but re-checking here rather than trusting
    # the caller keeps this task correct even if something else ever
    # creates a TranslationJob directly.
    transcription_job = getattr(job.testimony, "transcription_job", None)
    if transcription_job is None or transcription_job.status != TranscriptionJobStatus.DONE:
        job.status = TranslationJobStatus.FAILED
        job.error_message = "No completed transcript available to translate yet."
        job.retry_count += 1
        job.save(update_fields=["status", "error_message", "retry_count", "updated_at"])
        return

    job.status = TranslationJobStatus.PROCESSING
    job.save(update_fields=["status", "updated_at"])

    try:
        translated = translate_text(
            text=transcription_job.transcript,
            target_language=job.language,
        )
    except AITextServiceError as exc:
        job.status = TranslationJobStatus.FAILED
        job.error_message = str(exc)
        job.retry_count += 1
        job.save(update_fields=["status", "error_message", "retry_count", "updated_at"])
        logger.warning("run_translation_job: job %s failed: %s", job_id, exc)
        return

    job.status = TranslationJobStatus.DONE
    job.translated_text = translated
    job.error_message = ""
    job.save(update_fields=["status", "translated_text", "error_message", "updated_at"])
