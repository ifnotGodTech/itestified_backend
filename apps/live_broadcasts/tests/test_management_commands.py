from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.creators.models import CreatorProfile
from apps.live_broadcasts.models import LiveBroadcast, LiveBroadcastRecordingStatus, LiveBroadcastStatus
from apps.testimonies.models import TestimonyCategory
from apps.users.tests.factories import UserFactory


class ReconcileStaleLiveBroadcastsCommandTests(TestCase):
    def test_reports_how_many_broadcasts_it_ended(self):
        user = UserFactory(email="ministry@example.com")
        CreatorProfile.objects.create(user=user, display_name="Grace Chapel", is_verified=True)
        category = TestimonyCategory.objects.create(name="Faith", slug="faith")
        broadcast = LiveBroadcast.objects.create(creator=user, title="Sunday Service", category=category)
        broadcast.status = LiveBroadcastStatus.LIVE
        broadcast.started_at = timezone.now() - timezone.timedelta(hours=2)
        broadcast.max_duration_minutes_applied = 30
        broadcast.recording_status = LiveBroadcastRecordingStatus.FAILED
        broadcast.save()

        out = StringIO()
        call_command("reconcile_stale_live_broadcasts", stdout=out)

        self.assertIn("Ended 1 stale live broadcast", out.getvalue())
        broadcast.refresh_from_db()
        self.assertEqual(broadcast.status, LiveBroadcastStatus.ENDED)
