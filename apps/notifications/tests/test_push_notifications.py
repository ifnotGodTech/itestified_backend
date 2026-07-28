from unittest.mock import patch

from django.test import TestCase

from apps.notifications.models import DeviceToken, NotificationType, UserNotification, UserNotificationPreference
from apps.notifications.services import (
    notify_admins_of_new_donation,
    notify_all_users_of_app_update,
    notify_all_users_of_scripture_published,
    notify_new_video_testimony_published,
    notify_testimony_approved,
    notify_testimony_comment,
    notify_testimony_rejected,
    notify_testimony_submitted_to_admins,
    send_push_to_users,
)
from apps.users.choices import UserAccountStatus
from apps.users.tests.factories import UserFactory


class _FakeTestimony:
    def __init__(self, title: str):
        self.title = title


class _FakeScripture:
    def __init__(self, bible_text: str):
        self.bible_text = bible_text


class SendPushToUsersTests(TestCase):
    """Phase 6 Slice 10: allow_push_notifications gating + on_commit deferral."""

    def test_dispatches_to_a_users_device_tokens_on_commit(self):
        user = UserFactory(email="pushable@example.com")
        DeviceToken.objects.create(user=user, token="tok-1", platform="android")
        DeviceToken.objects.create(user=user, token="tok-2", platform="ios")

        with patch("apps.notifications.services.send_push_to_tokens", return_value=[]) as send_mock:
            with self.captureOnCommitCallbacks(execute=True):
                send_push_to_users(user_ids=[user.id], title="Hi", body="Hello there")

        send_mock.assert_called_once()
        kwargs = send_mock.call_args.kwargs
        self.assertCountEqual(kwargs["tokens"], ["tok-1", "tok-2"])
        self.assertEqual(kwargs["title"], "Hi")
        self.assertEqual(kwargs["body"], "Hello there")

    def test_does_not_dispatch_before_the_transaction_commits(self):
        user = UserFactory(email="deferred@example.com")
        DeviceToken.objects.create(user=user, token="tok-deferred", platform="android")

        # No captureOnCommitCallbacks here: outside that context manager,
        # on_commit callbacks queued during a still-open TestCase transaction
        # never fire, proving the send is genuinely deferred rather than
        # immediate.
        with patch("apps.notifications.services.send_push_to_tokens", return_value=[]) as send_mock:
            send_push_to_users(user_ids=[user.id], title="Hi", body="Hello")
            send_mock.assert_not_called()

    def test_skips_users_who_opted_out_of_push(self):
        user = UserFactory(email="opted-out-push@example.com")
        UserNotificationPreference.objects.create(user=user, allow_push_notifications=False)
        DeviceToken.objects.create(user=user, token="tok-opted-out", platform="android")

        with patch("apps.notifications.services.send_push_to_tokens") as send_mock:
            with self.captureOnCommitCallbacks(execute=True):
                send_push_to_users(user_ids=[user.id], title="Hi", body="Hello")

        send_mock.assert_not_called()

    def test_sends_to_users_who_never_set_a_preference(self):
        # Model default is allow_push_notifications=True.
        user = UserFactory(email="no-pref-push@example.com")
        DeviceToken.objects.create(user=user, token="tok-default", platform="android")

        with patch("apps.notifications.services.send_push_to_tokens", return_value=[]) as send_mock:
            with self.captureOnCommitCallbacks(execute=True):
                send_push_to_users(user_ids=[user.id], title="Hi", body="Hello")

        send_mock.assert_called_once()

    def test_does_nothing_when_the_user_has_no_device_tokens(self):
        user = UserFactory(email="no-devices@example.com")

        with patch("apps.notifications.services.send_push_to_tokens") as send_mock:
            with self.captureOnCommitCallbacks(execute=True):
                send_push_to_users(user_ids=[user.id], title="Hi", body="Hello")

        send_mock.assert_not_called()

    def test_deletes_tokens_fcm_reports_as_unregistered(self):
        user = UserFactory(email="stale-token@example.com")
        DeviceToken.objects.create(user=user, token="tok-stale", platform="android")
        DeviceToken.objects.create(user=user, token="tok-live", platform="android")

        with patch(
            "apps.notifications.services.send_push_to_tokens",
            return_value=["tok-stale"],
        ):
            with self.captureOnCommitCallbacks(execute=True):
                send_push_to_users(user_ids=[user.id], title="Hi", body="Hello")

        self.assertFalse(DeviceToken.objects.filter(token="tok-stale").exists())
        self.assertTrue(DeviceToken.objects.filter(token="tok-live").exists())

    def test_a_send_failure_is_swallowed_not_raised(self):
        user = UserFactory(email="push-fails@example.com")
        DeviceToken.objects.create(user=user, token="tok-fails", platform="android")

        with patch(
            "apps.notifications.services.send_push_to_tokens",
            side_effect=RuntimeError("fcm down"),
        ):
            with self.captureOnCommitCallbacks(execute=True):
                send_push_to_users(user_ids=[user.id], title="Hi", body="Hello")  # must not raise

        self.assertTrue(DeviceToken.objects.filter(token="tok-fails").exists())

    def test_platform_filter_only_targets_that_platforms_tokens(self):
        user = UserFactory(email="cross-platform@example.com")
        DeviceToken.objects.create(user=user, token="tok-android", platform="android")
        DeviceToken.objects.create(user=user, token="tok-ios", platform="ios")

        with patch("apps.notifications.services.send_push_to_tokens", return_value=[]) as send_mock:
            with self.captureOnCommitCallbacks(execute=True):
                send_push_to_users(user_ids=[user.id], title="Hi", body="Hello", platform="android")

        send_mock.assert_called_once()
        self.assertEqual(send_mock.call_args.kwargs["tokens"], ["tok-android"])


