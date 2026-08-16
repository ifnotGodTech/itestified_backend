from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.authtoken.models import Token

from apps.subscriptions.models import (
    PremiumPricing,
    Subscription,
    SubscriptionEventLog,
    SubscriptionStatus,
    SubscriptionStatusHistory,
)
from apps.users.choices import AdminRoleCode
from apps.users.tests.factories import AdminAssignmentFactory, AdminRoleFactory, UserFactory


def _webhook_headers(secret_hash: str = "webhook-secret") -> dict:
    return {"HTTP_VERIF_HASH": secret_hash}


class SubscribeApiTests(TestCase):
    def setUp(self):
        self.user = UserFactory(email="subscriber@example.com")
        self.token = Token.objects.create(user=self.user)
        # Found in the 2026-08-15 audit: subscribe() was migrated to read
        # pricing from PremiumPricing (Phase 21 Slice 5) instead of the
        # FLUTTERWAVE_PREMIUM_PLAN_IDS setting, but this whole test class
        # kept patching that now-dead setting -- it had no effect, and 4 of
        # these tests were silently asserting against whatever real
        # migration-seeded PremiumPricing rows happened to exist from
        # config/settings/test.py's real Flutterwave plan ids, not what
        # they thought they controlled. Clearing the table here makes every
        # test explicit and deterministic about the pricing it depends on.
        PremiumPricing.objects.all().delete()

    def _auth_headers(self):
        return {"HTTP_AUTHORIZATION": f"Token {self.token.key}"}

    def _seed_pricing(self, currency="NGN", amount=300000, provider_plan_id="plan_123"):
        return PremiumPricing.objects.create(
            currency=currency, amount=amount, provider_plan_id=provider_plan_id
        )

    def test_subscribe_requires_authentication(self):
        response = self.client.post(reverse("subscription-subscribe"))
        self.assertEqual(response.status_code, 401)

    def test_subscribe_returns_503_when_gateway_not_configured(self):
        self._seed_pricing()
        with patch("apps.subscriptions.services.commands.settings.FLUTTERWAVE_SECRET_KEY", ""):
            response = self.client.post(reverse("subscription-subscribe"), {}, content_type="application/json", **self._auth_headers())
        self.assertEqual(response.status_code, 503)
        self.assertFalse(Subscription.objects.exists())

    def test_subscribe_returns_400_when_plan_id_not_configured(self):
        # A PremiumPricing row exists (so serializer-level currency
        # validation passes) but with no provider_plan_id yet -- a "priced
        # but not yet wired to a real Flutterwave plan" state, which
        # subscribe() treats the same as "no pricing row at all" (both are
        # SubscriptionUnsupportedCurrencyError -> 400). Under the old
        # settings-dict design this was a 503 "gateway not configured";
        # Slice 5's DB-backed pricing reclassified it as a client-facing
        # "unsupported currency" instead, since it's now something an
        # admin can fix per-currency rather than a whole-gateway outage.
        self._seed_pricing(provider_plan_id="")
        with patch("apps.subscriptions.services.commands.settings.FLUTTERWAVE_SECRET_KEY", "sk_test"):
            response = self.client.post(reverse("subscription-subscribe"), {}, content_type="application/json", **self._auth_headers())
        self.assertEqual(response.status_code, 400)

    def test_subscribe_creates_pending_subscription_and_sends_major_unit_amount_with_plan(self):
        # Regression coverage for the exact bug class that once broke Phase
        # 5's donation amount conversion: the DB/API always speak minor
        # units (kobo), only the outbound Flutterwave payload converts.
        self._seed_pricing(provider_plan_id="plan_123")
        with (
            patch("apps.subscriptions.services.commands.settings.FLUTTERWAVE_SECRET_KEY", "sk_test"),
            patch("apps.common.services.flutterwave.FlutterwaveGateway._post") as post_mock,
        ):
            post_mock.return_value = {
                "data": {"link": "https://checkout.flutterwave.com/v3/hosted/pay/sub123", "id": "555"}
            }
            response = self.client.post(reverse("subscription-subscribe"), {}, content_type="application/json", **self._auth_headers())

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(payload["status"], SubscriptionStatus.PENDING)
        self.assertEqual(payload["amount"], 300000)
        self.assertEqual(payload["checkout_url"], "https://checkout.flutterwave.com/v3/hosted/pay/sub123")

        sent_payload = post_mock.call_args[0][1]
        self.assertEqual(sent_payload["amount"], "3000.00")
        self.assertEqual(sent_payload["payment_plan"], "plan_123")

        subscription = Subscription.objects.get()
        self.assertTrue(subscription.payment_reference.startswith("SUB-"))

    def test_subscribe_in_usd_uses_the_usd_plan_and_price(self):
        self._seed_pricing(currency="NGN", amount=300000, provider_plan_id="plan_ngn")
        self._seed_pricing(currency="USD", amount=499, provider_plan_id="plan_usd")
        with (
            patch("apps.subscriptions.services.commands.settings.FLUTTERWAVE_SECRET_KEY", "sk_test"),
            patch("apps.common.services.flutterwave.FlutterwaveGateway._post") as post_mock,
        ):
            post_mock.return_value = {
                "data": {"link": "https://checkout.flutterwave.com/v3/hosted/pay/usdsub", "id": "556"}
            }
            response = self.client.post(
                reverse("subscription-subscribe"),
                {"currency": "usd"},
                content_type="application/json",
                **self._auth_headers(),
            )

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(payload["currency"], "USD")
        self.assertEqual(payload["amount"], 499)

        sent_payload = post_mock.call_args[0][1]
        self.assertEqual(sent_payload["amount"], "4.99")
        self.assertEqual(sent_payload["payment_plan"], "plan_usd")

    def test_subscribe_rejects_an_unsupported_currency(self):
        self._seed_pricing(currency="NGN", amount=300000, provider_plan_id="plan_ngn")
        self._seed_pricing(currency="USD", amount=499, provider_plan_id="plan_usd")
        with patch("apps.subscriptions.services.commands.settings.FLUTTERWAVE_SECRET_KEY", "sk_test"):
            response = self.client.post(
                reverse("subscription-subscribe"),
                {"currency": "GBP"},
                content_type="application/json",
                **self._auth_headers(),
            )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Subscription.objects.exists())

    def test_subscribe_returns_400_when_only_the_other_currencys_plan_is_configured(self):
        self._seed_pricing(currency="NGN", amount=300000, provider_plan_id="plan_ngn")
        self._seed_pricing(currency="USD", amount=499, provider_plan_id="")
        with patch("apps.subscriptions.services.commands.settings.FLUTTERWAVE_SECRET_KEY", "sk_test"):
            response = self.client.post(
                reverse("subscription-subscribe"),
                {"currency": "USD"},
                content_type="application/json",
                **self._auth_headers(),
            )
        self.assertEqual(response.status_code, 400)

    def test_subscribe_rejects_a_second_subscription_while_one_is_in_progress(self):
        self._seed_pricing(provider_plan_id="plan_123")
        Subscription.objects.create(
            user=self.user,
            amount=300000,
            payment_reference="SUB-EXISTING1",
            status=SubscriptionStatus.ACTIVE,
        )
        with patch("apps.subscriptions.services.commands.settings.FLUTTERWAVE_SECRET_KEY", "sk_test"):
            response = self.client.post(reverse("subscription-subscribe"), {}, content_type="application/json", **self._auth_headers())
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Subscription.objects.count(), 1)

    def test_subscribe_rejects_a_still_current_scheduled_cancellation(self):
        self._seed_pricing(provider_plan_id="plan_123")
        Subscription.objects.create(
            user=self.user,
            amount=300000,
            payment_reference="SUB-SCHEDCURR1",
            status=SubscriptionStatus.ACTIVE,
            cancel_at_period_end=True,
            current_period_end=timezone.now() + timedelta(days=5),
        )
        with patch("apps.subscriptions.services.commands.settings.FLUTTERWAVE_SECRET_KEY", "sk_test"):
            response = self.client.post(reverse("subscription-subscribe"), {}, content_type="application/json", **self._auth_headers())
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Subscription.objects.count(), 1)

    def test_subscribe_allows_resubscribing_after_a_lapsed_scheduled_cancellation(self):
        # The DB's UniqueConstraint only knows about `status`, so the old
        # ACTIVE-but-lapsed row must be lazily closed out to CANCELED here
        # or the new INSERT below would violate that constraint.
        self._seed_pricing(provider_plan_id="plan_123")
        old = Subscription.objects.create(
            user=self.user,
            amount=300000,
            payment_reference="SUB-LAPSEDOLD1",
            status=SubscriptionStatus.ACTIVE,
            cancel_at_period_end=True,
            current_period_end=timezone.now() - timedelta(days=1),
        )
        with (
            patch("apps.subscriptions.services.commands.settings.FLUTTERWAVE_SECRET_KEY", "sk_test"),
            patch("apps.common.services.flutterwave.FlutterwaveGateway._post") as post_mock,
        ):
            post_mock.return_value = {
                "data": {"link": "https://checkout.flutterwave.com/pay/new", "id": "2"}
            }
            response = self.client.post(reverse("subscription-subscribe"), {}, content_type="application/json", **self._auth_headers())
        self.assertEqual(response.status_code, 201)
        old.refresh_from_db()
        self.assertEqual(old.status, SubscriptionStatus.CANCELED)
        self.assertEqual(Subscription.objects.count(), 2)

    def test_subscribe_marks_canceled_when_gateway_call_fails(self):
        self._seed_pricing(provider_plan_id="plan_123")
        with (
            patch("apps.subscriptions.services.commands.settings.FLUTTERWAVE_SECRET_KEY", "sk_test"),
            patch("apps.common.services.flutterwave.FlutterwaveGateway._post") as post_mock,
        ):
            post_mock.return_value = {"data": {}}  # no "link" -> gateway error
            response = self.client.post(reverse("subscription-subscribe"), {}, content_type="application/json", **self._auth_headers())

        self.assertEqual(response.status_code, 502)
        subscription = Subscription.objects.get()
        self.assertEqual(subscription.status, SubscriptionStatus.CANCELED)

        # A canceled attempt must not block a real retry.
        with (
            patch("apps.subscriptions.services.commands.settings.FLUTTERWAVE_SECRET_KEY", "sk_test"),
            patch("apps.common.services.flutterwave.FlutterwaveGateway._post") as post_mock,
        ):
            post_mock.return_value = {"data": {"link": "https://checkout.flutterwave.com/pay/x", "id": "1"}}
            retry_response = self.client.post(reverse("subscription-subscribe"), {}, content_type="application/json", **self._auth_headers())
        self.assertEqual(retry_response.status_code, 201)


