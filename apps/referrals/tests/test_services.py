from decimal import Decimal

from django.test import TestCase

from apps.referrals.exceptions import ReferralCommissionRateInvalidPercentError
from apps.referrals.models import ReferralCommissionRate
from apps.referrals.selectors import get_current_commission_percent, get_current_commission_rate
from apps.referrals.services.commands import set_referral_commission_rate
from apps.users.tests.factories import UserFactory


class SetReferralCommissionRateTests(TestCase):
    def setUp(self):
        self.admin_user = UserFactory(email="rate-admin@example.com")

    def test_rejects_a_negative_percent(self):
        with self.assertRaises(ReferralCommissionRateInvalidPercentError):
            set_referral_commission_rate(percent=Decimal("-1"), actor=self.admin_user)
        self.assertFalse(ReferralCommissionRate.objects.exists())

    def test_rejects_a_percent_above_100(self):
        with self.assertRaises(ReferralCommissionRateInvalidPercentError):
            set_referral_commission_rate(percent=Decimal("100.01"), actor=self.admin_user)
        self.assertFalse(ReferralCommissionRate.objects.exists())

    def test_creates_the_first_rate_and_a_history_row_with_no_from_value(self):
        rate = set_referral_commission_rate(percent=Decimal("15.00"), actor=self.admin_user)
        self.assertEqual(rate.percent, Decimal("15.00"))
        self.assertEqual(rate.updated_by, self.admin_user)
        history = rate.history.get()
        self.assertIsNone(history.from_percent)
        self.assertEqual(history.to_percent, Decimal("15.00"))
        self.assertEqual(history.actor, self.admin_user)

    def test_changing_the_rate_updates_the_same_row_and_records_history(self):
        set_referral_commission_rate(percent=Decimal("15.00"), actor=self.admin_user)
        second_admin = UserFactory(email="rate-admin-2@example.com")

        rate = set_referral_commission_rate(percent=Decimal("20.00"), actor=second_admin)

        self.assertEqual(ReferralCommissionRate.objects.count(), 1)
        rate.refresh_from_db()
        self.assertEqual(rate.percent, Decimal("20.00"))
        self.assertEqual(rate.updated_by, second_admin)

        history = rate.history.order_by("-created_at").first()
        self.assertEqual(history.from_percent, Decimal("15.00"))
        self.assertEqual(history.to_percent, Decimal("20.00"))
        self.assertEqual(history.actor, second_admin)
        self.assertEqual(rate.history.count(), 2)


class ReferralCommissionRateSelectorTests(TestCase):
    def test_get_current_commission_rate_returns_none_when_unset(self):
        self.assertIsNone(get_current_commission_rate())

    def test_get_current_commission_percent_defaults_to_zero_when_unset(self):
        self.assertEqual(get_current_commission_percent(), Decimal("0"))

    def test_get_current_commission_percent_reflects_the_latest_set_rate(self):
        admin_user = UserFactory(email="rate-admin-3@example.com")
        set_referral_commission_rate(percent=Decimal("12.50"), actor=admin_user)
        self.assertEqual(get_current_commission_percent(), Decimal("12.50"))
