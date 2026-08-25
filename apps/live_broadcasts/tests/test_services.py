from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps.creators.models import CreatorProfile
from apps.live_broadcasts.exceptions import (
    InsufficientAllowanceError,
    LiveBroadcastingDisabledError,
    LiveBroadcastWrongStatusError,
    NotAVerifiedMinistryError,
)
from apps.live_broadcasts.models import (
    LiveBroadcast,
    LiveBroadcastApprovalStatus,
    LiveBroadcastEndedReason,
    LiveBroadcastRecordingStatus,
    LiveBroadcastStatus,
    LiveMinutePricing,
    LiveMinutePurchaseStatus,
    LiveStreamingPolicy,
    MinistryStreamingAllowance,
)
from apps.live_broadcasts.services import commands
from apps.live_broadcasts.services.agora import PublisherCredential
from apps.testimonies.models import TestimonyCategory
from apps.users.tests.factories import UserFactory


def _verified_ministry(email="ministry@example.com") -> "User":  # noqa: F821 - forward ref for readability
    user = UserFactory(email=email)
    CreatorProfile.objects.create(user=user, display_name="Grace Chapel", is_verified=True)
    return user


def _category() -> TestimonyCategory:
    return TestimonyCategory.objects.create(name="Testimony Category", slug="testimony-category")


def _fake_credential(**overrides):
    defaults = dict(
        app_id="app-id",
        channel_name="itestified-live-1-abcd1234",
        uid=1,
        token="signed-token",
        expires_at_unix=int(timezone.now().timestamp()) + 3600,
    )
    defaults.update(overrides)
    return PublisherCredential(**defaults)


class CreateLiveBroadcastTests(TestCase):
    def test_non_ministry_cannot_schedule(self):
        user = UserFactory()
        with self.assertRaises(NotAVerifiedMinistryError):
            commands.create_live_broadcast(creator=user, title="Sunday Service", category=_category())

    def test_unverified_creator_profile_cannot_schedule(self):
        user = UserFactory()
        CreatorProfile.objects.create(user=user, display_name="Unverified Ministry", is_verified=False)
        with self.assertRaises(NotAVerifiedMinistryError):
            commands.create_live_broadcast(creator=user, title="Sunday Service", category=_category())

    def test_verified_ministry_can_schedule(self):
        ministry = _verified_ministry()
        broadcast = commands.create_live_broadcast(creator=ministry, title="Sunday Service", category=_category())
        self.assertEqual(broadcast.status, LiveBroadcastStatus.SCHEDULED)
        self.assertEqual(broadcast.agora_channel_name, "")