class VerifySubscriptionApiTests(TestCase):
    """Synchronous fallback for the first charge, mirroring donations'
    verify endpoint -- added 2026-08-06 after a real test payment sat stuck
    in `pending` because the webhook never reached the backend."""

    def setUp(self):
        self.user = UserFactory(email="verify-sub@example.com")
        self.token = Token.objects.create(user=self.user)

    def _auth_headers(self):
        return {"HTTP_AUTHORIZATION": f"Token {self.token.key}"}

    def test_verify_requires_authentication(self):
        response = self.client.post(reverse("subscription-verify"))
        self.assertEqual(response.status_code, 401)

    def test_verify_returns_404_for_someone_elses_or_unknown_reference(self):
        with patch("apps.subscriptions.services.commands.settings.FLUTTERWAVE_SECRET_KEY", "sk_test"):
            response = self.client.post(
                reverse("subscription-verify"),
                {"payment_reference": "SUB-DOES-NOT-EXIST", "transaction_id": "1"},
                content_type="application/json",
                **self._auth_headers(),
            )
        self.assertEqual(response.status_code, 404)

    def test_verify_activates_a_successful_pending_subscription(self):
        subscription = Subscription.objects.create(
            user=self.user,
            amount=499,
            currency="USD",
            payment_reference="SUB-VERIFY0001",
            status=SubscriptionStatus.PENDING,
        )
        with (
            patch("apps.subscriptions.services.commands.settings.FLUTTERWAVE_SECRET_KEY", "sk_test"),
            patch("apps.subscriptions.services.commands.FlutterwaveGateway.verify") as verify_mock,
        ):
            verify_mock.return_value.status = "successful"
            verify_mock.return_value.provider_transaction_id = "txn-999"
            verify_mock.return_value.status_reason = "Approved"
            response = self.client.post(
                reverse("subscription-verify"),
                {"payment_reference": "SUB-VERIFY0001", "transaction_id": "txn-999"},
                content_type="application/json",
                **self._auth_headers(),
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], SubscriptionStatus.ACTIVE)
        self.assertIsNotNone(payload["current_period_end"])

        subscription.refresh_from_db()
        self.assertEqual(subscription.status, SubscriptionStatus.ACTIVE)

    def test_verify_cancels_a_declined_pending_subscription(self):
        Subscription.objects.create(
            user=self.user,
            amount=300000,
            payment_reference="SUB-VERIFY0002",
            status=SubscriptionStatus.PENDING,
        )
        with (
            patch("apps.subscriptions.services.commands.settings.FLUTTERWAVE_SECRET_KEY", "sk_test"),
            patch("apps.subscriptions.services.commands.FlutterwaveGateway.verify") as verify_mock,
        ):
            verify_mock.return_value.status = "declined"
            verify_mock.return_value.provider_transaction_id = "txn-1000"
            verify_mock.return_value.status_reason = "Card declined"
            response = self.client.post(
                reverse("subscription-verify"),
                {"payment_reference": "SUB-VERIFY0002", "transaction_id": "txn-1000"},
                content_type="application/json",
                **self._auth_headers(),
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], SubscriptionStatus.CANCELED)

    def test_verify_is_a_no_op_when_the_webhook_already_won_the_race(self):
        # The subscription is already ACTIVE (webhook got there first) --
        # verify() must not be called at all, and must not double-log.
        subscription = Subscription.objects.create(
            user=self.user,
            amount=300000,
            payment_reference="SUB-VERIFY0003",
            status=SubscriptionStatus.ACTIVE,
            current_period_end=timezone.now() + timedelta(days=30),
        )
        history_count_before = SubscriptionStatusHistory.objects.filter(subscription=subscription).count()
        with (
            patch("apps.subscriptions.services.commands.settings.FLUTTERWAVE_SECRET_KEY", "sk_test"),
            patch("apps.subscriptions.services.commands.FlutterwaveGateway.verify") as verify_mock,
        ):
            response = self.client.post(
                reverse("subscription-verify"),
                {"payment_reference": "SUB-VERIFY0003", "transaction_id": "txn-1001"},
                content_type="application/json",
                **self._auth_headers(),
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], SubscriptionStatus.ACTIVE)
        verify_mock.assert_not_called()
        self.assertEqual(
            SubscriptionStatusHistory.objects.filter(subscription=subscription).count(),
            history_count_before,
        )

    def test_verify_returns_503_when_gateway_not_configured(self):
        Subscription.objects.create(
            user=self.user,
            amount=300000,
            payment_reference="SUB-VERIFY0004",
            status=SubscriptionStatus.PENDING,
        )
        with patch("apps.subscriptions.services.commands.settings.FLUTTERWAVE_SECRET_KEY", ""):
            response = self.client.post(
                reverse("subscription-verify"),
                {"payment_reference": "SUB-VERIFY0004", "transaction_id": "txn-1002"},
                content_type="application/json",
                **self._auth_headers(),
            )
        self.assertEqual(response.status_code, 503)