class NotifyFunctionsPushWiringTests(TestCase):
    """Confirms only the three Slice 10-approved notification types push."""

    def _with_device(self, email: str) -> "UserFactory":
        user = UserFactory(email=email)
        DeviceToken.objects.create(user=user, token=f"tok-{email}", platform="android")
        return user

    def test_testimony_approved_pushes(self):
        recipient = self._with_device("approved-recipient@example.com")
        actor = UserFactory(email="approver@example.com")

        with patch("apps.notifications.services.send_push_to_tokens", return_value=[]) as send_mock:
            with self.captureOnCommitCallbacks(execute=True):
                notify_testimony_approved(recipient=recipient, actor=actor, testimony_title="My Story")

        send_mock.assert_called_once()

    def test_testimony_comment_pushes(self):
        recipient = self._with_device("comment-recipient@example.com")
        actor = UserFactory(email="commenter@example.com")

        with patch("apps.notifications.services.send_push_to_tokens", return_value=[]) as send_mock:
            with self.captureOnCommitCallbacks(execute=True):
                notify_testimony_comment(recipient=recipient, actor=actor, testimony_title="My Story")

        send_mock.assert_called_once()

    def test_new_video_testimony_pushes(self):
        recipient = self._with_device("video-recipient@example.com")

        with patch("apps.notifications.services.send_push_to_tokens", return_value=[]) as send_mock:
            with self.captureOnCommitCallbacks(execute=True):
                notify_new_video_testimony_published(testimony=_FakeTestimony("A Miracle"))

        send_mock.assert_called_once()

    def test_scripture_published_pushes(self):
        recipient = self._with_device("scripture-recipient@example.com")

        with patch("apps.notifications.services.send_push_to_tokens", return_value=[]) as send_mock:
            with self.captureOnCommitCallbacks(execute=True):
                notify_all_users_of_scripture_published(scripture=_FakeScripture("John 3:16"))

        send_mock.assert_called_once()

    def test_testimony_rejected_does_not_push(self):
        recipient = self._with_device("rejected-recipient@example.com")
        actor = UserFactory(email="rejector@example.com")

        with patch("apps.notifications.services.send_push_to_tokens") as send_mock:
            with self.captureOnCommitCallbacks(execute=True):
                notify_testimony_rejected(
                    recipient=recipient, actor=actor, testimony_title="My Story", reason="Needs more detail"
                )

        send_mock.assert_not_called()

    def test_testimony_submitted_to_admins_does_not_push(self):
        admin = self._with_device("submit-admin@example.com")
        actor = UserFactory(email="submitter@example.com")
        from apps.users.choices import AdminRoleCode
        from apps.users.tests.factories import AdminAssignmentFactory, AdminRoleFactory

        AdminAssignmentFactory(user=admin, role=AdminRoleFactory(code=AdminRoleCode.CONTENT_ADMIN))

        with patch("apps.notifications.services.send_push_to_tokens") as send_mock:
            with self.captureOnCommitCallbacks(execute=True):
                notify_testimony_submitted_to_admins(
                    testimony_title="My Story", testimony_type="text", actor=actor
                )

        send_mock.assert_not_called()

    def test_donation_received_does_not_push(self):
        admin = self._with_device("donation-admin@example.com")
        donor = UserFactory(email="donor-push-test@example.com")
        from apps.users.choices import AdminRoleCode
        from apps.users.tests.factories import AdminAssignmentFactory, AdminRoleFactory

        AdminAssignmentFactory(user=admin, role=AdminRoleFactory(code=AdminRoleCode.FINANCE_ADMIN))

        with patch("apps.notifications.services.send_push_to_tokens") as send_mock:
            with self.captureOnCommitCallbacks(execute=True):
                notify_admins_of_new_donation(
                    donor=donor, donor_label="A Donor", amount_label="NGN 5,000.00"
                )

        send_mock.assert_not_called()


