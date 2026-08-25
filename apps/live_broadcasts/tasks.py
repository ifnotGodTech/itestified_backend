import logging

from celery import shared_task
from django.conf import settings

from .models import LiveBroadcast, LiveBroadcastRecordingStatus
from .services import agora, commands

logger = logging.getLogger(__name__)

# Agora's Cloud Recording `stop` returns before the file finishes
# uploading to storage (see Phase 27 Slice 5's own note), so this polls
# `query` with backoff rather than assuming the file is ready immediately.
# 10 attempts x up to 30s apart comfortably covers a real upload without
# polling forever if something's actually stuck.
MAX_POLL_ATTEMPTS = 10
POLL_COUNTDOWN_SECONDS = 30


def _extract_file_name(server_response: dict) -> str:
    """Agora's exact mix-mode fileList shape couldn't be directly verified
    against live docs while building this (see services/agora.py's own
    note) -- handle both a bare filename string and a fileList array of
    objects defensively rather than assuming one shape."""
    file_list = server_response.get("fileList")
    if isinstance(file_list, str) and file_list.strip():
        return file_list.strip()
    if isinstance(file_list, list) and file_list:
        first = file_list[0]
        if isinstance(first, dict):
            return str(first.get("fileName") or "").strip()
        return str(first).strip()
    return ""


@shared_task(bind=True, max_retries=MAX_POLL_ATTEMPTS)
def poll_and_archive_recording(self, broadcast_id: int) -> None:
    try:
        broadcast = LiveBroadcast.objects.get(id=broadcast_id)
    except LiveBroadcast.DoesNotExist:
        logger.warning("poll_and_archive_recording: broadcast %s no longer exists", broadcast_id)
        return

    if broadcast.recording_status != LiveBroadcastRecordingStatus.STOPPING:
        logger.info(
            "poll_and_archive_recording: broadcast %s not in STOPPING (status=%s), skipping",
            broadcast_id,
            broadcast.recording_status,
        )
        return

    try:
        server_response = agora.query_cloud_recording(
            resource_id=broadcast.agora_recording_resource_id, sid=broadcast.agora_recording_sid
        )
    except Exception as exc:  # noqa: BLE001 - retry on any transient Agora/network failure.
        logger.warning("poll_and_archive_recording: query failed for broadcast %s: %s", broadcast_id, exc)
        if self.request.retries >= MAX_POLL_ATTEMPTS - 1:
            logger.error(
                "poll_and_archive_recording: query kept failing after %s attempts for broadcast %s -- giving up",
                MAX_POLL_ATTEMPTS,
                broadcast_id,
            )
            commands.mark_recording_failed(broadcast=broadcast)
            return
        raise self.retry(countdown=POLL_COUNTDOWN_SECONDS, exc=exc)

    file_name = _extract_file_name(server_response)
    if not file_name:
        if self.request.retries >= MAX_POLL_ATTEMPTS - 1:
            logger.error(
                "poll_and_archive_recording: no file after %s attempts for broadcast %s -- giving up",
                MAX_POLL_ATTEMPTS,
                broadcast_id,
            )
            commands.mark_recording_failed(broadcast=broadcast)
            return
        raise self.retry(countdown=POLL_COUNTDOWN_SECONDS)

    base_url = settings.AGORA_RECORDING_PUBLIC_URL_BASE.rstrip("/")
    if not base_url:
        logger.error(
            "poll_and_archive_recording: AGORA_RECORDING_PUBLIC_URL_BASE not configured, cannot archive broadcast %s",
            broadcast_id,
        )
        commands.mark_recording_failed(broadcast=broadcast)
        return

    video_url = f"{base_url}/{file_name.lstrip('/')}"
    commands.archive_broadcast_recording(broadcast=broadcast, video_url=video_url)