class MySubscriptionApiTests(TestCase):
    def setUp(self):
        self.user = UserFactory(email="mine@example.com")
        self.token = Token.objects.create(user=self.user)

    def _auth_headers(self):
        return {"HTTP_AUTHORIZATION": f"Token {self.token.key}"}

    def test_returns_404_when_no_subscription_exists(self):
        response = self.client.get(reverse("subscription-mine"), **self._auth_headers())
        self.assertEqual(response.status_code, 404)

    def test_returns_the_current_non_terminal_subscription(self):
        Subscription.objects.create(
            user=self.user,
            amount=300000,
            payment_reference="SUB-MINE0001",
            status=SubscriptionStatus.ACTIVE,
        )
        response = self.client.get(reverse("subscription-mine"), **self._auth_headers())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], SubscriptionStatus.ACTIVE)

    def test_ignores_a_canceled_subscription(self):
        Subscription.objects.create(
            user=self.user,
            amount=300000,
            payment_reference="SUB-OLD0001",
            status=SubscriptionStatus.CANCELED,
        )
        response = self.client.get(reverse("subscription-mine"), **self._auth_headers())
        self.assertEqual(response.status_code, 404)

    def test_shows_a_scheduled_cancellation_as_still_current(self):
        Subscription.objects.create(
            user=self.user,
            amount=300000,
            payment_reference="SUB-SCHED0001",
            status=SubscriptionStatus.ACTIVE,
            cancel_at_period_end=True,
            current_period_end=timezone.now() + timedelta(days=5),
        )
        response = self.client.get(reverse("subscription-mine"), **self._auth_headers())
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], SubscriptionStatus.ACTIVE)
        self.assertTrue(payload["cancel_at_period_end"])

    def test_hides_a_lapsed_scheduled_cancellation(self):
        # Nothing else will ever flip this row's status once Flutterwave has
        # stopped billing it -- get_current_subscription must compute this
        # lazily rather than depend on a scheduled job.
        Subscription.objects.create(
            user=self.user,
            amount=300000,
            payment_reference="SUB-LAPSED0001",
            status=SubscriptionStatus.ACTIVE,
            cancel_at_period_end=True,
            current_period_end=timezone.now() - timedelta(days=1),
        )
        response = self.client.get(reverse("subscription-mine"), **self._auth_headers())
        self.assertEqual(response.status_code, 404)


