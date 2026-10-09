from unittest.mock import patch

from django.test import TestCase, override_settings

from apps.common.services.media_uploads import CloudinaryUploadError
from apps.creators.models import CreatorProfile
from apps.live_broadcasts.models import LiveBroadcast, LiveBroadcastRecordingStatus
from apps.live_broadcasts.tasks import archive_stopped_recording
from apps.testimonies.models import TestimonyCategory
from apps.users.tests.factories import UserFactory


def _stopping_broadcast():
    user = UserFactory(email="ministry@example.com")
    CreatorProfile.objects.create(user=user, display_name="Grace Chapel", is_verified=True)
    category = TestimonyCategory.objects.create(name="Faith", slug="faith")
    broadcast = LiveBroadcast.objects.create(creator=user, title="Sunday Service", category=category)
    broadcast.recording_status = LiveBroadcastRecordingStatus.STOPPING
    broadcast.agora_recording_resource_id = "resource-1"
    broadcast.agora_recording_sid = "sid-1"
    broadcast.save()
    return broadcast


@override_settings(AGORA_RECORDING_PUBLIC_URL_BASE="https://bucket.example.com")
class ArchiveStoppedRecordingTests(TestCase):
    """2026-09-10 correction: file_name now comes straight from stop's own
    response (captured synchronously in end_broadcast()), not from a
    later query_cloud_recording poll -- a real broadcast's first live
    test proved that poll never actually worked (every query attempt
    404'd, since Agora considers the session over once stop succeeds).
    This task's only remaining job is the Cloudinary relay + archive."""

    @patch("apps.live_broadcasts.tasks.commands.archive_broadcast_recording")
    @patch("apps.live_broadcasts.tasks.commands.relay_recording_to_cloudinary")
    def test_relays_to_cloudinary_then_archives_with_the_cloudinary_url(self, relay_mock, archive_mock):
        broadcast = _stopping_broadcast()
        relay_mock.return_value = "https://res.cloudinary.com/itestified/video/upload/live-broadcast-1.mp4"

        archive_stopped_recording.apply(args=[broadcast.id, "recordings/sunday.mp4"])

        relay_mock.assert_called_once_with(
            broadcast=broadcast, source_url="https://bucket.example.com/recordings/sunday.mp4"
        )
        archive_mock.assert_called_once_with(
            broadcast=broadcast,
            video_url="https://res.cloudinary.com/itestified/video/upload/live-broadcast-1.mp4",
        )

    @patch("apps.live_broadcasts.tasks.commands.mark_recording_failed")
    def test_no_file_name_marks_failed_immediately_no_retry(self, mark_failed_mock):
        broadcast = _stopping_broadcast()

        result = archive_stopped_recording.apply(args=[broadcast.id, ""])

        self.assertIsNone(result.result)
        mark_failed_mock.assert_called_once()

    @patch("apps.live_broadcasts.tasks.commands.mark_recording_failed")
    @override_settings(AGORA_RECORDING_PUBLIC_URL_BASE="")
    def test_missing_public_url_base_marks_failed(self, mark_failed_mock):
        broadcast = _stopping_broadcast()

        archive_stopped_recording.apply(args=[broadcast.id, "recordings/sunday.mp4"])

        mark_failed_mock.assert_called_once()

    def test_skips_a_broadcast_no_longer_stopping(self):
        broadcast = _stopping_broadcast()
        broadcast.recording_status = LiveBroadcastRecordingStatus.ARCHIVED
        broadcast.save()

        with patch("apps.live_broadcasts.tasks.commands.relay_recording_to_cloudinary") as relay_mock:
            archive_stopped_recording.apply(args=[broadcast.id, "recordings/sunday.mp4"])
            relay_mock.assert_not_called()

    @patch("apps.live_broadcasts.tasks.commands.archive_broadcast_recording")
    @patch("apps.live_broadcasts.tasks.commands.mark_recording_failed")
    @patch("apps.live_broadcasts.tasks.commands.relay_recording_to_cloudinary")
    def test_gives_up_after_max_attempts_when_cloudinary_relay_keeps_failing(
        self, relay_mock, mark_failed_mock, archive_mock
    ):
        broadcast = _stopping_broadcast()
        relay_mock.side_effect = CloudinaryUploadError("Recording relay upload failed: timeout")

        result = archive_stopped_recording.apply(args=[broadcast.id, "recordings/sunday.mp4"], retries=9)

        self.assertIsNone(result.result)
        mark_failed_mock.assert_called_once()
        archive_mock.assert_not_called()
