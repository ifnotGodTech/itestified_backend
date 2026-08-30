from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.authtoken.models import Token

from apps.referrals.models import ReferralCommission
from apps.referrals.selectors import format_referred_user_label
from apps.subscriptions.models import Subscription, SubscriptionStatus
from apps.users.tests.factories import ProfileFactory, UserFactory


class FormatReferredUserLabelTests(TestCase):
    def test_first_name_and_last_initial(self):
        self.assertEqual(format_referred_user_label("David Okafor"), "David O.")

    def test_middle_names_ignored(self):
        self.assertEqual(format_referred_user_label("Mary Jane Adeyemi"), "Mary A.")

    def test_single_name_used_as_is(self):
        self.assertEqual(format_referred_user_label("Praise"), "Praise")

    def test_blank_name_falls_back(self):
        self.assertEqual(format_referred_user_label(""), "A referral")
        self.assertEqual(format_referred_user_label("   "), "A referral")


class MyReferralCommissionsApiTests(TestCase):
    """Phase 24 Slice 7: a referrer views their own earnings."""

    def setUp(self):
        self.referrer = UserFactory(email="earnings-referrer@example.com")
        ProfileFactory(user=self.referrer, full_name="David Okafor")
        self.token = Token.objects.create(user=self.referrer)
        self.referred_user = UserFactory(email="earnings-referred@example.com")
        ProfileFactory(user=self.referred_user, full_name="Grace Nwosu")
        self.other_referrer = UserFactory(email="earnings-other-referrer@example.com")

    def _auth_headers(self):
        return {"HTTP_AUTHORIZATION": f"Token {self.token.key}"}

    def _make_premium(self, user=None):
        user = user or self.referrer
        Subscription.objects.create(
            user=user,
            amount=300000,
            payment_reference=f"SUB-EARNINGS-{user.id}",
            status=SubscriptionStatus.ACTIVE,
        )

    def _create_commission(self, **overrides):
        defaults = dict(
            referrer=self.referrer,
            referred_user=self.referred_user,
            amount=1800,
            currency="USD",
            rate_percent=Decimal("15.00"),
            billing_period_end=timezone.now(),
            provider_transaction_id="txn-earnings-1",
        )
        defaults.update(overrides)

        subscription = Subscription.objects.filter(user=defaults["referred_user"]).first()
        if subscription is None:
            subscription = Subscription.objects.create(
                user=defaults["referred_user"],
                amount=12000,
                payment_reference=f"SUB-EARNINGS-REFERRED-{defaults['provider_transaction_id']}",
                status=SubscriptionStatus.ACTIVE,
            )
        defaults["subscription"] = subscription
        return ReferralCommission.objects.create(**defaults)

    def test_requires_authentication(self):
        response = self.client.get(reverse("referral-my-commissions"))
        self.assertEqual(response.status_code, 401)

    def test_requires_active_premium(self):
        response = self.client.get(reverse("referral-my-commissions"), **self._auth_headers())
        self.assertEqual(response.status_code, 403)

    def test_returns_empty_list_and_zero_totals_when_no_commissions_exist(self):
        self._make_premium()
        response = self.client.get(reverse("referral-my-commissions"), **self._auth_headers())
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["results"], [])
        self.assertEqual(payload["paid_totals"], [])
        self.assertEqual(payload["pending_totals"], [])

    def test_returns_rows_with_referred_user_label_not_email(self):
        self._make_premium()
        self._create_commission(provider_transaction_id="txn-earnings-a")
        response = self.client.get(reverse("referral-my-commissions"), **self._auth_headers())
        self.assertEqual(response.status_code, 200)
        row = response.json()["results"][0]
        self.assertEqual(row["referred_user_label"], "Grace N.")
        self.assertNotIn("email", row)
        self.assertNotIn(self.referred_user.email, str(row))

    def test_paid_and_pending_totals_are_split_by_currency(self):
        self._make_premium()
        self._create_commission(
            provider_transaction_id="txn-earnings-paid-usd", amount=1800, currency="USD", is_paid=True
        )
        self._create_commission(
            provider_transaction_id="txn-earnings-pending-usd", amount=1200, currency="USD", is_paid=False
        )
        self._create_commission(
            provider_transaction_id="txn-earnings-pending-ngn", amount=45000, currency="NGN", is_paid=False
        )
        response = self.client.get(reverse("referral-my-commissions"), **self._auth_headers())
        payload = response.json()
        self.assertEqual(payload["paid_totals"], [{"currency": "USD", "amount": 1800}])
        self.assertEqual(
            sorted(payload["pending_totals"], key=lambda row: row["currency"]),
            [{"currency": "NGN", "amount": 45000}, {"currency": "USD", "amount": 1200}],
        )

    def test_never_returns_another_referrers_commissions(self):
        self._make_premium()
        self._make_premium(user=self.other_referrer)
        self._create_commission(
            referrer=self.other_referrer, provider_transaction_id="txn-earnings-other-referrer"
        )
        response = self.client.get(reverse("referral-my-commissions"), **self._auth_headers())
        payload = response.json()
        self.assertEqual(payload["results"], [])
        self.assertEqual(payload["paid_totals"], [])

    def test_rejects_session_authentication(self):
        self._make_premium()
        self.client.force_login(self.referrer)
        response = self.client.get(reverse("referral-my-commissions"))
        self.assertEqual(response.status_code, 401)