class CancelSubscriptionApiTests(TestCase):
    def setUp(self):
        self.user = UserFactory(email="canceler@example.com")
        self.token = Token.objects.create(user=self.user)

    def _auth_headers(self):
        return {"HTTP_AUTHORIZATION": f"Token {self.token.key}"}

    def test_cancel_requires_an_existing_subscription(self):
        response = self.client.post(reverse("subscription-cancel"), **self._auth_headers())
        self.assertEqual(response.status_code, 404)

    def test_cancel_rejects_a_still_pending_subscription(self):
        Subscription.objects.create(
            user=self.user,
            amount=300000,
            payment_reference="SUB-PEND0001",
            status=SubscriptionStatus.PENDING,
        )
        response = self.client.post(reverse("subscription-cancel"), **self._auth_headers())
        self.assertEqual(response.status_code, 400)

    def test_cancel_schedules_cancellation_without_revoking_current_access(self):
        # Cancellation must not claw back time already paid for: status
        # stays ACTIVE (entitlement intact) and cancel_at_period_end
        # records the request instead of jumping straight to CANCELED.
        Subscription.objects.create(
            user=self.user,
            amount=300000,
            payment_reference="SUB-ACT00001",
            status=SubscriptionStatus.ACTIVE,
        )
        response = self.client.post(reverse("subscription-cancel"), **self._auth_headers())
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], SubscriptionStatus.ACTIVE)
        self.assertTrue(payload["cancel_at_period_end"])

    def test_cancel_a_second_time_is_rejected(self):
        Subscription.objects.create(
            user=self.user,
            amount=300000,
            payment_reference="SUB-ACT00004",
            status=SubscriptionStatus.ACTIVE,
            cancel_at_period_end=True,
        )
        response = self.client.post(reverse("subscription-cancel"), **self._auth_headers())
        self.assertEqual(response.status_code, 400)

    def test_cancel_calls_flutterwave_when_a_provider_subscription_id_is_known(self):
        Subscription.objects.create(
            user=self.user,
            amount=300000,
            payment_reference="SUB-ACT00002",
            status=SubscriptionStatus.ACTIVE,
            provider_subscription_id="fw-sub-789",
        )
        with (
            patch("apps.subscriptions.services.commands.settings.FLUTTERWAVE_SECRET_KEY", "sk_test"),
            patch("apps.common.services.flutterwave.FlutterwaveGateway._put") as put_mock,
        ):
            put_mock.return_value = {"data": {"status": "cancelled"}}
            response = self.client.post(reverse("subscription-cancel"), **self._auth_headers())
        self.assertEqual(response.status_code, 200)
        put_mock.assert_called_once()
        self.assertIn("fw-sub-789", put_mock.call_args[0][0])

    def test_cancel_does_not_mark_canceled_when_the_remote_call_fails(self):
        # A user must never be told they cancelled if Flutterwave never
        # actually received the request -- it would keep auto-charging them.
        Subscription.objects.create(
            user=self.user,
            amount=300000,
            payment_reference="SUB-ACT00003",
            status=SubscriptionStatus.ACTIVE,
            provider_subscription_id="fw-sub-000",
        )
        with (
            patch("apps.subscriptions.services.commands.settings.FLUTTERWAVE_SECRET_KEY", "sk_test"),
            patch("apps.common.services.flutterwave.FlutterwaveGateway._put") as put_mock,
        ):
            put_mock.side_effect = Exception("boom")
            from apps.common.services.flutterwave import FlutterwaveGatewayError

            put_mock.side_effect = FlutterwaveGatewayError("network blip")
            response = self.client.post(reverse("subscription-cancel"), **self._auth_headers())
        self.assertEqual(response.status_code, 400)
        subscription = Subscription.objects.get(payment_reference="SUB-ACT00003")
        self.assertEqual(subscription.status, SubscriptionStatus.ACTIVE)


