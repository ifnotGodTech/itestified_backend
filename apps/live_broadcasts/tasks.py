import logging

from celery import shared_task
from django.conf import settings

from apps.common.services.media_uploads import CloudinaryUploadError

from .models import LiveBroadcast, LiveBroadcastRecordingStatus
from .services import commands

logger = logging.getLogger(__name__)

# 2026-09-10 correction: this used to poll agora.query_cloud_recording()
# with backoff after stop_cloud_recording(), on the assumption stop
# returns before the file finishes uploading. A real broadcast's first
# live test proved that assumption wrong -- every query attempt 404'd
# from the very first one, because Agora's own docs confirm query (and a
# second stop) return 404 once a recording session has already ended,
# which stop_cloud_recording succeeding already means it has. The file
# name now comes from stop's own response (captured in end_broadcast(),
# see commands.py), passed straight in here -- no polling needed for
# that part anymore. What's still genuinely retryable is the Cloudinary
# relay step below (a real, separate network call).
MAX_RELAY_ATTEMPTS = 10
RELAY_RETRY_COUNTDOWN_SECONDS = 30


@shared_task(bind=True, max_retries=MAX_RELAY_ATTEMPTS)
def archive_stopped_recording(self, broadcast_id: int, file_name: str) -> None:
    try:
        broadcast = LiveBroadcast.objects.get(id=broadcast_id)
    except LiveBroadcast.DoesNotExist:
        logger.warning("archive_stopped_recording: broadcast %s no longer exists", broadcast_id)
        return

    if broadcast.recording_status != LiveBroadcastRecordingStatus.STOPPING:
        logger.info(
            "archive_stopped_recording: broadcast %s not in STOPPING (status=%s), skipping",
            broadcast_id,
            broadcast.recording_status,
        )
        return

    if not file_name:
        # Agora's stop response carried no file -- there's genuinely
        # nothing to archive (e.g. a session that never had a real
        # publisher), not a transient failure worth retrying against an
        # endpoint (query) already confirmed unusable post-stop.
        logger.error("archive_stopped_recording: stop returned no file for broadcast %s", broadcast_id)
        commands.mark_recording_failed(broadcast=broadcast)
        return

    base_url = settings.AGORA_RECORDING_PUBLIC_URL_BASE.rstrip("/")
    if not base_url:
        logger.error(
            "archive_stopped_recording: AGORA_RECORDING_PUBLIC_URL_BASE not configured, cannot archive broadcast %s",
            broadcast_id,
        )
        commands.mark_recording_failed(broadcast=broadcast)
        return

    s3_relay_url = f"{base_url}/{file_name.lstrip('/')}"
    logger.info("archive_stopped_recording: attempting relay for broadcast %s from %s", broadcast_id, s3_relay_url)

    # 2026-09-08 refinement: the S3 file above is a relay, not the
    # testimony's permanent home (see commands.relay_recording_to_cloudinary's
    # own docstring for why) -- re-host it in Cloudinary before archiving.
    # This is the one genuinely transient step left in this pipeline.
    try:
        video_url = commands.relay_recording_to_cloudinary(broadcast=broadcast, source_url=s3_relay_url)
    except CloudinaryUploadError as exc:
        logger.warning(
            "archive_stopped_recording: Cloudinary relay failed for broadcast %s: %s", broadcast_id, exc
        )
        if self.request.retries >= MAX_RELAY_ATTEMPTS - 1:
            logger.error(
                "archive_stopped_recording: Cloudinary relay kept failing after %s attempts for broadcast %s -- giving up",
                MAX_RELAY_ATTEMPTS,
                broadcast_id,
            )
            commands.mark_recording_failed(broadcast=broadcast)
            return
        raise self.retry(countdown=RELAY_RETRY_COUNTDOWN_SECONDS, exc=exc)

    commands.archive_broadcast_recording(broadcast=broadcast, video_url=video_url)
