from decimal import Decimal

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.referrals.models import ReferralAttribution, ReferralCommission
from apps.referrals.services.commands import (
    record_commission_for_successful_charge,
    set_referral_commission_rate,
)
from apps.subscriptions.models import Subscription, SubscriptionStatus
from apps.users.tests.factories import UserFactory


def _webhook_headers(secret_hash: str = "webhook-secret") -> dict:
    return {"HTTP_VERIF_HASH": secret_hash}


class RecordCommissionForSuccessfulChargeTests(TestCase):
    def setUp(self):
        self.admin_user = UserFactory(email="commission-admin@example.com")
        self.referrer = UserFactory(email="referrer@example.com")
        self.referred_user = UserFactory(email="referred@example.com")
        ReferralAttribution.objects.create(referred_user=self.referred_user, referrer=self.referrer)

    def _active_referrer_subscription(self):
        return Subscription.objects.create(
            user=self.referrer,
            amount=300000,
            payment_reference="SUB-REFERRER01",
            status=SubscriptionStatus.ACTIVE,
        )

    def _referred_subscription(self, provider_transaction_id="txn-referred-1", amount=300000):
        return Subscription.objects.create(
            user=self.referred_user,
            amount=amount,
            payment_reference="SUB-REFERRED01",
            status=SubscriptionStatus.ACTIVE,
            current_period_end=timezone.now(),
            provider_transaction_id=provider_transaction_id,
        )

    def test_no_commission_when_no_attribution(self):
        stranger = UserFactory(email="no-referrer@example.com")
        set_referral_commission_rate(percent=Decimal("15.00"), actor=self.admin_user)
        self._active_referrer_subscription()
        subscription = Subscription.objects.create(
            user=stranger,
            amount=300000,
            payment_reference="SUB-NOATTR01",
            status=SubscriptionStatus.ACTIVE,
            provider_transaction_id="txn-no-attr",
        )
        result = record_commission_for_successful_charge(subscription=subscription)
        self.assertIsNone(result)
        self.assertFalse(ReferralCommission.objects.exists())

    def test_no_commission_when_referrer_is_not_currently_premium(self):
        set_referral_commission_rate(percent=Decimal("15.00"), actor=self.admin_user)
        # Referrer has no active subscription at all.
        subscription = self._referred_subscription()
        result = record_commission_for_successful_charge(subscription=subscription)
        self.assertIsNone(result)
        self.assertFalse(ReferralCommission.objects.exists())

    def test_no_commission_when_rate_has_never_been_set(self):
        self._active_referrer_subscription()
        subscription = self._referred_subscription()
        result = record_commission_for_successful_charge(subscription=subscription)
        self.assertIsNone(result)
        self.assertFalse(ReferralCommission.objects.exists())

    def test_creates_a_commission_row_with_the_rate_snapshotted(self):
        set_referral_commission_rate(percent=Decimal("15.00"), actor=self.admin_user)
        self._active_referrer_subscription()
        subscription = self._referred_subscription(amount=300000)

        commission = record_commission_for_successful_charge(subscription=subscription)

        self.assertIsNotNone(commission)
        self.assertEqual(commission.referrer, self.referrer)
        self.assertEqual(commission.referred_user, self.referred_user)
        self.assertEqual(commission.subscription, subscription)
        self.assertEqual(commission.amount, 45000)  # 15% of 300000
        self.assertEqual(commission.currency, "NGN")
        self.assertEqual(commission.rate_percent, Decimal("15.00"))
        self.assertEqual(commission.billing_period_end, subscription.current_period_end)
        self.assertFalse(commission.is_paid)

    def test_is_idempotent_for_the_same_charge(self):
        set_referral_commission_rate(percent=Decimal("15.00"), actor=self.admin_user)
        self._active_referrer_subscription()
        subscription = self._referred_subscription()

        first = record_commission_for_successful_charge(subscription=subscription)
        second = record_commission_for_successful_charge(subscription=subscription)

        self.assertEqual(first.id, second.id)
        self.assertEqual(ReferralCommission.objects.count(), 1)

    def test_a_later_rate_change_never_touches_an_already_created_row(self):
        set_referral_commission_rate(percent=Decimal("15.00"), actor=self.admin_user)
        self._active_referrer_subscription()
        first_subscription = self._referred_subscription(provider_transaction_id="txn-cycle-1")
        first_commission = record_commission_for_successful_charge(subscription=first_subscription)

        set_referral_commission_rate(percent=Decimal("20.00"), actor=self.admin_user)
        first_subscription.provider_transaction_id = "txn-cycle-2"
        first_subscription.save(update_fields=["provider_transaction_id"])
        second_commission = record_commission_for_successful_charge(subscription=first_subscription)

        first_commission.refresh_from_db()
        self.assertEqual(first_commission.rate_percent, Decimal("15.00"))
        self.assertEqual(second_commission.rate_percent, Decimal("20.00"))

    def test_no_commission_without_a_provider_transaction_id(self):
        set_referral_commission_rate(percent=Decimal("15.00"), actor=self.admin_user)
        self._active_referrer_subscription()
        subscription = self._referred_subscription(provider_transaction_id="")
        result = record_commission_for_successful_charge(subscription=subscription)
        self.assertIsNone(result)
        self.assertFalse(ReferralCommission.objects.exists())


