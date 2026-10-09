from unittest.mock import Mock, patch

import requests
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.creators.models import CreatorFollow, CreatorProfile
from apps.live_broadcasts.exceptions import (
    AgoraNotConfiguredError,
    InsufficientAllowanceError,
    LiveBroadcastingDisabledError,
    LiveBroadcastWrongStatusError,
    NotAVerifiedMinistryError,
    PlatformCeilingExceededError,
)
from apps.live_broadcasts.models import (
    LiveBroadcast,
    LiveBroadcastApprovalStatus,
    LiveBroadcastEndedReason,
    LiveBroadcastRecordingStatus,
    LiveBroadcastStatus,
    LiveMinutePricing,
    LiveMinutePricingHistory,
    LiveMinutePurchaseStatus,
    LiveStreamingPolicy,
    LiveStreamingPolicyHistory,
    MinistryStreamingAllowance,
)
from apps.live_broadcasts.services import agora, commands
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

    @patch("apps.live_broadcasts.services.commands.agora.issue_publisher_credential")
    def test_stale_copy_of_an_already_live_broadcast_cannot_go_live_again(self, issue_mock):
        # Regression (2026-10-09): a double-tap sends two requests that each
        # loaded the broadcast while it was still SCHEDULED. go_live must
        # re-read the row under lock rather than trust the caller's copy.
        # Allowance covers two broadcasts so only the status check can stop it.
        now = timezone.now()
        MinistryStreamingAllowance.objects.create(
            creator=self.ministry, year=now.year, month=now.month, base_allowance_minutes=200, purchased_minutes=3000
        )
        issue_mock.side_effect = lambda **kwargs: _fake_credential(channel_name=kwargs["channel_name"])
        stale_copy = LiveBroadcast.objects.get(pk=self.broadcast.pk)

        commands.go_live(broadcast=self.broadcast, actor=self.ministry)
        with self.assertRaises(LiveBroadcastWrongStatusError):
            commands.go_live(broadcast=stale_copy, actor=self.ministry)
        issue_mock.assert_called_once()

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