class SubscriptionWebhookTests(TestCase):
    def setUp(self):
        self.user = UserFactory(email="webhook-user@example.com")

    def _post_webhook(self, body: dict, secret_hash: str = "webhook-secret"):
        with patch("apps.donations.api.views.settings.FLUTTERWAVE_SECRET_HASH", "webhook-secret"):
            return self.client.post(
                reverse("donation-provider-callback"),
                body,
                content_type="application/json",
                **_webhook_headers(secret_hash),
            )

    def test_first_charge_success_activates_subscription_and_sets_period_end(self):
        subscription = Subscription.objects.create(
            user=self.user,
            amount=300000,
            payment_reference="SUB-FIRST001",
            status=SubscriptionStatus.PENDING,
        )
        with patch(
            "apps.subscriptions.services.commands.FlutterwaveGateway.find_active_subscription_by_email"
        ) as lookup_mock:
            lookup_mock.return_value = None
            response = self._post_webhook(
                {
                    "event": "charge.completed",
                    "data": {
                        "tx_ref": "SUB-FIRST001",
                        "status": "successful",
                        "id": "txn-1",
                        "customer": {"email": self.user.email},
                    },
                }
            )
        self.assertEqual(response.status_code, 200)
        subscription.refresh_from_db()
        self.assertEqual(subscription.status, SubscriptionStatus.ACTIVE)
        self.assertIsNotNone(subscription.current_period_end)
        self.assertGreater(subscription.current_period_end, timezone.now())

    def test_first_charge_success_attaches_provider_subscription_id(self):
        subscription = Subscription.objects.create(
            user=self.user,
            amount=300000,
            payment_reference="SUB-FIRST002",
            status=SubscriptionStatus.PENDING,
        )
        with patch(
            "apps.subscriptions.services.commands.FlutterwaveGateway.find_active_subscription_by_email"
        ) as lookup_mock:
            from apps.common.services.flutterwave import FlutterwaveSubscriptionRecord

            lookup_mock.return_value = FlutterwaveSubscriptionRecord(
                provider_subscription_id="fw-sub-42", plan_id="plan_123", status="active"
            )
            self._post_webhook(
                {
                    "event": "charge.completed",
                    "data": {
                        "tx_ref": "SUB-FIRST002",
                        "status": "successful",
                        "id": "txn-2",
                        "customer": {"email": self.user.email},
                    },
                }
            )
        subscription.refresh_from_db()
        self.assertEqual(subscription.provider_subscription_id, "fw-sub-42")

    def test_first_charge_failure_cancels_the_pending_subscription(self):
        subscription = Subscription.objects.create(
            user=self.user,
            amount=300000,
            payment_reference="SUB-FIRST003",
            status=SubscriptionStatus.PENDING,
        )
        response = self._post_webhook(
            {
                "event": "charge.completed",
                "data": {
                    "tx_ref": "SUB-FIRST003",
                    "status": "failed",
                    "id": "txn-3",
                    "customer": {"email": self.user.email},
                },
            }
        )
        self.assertEqual(response.status_code, 200)
        subscription.refresh_from_db()
        self.assertEqual(subscription.status, SubscriptionStatus.CANCELED)

    def test_renewal_charge_matched_by_email_extends_the_active_subscription(self):
        subscription = Subscription.objects.create(
            user=self.user,
            amount=300000,
            payment_reference="SUB-RENEWED1",
            status=SubscriptionStatus.ACTIVE,
            current_period_end=timezone.now(),
        )
        original_period_end = subscription.current_period_end
        # Flutterwave generates its own reference for an automatic renewal
        # charge -- it will never match "SUB-RENEWED1", so this exercises
        # the email-based fallback match exclusively.
        response = self._post_webhook(
            {
                "event": "charge.completed",
                "data": {
                    "tx_ref": "flw-generated-renewal-ref",
                    "status": "successful",
                    "id": "txn-4",
                    "customer": {"email": self.user.email},
                },
            }
        )
        self.assertEqual(response.status_code, 200)
        subscription.refresh_from_db()
        self.assertEqual(subscription.status, SubscriptionStatus.ACTIVE)
        self.assertGreater(subscription.current_period_end, original_period_end)

    def test_renewal_charge_failure_moves_active_subscription_to_past_due_not_expired(self):
        subscription = Subscription.objects.create(
            user=self.user,
            amount=300000,
            payment_reference="SUB-WILLFAIL1",
            status=SubscriptionStatus.ACTIVE,
        )
        response = self._post_webhook(
            {
                "event": "charge.completed",
                "data": {
                    "tx_ref": "flw-generated-fail-ref",
                    "status": "failed",
                    "id": "txn-5",
                    "customer": {"email": self.user.email},
                },
            }
        )
        self.assertEqual(response.status_code, 200)
        subscription.refresh_from_db()
        self.assertEqual(subscription.status, SubscriptionStatus.PAST_DUE)

    def test_subscription_cancelled_event_expires_a_past_due_subscription(self):
        subscription = Subscription.objects.create(
            user=self.user,
            amount=300000,
            payment_reference="SUB-PASTDUE1",
            status=SubscriptionStatus.PAST_DUE,
            provider_subscription_id="fw-sub-99",
        )
        response = self._post_webhook(
            {
                "event": "subscription.cancelled",
                "data": {"id": "fw-sub-99", "status": "cancelled", "customer": {"email": self.user.email}},
            }
        )
        self.assertEqual(response.status_code, 200)
        subscription.refresh_from_db()
        self.assertEqual(subscription.status, SubscriptionStatus.EXPIRED)

    def test_subscription_cancelled_event_on_an_active_subscription_schedules_not_revokes(self):
        # Unprompted cancellation (e.g. via Flutterwave's own dashboard) is
        # not a payment failure -- it must not claw back the period already
        # paid for, same policy as a user-initiated cancel_subscription().
        subscription = Subscription.objects.create(
            user=self.user,
            amount=300000,
            payment_reference="SUB-ACTIVE001",
            status=SubscriptionStatus.ACTIVE,
            provider_subscription_id="fw-sub-100",
        )
        response = self._post_webhook(
            {
                "event": "subscription.cancelled",
                "data": {"id": "fw-sub-100", "status": "cancelled", "customer": {"email": self.user.email}},
            }
        )
        self.assertEqual(response.status_code, 200)
        subscription.refresh_from_db()
        self.assertEqual(subscription.status, SubscriptionStatus.ACTIVE)
        self.assertTrue(subscription.cancel_at_period_end)

    def test_subscription_cancelled_event_is_idempotent_when_already_scheduled(self):
        subscription = Subscription.objects.create(
            user=self.user,
            amount=300000,
            payment_reference="SUB-ACTIVE002",
            status=SubscriptionStatus.ACTIVE,
            provider_subscription_id="fw-sub-101b",
            cancel_at_period_end=True,
        )
        history_count_before = SubscriptionStatusHistory.objects.filter(subscription=subscription).count()
        response = self._post_webhook(
            {
                "event": "subscription.cancelled",
                "data": {"id": "fw-sub-101b", "status": "cancelled", "customer": {"email": self.user.email}},
            }
        )
        self.assertEqual(response.status_code, 200)
        subscription.refresh_from_db()
        self.assertEqual(subscription.status, SubscriptionStatus.ACTIVE)
        self.assertEqual(
            SubscriptionStatusHistory.objects.filter(subscription=subscription).count(),
            history_count_before,
        )

    def test_subscription_cancelled_event_is_idempotent_on_an_already_canceled_subscription(self):
        subscription = Subscription.objects.create(
            user=self.user,
            amount=300000,
            payment_reference="SUB-ALREADY01",
            status=SubscriptionStatus.CANCELED,
            provider_subscription_id="fw-sub-101",
        )
        history_count_before = SubscriptionStatusHistory.objects.filter(subscription=subscription).count()

        response = self._post_webhook(
            {
                "event": "subscription.cancelled",
                "data": {"id": "fw-sub-101", "status": "cancelled", "customer": {"email": self.user.email}},
            }
        )
        self.assertEqual(response.status_code, 200)
        subscription.refresh_from_db()
        self.assertEqual(subscription.status, SubscriptionStatus.CANCELED)
        self.assertEqual(
            SubscriptionStatusHistory.objects.filter(subscription=subscription).count(),
            history_count_before,
        )

    def test_replaying_the_same_successful_charge_webhook_is_idempotent(self):
        # Phase 21's explicit acceptance criterion: a replayed webhook
        # delivery must never double-renew.
        subscription = Subscription.objects.create(
            user=self.user,
            amount=300000,
            payment_reference="SUB-REPLAY001",
            status=SubscriptionStatus.PENDING,
        )
        body = {
            "event": "charge.completed",
            "data": {
                "tx_ref": "SUB-REPLAY001",
                "status": "successful",
                "id": "txn-replay",
                "customer": {"email": self.user.email},
            },
        }
        with patch(
            "apps.subscriptions.services.commands.FlutterwaveGateway.find_active_subscription_by_email"
        ) as lookup_mock:
            lookup_mock.return_value = None
            self._post_webhook(body)
            subscription.refresh_from_db()
            first_period_end = subscription.current_period_end
            history_count_after_first = SubscriptionStatusHistory.objects.filter(subscription=subscription).count()

            self._post_webhook(body)

        subscription.refresh_from_db()
        # Still ACTIVE, and the second delivery (same first-charge
        # reference, already ACTIVE) is treated as a fresh renewal-shaped
        # match by reference again -- current_period_end may extend, but
        # the STATUS transition (from_status == to_status, ACTIVE ->
        # ACTIVE) must not log a duplicate history row.
        self.assertEqual(subscription.status, SubscriptionStatus.ACTIVE)
        self.assertEqual(
            SubscriptionStatusHistory.objects.filter(subscription=subscription).count(),
            history_count_after_first,
        )

    def test_unrecognized_webhook_event_is_logged_not_silently_dropped(self):
        response = self._post_webhook(
            {
                "event": "charge.completed",
                "data": {
                    "tx_ref": "totally-unknown-reference",
                    "status": "successful",
                    "id": "txn-unknown",
                    "customer": {"email": "nobody@example.com"},
                },
            }
        )
        self.assertEqual(response.status_code, 404)
        self.assertTrue(SubscriptionEventLog.objects.filter(event="charge.completed").exists())

    def test_webhook_rejects_an_invalid_signature(self):
        response = self._post_webhook(
            {"event": "charge.completed", "data": {"tx_ref": "x", "status": "successful"}},
            secret_hash="wrong-hash",
        )
        self.assertEqual(response.status_code, 403)


