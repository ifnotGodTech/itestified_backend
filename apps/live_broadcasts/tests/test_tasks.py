from unittest.mock import patch

from django.test import TestCase, override_settings

from apps.creators.models import CreatorProfile
from apps.live_broadcasts.models import LiveBroadcast, LiveBroadcastRecordingStatus
from apps.live_broadcasts.tasks import poll_and_archive_recording
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
class PollAndArchiveRecordingTests(TestCase):
    @patch("apps.live_broadcasts.tasks.commands.archive_broadcast_recording")
    @patch("apps.live_broadcasts.tasks.agora.query_cloud_recording")
    def test_archives_once_the_file_is_ready(self, query_mock, archive_mock):
        broadcast = _stopping_broadcast()
        query_mock.return_value = {"fileList": "recordings/sunday.mp4"}

        poll_and_archive_recording.apply(args=[broadcast.id])

        archive_mock.assert_called_once_with(
            broadcast=broadcast, video_url="https://bucket.example.com/recordings/sunday.mp4"
        )

    @patch("apps.live_broadcasts.tasks.commands.archive_broadcast_recording")
    @patch("apps.live_broadcasts.tasks.agora.query_cloud_recording")
    def test_handles_a_fileList_array_of_objects(self, query_mock, archive_mock):
        broadcast = _stopping_broadcast()
        query_mock.return_value = {"fileList": [{"fileName": "recordings/sunday.mp4", "trackType": "audio_and_video"}]}

        poll_and_archive_recording.apply(args=[broadcast.id])

        archive_mock.assert_called_once_with(
            broadcast=broadcast, video_url="https://bucket.example.com/recordings/sunday.mp4"
        )

    @patch("apps.live_broadcasts.tasks.commands.mark_recording_failed")
    @patch("apps.live_broadcasts.tasks.agora.query_cloud_recording")
    def test_gives_up_after_max_attempts_with_no_file(self, query_mock, mark_failed_mock):
        broadcast = _stopping_broadcast()
        query_mock.return_value = {}

        result = poll_and_archive_recording.apply(args=[broadcast.id], retries=9)

        self.assertIsNone(result.result)
        mark_failed_mock.assert_called_once()

    def test_skips_a_broadcast_no_longer_stopping(self):
        broadcast = _stopping_broadcast()
        broadcast.recording_status = LiveBroadcastRecordingStatus.ARCHIVED
        broadcast.save()

        # Should return cleanly without attempting any Agora call.
        with patch("apps.live_broadcasts.tasks.agora.query_cloud_recording") as query_mock:
            poll_and_archive_recording.apply(args=[broadcast.id])
            query_mock.assert_not_called()