class GoLivePlatformCeilingTests(TestCase):
    """2026-09-10 refinement -- every Ministry can stay within their own
    MinistryStreamingAllowance while the platform-wide total still quietly
    exceeds Agora's real shared free-tier ceiling. These tests are scoped
    to that specific gap, distinct from GoLiveTests' per-Ministry-only
    checks above."""

    def setUp(self):
        self.ministry = _verified_ministry()
        self.category = _category()
        # Tight ceiling (default worst case is 50 x 30 = 1,500) so a single
        # broadcast is enough to explore both sides of it without needing
        # many fixture broadcasts.
        LiveStreamingPolicy.objects.create(pk=1, shared_monthly_ceiling_minutes=1000)
        self.broadcast = LiveBroadcast.objects.create(
            creator=self.ministry, title="Sunday Service", category=self.category
        )

    def _generous_own_allowance(self, creator=None, purchased_minutes=0):
        now = timezone.now()
        MinistryStreamingAllowance.objects.create(
            creator=creator or self.ministry,
            year=now.year,
            month=now.month,
            base_allowance_minutes=5000,
            purchased_minutes=purchased_minutes,
        )

    @patch("apps.live_broadcasts.services.commands.agora.issue_publisher_credential")
    def test_blocked_when_platform_ceiling_too_tight_and_nothing_purchased(self, issue_mock):
        # Own allowance is nowhere close to the bottleneck -- proves this
        # is a platform-wide check, not a repeat of the per-Ministry one.
        self._generous_own_allowance()
        with self.assertRaises(PlatformCeilingExceededError) as ctx:
            commands.go_live(broadcast=self.broadcast, actor=self.ministry)
        self.assertEqual(ctx.exception.shortfall_minutes, 1500 - 1000)
        self.assertEqual(ctx.exception.remaining_minutes, 1000)
        issue_mock.assert_not_called()

    @patch("apps.live_broadcasts.services.commands.agora.issue_publisher_credential")
    def test_blocked_by_another_ministrys_usage_not_its_own_allowance(self, issue_mock):
        issue_mock.return_value = _fake_credential()
        # Roomier ceiling than setUp's -- big enough for one broadcast
        # (1,500) with some headroom (500) left over, but not two.
        LiveStreamingPolicy.objects.filter(pk=1).update(shared_monthly_ceiling_minutes=2000)
        other_ministry = _verified_ministry(email="other-ministry@example.com")
        self._generous_own_allowance(creator=other_ministry)
        other_broadcast = LiveBroadcast.objects.create(
            creator=other_ministry, title="Midweek Service", category=self.category
        )
        # Uses 1,500 of the 2,000-minute ceiling, leaving only 500.
        commands.go_live(broadcast=other_broadcast, actor=other_ministry)

        self._generous_own_allowance()
        with self.assertRaises(PlatformCeilingExceededError) as ctx:
            commands.go_live(broadcast=self.broadcast, actor=self.ministry)
        self.assertEqual(ctx.exception.shortfall_minutes, 1000)
        self.assertEqual(ctx.exception.remaining_minutes, 500)

    @patch("apps.live_broadcasts.services.commands.agora.issue_publisher_credential")
    def test_purchased_minutes_earmark_and_exempt_the_broadcast_from_the_ceiling(self, issue_mock):
        issue_mock.return_value = _fake_credential()
        # Own base allowance alone would already cover this broadcast --
        # the earmark must still kick in because the *platform* ceiling,
        # not this Ministry's allowance, is what's actually blocking it.
        self._generous_own_allowance(purchased_minutes=500)

        commands.go_live(broadcast=self.broadcast, actor=self.ministry)

        self.broadcast.refresh_from_db()
        self.assertEqual(self.broadcast.status, LiveBroadcastStatus.LIVE)
        # Shortfall was 1500 - 1000 = 500, exactly covered by the 500
        # purchased minutes -- nothing left over to earmark.
        self.assertEqual(self.broadcast.platform_ceiling_minutes_paid, 500)

    @patch("apps.live_broadcasts.services.commands.agora.issue_publisher_credential")
    def test_partial_purchased_minutes_still_report_the_remaining_shortfall(self, issue_mock):
        issue_mock.return_value = _fake_credential()
        self._generous_own_allowance(purchased_minutes=200)

        with self.assertRaises(PlatformCeilingExceededError) as ctx:
            commands.go_live(broadcast=self.broadcast, actor=self.ministry)
        # Needed 500 to cover the shortfall, only had 200 -- 300 still short.
        self.assertEqual(ctx.exception.shortfall_minutes, 300)
        issue_mock.assert_not_called()

    @patch("apps.live_broadcasts.services.commands.agora.issue_publisher_credential")
    def test_an_earlier_broadcasts_earmark_cannot_be_spent_twice(self, issue_mock):
        issue_mock.return_value = _fake_credential()
        self._generous_own_allowance(purchased_minutes=500)

        # First broadcast spends the full 500 purchased minutes earmarking
        # its own shortfall against the (now-exhausted) 1,000-minute ceiling.
        commands.go_live(broadcast=self.broadcast, actor=self.ministry)

        second = LiveBroadcast.objects.create(
            creator=self.ministry, title="Evening Service", category=self.category
        )
        # No purchased minutes left to earmark, and the platform ceiling is
        # already fully spent by the first broadcast -- must fail, not
        # silently reuse the same 500 minutes again.
        with self.assertRaises(PlatformCeilingExceededError):
            commands.go_live(broadcast=second, actor=self.ministry)

    def test_platform_free_reserved_minutes_excludes_the_paid_portion(self):
        from apps.live_broadcasts import selectors

        now = timezone.now()
        self.broadcast.status = LiveBroadcastStatus.LIVE
        self.broadcast.started_at = now
        self.broadcast.max_viewers_applied = 50
        self.broadcast.max_duration_minutes_applied = 30
        self.broadcast.platform_ceiling_minutes_paid = 500
        self.broadcast.save()

        # 1,500 worst-case minus the 500 that was explicitly paid for.
        self.assertEqual(
            selectors.platform_free_reserved_minutes_this_month(year=now.year, month=now.month), 1000
        )


