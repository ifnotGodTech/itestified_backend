from unittest.mock import patch

from django.test import TestCase

from apps.donations.models import Donation, DonationStatus
from apps.donations.services.commands import apply_provider_callback, create_donation, verify_donation
from apps.donations.services.notifications import (
    maybe_notify_new_donation,
    maybe_send_donation_thank_you_email,
)
from apps.notifications.models import NotificationType, UserNotification, UserNotificationPreference
from apps.users.choices import AdminRoleCode
from apps.users.tests.factories import AdminAssignmentFactory, AdminRoleFactory, UserFactory


class MaybeNotifyNewDonationTests(TestCase):
    """Phase 6 Slice 8: 'New Donation Received' admin preference."""

    def test_notifies_admins_who_have_not_opted_out(self):
        donor = UserFactory(email="donor@example.com")
        admin = UserFactory(email="admin-default@example.com")
        AdminAssignmentFactory(user=admin, role=AdminRoleFactory(code=AdminRoleCode.FINANCE_ADMIN))
        donation = Donation.objects.create(
            user=donor, amount=500000, currency="NGN", payment_reference="DON-NOTIFY-1"
        )

        maybe_notify_new_donation(donation)

        notification = UserNotification.objects.get(recipient=admin)
        self.assertEqual(notification.notification_type, NotificationType.DONATION_RECEIVED)
        self.assertIn("NGN 5,000.00", notification.message)

    def test_skips_admins_who_opted_out(self):
        donor = UserFactory(email="donor2@example.com")
        admin = UserFactory(email="admin-opted-out@example.com")
        AdminAssignmentFactory(user=admin, role=AdminRoleFactory(code=AdminRoleCode.FINANCE_ADMIN))
        UserNotificationPreference.objects.create(user=admin, notify_new_donation_received=False)
        donation = Donation.objects.create(
            user=donor, amount=200000, currency="NGN", payment_reference="DON-NOTIFY-2"
        )

        maybe_notify_new_donation(donation)

        self.assertFalse(UserNotification.objects.filter(recipient=admin).exists())

    def test_notifies_admins_who_explicitly_opted_in(self):
        donor = UserFactory(email="donor3@example.com")
        admin = UserFactory(email="admin-opted-in@example.com")
        AdminAssignmentFactory(user=admin, role=AdminRoleFactory(code=AdminRoleCode.FINANCE_ADMIN))
        UserNotificationPreference.objects.create(user=admin, notify_new_donation_received=True)
        donation = Donation.objects.create(
            user=donor, amount=100000, currency="NGN", payment_reference="DON-NOTIFY-3"
        )

        maybe_notify_new_donation(donation)

        self.assertTrue(UserNotification.objects.filter(recipient=admin).exists())

    def test_does_not_notify_the_donor_even_if_the_donor_is_an_admin(self):
        donor_admin = UserFactory(email="donor-admin@example.com")
        AdminAssignmentFactory(user=donor_admin, role=AdminRoleFactory(code=AdminRoleCode.FINANCE_ADMIN))
        donation = Donation.objects.create(
            user=donor_admin, amount=100000, currency="NGN", payment_reference="DON-NOTIFY-4"
        )

        maybe_notify_new_donation(donation)

        self.assertFalse(UserNotification.objects.filter(recipient=donor_admin).exists())

    def test_a_failure_here_is_swallowed_not_raised(self):
        donor = UserFactory(email="donor5@example.com")
        donation = Donation.objects.create(
            user=donor, amount=100000, currency="NGN", payment_reference="DON-NOTIFY-5"
        )
        with patch(
            "apps.donations.services.notifications.notify_admins_of_new_donation",
            side_effect=RuntimeError("boom"),
        ):
            maybe_notify_new_donation(donation)  # must not raise


class MaybeSendDonationThankYouEmailTests(TestCase):
    """Phase 6 Slice 8: 'Thank You Email' donor preference."""

    def _donation(self, user) -> Donation:
        return Donation.objects.create(
            user=user,
            amount=500000,
            currency="NGN",
            payment_reference=f"DON-THANKS-{user.id}",
            status=DonationStatus.SUCCESSFUL,
        )

    def test_sends_when_donor_opted_in_and_allows_email(self):
        donor = UserFactory(email="opted-in-donor@example.com")
        UserNotificationPreference.objects.create(
            user=donor, allow_email_notifications=True, send_donation_thank_you_email=True
        )
        donation = self._donation(donor)

        with patch("apps.donations.services.notifications.send_email") as send_mock:
            maybe_send_donation_thank_you_email(donation)

        send_mock.assert_called_once()
        self.assertEqual(send_mock.call_args.kwargs["to_email"], donor.email)

    def test_does_not_send_when_donor_never_opted_in(self):
        donor = UserFactory(email="no-pref-donor@example.com")
        donation = self._donation(donor)

        with patch("apps.donations.services.notifications.send_email") as send_mock:
            maybe_send_donation_thank_you_email(donation)

        send_mock.assert_not_called()

    def test_does_not_send_when_opted_in_but_email_notifications_disabled(self):
        donor = UserFactory(email="email-disabled-donor@example.com")
        UserNotificationPreference.objects.create(
            user=donor, allow_email_notifications=False, send_donation_thank_you_email=True
        )
        donation = self._donation(donor)

        with patch("apps.donations.services.notifications.send_email") as send_mock:
            maybe_send_donation_thank_you_email(donation)

        send_mock.assert_not_called()

    def test_does_not_send_when_thank_you_disabled_but_email_allowed(self):
        donor = UserFactory(email="thanks-disabled-donor@example.com")
        UserNotificationPreference.objects.create(
            user=donor, allow_email_notifications=True, send_donation_thank_you_email=False
        )
        donation = self._donation(donor)

        with patch("apps.donations.services.notifications.send_email") as send_mock:
            maybe_send_donation_thank_you_email(donation)

        send_mock.assert_not_called()

    def test_a_failure_here_is_swallowed_not_raised(self):
        donor = UserFactory(email="failure-donor@example.com")
        UserNotificationPreference.objects.create(
            user=donor, allow_email_notifications=True, send_donation_thank_you_email=True
        )
        donation = self._donation(donor)

        with patch("apps.donations.services.notifications.send_email", side_effect=RuntimeError("brevo down")):
            maybe_send_donation_thank_you_email(donation)  # must not raise