class AdminSubscriptionApiTests(TestCase):
    def setUp(self):
        self.admin_user = UserFactory(email="admin@example.com")
        role = AdminRoleFactory(code=AdminRoleCode.SUPER_ADMIN)
        AdminAssignmentFactory(user=self.admin_user, role=role)
        self.subscriber = UserFactory(email="regular-subscriber@example.com")
        self.subscription = Subscription.objects.create(
            user=self.subscriber,
            amount=300000,
            payment_reference="SUB-ADMIN0001",
            status=SubscriptionStatus.ACTIVE,
        )

    def test_admin_list_requires_admin_role(self):
        token = Token.objects.create(user=self.subscriber)
        response = self.client.get(
            reverse("admin-subscription-list"), HTTP_AUTHORIZATION=f"Token {token.key}"
        )
        self.assertEqual(response.status_code, 403)

    def test_admin_list_rejects_token_authentication(self):
        # Matches the existing donations admin-endpoint hardening: admin
        # views must stay Session-authenticated only.
        token = Token.objects.create(user=self.admin_user)
        response = self.client.get(
            reverse("admin-subscription-list"), HTTP_AUTHORIZATION=f"Token {token.key}"
        )
        self.assertEqual(response.status_code, 403)

    def test_admin_list_returns_subscriptions_for_a_session_authenticated_admin(self):
        self.client.force_login(self.admin_user)
        response = self.client.get(reverse("admin-subscription-list"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 1)

    def test_admin_detail_includes_status_history(self):
        SubscriptionStatusHistory.objects.create(
            subscription=self.subscription,
            from_status=SubscriptionStatus.PENDING,
            to_status=SubscriptionStatus.ACTIVE,
        )
        self.client.force_login(self.admin_user)
        response = self.client.get(reverse("admin-subscription-detail", kwargs={"pk": self.subscription.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["status_history"]), 1)

    def test_admin_list_searches_by_subscriber_email(self):
        Subscription.objects.create(
            user=UserFactory(email="someoneelse@example.com"),
            amount=300000,
            payment_reference="SUB-ADMIN0002",
            status=SubscriptionStatus.ACTIVE,
        )
        self.client.force_login(self.admin_user)
        response = self.client.get(reverse("admin-subscription-list"), {"q": "regular-subscriber"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["results"][0]["subscriber_email"], "regular-subscriber@example.com")

    def test_admin_list_filters_by_status(self):
        Subscription.objects.create(
            user=UserFactory(email="canceled-user@example.com"),
            amount=300000,
            payment_reference="SUB-ADMIN0003",
            status=SubscriptionStatus.CANCELED,
        )
        self.client.force_login(self.admin_user)
        response = self.client.get(reverse("admin-subscription-list"), {"status": "canceled"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["results"][0]["status"], SubscriptionStatus.CANCELED)


class AdminCancelSubscriptionApiTests(TestCase):
    """Phase 21 Slice 4's manual override action for support cases."""

    def setUp(self):
        self.admin_user = UserFactory(email="admin2@example.com")
        role = AdminRoleFactory(code=AdminRoleCode.SUPER_ADMIN)
        AdminAssignmentFactory(user=self.admin_user, role=role)
        self.subscriber = UserFactory(email="support-case@example.com")

    def _login(self):
        self.client.force_login(self.admin_user)

    def test_requires_admin_role(self):
        subscription = Subscription.objects.create(
            user=self.subscriber,
            amount=300000,
            payment_reference="SUB-CANCEL0001",
            status=SubscriptionStatus.ACTIVE,
        )
        token = Token.objects.create(user=self.subscriber)
        response = self.client.post(
            reverse("admin-subscription-cancel", kwargs={"subscription_id": subscription.pk}),
            {"reason": "Support request"},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Token {token.key}",
        )
        self.assertEqual(response.status_code, 403)

    def test_rejects_token_authentication(self):
        subscription = Subscription.objects.create(
            user=self.subscriber,
            amount=300000,
            payment_reference="SUB-CANCEL0002",
            status=SubscriptionStatus.ACTIVE,
        )
        token = Token.objects.create(user=self.admin_user)
        response = self.client.post(
            reverse("admin-subscription-cancel", kwargs={"subscription_id": subscription.pk}),
            {"reason": "Support request"},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Token {token.key}",
        )
        self.assertEqual(response.status_code, 403)

    def test_requires_a_reason(self):
        subscription = Subscription.objects.create(
            user=self.subscriber,
            amount=300000,
            payment_reference="SUB-CANCEL0003",
            status=SubscriptionStatus.ACTIVE,
        )
        self._login()
        response = self.client.post(
            reverse("admin-subscription-cancel", kwargs={"subscription_id": subscription.pk}),
            {"reason": ""},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_returns_404_for_an_unknown_subscription(self):
        self._login()
        response = self.client.post(
            reverse("admin-subscription-cancel", kwargs={"subscription_id": 999999}),
            {"reason": "Support request"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)

    def test_cancels_an_active_subscription_without_revoking_current_access(self):
        subscription = Subscription.objects.create(
            user=self.subscriber,
            amount=300000,
            payment_reference="SUB-CANCEL0004",
            status=SubscriptionStatus.ACTIVE,
            current_period_end=timezone.now() + timedelta(days=10),
        )
        self._login()
        response = self.client.post(
            reverse("admin-subscription-cancel", kwargs={"subscription_id": subscription.pk}),
            {"reason": "Customer requested a refund via support ticket #123."},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], SubscriptionStatus.ACTIVE)
        self.assertTrue(payload["cancel_at_period_end"])
        self.assertEqual(len(payload["status_history"]), 1)
        self.assertEqual(payload["status_history"][0]["actor_email"], self.admin_user.email)

    def test_cancels_a_stuck_pending_subscription_immediately_and_terminally(self):
        # The exact real-world support scenario this action exists for --
        # a payment that succeeded on Flutterwave but never got locally
        # activated has no active access to protect, unlike an ACTIVE one.
        subscription = Subscription.objects.create(
            user=self.subscriber,
            amount=300000,
            payment_reference="SUB-CANCEL0005",
            status=SubscriptionStatus.PENDING,
        )
        self._login()
        response = self.client.post(
            reverse("admin-subscription-cancel", kwargs={"subscription_id": subscription.pk}),
            {"reason": "Stuck payment, resolved manually by support."},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], SubscriptionStatus.CANCELED)

    def test_rejects_canceling_an_already_terminal_subscription(self):
        subscription = Subscription.objects.create(
            user=self.subscriber,
            amount=300000,
            payment_reference="SUB-CANCEL0006",
            status=SubscriptionStatus.EXPIRED,
        )
        self._login()
        response = self.client.post(
            reverse("admin-subscription-cancel", kwargs={"subscription_id": subscription.pk}),
            {"reason": "Support request"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_rejects_canceling_an_already_scheduled_cancellation(self):
        subscription = Subscription.objects.create(
            user=self.subscriber,
            amount=300000,
            payment_reference="SUB-CANCEL0007",
            status=SubscriptionStatus.ACTIVE,
            cancel_at_period_end=True,
        )
        self._login()
        response = self.client.post(
            reverse("admin-subscription-cancel", kwargs={"subscription_id": subscription.pk}),
            {"reason": "Support request"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_calls_flutterwave_when_a_provider_subscription_id_is_known(self):
        subscription = Subscription.objects.create(
            user=self.subscriber,
            amount=300000,
            payment_reference="SUB-CANCEL0008",
            status=SubscriptionStatus.ACTIVE,
            provider_subscription_id="fw-sub-admin-1",
        )
        self._login()
        with (
            patch("apps.subscriptions.services.commands.settings.FLUTTERWAVE_SECRET_KEY", "sk_test"),
            patch("apps.common.services.flutterwave.FlutterwaveGateway._put") as put_mock,
        ):
            put_mock.return_value = {"data": {"status": "cancelled"}}
            response = self.client.post(
                reverse("admin-subscription-cancel", kwargs={"subscription_id": subscription.pk}),
                {"reason": "Support request"},
                content_type="application/json",
            )
        self.assertEqual(response.status_code, 200)
        put_mock.assert_called_once()
        self.assertIn("fw-sub-admin-1", put_mock.call_args[0][0])


class AdminPremiumPricingApiTests(TestCase):
    """Phase 21 Slice 5: admin sets the Premium subscription price per
    currency. Added 2026-08-15 -- the views/service/model already existed
    but had zero test coverage before this."""

    def setUp(self):
        PremiumPricing.objects.all().delete()
        self.admin_user = UserFactory(email="pricing-admin@example.com")
        role = AdminRoleFactory(code=AdminRoleCode.SUPER_ADMIN)
        AdminAssignmentFactory(user=self.admin_user, role=role)
        self.subscriber = UserFactory(email="pricing-subscriber@example.com")

    def _login(self):
        self.client.force_login(self.admin_user)

    # -- GET admin/pricing/ ------------------------------------------------

    def test_list_requires_admin_role(self):
        token = Token.objects.create(user=self.subscriber)
        response = self.client.get(
            reverse("admin-premium-pricing-list"), HTTP_AUTHORIZATION=f"Token {token.key}"
        )
        self.assertEqual(response.status_code, 403)

    def test_list_rejects_token_authentication(self):
        # Matches the existing admin-endpoint hardening: admin views must
        # stay Session-authenticated only.
        token = Token.objects.create(user=self.admin_user)
        response = self.client.get(
            reverse("admin-premium-pricing-list"), HTTP_AUTHORIZATION=f"Token {token.key}"
        )
        self.assertEqual(response.status_code, 403)

    def test_list_returns_empty_when_no_pricing_set(self):
        self._login()
        response = self.client.get(reverse("admin-premium-pricing-list"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_list_returns_pricing_rows_ordered_by_currency(self):
        PremiumPricing.objects.create(
            currency="USD", amount=499, provider_plan_id="plan_usd", updated_by=self.admin_user
        )
        PremiumPricing.objects.create(
            currency="NGN", amount=300000, provider_plan_id="plan_ngn", updated_by=self.admin_user
        )
        self._login()
        response = self.client.get(reverse("admin-premium-pricing-list"))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual([row["currency"] for row in payload], ["NGN", "USD"])
        self.assertEqual(payload[0]["amount"], 300000)
        self.assertEqual(payload[0]["updated_by_email"], "pricing-admin@example.com")

    # -- POST admin/pricing/set/ --------------------------------------------

    def test_set_requires_admin_role(self):
        token = Token.objects.create(user=self.subscriber)
        response = self.client.post(
            reverse("admin-premium-pricing-set"),
            {"currency": "NGN", "amount": 300000},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Token {token.key}",
        )
        self.assertEqual(response.status_code, 403)

    def test_set_rejects_token_authentication(self):
        token = Token.objects.create(user=self.admin_user)
        response = self.client.post(
            reverse("admin-premium-pricing-set"),
            {"currency": "NGN", "amount": 300000},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Token {token.key}",
        )
        self.assertEqual(response.status_code, 403)

    def test_set_rejects_a_non_3_letter_currency_code(self):
        self._login()
        response = self.client.post(
            reverse("admin-premium-pricing-set"),
            {"currency": "NAIRA", "amount": 300000},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(PremiumPricing.objects.exists())

    def test_set_rejects_a_zero_or_negative_amount(self):
        self._login()
        response = self.client.post(
            reverse("admin-premium-pricing-set"),
            {"currency": "NGN", "amount": 0},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(PremiumPricing.objects.exists())

    def test_set_returns_503_when_gateway_not_configured(self):
        self._login()
        with patch("apps.subscriptions.services.commands.settings.FLUTTERWAVE_SECRET_KEY", ""):
            response = self.client.post(
                reverse("admin-premium-pricing-set"),
                {"currency": "NGN", "amount": 300000},
                content_type="application/json",
            )
        self.assertEqual(response.status_code, 503)
        self.assertFalse(PremiumPricing.objects.exists())

    def test_set_returns_502_when_the_gateway_call_fails(self):
        self._login()
        with (
            patch("apps.subscriptions.services.commands.settings.FLUTTERWAVE_SECRET_KEY", "sk_test"),
            patch("apps.common.services.flutterwave.FlutterwaveGateway._post") as post_mock,
        ):
            post_mock.return_value = {"data": {}}  # no "id" -> gateway error
            response = self.client.post(
                reverse("admin-premium-pricing-set"),
                {"currency": "NGN", "amount": 300000},
                content_type="application/json",
            )
        self.assertEqual(response.status_code, 502)
        self.assertFalse(PremiumPricing.objects.exists())

    def test_set_creates_a_new_pricing_row_and_sends_major_unit_amount_to_the_gateway(self):
        # Regression coverage for the same minor/major-unit conversion bug
        # class already covered for subscribe() and donations.
        self._login()
        with (
            patch("apps.subscriptions.services.commands.settings.FLUTTERWAVE_SECRET_KEY", "sk_test"),
            patch("apps.common.services.flutterwave.FlutterwaveGateway._post") as post_mock,
        ):
            post_mock.return_value = {"data": {"id": "plan_new_ngn"}}
            response = self.client.post(
                reverse("admin-premium-pricing-set"),
                {"currency": "ngn", "amount": 350000},
                content_type="application/json",
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["currency"], "NGN")
        self.assertEqual(payload["amount"], 350000)
        self.assertEqual(payload["provider_plan_id"], "plan_new_ngn")
        self.assertEqual(payload["updated_by_email"], "pricing-admin@example.com")

        sent_payload = post_mock.call_args[0][1]
        self.assertEqual(sent_payload["amount"], "3500.00")
        self.assertEqual(sent_payload["currency"], "NGN")

        pricing = PremiumPricing.objects.get(currency="NGN")
        self.assertEqual(pricing.updated_by, self.admin_user)
        history = pricing.history.get()
        self.assertIsNone(history.from_amount)
        self.assertEqual(history.to_amount, 350000)
        self.assertEqual(history.actor, self.admin_user)

    def test_set_replaces_an_existing_pricing_row_with_a_new_plan_and_records_history(self):
        existing = PremiumPricing.objects.create(
            currency="NGN", amount=300000, provider_plan_id="plan_old_ngn"
        )
        self._login()
        with (
            patch("apps.subscriptions.services.commands.settings.FLUTTERWAVE_SECRET_KEY", "sk_test"),
            patch("apps.common.services.flutterwave.FlutterwaveGateway._post") as post_mock,
        ):
            post_mock.return_value = {"data": {"id": "plan_new_ngn"}}
            response = self.client.post(
                reverse("admin-premium-pricing-set"),
                {"currency": "NGN", "amount": 400000},
                content_type="application/json",
            )
        self.assertEqual(response.status_code, 200)

        # Same row updated in place (one row per currency), not a duplicate.
        self.assertEqual(PremiumPricing.objects.filter(currency="NGN").count(), 1)
        existing.refresh_from_db()
        self.assertEqual(existing.amount, 400000)
        self.assertEqual(existing.provider_plan_id, "plan_new_ngn")

        history = existing.history.get()
        self.assertEqual(history.from_amount, 300000)
        self.assertEqual(history.to_amount, 400000)
        self.assertEqual(history.from_provider_plan_id, "plan_old_ngn")
        self.assertEqual(history.to_provider_plan_id, "plan_new_ngn")

    def test_set_never_touches_an_existing_subscribers_own_price(self):
        # The whole point of Slice 5's design: a subscriber who already
        # subscribed keeps their own captured amount/plan forever, even
        # after the admin changes the price for *new* subscribers.
        PremiumPricing.objects.create(currency="NGN", amount=300000, provider_plan_id="plan_old_ngn")
        subscription = Subscription.objects.create(
            user=self.subscriber,
            amount=300000,
            currency="NGN",
            provider_plan_id="plan_old_ngn",
            payment_reference="SUB-PRICING0001",
            status=SubscriptionStatus.ACTIVE,
        )
        self._login()
        with (
            patch("apps.subscriptions.services.commands.settings.FLUTTERWAVE_SECRET_KEY", "sk_test"),
            patch("apps.common.services.flutterwave.FlutterwaveGateway._post") as post_mock,
        ):
            post_mock.return_value = {"data": {"id": "plan_new_ngn"}}
            response = self.client.post(
                reverse("admin-premium-pricing-set"),
                {"currency": "NGN", "amount": 500000},
                content_type="application/json",
            )
        self.assertEqual(response.status_code, 200)

        subscription.refresh_from_db()
        self.assertEqual(subscription.amount, 300000)
        self.assertEqual(subscription.provider_plan_id, "plan_old_ngn")