class NotifyFollowersOfLiveBroadcastTests(TestCase):
    def setUp(self):
        self.ministry = _verified_ministry()
        self.category = _category()
        self.broadcast = LiveBroadcast.objects.create(
            creator=self.ministry, title="Sunday Service", category=self.category
        )
        MinistryStreamingAllowance.objects.create(
            creator=self.ministry, year=timezone.now().year, month=timezone.now().month,
            base_allowance_minutes=200, purchased_minutes=1300,
        )

    @patch("apps.live_broadcasts.services.commands.agora.issue_publisher_credential")
    def test_followers_are_notified_when_the_broadcast_goes_live(self, issue_mock):
        from apps.notifications.models import NotificationType, UserNotification

        follower = UserFactory(email="follower@example.com")
        non_follower = UserFactory(email="stranger@example.com")
        CreatorFollow.objects.create(follower=follower, creator=self.ministry)
        issue_mock.return_value = _fake_credential()

        with self.captureOnCommitCallbacks(execute=True):
            commands.go_live(broadcast=self.broadcast, actor=self.ministry)

        self.assertTrue(
            UserNotification.objects.filter(
                recipient=follower, notification_type=NotificationType.LIVE_BROADCAST_STARTED
            ).exists()
        )
        self.assertFalse(
            UserNotification.objects.filter(
                recipient=non_follower, notification_type=NotificationType.LIVE_BROADCAST_STARTED
            ).exists()
        )

    @patch("apps.live_broadcasts.services.commands.agora.issue_publisher_credential")
    def test_no_notifications_created_when_there_are_no_followers(self, issue_mock):
        from apps.notifications.models import NotificationType, UserNotification

        issue_mock.return_value = _fake_credential()
        with self.captureOnCommitCallbacks(execute=True):
            commands.go_live(broadcast=self.broadcast, actor=self.ministry)

        self.assertFalse(
            UserNotification.objects.filter(notification_type=NotificationType.LIVE_BROADCAST_STARTED).exists()
        )


class NotifyAdminsOfLiveBroadcastStartedTests(TestCase):
    def setUp(self):
        self.ministry = _verified_ministry()
        self.category = _category()
        self.broadcast = LiveBroadcast.objects.create(
            creator=self.ministry, title="Sunday Service", category=self.category
        )
        MinistryStreamingAllowance.objects.create(
            creator=self.ministry, year=timezone.now().year, month=timezone.now().month,
            base_allowance_minutes=200, purchased_minutes=1300,
        )

    @patch("apps.live_broadcasts.services.commands.agora.issue_publisher_credential")
    def test_on_duty_admins_are_notified_when_a_broadcast_goes_live(self, issue_mock):
        from apps.notifications.models import NotificationType, UserNotification
        from apps.users.choices import AdminAssignmentStatus, AdminRoleCode
        from apps.users.tests.factories import AdminAssignmentFactory, AdminRoleFactory

        active_admin = UserFactory(email="admin@example.com")
        AdminAssignmentFactory(user=active_admin, role=AdminRoleFactory(code=AdminRoleCode.SUPER_ADMIN))
        inactive_admin = UserFactory(email="inactive-admin@example.com")
        AdminAssignmentFactory(
            user=inactive_admin,
            role=AdminRoleFactory(code=AdminRoleCode.MODERATOR),
            status=AdminAssignmentStatus.DEACTIVATED,
        )
        issue_mock.return_value = _fake_credential()

        with self.captureOnCommitCallbacks(execute=True):
            commands.go_live(broadcast=self.broadcast, actor=self.ministry)

        self.assertTrue(
            UserNotification.objects.filter(
                recipient=active_admin, notification_type=NotificationType.LIVE_BROADCAST_ADMIN_ALERT
            ).exists()
        )
        self.assertFalse(
            UserNotification.objects.filter(
                recipient=inactive_admin, notification_type=NotificationType.LIVE_BROADCAST_ADMIN_ALERT
            ).exists()
        )

    @patch("apps.live_broadcasts.services.commands.agora.issue_publisher_credential")
    def test_no_admin_notifications_created_when_there_are_no_active_admins(self, issue_mock):
        from apps.notifications.models import NotificationType, UserNotification

        issue_mock.return_value = _fake_credential()
        with self.captureOnCommitCallbacks(execute=True):
            commands.go_live(broadcast=self.broadcast, actor=self.ministry)

        self.assertFalse(
            UserNotification.objects.filter(notification_type=NotificationType.LIVE_BROADCAST_ADMIN_ALERT).exists()
        )


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

    @patch("apps.live_broadcasts.tasks.archive_stopped_recording.delay")
    @patch("apps.live_broadcasts.services.commands.agora.stop_cloud_recording")
    def test_ending_a_recording_broadcast_stops_recording_and_enqueues_archival(self, stop_mock, delay_mock):
        # 2026-09-10 correction: end_broadcast() now reads the file name
        # straight from stop's own response (see stop_cloud_recording's
        # docstring for why the old query-poll design never worked), so
        # the mock must return a realistic serverResponse shape.
        stop_mock.return_value = {"fileList": "recordings/sunday.mp4"}
        broadcast = self._live_broadcast()
        with self.captureOnCommitCallbacks(execute=True):
            commands.end_broadcast(broadcast=broadcast, reason=LiveBroadcastEndedReason.CREATOR_ENDED)

        broadcast.refresh_from_db()
        self.assertEqual(broadcast.status, LiveBroadcastStatus.ENDED)
        self.assertEqual(broadcast.ended_reason, LiveBroadcastEndedReason.CREATOR_ENDED)
        self.assertEqual(broadcast.recording_status, LiveBroadcastRecordingStatus.STOPPING)
        stop_mock.assert_called_once()
        delay_mock.assert_called_once_with(broadcast.id, "recordings/sunday.mp4")

    @patch("apps.live_broadcasts.tasks.archive_stopped_recording.delay")
    def test_ending_a_broadcast_with_no_recording_does_not_enqueue_polling(self, delay_mock):
        broadcast = self._live_broadcast(recording_status=LiveBroadcastRecordingStatus.FAILED)
        commands.end_broadcast(broadcast=broadcast, reason=LiveBroadcastEndedReason.DROPPED)

        broadcast.refresh_from_db()
        self.assertEqual(broadcast.status, LiveBroadcastStatus.ENDED)
        self.assertEqual(broadcast.ended_reason, LiveBroadcastEndedReason.DROPPED)
        delay_mock.assert_not_called()


