from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from rest_framework.authtoken.models import Token

from apps.referrals.models import ReferralCommissionRate
from apps.users.choices import AdminRoleCode
from apps.users.tests.factories import AdminAssignmentFactory, AdminRoleFactory, UserFactory


class AdminReferralCommissionRateApiTests(TestCase):
    """Phase 24 Slice 1: admin sets the referral commission percentage."""

    def setUp(self):
        self.admin_user = UserFactory(email="referral-rate-admin@example.com")
        role = AdminRoleFactory(code=AdminRoleCode.SUPER_ADMIN)
        AdminAssignmentFactory(user=self.admin_user, role=role)
        self.non_admin = UserFactory(email="referral-rate-non-admin@example.com")

    def _login(self):
        self.client.force_login(self.admin_user)

    # -- GET admin/commission-rate/ -----------------------------------------

    def test_get_requires_admin_role(self):
        token = Token.objects.create(user=self.non_admin)
        response = self.client.get(
            reverse("admin-referral-commission-rate"), HTTP_AUTHORIZATION=f"Token {token.key}"
        )
        self.assertEqual(response.status_code, 403)

    def test_get_rejects_token_authentication(self):
        token = Token.objects.create(user=self.admin_user)
        response = self.client.get(
            reverse("admin-referral-commission-rate"), HTTP_AUTHORIZATION=f"Token {token.key}"
        )
        self.assertEqual(response.status_code, 403)

    def test_get_returns_a_zero_default_when_no_rate_has_ever_been_set(self):
        self._login()
        response = self.client.get(reverse("admin-referral-commission-rate"))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIsNone(payload["id"])
        self.assertEqual(payload["percent"], "0.00")

    def test_get_returns_the_current_rate(self):
        ReferralCommissionRate.objects.create(percent=Decimal("15.00"), updated_by=self.admin_user)
        self._login()
        response = self.client.get(reverse("admin-referral-commission-rate"))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["percent"], "15.00")
        self.assertEqual(payload["updated_by_email"], "referral-rate-admin@example.com")

    # -- POST admin/commission-rate/ ----------------------------------------

    def test_set_requires_admin_role(self):
        token = Token.objects.create(user=self.non_admin)
        response = self.client.post(
            reverse("admin-referral-commission-rate"),
            {"percent": "15.00"},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Token {token.key}",
        )
        self.assertEqual(response.status_code, 403)

    def test_set_rejects_a_negative_percent(self):
        self._login()
        response = self.client.post(
            reverse("admin-referral-commission-rate"),
            {"percent": "-5.00"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(ReferralCommissionRate.objects.exists())

    def test_set_rejects_a_percent_above_100(self):
        self._login()
        response = self.client.post(
            reverse("admin-referral-commission-rate"),
            {"percent": "150.00"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(ReferralCommissionRate.objects.exists())

    def test_set_creates_the_first_rate(self):
        self._login()
        response = self.client.post(
            reverse("admin-referral-commission-rate"),
            {"percent": "15.00"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["percent"], "15.00")
        self.assertEqual(payload["updated_by_email"], "referral-rate-admin@example.com")

        rate = ReferralCommissionRate.objects.get()
        history = rate.history.get()
        self.assertIsNone(history.from_percent)
        self.assertEqual(history.to_percent, Decimal("15.00"))
        self.assertEqual(history.actor, self.admin_user)

    def test_set_updates_the_same_row_and_records_history(self):
        existing = ReferralCommissionRate.objects.create(percent=Decimal("15.00"))
        self._login()
        response = self.client.post(
            reverse("admin-referral-commission-rate"),
            {"percent": "20.00"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)

        self.assertEqual(ReferralCommissionRate.objects.count(), 1)
        existing.refresh_from_db()
        self.assertEqual(existing.percent, Decimal("20.00"))

        history = existing.history.get()
        self.assertEqual(history.from_percent, Decimal("15.00"))
        self.assertEqual(history.to_percent, Decimal("20.00"))
        self.assertEqual(history.actor, self.admin_user)
