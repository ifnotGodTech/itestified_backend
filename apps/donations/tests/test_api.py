from django.test import TestCase
from django.urls import reverse
from rest_framework.authtoken.models import Token
from unittest.mock import patch

from apps.donations.models import Donation, DonationStatus
from apps.users.choices import AdminRoleCode
from apps.users.tests.factories import AdminAssignmentFactory, AdminRoleFactory, UserFactory


class DonationApiTests(TestCase):
    def test_donation_endpoints_require_authentication(self):
        create_response = self.client.post(
            reverse("donation-create"),
            {"amount": 5000, "currency": "NGN"},
            content_type="application/json",
        )
        self.assertEqual(create_response.status_code, 401)

        list_response = self.client.get(reverse("donation-mine-list"))
        self.assertEqual(list_response.status_code, 401)

    def test_phase5_slice1_create_donation_returns_pending_and_reference(self):
        user = UserFactory(email="giver@example.com")
        token = Token.objects.create(user=user)

        with patch("apps.donations.api.views.settings.FLUTTERWAVE_SECRET_KEY", ""):
            response = self.client.post(
                reverse("donation-create"),
                {"amount": 5000, "currency": "NGN"},
                content_type="application/json",
                HTTP_AUTHORIZATION=f"Token {token.key}",
            )
        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(payload["status"], DonationStatus.PENDING)
        self.assertTrue(payload["payment_reference"].startswith("DON-"))
        self.assertIn("checkout_url", payload)

    def test_create_donation_rejects_non_integer_amount(self):
        user = UserFactory(email="giver-decimal@example.com")
        token = Token.objects.create(user=user)

        response = self.client.post(
            reverse("donation-create"),
            {"amount": 10.5, "currency": "NGN"},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Token {token.key}",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("amount", response.json())

    def test_phase5_slice2_provider_callback_updates_status(self):
        user = UserFactory(email="provider@example.com")
        donation = Donation.objects.create(
            user=user,
            amount=1000,
            currency="NGN",
            payment_reference="DON-TESTREF",
            checkout_url="https://checkout.flutterwave.com/pay/don-testref",
        )

        with patch("apps.donations.api.views.settings.FLUTTERWAVE_SECRET_HASH", "secret-hash"):
            callback = self.client.post(
                reverse("donation-provider-callback"),
                {
                    "payment_reference": donation.payment_reference,
                    "status": DonationStatus.SUCCESSFUL,
                    "provider_transaction_id": "FW-12345",
                },
                content_type="application/json",
                HTTP_VERIF_HASH="secret-hash",
            )
        self.assertEqual(callback.status_code, 200)
        donation.refresh_from_db()
        self.assertEqual(donation.status, DonationStatus.SUCCESSFUL)
        self.assertEqual(donation.provider_transaction_id, "FW-12345")
    
    def test_provider_callback_accepts_flutterwave_shape(self):
        user = UserFactory(email="provider2@example.com")
        donation = Donation.objects.create(
            user=user,
            amount=1000,
            currency="NGN",
            payment_reference="DON-TESTREF-2",
        )

        with patch("apps.donations.api.views.settings.FLUTTERWAVE_SECRET_HASH", "secret-hash"):
            callback = self.client.post(
                reverse("donation-provider-callback"),
                {
                    "data": {
                        "tx_ref": donation.payment_reference,
                        "status": "successful",
                        "id": "556677",
                    },
                },
                content_type="application/json",
                HTTP_VERIF_HASH="secret-hash",
            )
        self.assertEqual(callback.status_code, 200)
        donation.refresh_from_db()
        self.assertEqual(donation.status, DonationStatus.SUCCESSFUL)
        self.assertEqual(donation.provider_transaction_id, "556677")

    def test_provider_callback_returns_503_when_secret_hash_not_configured(self):
        user = UserFactory(email="provider3@example.com")
        donation = Donation.objects.create(
            user=user,
            amount=1000,
            currency="NGN",
            payment_reference="DON-TESTREF-3",
        )

        with patch("apps.donations.api.views.settings.FLUTTERWAVE_SECRET_HASH", ""):
            callback = self.client.post(
                reverse("donation-provider-callback"),
                {
                    "payment_reference": donation.payment_reference,
                    "status": DonationStatus.SUCCESSFUL,
                    "provider_transaction_id": "FW-99999",
                },
                content_type="application/json",
            )

        self.assertEqual(callback.status_code, 503)

    def test_provider_callback_rejects_invalid_signature(self):
        user = UserFactory(email="provider4@example.com")
        donation = Donation.objects.create(
            user=user,
            amount=1000,
            currency="NGN",
            payment_reference="DON-TESTREF-4",
        )

        with patch("apps.donations.api.views.settings.FLUTTERWAVE_SECRET_HASH", "secret-hash"):
            callback = self.client.post(
                reverse("donation-provider-callback"),
                {
                    "payment_reference": donation.payment_reference,
                    "status": DonationStatus.SUCCESSFUL,
                    "provider_transaction_id": "FW-11111",
                },
                content_type="application/json",
                HTTP_VERIF_HASH="wrong-hash",
            )

        self.assertEqual(callback.status_code, 403)

    def test_phase5_slice3_view_own_history_only(self):
        user = UserFactory(email="history@example.com")
        other = UserFactory(email="other-history@example.com")
        token = Token.objects.create(user=user)
        Donation.objects.create(
            user=user,
            amount=1000,
            currency="NGN",
            payment_reference="DON-HIST-1",
            status=DonationStatus.SUCCESSFUL,
        )
        Donation.objects.create(
            user=other,
            amount=2000,
            currency="NGN",
            payment_reference="DON-HIST-2",
            status=DonationStatus.DECLINED,
        )

        response = self.client.get(
            reverse("donation-mine-list"),
            HTTP_AUTHORIZATION=f"Token {token.key}",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["results"][0]["payment_reference"], "DON-HIST-1")

    def test_phase5_slice4_view_own_donation_detail(self):
        user = UserFactory(email="detail@example.com")
        other = UserFactory(email="other-detail@example.com")
        token = Token.objects.create(user=user)
        mine = Donation.objects.create(
            user=user,
            amount=3000,
            currency="USD",
            payment_reference="DON-DET-1",
            status=DonationStatus.PENDING,
        )
        other_one = Donation.objects.create(
            user=other,
            amount=3000,
            currency="USD",
            payment_reference="DON-DET-2",
            status=DonationStatus.PENDING,
        )

        ok_response = self.client.get(
            reverse("donation-mine-detail", kwargs={"pk": mine.id}),
            HTTP_AUTHORIZATION=f"Token {token.key}",
        )
        self.assertEqual(ok_response.status_code, 200)
        self.assertEqual(ok_response.json()["payment_reference"], "DON-DET-1")

        denied_response = self.client.get(
            reverse("donation-mine-detail", kwargs={"pk": other_one.id}),
            HTTP_AUTHORIZATION=f"Token {token.key}",
        )
        self.assertEqual(denied_response.status_code, 404)

    def test_verify_endpoint_updates_status_from_gateway(self):
        user = UserFactory(email="verify@example.com")
        token = Token.objects.create(user=user)
        donation = Donation.objects.create(
            user=user,
            amount=4000,
            currency="NGN",
            payment_reference="DON-VERIFY-1",
            provider_transaction_id="9988",
        )

        with (
            patch("apps.donations.api.views.settings.FLUTTERWAVE_SECRET_KEY", "sk_test"),
            patch("apps.donations.api.views.FlutterwaveGateway.verify") as verify_mock,
        ):
            verify_mock.return_value.status = DonationStatus.SUCCESSFUL
            verify_mock.return_value.provider_transaction_id = "9988"
            verify_mock.return_value.status_reason = "Approved"
            response = self.client.post(
                reverse("donation-verify"),
                {
                    "payment_reference": donation.payment_reference,
                    "transaction_id": "9988",
                },
                content_type="application/json",
                HTTP_AUTHORIZATION=f"Token {token.key}",
            )

        self.assertEqual(response.status_code, 200)
        donation.refresh_from_db()
        self.assertEqual(donation.status, DonationStatus.SUCCESSFUL)

    def test_admin_can_view_all_donations_with_filters(self):
        admin_user = UserFactory(email="admin-donations@example.com")
        admin_token = Token.objects.create(user=admin_user)
        AdminRoleFactory(code=AdminRoleCode.FINANCE_ADMIN)
        AdminAssignmentFactory(user=admin_user, role=AdminRoleFactory(code=AdminRoleCode.FINANCE_ADMIN))
        user = UserFactory(email="alpha@example.com")
        other = UserFactory(email="beta@example.com")
        Donation.objects.create(
            user=user,
            amount=1000,
            currency="NGN",
            payment_reference="DON-ADMIN-1",
            status=DonationStatus.SUCCESSFUL,
        )
        Donation.objects.create(
            user=other,
            amount=2000,
            currency="USD",
            payment_reference="DON-ADMIN-2",
            status=DonationStatus.PENDING,
        )

        response = self.client.get(
            reverse("admin-donation-list"),
            {"status": "successful", "q": "alpha"},
            HTTP_AUTHORIZATION=f"Token {admin_token.key}",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["results"][0]["payment_reference"], "DON-ADMIN-1")

    def test_non_admin_cannot_access_admin_donation_list(self):
        user = UserFactory(email="plain@example.com")
        token = Token.objects.create(user=user)
        response = self.client.get(
            reverse("admin-donation-list"),
            HTTP_AUTHORIZATION=f"Token {token.key}",
        )
        self.assertEqual(response.status_code, 403)

    def test_admin_can_view_detail_and_reverse_successful_donation(self):
        admin_user = UserFactory(email="admin-reverse@example.com")
        admin_token = Token.objects.create(user=admin_user)
        AdminAssignmentFactory(user=admin_user, role=AdminRoleFactory(code=AdminRoleCode.FINANCE_ADMIN))

        donor = UserFactory(email="donor@example.com")
        donation = Donation.objects.create(
            user=donor,
            amount=5500,
            currency="NGN",
            payment_reference="DON-REV-1",
            status=DonationStatus.SUCCESSFUL,
        )

        reverse_response = self.client.post(
            reverse("admin-donation-reverse", kwargs={"donation_id": donation.id}),
            {"reason": "Duplicate charge reported by donor"},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Token {admin_token.key}",
        )
        self.assertEqual(reverse_response.status_code, 200)
        donation.refresh_from_db()
        self.assertEqual(donation.status, DonationStatus.REVERSED)

        detail_response = self.client.get(
            reverse("admin-donation-detail", kwargs={"pk": donation.id}),
            HTTP_AUTHORIZATION=f"Token {admin_token.key}",
        )
        self.assertEqual(detail_response.status_code, 200)
        detail_payload = detail_response.json()
        self.assertEqual(detail_payload["status"], DonationStatus.REVERSED)
        self.assertGreaterEqual(len(detail_payload["status_history"]), 1)

    def test_admin_reverse_requires_successful_donation(self):
        admin_user = UserFactory(email="admin-reverse-pending@example.com")
        admin_token = Token.objects.create(user=admin_user)
        AdminAssignmentFactory(user=admin_user, role=AdminRoleFactory(code=AdminRoleCode.FINANCE_ADMIN))
        donor = UserFactory(email="pending-donor@example.com")
        donation = Donation.objects.create(
            user=donor,
            amount=2000,
            currency="NGN",
            payment_reference="DON-REV-2",
            status=DonationStatus.PENDING,
        )

        response = self.client.post(
            reverse("admin-donation-reverse", kwargs={"donation_id": donation.id}),
            {"reason": "Requested reversal"},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Token {admin_token.key}",
        )
        self.assertEqual(response.status_code, 400)
