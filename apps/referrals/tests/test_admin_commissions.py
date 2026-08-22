from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.authtoken.models import Token

from apps.referrals.models import ReferralCommission
from apps.users.choices import AdminRoleCode
from apps.users.tests.factories import AdminAssignmentFactory, AdminRoleFactory, UserFactory


class AdminReferralCommissionApiTests(TestCase):
    """Phase 24 Slice 3: admin reviews the commission ledger and marks
    month-end payouts."""

    def setUp(self):
        self.admin_user = UserFactory(email="commission-list-admin@example.com")
        role = AdminRoleFactory(code=AdminRoleCode.SUPER_ADMIN)
        AdminAssignmentFactory(user=self.admin_user, role=role)
        self.non_admin = UserFactory(email="commission-list-non-admin@example.com")
        self.referrer = UserFactory(email="ledger-referrer@example.com")
        self.referred_user = UserFactory(email="ledger-referred@example.com")

    def _login(self):
        self.client.force_login(self.admin_user)

    def _create_commission(self, **overrides):
        defaults = dict(
            referrer=self.referrer,
            referred_user=self.referred_user,
            amount=45000,
            currency="NGN",
            rate_percent=Decimal("15.00"),
            billing_period_end=timezone.now(),
            provider_transaction_id="txn-ledger-1",
        )
        defaults.update(overrides)
        from apps.subscriptions.models import Subscription, SubscriptionStatus

        subscription = Subscription.objects.filter(user=self.referred_user).first()
        if subscription is None:
            subscription = Subscription.objects.create(
                user=self.referred_user,
                amount=300000,
                payment_reference=f"SUB-LEDGER-{defaults['provider_transaction_id']}",
                status=SubscriptionStatus.ACTIVE,
            )
        defaults["subscription"] = subscription
        return ReferralCommission.objects.create(**defaults)

    # -- GET admin/commissions/ ---------------------------------------------

    def test_list_requires_admin_role(self):
        token = Token.objects.create(user=self.non_admin)
        response = self.client.get(
            reverse("admin-referral-commission-list"), HTTP_AUTHORIZATION=f"Token {token.key}"
        )
        self.assertEqual(response.status_code, 403)

    def test_list_rejects_token_authentication(self):
        token = Token.objects.create(user=self.admin_user)
        response = self.client.get(
            reverse("admin-referral-commission-list"), HTTP_AUTHORIZATION=f"Token {token.key}"
        )
        self.assertEqual(response.status_code, 403)

    def test_list_returns_empty_with_zero_totals_when_no_commissions_exist(self):
        self._login()
        response = self.client.get(reverse("admin-referral-commission-list"))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["results"], [])
        self.assertEqual(payload["totals"], [])

    def test_list_returns_rows_with_emails_and_totals_by_currency(self):
        self._create_commission(provider_transaction_id="txn-ledger-a", amount=45000, currency="NGN")
        self._create_commission(provider_transaction_id="txn-ledger-b", amount=5000, currency="USD")
        self._login()
        response = self.client.get(reverse("admin-referral-commission-list"))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["results"]), 2)
        row = payload["results"][0]
        self.assertEqual(row["referrer_email"], "ledger-referrer@example.com")
        self.assertEqual(row["referred_user_email"], "ledger-referred@example.com")
        totals = {t["currency"]: t["amount"] for t in payload["totals"]}
        self.assertEqual(totals, {"NGN": 45000, "USD": 5000})

    def test_list_filters_by_is_paid(self):
        self._create_commission(provider_transaction_id="txn-unpaid", is_paid=False)
        self._create_commission(provider_transaction_id="txn-paid", is_paid=True, paid_at=timezone.now())
        self._login()
        response = self.client.get(reverse("admin-referral-commission-list"), {"is_paid": "true"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["results"]), 1)
        self.assertTrue(payload["results"][0]["is_paid"])

    def test_list_filters_by_referrer_or_referred_email_search(self):
        other_referrer = UserFactory(email="someone-else@example.com")
        self._create_commission(provider_transaction_id="txn-match")
        self._create_commission(
            provider_transaction_id="txn-no-match", referrer=other_referrer
        )
        self._login()
        response = self.client.get(reverse("admin-referral-commission-list"), {"q": "ledger-referrer"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["results"]), 1)
        self.assertEqual(payload["results"][0]["referrer_email"], "ledger-referrer@example.com")

    # -- POST admin/commissions/<id>/mark-paid/ ------------------------------

    def test_mark_paid_requires_admin_role(self):
        commission = self._create_commission()
        token = Token.objects.create(user=self.non_admin)
        response = self.client.post(
            reverse("admin-referral-commission-mark-paid", args=[commission.id]),
            HTTP_AUTHORIZATION=f"Token {token.key}",
        )
        self.assertEqual(response.status_code, 403)

    def test_mark_paid_returns_404_for_an_unknown_commission(self):
        self._login()
        response = self.client.post(reverse("admin-referral-commission-mark-paid", args=[999999]))
        self.assertEqual(response.status_code, 404)

    def test_mark_paid_succeeds_and_records_the_actor(self):
        commission = self._create_commission()
        self._login()
        response = self.client.post(reverse("admin-referral-commission-mark-paid", args=[commission.id]))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["is_paid"])
        self.assertEqual(payload["paid_by_email"], "commission-list-admin@example.com")
        self.assertIsNotNone(payload["paid_at"])

        commission.refresh_from_db()
        self.assertTrue(commission.is_paid)
        self.assertEqual(commission.paid_by, self.admin_user)

    def test_mark_paid_twice_fails_on_the_second_attempt(self):
        commission = self._create_commission()
        self._login()
        first = self.client.post(reverse("admin-referral-commission-mark-paid", args=[commission.id]))
        self.assertEqual(first.status_code, 200)

        second = self.client.post(reverse("admin-referral-commission-mark-paid", args=[commission.id]))
        self.assertEqual(second.status_code, 400)