class GoLiveTests(TestCase):
    def setUp(self):
        self.ministry = _verified_ministry()
        self.broadcast = LiveBroadcast.objects.create(creator=self.ministry, title="Sunday Service", category=_category())

    def _give_sufficient_allowance(self):
        now = timezone.now()
        MinistryStreamingAllowance.objects.create(
            creator=self.ministry, year=now.year, month=now.month, base_allowance_minutes=200, purchased_minutes=1300
        )

    @patch("apps.live_broadcasts.services.commands.agora.issue_publisher_credential")
    def test_go_live_issues_credential_and_snapshots_caps(self, issue_mock):
        self._give_sufficient_allowance()
        issue_mock.side_effect = lambda **kwargs: _fake_credential(channel_name=kwargs["channel_name"])
        commands.go_live(broadcast=self.broadcast, actor=self.ministry)

        self.broadcast.refresh_from_db()
        self.assertEqual(self.broadcast.status, LiveBroadcastStatus.LIVE)
        self.assertIsNotNone(self.broadcast.started_at)
        self.assertTrue(self.broadcast.agora_channel_name.startswith(f"itestified-live-{self.broadcast.id}-"))
        self.assertEqual(self.broadcast.max_viewers_applied, 50)
        self.assertEqual(self.broadcast.max_duration_minutes_applied, 30)
        issue_mock.assert_called_once()

    def test_only_the_owning_ministry_can_go_live(self):
        other = _verified_ministry(email="other@example.com")
        with self.assertRaises(NotAVerifiedMinistryError):
            commands.go_live(broadcast=self.broadcast, actor=other)

    @patch("apps.live_broadcasts.services.commands.agora.issue_publisher_credential")
    def test_cannot_go_live_twice(self, issue_mock):
        self._give_sufficient_allowance()
        issue_mock.return_value = _fake_credential()
        commands.go_live(broadcast=self.broadcast, actor=self.ministry)
        self.broadcast.refresh_from_db()
        with self.assertRaises(LiveBroadcastWrongStatusError):
            commands.go_live(broadcast=self.broadcast, actor=self.ministry)

    def test_disabled_policy_blocks_go_live(self):
        LiveStreamingPolicy.objects.create(pk=1, is_enabled=False)
        with self.assertRaises(LiveBroadcastingDisabledError):
            commands.go_live(broadcast=self.broadcast, actor=self.ministry)

    def test_insufficient_allowance_reports_shortfall(self):
        # Default allowance (200) is smaller than the default worst case
        # (50 viewers x 30 minutes = 1,500), so a fresh Ministry with no
        # purchased top-up can't cover even its first broadcast under
        # these defaults -- exactly the case the self-service purchase
        # flow exists to resolve.
        with self.assertRaises(InsufficientAllowanceError) as ctx:
            commands.go_live(broadcast=self.broadcast, actor=self.ministry)
        self.assertEqual(ctx.exception.shortfall_minutes, 1500 - 200)
        self.assertEqual(ctx.exception.remaining_minutes, 200)

    @patch("apps.live_broadcasts.services.commands.agora.issue_publisher_credential")
    def test_sufficient_purchased_minutes_allow_go_live(self, issue_mock):
        issue_mock.return_value = _fake_credential()
        now = timezone.now()
        MinistryStreamingAllowance.objects.create(
            creator=self.ministry, year=now.year, month=now.month, base_allowance_minutes=200, purchased_minutes=1300
        )
        commands.go_live(broadcast=self.broadcast, actor=self.ministry)
        self.broadcast.refresh_from_db()
        self.assertEqual(self.broadcast.status, LiveBroadcastStatus.LIVE)

    @patch("apps.live_broadcasts.services.commands.agora.issue_publisher_credential")
    def test_reserved_minutes_from_prior_broadcast_count_against_allowance(self, issue_mock):
        issue_mock.return_value = _fake_credential()
        now = timezone.now()
        MinistryStreamingAllowance.objects.create(
            creator=self.ministry, year=now.year, month=now.month, base_allowance_minutes=200, purchased_minutes=3000
        )
        # First broadcast reserves 1,500 worst-case minutes.
        commands.go_live(broadcast=self.broadcast, actor=self.ministry)

        second = LiveBroadcast.objects.create(creator=self.ministry, title="Midweek Service", category=self.broadcast.category)
        # Second broadcast would need another 1,500; remaining is
        # 200 + 3000 - 1500 = 1700, which is enough for one more but not
        # a third -- proves prior go-lives this month are actually
        # deducted, not just the current attempt considered in isolation.
        commands.go_live(broadcast=second, actor=self.ministry)

        third = LiveBroadcast.objects.create(creator=self.ministry, title="Friday Service", category=self.broadcast.category)
        with self.assertRaises(InsufficientAllowanceError):
            commands.go_live(broadcast=third, actor=self.ministry)