class AdminEndBroadcastTests(TestCase):
    def setUp(self):
        self.ministry = _verified_ministry()
        self.category = _category()

    def _live_broadcast(self):
        broadcast = LiveBroadcast.objects.create(
            creator=self.ministry, title="Sunday Service", category=self.category
        )
        broadcast.status = LiveBroadcastStatus.LIVE
        broadcast.started_at = timezone.now()
        broadcast.agora_channel_name = "itestified-live-1-abcd"
        broadcast.agora_publisher_uid = self.ministry.id
        broadcast.max_duration_minutes_applied = 30
        broadcast.recording_status = LiveBroadcastRecordingStatus.FAILED
        broadcast.save()
        return broadcast

    def test_cannot_admin_end_a_non_live_broadcast(self):
        broadcast = LiveBroadcast.objects.create(
            creator=self.ministry, title="Sunday Service", category=self.category
        )
        with self.assertRaises(LiveBroadcastWrongStatusError):
            commands.admin_end_broadcast(broadcast=broadcast, actor=self.ministry, note="Guideline violation.")

    @patch("apps.live_broadcasts.services.commands.agora.ban_channel_publisher")
    def test_admin_end_kicks_the_publisher_and_ends_the_broadcast(self, ban_mock):
        from apps.notifications.models import NotificationType, UserNotification

        broadcast = self._live_broadcast()
        admin = UserFactory(email="admin@example.com")

        with self.captureOnCommitCallbacks(execute=True):
            result = commands.admin_end_broadcast(broadcast=broadcast, actor=admin, note="Inappropriate content.")

        ban_mock.assert_called_once_with(
            channel_name="itestified-live-1-abcd", uid=self.ministry.id, ban_seconds=commands.ADMIN_KICK_COOLDOWN_SECONDS
        )
        self.assertEqual(result.status, LiveBroadcastStatus.ENDED)
        self.assertEqual(result.ended_reason, LiveBroadcastEndedReason.ADMIN_TERMINATED)
        self.assertEqual(result.admin_termination_note, "Inappropriate content.")

        notification = UserNotification.objects.get(
            recipient=self.ministry, notification_type=NotificationType.LIVE_BROADCAST_ADMIN_TERMINATED
        )
        self.assertIn("Inappropriate content.", notification.message)

    @patch("apps.live_broadcasts.services.commands.agora.ban_channel_publisher", side_effect=AgoraNotConfiguredError())
    def test_admin_end_does_not_end_the_broadcast_when_the_kick_fails(self, ban_mock):
        broadcast = self._live_broadcast()
        admin = UserFactory(email="admin@example.com")

        with self.assertRaises(AgoraNotConfiguredError):
            commands.admin_end_broadcast(broadcast=broadcast, actor=admin, note="Guideline violation.")

        broadcast.refresh_from_db()
        self.assertEqual(broadcast.status, LiveBroadcastStatus.LIVE)


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

    def test_archiving_twice_creates_only_one_testimony(self):
        # Regression (2026-10-09): a duplicate Celery delivery of
        # archive_stopped_recording must not create a second DRAFT testimony.
        from apps.testimonies.models import Testimony

        ministry = _verified_ministry()
        broadcast = LiveBroadcast.objects.create(creator=ministry, title="Sunday Service", category=_category())
        stale_copy = LiveBroadcast.objects.get(pk=broadcast.pk)

        first = commands.archive_broadcast_recording(broadcast=broadcast, video_url="https://cdn.example/a.mp4")
        second = commands.archive_broadcast_recording(broadcast=stale_copy, video_url="https://cdn.example/a.mp4")

        self.assertEqual(first.id, second.id)
        self.assertEqual(Testimony.objects.filter(author=ministry).count(), 1)