class ReferralAttributionModelTests(TestCase):
    def test_a_user_cannot_be_attributed_to_themselves(self):
        user = UserFactory(email="self-referral@example.com")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ReferralAttribution.objects.create(referred_user=user, referrer=user)


class ReferralCommissionWebhookTests(TestCase):
    """Integration coverage through the real shared Flutterwave webhook
    (apps.donations.api.views.DonationProviderCallbackView), the actual
    entry point Phase 24 Slice 2 hooks into -- not just the service
    function in isolation."""

    def setUp(self):
        self.admin_user = UserFactory(email="commission-webhook-admin@example.com")
        self.referrer = UserFactory(email="webhook-referrer@example.com")
        self.referred_user = UserFactory(email="webhook-referred@example.com")
        ReferralAttribution.objects.create(referred_user=self.referred_user, referrer=self.referrer)
        Subscription.objects.create(
            user=self.referrer,
            amount=300000,
            payment_reference="SUB-WEBHOOK-REFERRER",
            status=SubscriptionStatus.ACTIVE,
        )
        set_referral_commission_rate(percent=Decimal("15.00"), actor=self.admin_user)

    def _post_webhook(self, body: dict, secret_hash: str = "webhook-secret"):
        from unittest.mock import patch

        with patch("apps.donations.api.views.settings.FLUTTERWAVE_SECRET_HASH", "webhook-secret"):
            return self.client.post(
                reverse("donation-provider-callback"),
                body,
                content_type="application/json",
                **_webhook_headers(secret_hash),
            )

    def test_first_charge_success_creates_a_commission_for_the_referrer(self):
        Subscription.objects.create(
            user=self.referred_user,
            amount=300000,
            payment_reference="SUB-WEBHOOK-REFERRED",
            status=SubscriptionStatus.PENDING,
        )
        response = self._post_webhook(
            {
                "event": "charge.completed",
                "data": {
                    "tx_ref": "SUB-WEBHOOK-REFERRED",
                    "status": "successful",
                    "id": "txn-webhook-1",
                    "customer": {"email": self.referred_user.email},
                },
            }
        )
        self.assertEqual(response.status_code, 200)
        commission = ReferralCommission.objects.get()
        self.assertEqual(commission.referrer, self.referrer)
        self.assertEqual(commission.referred_user, self.referred_user)
        self.assertEqual(commission.amount, 45000)

    def test_failed_charge_creates_no_commission(self):
        Subscription.objects.create(
            user=self.referred_user,
            amount=300000,
            payment_reference="SUB-WEBHOOK-FAILED",
            status=SubscriptionStatus.PENDING,
        )
        response = self._post_webhook(
            {
                "event": "charge.completed",
                "data": {
                    "tx_ref": "SUB-WEBHOOK-FAILED",
                    "status": "failed",
                    "id": "txn-webhook-2",
                    "customer": {"email": self.referred_user.email},
                },
            }
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(ReferralCommission.objects.exists())

    def test_renewal_charge_success_creates_a_commission(self):
        Subscription.objects.create(
            user=self.referred_user,
            amount=300000,
            payment_reference="SUB-WEBHOOK-RENEWAL",
            status=SubscriptionStatus.ACTIVE,
            current_period_end=timezone.now(),
        )
        response = self._post_webhook(
            {
                "event": "charge.completed",
                "data": {
                    "tx_ref": "flw-generated-renewal-ref",
                    "status": "successful",
                    "id": "txn-webhook-3",
                    "customer": {"email": self.referred_user.email},
                },
            }
        )
        self.assertEqual(response.status_code, 200)
        commission = ReferralCommission.objects.get()
        self.assertEqual(commission.referred_user, self.referred_user)