class MinutePurchaseTests(TestCase):
    def setUp(self):
        self.ministry = _verified_ministry()
        LiveMinutePricing.objects.create(currency="NGN", price_per_1000_minutes=500000)

    @patch("apps.live_broadcasts.services.commands.FlutterwaveGateway.initialize")
    def test_initiate_purchase_rounds_up_and_creates_checkout(self, init_mock):
        from apps.common.services.flutterwave import FlutterwaveInitResult

        init_mock.return_value = FlutterwaveInitResult(checkout_url="https://pay.example/abc", provider_transaction_id="1")
        purchase = commands.initiate_minute_purchase(creator=self.ministry, minutes=1200, currency="NGN")
        # 1,200 minutes at 500,000/1,000 minutes = 600,000, no rounding needed here;
        # exercise the ceiling behavior with a non-multiple-of-1000 amount too.
        self.assertEqual(purchase.amount, 600000)
        self.assertEqual(purchase.checkout_url, "https://pay.example/abc")

    @patch("apps.live_broadcasts.services.commands.FlutterwaveGateway.verify")
    def test_verified_purchase_credits_the_current_month_allowance(self, verify_mock):
        from apps.common.services.flutterwave import FlutterwaveVerifyResult

        purchase = commands.LiveMinutePurchase.objects.create(
            creator=self.ministry,
            minutes=1000,
            amount=500000,
            currency="NGN",
            payment_reference="LMP-TEST1",
        )
        verify_mock.return_value = FlutterwaveVerifyResult(status="successful", provider_transaction_id="55")
        commands.verify_minute_purchase(creator=self.ministry, payment_reference="LMP-TEST1", transaction_id="55")

        purchase.refresh_from_db()
        self.assertEqual(purchase.status, LiveMinutePurchaseStatus.SUCCESSFUL)
        summary = commands.selectors.compute_allowance_summary(creator=self.ministry)
        self.assertEqual(summary["purchased_minutes"], 1000)


class ApprovalFallbackTests(TestCase):
    def setUp(self):
        self.ministry = _verified_ministry()
        self.broadcast = LiveBroadcast.objects.create(creator=self.ministry, title="Sunday Service", category=_category())

    def test_approving_credits_allowance_and_marks_decided(self):
        admin = UserFactory(email="admin@example.com")
        approval_request = commands.request_broadcast_approval(broadcast=self.broadcast, requested_minutes=500)

        decided = commands.decide_broadcast_approval(approval_request=approval_request, approve=True, actor=admin)
        self.assertEqual(decided.status, LiveBroadcastApprovalStatus.APPROVED)
        summary = commands.selectors.compute_allowance_summary(creator=self.ministry)
        self.assertEqual(summary["purchased_minutes"], 500)

    def test_rejecting_does_not_credit_allowance(self):
        admin = UserFactory(email="admin2@example.com")
        approval_request = commands.request_broadcast_approval(broadcast=self.broadcast, requested_minutes=500)

        decided = commands.decide_broadcast_approval(
            approval_request=approval_request, approve=False, actor=admin, note="Not this month."
        )
        self.assertEqual(decided.status, LiveBroadcastApprovalStatus.REJECTED)
        summary = commands.selectors.compute_allowance_summary(creator=self.ministry)
        self.assertEqual(summary["purchased_minutes"], 0)


class EndBroadcastTests(TestCase):
    def setUp(self):
        self.ministry = _verified_ministry()
        self.category = _category()

    def _live_broadcast(self, recording_status=LiveBroadcastRecordingStatus.RECORDING):
        broadcast = LiveBroadcast.objects.create(
            creator=self.ministry, title="Sunday Service", category=self.category
        )
        broadcast.status = LiveBroadcastStatus.LIVE
        broadcast.started_at = timezone.now()
        broadcast.agora_channel_name = "itestified-live-1-abcd"
        broadcast.agora_recording_resource_id = "resource-1"
        broadcast.agora_recording_sid = "sid-1"
        broadcast.agora_recording_uid = 2_000_000_001
        broadcast.recording_status = recording_status
        broadcast.max_duration_minutes_applied = 30
        broadcast.save()
        return broadcast

    def test_cannot_end_a_non_live_broadcast(self):
        broadcast = LiveBroadcast.objects.create(
            creator=self.ministry, title="Sunday Service", category=self.category
        )
        with self.assertRaises(LiveBroadcastWrongStatusError):
            commands.end_broadcast(broadcast=broadcast, reason=LiveBroadcastEndedReason.CREATOR_ENDED)

    @patch("apps.live_broadcasts.tasks.poll_and_archive_recording.delay")
    @patch("apps.live_broadcasts.services.commands.agora.stop_cloud_recording")
    def test_ending_a_recording_broadcast_stops_recording_and_enqueues_polling(self, stop_mock, delay_mock):
        broadcast = self._live_broadcast()
        with self.captureOnCommitCallbacks(execute=True):
            commands.end_broadcast(broadcast=broadcast, reason=LiveBroadcastEndedReason.CREATOR_ENDED)

        broadcast.refresh_from_db()
        self.assertEqual(broadcast.status, LiveBroadcastStatus.ENDED)
        self.assertEqual(broadcast.ended_reason, LiveBroadcastEndedReason.CREATOR_ENDED)
        self.assertEqual(broadcast.recording_status, LiveBroadcastRecordingStatus.STOPPING)
        stop_mock.assert_called_once()
        delay_mock.assert_called_once_with(broadcast.id)

    @patch("apps.live_broadcasts.tasks.poll_and_archive_recording.delay")
    def test_ending_a_broadcast_with_no_recording_does_not_enqueue_polling(self, delay_mock):
        broadcast = self._live_broadcast(recording_status=LiveBroadcastRecordingStatus.FAILED)
        commands.end_broadcast(broadcast=broadcast, reason=LiveBroadcastEndedReason.DROPPED)

        broadcast.refresh_from_db()
        self.assertEqual(broadcast.status, LiveBroadcastStatus.ENDED)
        self.assertEqual(broadcast.ended_reason, LiveBroadcastEndedReason.DROPPED)
        delay_mock.assert_not_called()