class ExtractRecordingFileNameTests(TestCase):
    """2026-09-10 fix -- with avFileType: ["hls", "mp4"] a real fileList
    contains both the .m3u8 manifest and the .mp4 file; picking whichever
    is first (the original logic) can hand Cloudinary the unplayable HLS
    manifest instead, which was confirmed live to fail with Cloudinary's
    own "invalid file" error."""

    def test_bare_string_response(self):
        self.assertEqual(
            agora.extract_recording_file_name({"fileList": "recordings/sunday.m3u8"}),
            "recordings/sunday.m3u8",
        )

    def test_prefers_mp4_when_hls_listed_first(self):
        response = {
            "fileList": [
                {"fileName": "recordings/sunday.m3u8"},
                {"fileName": "recordings/sunday.mp4"},
            ]
        }
        self.assertEqual(agora.extract_recording_file_name(response), "recordings/sunday.mp4")

    def test_prefers_mp4_when_mp4_listed_first(self):
        response = {
            "fileList": [
                {"fileName": "recordings/sunday.mp4"},
                {"fileName": "recordings/sunday.m3u8"},
            ]
        }
        self.assertEqual(agora.extract_recording_file_name(response), "recordings/sunday.mp4")

    def test_falls_back_to_first_entry_when_no_mp4_present(self):
        response = {"fileList": [{"fileName": "recordings/sunday.m3u8"}]}
        self.assertEqual(agora.extract_recording_file_name(response), "recordings/sunday.m3u8")

    def test_empty_response_returns_empty_string(self):
        self.assertEqual(agora.extract_recording_file_name({}), "")


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


class BrowseSelectorTests(TestCase):
    def setUp(self):
        self.ministry = _verified_ministry()
        self.category = _category()

    def test_list_live_broadcasts_only_returns_live_ones(self):
        from apps.live_broadcasts import selectors

        live = LiveBroadcast.objects.create(creator=self.ministry, title="Live One", category=self.category)
        live.status = LiveBroadcastStatus.LIVE
        live.save()
        LiveBroadcast.objects.create(creator=self.ministry, title="Still Scheduled", category=self.category)

        results = list(selectors.list_live_broadcasts())
        self.assertEqual([b.id for b in results], [live.id])

    def test_list_upcoming_broadcasts_excludes_past_and_non_scheduled(self):
        from apps.live_broadcasts import selectors

        future = LiveBroadcast.objects.create(
            creator=self.ministry,
            title="Next Week",
            category=self.category,
            scheduled_at=timezone.now() + timezone.timedelta(days=7),
        )
        LiveBroadcast.objects.create(
            creator=self.ministry,
            title="Already Passed",
            category=self.category,
            scheduled_at=timezone.now() - timezone.timedelta(days=1),
        )
        live_now = LiveBroadcast.objects.create(
            creator=self.ministry,
            title="Currently Live",
            category=self.category,
            scheduled_at=timezone.now() + timezone.timedelta(days=1),
        )
        live_now.status = LiveBroadcastStatus.LIVE
        live_now.save()

        results = list(selectors.list_upcoming_broadcasts())
        self.assertEqual([b.id for b in results], [future.id])