class DonationCommandsNotificationWiringTests(TestCase):
    """Confirms create_donation/verify_donation/apply_provider_callback actually
    schedule the new side effects (via transaction.on_commit) at the right
    transitions -- not just that the standalone helpers work in isolation."""

    def test_create_donation_schedules_admin_notification_on_commit(self):
        donor = UserFactory(email="wiring-donor@example.com")
        admin = UserFactory(email="wiring-admin@example.com")
        AdminAssignmentFactory(user=admin, role=AdminRoleFactory(code=AdminRoleCode.FINANCE_ADMIN))

        with (
            patch("apps.donations.services.commands.settings.FLUTTERWAVE_SECRET_KEY", "sk_test"),
            patch("apps.donations.services.commands.FlutterwaveGateway.initialize") as init_mock,
        ):
            init_mock.return_value.checkout_url = "https://checkout.flutterwave.com/pay/abc"
            init_mock.return_value.provider_transaction_id = "123"
            with self.captureOnCommitCallbacks(execute=True):
                create_donation(user=donor, amount=500000, currency="NGN")

        self.assertTrue(UserNotification.objects.filter(recipient=admin).exists())

    def test_verify_donation_schedules_thank_you_email_only_on_successful_transition(self):
        donor = UserFactory(email="wiring-verify-donor@example.com")
        UserNotificationPreference.objects.create(
            user=donor, allow_email_notifications=True, send_donation_thank_you_email=True
        )
        donation = Donation.objects.create(
            user=donor, amount=500000, currency="NGN", payment_reference="DON-WIRING-1"
        )

        with (
            patch("apps.donations.services.commands.settings.FLUTTERWAVE_SECRET_KEY", "sk_test"),
            patch("apps.donations.services.commands.FlutterwaveGateway.verify") as verify_mock,
            patch("apps.donations.services.notifications.send_email") as send_mock,
        ):
            verify_mock.return_value.status = DonationStatus.SUCCESSFUL
            verify_mock.return_value.provider_transaction_id = "999"
            verify_mock.return_value.status_reason = "Approved"
            with self.captureOnCommitCallbacks(execute=True):
                verify_donation(user=donor, payment_reference=donation.payment_reference, transaction_id="999")

        send_mock.assert_called_once()

    def test_verify_donation_does_not_send_email_on_declined_transition(self):
        donor = UserFactory(email="wiring-declined-donor@example.com")
        UserNotificationPreference.objects.create(
            user=donor, allow_email_notifications=True, send_donation_thank_you_email=True
        )
        donation = Donation.objects.create(
            user=donor, amount=500000, currency="NGN", payment_reference="DON-WIRING-2"
        )

        with (
            patch("apps.donations.services.commands.settings.FLUTTERWAVE_SECRET_KEY", "sk_test"),
            patch("apps.donations.services.commands.FlutterwaveGateway.verify") as verify_mock,
            patch("apps.donations.services.notifications.send_email") as send_mock,
        ):
            verify_mock.return_value.status = DonationStatus.DECLINED
            verify_mock.return_value.provider_transaction_id = "998"
            verify_mock.return_value.status_reason = "Insufficient funds"
            with self.captureOnCommitCallbacks(execute=True):
                verify_donation(user=donor, payment_reference=donation.payment_reference, transaction_id="998")

        send_mock.assert_not_called()

    def test_apply_provider_callback_schedules_thank_you_email_on_successful_transition(self):
        donor = UserFactory(email="wiring-webhook-donor@example.com")
        UserNotificationPreference.objects.create(
            user=donor, allow_email_notifications=True, send_donation_thank_you_email=True
        )
        Donation.objects.create(
            user=donor, amount=500000, currency="NGN", payment_reference="DON-WIRING-3"
        )

        with patch("apps.donations.services.notifications.send_email") as send_mock:
            with self.captureOnCommitCallbacks(execute=True):
                apply_provider_callback(
                    payment_reference="DON-WIRING-3",
                    status_value=DonationStatus.SUCCESSFUL,
                    provider_transaction_id="997",
                    status_reason="Approved",
                )

        send_mock.assert_called_once()