class NotifyAllUsersOfAppUpdateTests(TestCase):
    def test_notifies_only_users_with_a_device_on_the_target_platform(self):
        actor = UserFactory(email="release-admin@example.com")
        android_user = UserFactory(email="android-user@example.com")
        DeviceToken.objects.create(user=android_user, token="tok-android-only", platform="android")
        ios_user = UserFactory(email="ios-user@example.com")
        DeviceToken.objects.create(user=ios_user, token="tok-ios-only", platform="ios")
        no_device_user = UserFactory(email="no-device-user@example.com")

        with patch("apps.notifications.services.send_push_to_tokens", return_value=[]) as send_mock:
            with self.captureOnCommitCallbacks(execute=True):
                notified_count = notify_all_users_of_app_update(actor=actor, platform="android")

        self.assertEqual(notified_count, 1)
        send_mock.assert_called_once()
        self.assertEqual(send_mock.call_args.kwargs["tokens"], ["tok-android-only"])
        self.assertTrue(
            UserNotification.objects.filter(
                recipient=android_user, notification_type=NotificationType.APP_UPDATE_AVAILABLE
            ).exists()
        )
        self.assertFalse(UserNotification.objects.filter(recipient=ios_user).exists())
        self.assertFalse(UserNotification.objects.filter(recipient=no_device_user).exists())

    def test_excludes_inactive_users(self):
        actor = UserFactory(email="release-admin-2@example.com")
        deactivated_user = UserFactory(
            email="deactivated-user@example.com", account_status=UserAccountStatus.DEACTIVATED
        )
        DeviceToken.objects.create(user=deactivated_user, token="tok-deactivated", platform="android")

        with patch("apps.notifications.services.send_push_to_tokens", return_value=[]) as send_mock:
            with self.captureOnCommitCallbacks(execute=True):
                notified_count = notify_all_users_of_app_update(actor=actor, platform="android")

        self.assertEqual(notified_count, 0)
        send_mock.assert_not_called()

    def test_returns_zero_when_no_devices_registered_for_the_platform(self):
        actor = UserFactory(email="release-admin-3@example.com")

        with patch("apps.notifications.services.send_push_to_tokens") as send_mock:
            with self.captureOnCommitCallbacks(execute=True):
                notified_count = notify_all_users_of_app_update(actor=actor, platform="android")

        self.assertEqual(notified_count, 0)
        send_mock.assert_not_called()


class NotifyAllUsersOfScripturePublishedTests(TestCase):
    def test_notifies_active_non_admin_users_and_excludes_the_acting_admin(self):
        from apps.users.choices import AdminRoleCode
        from apps.users.tests.factories import AdminAssignmentFactory, AdminRoleFactory

        actor = UserFactory(email="scripture-admin@example.com")
        AdminAssignmentFactory(user=actor, role=AdminRoleFactory(code=AdminRoleCode.CONTENT_ADMIN))
        member = UserFactory(email="scripture-member@example.com")
        DeviceToken.objects.create(user=member, token="tok-scripture-member", platform="android")

        with patch("apps.notifications.services.send_push_to_tokens", return_value=[]) as send_mock:
            with self.captureOnCommitCallbacks(execute=True):
                notified_count = notify_all_users_of_scripture_published(
                    scripture=_FakeScripture("Jeremiah 29:11"), actor=actor
                )

        self.assertEqual(notified_count, 1)
        send_mock.assert_called_once()
        notification = UserNotification.objects.get(recipient=member)
        self.assertEqual(notification.notification_type, NotificationType.SCRIPTURE_PUBLISHED)
        self.assertIn("Jeremiah 29:11", notification.message)
        self.assertFalse(UserNotification.objects.filter(recipient=actor).exists())

    def test_excludes_all_active_admins_even_without_an_actor(self):
        from apps.users.choices import AdminRoleCode
        from apps.users.tests.factories import AdminAssignmentFactory, AdminRoleFactory

        admin = UserFactory(email="scripture-cron-admin@example.com")
        AdminAssignmentFactory(user=admin, role=AdminRoleFactory(code=AdminRoleCode.CONTENT_ADMIN))
        member = UserFactory(email="scripture-cron-member@example.com")

        with patch("apps.notifications.services.send_push_to_tokens") as send_mock:
            with self.captureOnCommitCallbacks(execute=True):
                notified_count = notify_all_users_of_scripture_published(
                    scripture=_FakeScripture("Psalm 23:1"), actor=None
                )

        self.assertEqual(notified_count, 1)
        self.assertTrue(UserNotification.objects.filter(recipient=member).exists())
        self.assertFalse(UserNotification.objects.filter(recipient=admin).exists())
        send_mock.assert_not_called()

    def test_excludes_inactive_users(self):
        UserFactory(
            email="scripture-deactivated@example.com", account_status=UserAccountStatus.DEACTIVATED
        )

        with patch("apps.notifications.services.send_push_to_tokens") as send_mock:
            with self.captureOnCommitCallbacks(execute=True):
                notified_count = notify_all_users_of_scripture_published(
                    scripture=_FakeScripture("Romans 8:28"), actor=None
                )

        self.assertEqual(notified_count, 0)
        send_mock.assert_not_called()