class AdminMonitorSelectorTests(TestCase):
    def setUp(self):
        self.ministry = _verified_ministry()
        self.category = _category()
        MinistryStreamingAllowance.objects.create(
            creator=self.ministry, year=timezone.now().year, month=timezone.now().month,
            base_allowance_minutes=200, purchased_minutes=0,
        )

    def test_list_active_broadcasts_for_admin_attaches_viewer_count_and_allowance(self):
        from apps.live_broadcasts import selectors

        live = LiveBroadcast.objects.create(
            creator=self.ministry,
            title="Live One",
            category=self.category,
            status=LiveBroadcastStatus.LIVE,
            started_at=timezone.now() - timezone.timedelta(minutes=5),
            agora_channel_name="itestified-live-1-abcd",
            max_viewers_applied=50,
            max_duration_minutes_applied=30,
        )
        LiveBroadcast.objects.create(creator=self.ministry, title="Still Scheduled", category=self.category)

        with patch(
            "apps.live_broadcasts.selectors.agora_service.get_channel_viewer_count", return_value=7
        ) as viewer_mock:
            results = selectors.list_active_broadcasts_for_admin()

        self.assertEqual([b.id for b in results], [live.id])
        viewer_mock.assert_called_once_with(channel_name="itestified-live-1-abcd")
        self.assertEqual(results[0].viewer_count, 7)
        self.assertGreaterEqual(results[0].elapsed_seconds, 300)
        self.assertEqual(results[0].total_allowance_minutes, 200)

    def test_list_active_broadcasts_for_admin_reports_none_viewer_count_without_a_channel(self):
        from apps.live_broadcasts import selectors

        live = LiveBroadcast.objects.create(
            creator=self.ministry,
            title="Live One",
            category=self.category,
            status=LiveBroadcastStatus.LIVE,
            started_at=timezone.now(),
        )
        results = selectors.list_active_broadcasts_for_admin()
        self.assertEqual([b.id for b in results], [live.id])
        self.assertIsNone(results[0].viewer_count)

    def test_list_scheduled_broadcasts_for_admin_includes_start_now_broadcasts(self):
        from apps.live_broadcasts import selectors

        start_now = LiveBroadcast.objects.create(creator=self.ministry, title="Start Now", category=self.category)
        scheduled_ahead = LiveBroadcast.objects.create(
            creator=self.ministry,
            title="Next Week",
            category=self.category,
            scheduled_at=timezone.now() + timezone.timedelta(days=7),
        )
        live = LiveBroadcast.objects.create(
            creator=self.ministry, title="Already Live", category=self.category, status=LiveBroadcastStatus.LIVE
        )

        results = list(selectors.list_scheduled_broadcasts_for_admin())
        self.assertEqual({b.id for b in results}, {start_now.id, scheduled_ahead.id})
        self.assertNotIn(live.id, {b.id for b in results})


class JoinBroadcastAsViewerTests(TestCase):
    def setUp(self):
        self.ministry = _verified_ministry()
        self.category = _category()
        self.broadcast = LiveBroadcast.objects.create(
            creator=self.ministry, title="Sunday Service", category=self.category
        )

    def test_cannot_join_a_non_live_broadcast(self):
        with self.assertRaises(LiveBroadcastWrongStatusError):
            commands.join_broadcast_as_viewer(broadcast=self.broadcast)

    @patch("apps.live_broadcasts.services.commands.agora.issue_viewer_credential")
    def test_joining_a_live_broadcast_issues_a_subscriber_credential(self, issue_mock):
        self.broadcast.status = LiveBroadcastStatus.LIVE
        self.broadcast.agora_channel_name = "itestified-live-1-abcd"
        self.broadcast.save()
        issue_mock.return_value = PublisherCredential(
            app_id="app", channel_name="itestified-live-1-abcd", uid=1_000_000_001, token="t", expires_at_unix=1
        )

        commands.join_broadcast_as_viewer(broadcast=self.broadcast)

        issue_mock.assert_called_once()
        _, kwargs = issue_mock.call_args
        self.assertEqual(kwargs["channel_name"], "itestified-live-1-abcd")
        self.assertGreaterEqual(kwargs["uid"], commands.VIEWER_UID_RANGE_START)
        self.assertLess(kwargs["uid"], commands.VIEWER_UID_RANGE_START + commands.VIEWER_UID_RANGE_SIZE)


@override_settings(
    AGORA_APP_ID="app-id", AGORA_APP_CERTIFICATE="cert", AGORA_CUSTOMER_ID="cid", AGORA_CUSTOMER_SECRET="secret"
)
class GetChannelViewerCountTests(TestCase):
    @patch("apps.live_broadcasts.services.agora.requests.get")
    def test_returns_audience_total_when_channel_exists(self, get_mock):
        from apps.live_broadcasts.services import agora

        get_mock.return_value = Mock(
            json=lambda: {"data": {"channel_exist": True, "broadcasters": [1], "audience": [2, 3], "audience_total": 2}}
        )
        count = agora.get_channel_viewer_count(channel_name="itestified-live-1-abcd")
        self.assertEqual(count, 2)
        called_url = get_mock.call_args.args[0]
        self.assertIn("/dev/v1/channel/user/app-id/itestified-live-1-abcd", called_url)

    @patch("apps.live_broadcasts.services.agora.requests.get")
    def test_falls_back_to_audience_list_length_when_total_missing(self, get_mock):
        from apps.live_broadcasts.services import agora

        get_mock.return_value = Mock(
            json=lambda: {"data": {"channel_exist": True, "broadcasters": [1], "audience": [2, 3, 4]}}
        )
        count = agora.get_channel_viewer_count(channel_name="itestified-live-1-abcd")
        self.assertEqual(count, 3)

    @patch("apps.live_broadcasts.services.agora.requests.get")
    def test_returns_zero_when_channel_does_not_exist(self, get_mock):
        from apps.live_broadcasts.services import agora

        get_mock.return_value = Mock(json=lambda: {"data": {"channel_exist": False}})
        count = agora.get_channel_viewer_count(channel_name="itestified-live-1-abcd")
        self.assertEqual(count, 0)

    @patch("apps.live_broadcasts.services.agora.requests.get", side_effect=requests.ConnectionError("down"))
    def test_returns_none_on_request_failure(self, get_mock):
        from apps.live_broadcasts.services import agora

        self.assertIsNone(agora.get_channel_viewer_count(channel_name="itestified-live-1-abcd"))