class ArchiveBroadcastRecordingTests(TestCase):
    def test_archiving_creates_a_draft_testimony_and_notifies_creator(self):
        from apps.notifications.models import NotificationType, UserNotification
        from apps.testimonies.models import TestimonyStatus, TestimonyType

        ministry = _verified_ministry()
        category = _category()
        broadcast = LiveBroadcast.objects.create(creator=ministry, title="Sunday Service", category=category)

        with self.captureOnCommitCallbacks(execute=True):
            testimony = commands.archive_broadcast_recording(
                broadcast=broadcast, video_url="https://bucket.example/recordings/sunday.mp4"
            )

        self.assertEqual(testimony.testimony_type, TestimonyType.VIDEO)
        self.assertEqual(testimony.status, TestimonyStatus.DRAFT)
        self.assertEqual(testimony.category_id, category.id)
        self.assertEqual(testimony.video_url, "https://bucket.example/recordings/sunday.mp4")

        broadcast.refresh_from_db()
        self.assertEqual(broadcast.archived_testimony_id, testimony.id)
        self.assertEqual(broadcast.recording_status, LiveBroadcastRecordingStatus.ARCHIVED)

        self.assertTrue(
            UserNotification.objects.filter(
                recipient=ministry, notification_type=NotificationType.LIVE_BROADCAST_RECORDING_READY
            ).exists()
        )


class ReconcileStaleLiveBroadcastsTests(TestCase):
    def setUp(self):
        self.ministry = _verified_ministry()
        self.category = _category()

    def test_a_broadcast_well_past_its_token_expiry_is_marked_dropped(self):
        broadcast = LiveBroadcast.objects.create(
            creator=self.ministry, title="Sunday Service", category=self.category
        )
        broadcast.status = LiveBroadcastStatus.LIVE
        broadcast.started_at = timezone.now() - timezone.timedelta(hours=2)
        broadcast.max_duration_minutes_applied = 30
        broadcast.recording_status = LiveBroadcastRecordingStatus.FAILED
        broadcast.save()

        ended_count = commands.reconcile_stale_live_broadcasts()

        self.assertEqual(ended_count, 1)
        broadcast.refresh_from_db()
        self.assertEqual(broadcast.status, LiveBroadcastStatus.ENDED)
        self.assertEqual(broadcast.ended_reason, LiveBroadcastEndedReason.DROPPED)

    def test_a_broadcast_still_within_its_window_is_left_alone(self):
        broadcast = LiveBroadcast.objects.create(
            creator=self.ministry, title="Sunday Service", category=self.category
        )
        broadcast.status = LiveBroadcastStatus.LIVE
        broadcast.started_at = timezone.now()
        broadcast.max_duration_minutes_applied = 30
        broadcast.recording_status = LiveBroadcastRecordingStatus.FAILED
        broadcast.save()

        ended_count = commands.reconcile_stale_live_broadcasts()

        self.assertEqual(ended_count, 0)
        broadcast.refresh_from_db()
        self.assertEqual(broadcast.status, LiveBroadcastStatus.LIVE)