class GetChannelViewerCountNotConfiguredTests(TestCase):
    def test_returns_none_when_agora_is_not_configured(self):
        from apps.live_broadcasts.services import agora

        self.assertIsNone(agora.get_channel_viewer_count(channel_name="itestified-live-1-abcd"))


@override_settings(
    AGORA_APP_ID="app-id", AGORA_APP_CERTIFICATE="cert", AGORA_CUSTOMER_ID="cid", AGORA_CUSTOMER_SECRET="secret"
)
class BanChannelPublisherTests(TestCase):
    @patch("apps.live_broadcasts.services.agora.requests.post")
    def test_posts_the_expected_kicking_rule_payload(self, post_mock):
        from apps.live_broadcasts.services import agora

        post_mock.return_value = Mock(json=lambda: {"status": "success", "id": 1})
        agora.ban_channel_publisher(channel_name="itestified-live-1-abcd", uid=42, ban_seconds=300)

        post_mock.assert_called_once()
        called_url = post_mock.call_args.args[0]
        called_kwargs = post_mock.call_args.kwargs
        self.assertIn("/dev/v1/kicking-rule", called_url)
        self.assertEqual(
            called_kwargs["json"],
            {
                "appid": "app-id",
                "cname": "itestified-live-1-abcd",
                "uid": "42",
                "ip": "",
                "time": 300,
                "privileges": ["join_channel"],
            },
        )

    @patch("apps.live_broadcasts.services.agora.requests.post", side_effect=requests.ConnectionError("down"))
    def test_raises_on_request_failure_rather_than_swallowing_it(self, post_mock):
        from apps.live_broadcasts.services import agora

        with self.assertRaises(requests.ConnectionError):
            agora.ban_channel_publisher(channel_name="itestified-live-1-abcd", uid=42, ban_seconds=300)


class BanChannelPublisherNotConfiguredTests(TestCase):
    def test_raises_when_agora_is_not_configured(self):
        from apps.live_broadcasts.services import agora

        with self.assertRaises(AgoraNotConfiguredError):
            agora.ban_channel_publisher(channel_name="itestified-live-1-abcd", uid=42, ban_seconds=300)


@override_settings(
    AGORA_APP_ID="app-id", AGORA_APP_CERTIFICATE="cert", AGORA_CUSTOMER_ID="cid", AGORA_CUSTOMER_SECRET="secret"
)
class GetParticipantMinutesUsedTests(TestCase):
    @patch("apps.live_broadcasts.services.agora.requests.get")
    def test_sums_totalDuration_across_every_returned_row(self, get_mock):
        from apps.live_broadcasts.services import agora

        get_mock.return_value = Mock(
            json=lambda: {"data": [{"totalDuration": 120, "ts": 1}, {"totalDuration": 80, "ts": 2}]}
        )
        used = agora.get_participant_minutes_used(year=2026, month=8)
        self.assertEqual(used, 200)
        called_url = get_mock.call_args.args[0]
        called_params = get_mock.call_args.kwargs["params"]
        self.assertIn("/beta/insight/usage/by_time", called_url)
        self.assertEqual(called_params["appid"], "app-id")
        self.assertEqual(called_params["metric"], "totalDuration")
        self.assertEqual(called_params["aggregateGranularity"], "1d")

    @patch("apps.live_broadcasts.services.agora.requests.get", side_effect=requests.ConnectionError("down"))
    def test_returns_none_on_request_failure(self, get_mock):
        from apps.live_broadcasts.services import agora

        self.assertIsNone(agora.get_participant_minutes_used(year=2026, month=8))


class GetParticipantMinutesUsedNotConfiguredTests(TestCase):
    def test_returns_none_when_agora_is_not_configured(self):
        from apps.live_broadcasts.services import agora

        self.assertIsNone(agora.get_participant_minutes_used(year=2026, month=8))


class UpdateLiveStreamingPolicyTests(TestCase):
    def test_changing_one_field_writes_exactly_one_history_row(self):
        policy = commands.selectors.get_live_streaming_policy()
        admin = UserFactory(email="admin@example.com")

        updated = commands.update_live_streaming_policy(
            actor=admin,
            is_enabled=policy.is_enabled,
            max_concurrent_viewers=999,
            max_duration_minutes=policy.max_duration_minutes,
            shared_monthly_ceiling_minutes=policy.shared_monthly_ceiling_minutes,
            default_ministry_monthly_allowance_minutes=policy.default_ministry_monthly_allowance_minutes,
        )

        self.assertEqual(updated.max_concurrent_viewers, 999)
        self.assertEqual(updated.updated_by, admin)
        history = LiveStreamingPolicyHistory.objects.filter(policy=updated)
        self.assertEqual(history.count(), 1)
        entry = history.first()
        self.assertEqual(entry.field_name, "max_concurrent_viewers")
        self.assertEqual(entry.to_value, "999")
        self.assertEqual(entry.actor, admin)

    def test_changing_no_fields_writes_no_history_and_does_not_touch_updated_by(self):
        policy = commands.selectors.get_live_streaming_policy()
        admin = UserFactory(email="admin@example.com")

        updated = commands.update_live_streaming_policy(
            actor=admin,
            is_enabled=policy.is_enabled,
            max_concurrent_viewers=policy.max_concurrent_viewers,
            max_duration_minutes=policy.max_duration_minutes,
            shared_monthly_ceiling_minutes=policy.shared_monthly_ceiling_minutes,
            default_ministry_monthly_allowance_minutes=policy.default_ministry_monthly_allowance_minutes,
        )

        self.assertIsNone(updated.updated_by)
        self.assertEqual(LiveStreamingPolicyHistory.objects.count(), 0)

    def test_changing_multiple_fields_writes_one_row_each(self):
        policy = commands.selectors.get_live_streaming_policy()
        admin = UserFactory(email="admin@example.com")

        commands.update_live_streaming_policy(
            actor=admin,
            is_enabled=False,
            max_concurrent_viewers=10,
            max_duration_minutes=policy.max_duration_minutes,
            shared_monthly_ceiling_minutes=policy.shared_monthly_ceiling_minutes,
            default_ministry_monthly_allowance_minutes=policy.default_ministry_monthly_allowance_minutes,
        )

        changed_fields = set(LiveStreamingPolicyHistory.objects.values_list("field_name", flat=True))
        self.assertEqual(changed_fields, {"is_enabled", "max_concurrent_viewers"})


class SetLiveMinutePriceTests(TestCase):
    def test_creating_a_new_price_records_a_null_from_amount(self):
        admin = UserFactory(email="admin@example.com")
        pricing = commands.set_live_minute_price(currency="NGN", price_per_1000_minutes=500000, actor=admin)

        self.assertEqual(pricing.price_per_1000_minutes, 500000)
        self.assertEqual(pricing.updated_by, admin)
        history = LiveMinutePricingHistory.objects.get(pricing=pricing)
        self.assertIsNone(history.from_amount)
        self.assertEqual(history.to_amount, 500000)

    def test_updating_an_existing_price_records_the_prior_amount(self):
        admin = UserFactory(email="admin@example.com")
        LiveMinutePricing.objects.create(currency="NGN", price_per_1000_minutes=400000)

        pricing = commands.set_live_minute_price(currency="NGN", price_per_1000_minutes=600000, actor=admin)

        self.assertEqual(pricing.price_per_1000_minutes, 600000)
        history = LiveMinutePricingHistory.objects.get(pricing=pricing)
        self.assertEqual(history.from_amount, 400000)
        self.assertEqual(history.to_amount, 600000)


class MinistryUsageSelectorTests(TestCase):
    def test_only_ministries_with_an_allowance_row_this_month_are_included(self):
        from apps.live_broadcasts import selectors

        ministry = _verified_ministry()
        now = timezone.now()
        MinistryStreamingAllowance.objects.create(
            creator=ministry, year=now.year, month=now.month, base_allowance_minutes=200, purchased_minutes=50
        )
        _verified_ministry(email="untouched@example.com")

        rows = selectors.list_ministry_usage_for_current_month()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["creator"], ministry)
        self.assertEqual(rows[0]["total_allowance_minutes"], 250)

    @patch("apps.live_broadcasts.selectors.agora_service.get_participant_minutes_used", return_value=1234)
    def test_platform_usage_summary_reports_used_minutes_and_ceiling(self, usage_mock):
        from apps.live_broadcasts import selectors

        summary = selectors.compute_platform_usage_summary()
        self.assertEqual(summary["used_minutes"], 1234)
        self.assertEqual(summary["shared_monthly_ceiling_minutes"], LiveStreamingPolicy().shared_monthly_ceiling_minutes)
