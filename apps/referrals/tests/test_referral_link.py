from django.test import TestCase
from django.urls import reverse
from rest_framework.authtoken.models import Token

from apps.referrals.models import ReferralCode, ReferralTermsAcceptance
from apps.referrals.services.commands import accept_referral_terms, get_or_create_referral_code
from apps.subscriptions.models import Subscription, SubscriptionStatus
from apps.users.tests.factories import UserFactory


class GetOrCreateReferralCodeTests(TestCase):
    def setUp(self):
        self.user = UserFactory(email="code-user@example.com")

    def test_creates_an_8_character_code_from_the_ambiguity_free_alphabet(self):
        code = get_or_create_referral_code(user=self.user)
        self.assertEqual(len(code.code), 8)
        self.assertTrue(code.code.isupper() or code.code.isdigit() or code.code.isalnum())
        for ambiguous in "0O1IL":
            self.assertNotIn(ambiguous, code.code)

    def test_is_idempotent_and_permanent(self):
        first = get_or_create_referral_code(user=self.user)
        second = get_or_create_referral_code(user=self.user)
        self.assertEqual(first.id, second.id)
        self.assertEqual(ReferralCode.objects.filter(user=self.user).count(), 1)

    def test_two_users_never_collide(self):
        other = UserFactory(email="code-user-2@example.com")
        first = get_or_create_referral_code(user=self.user)
        second = get_or_create_referral_code(user=other)
        self.assertNotEqual(first.code, second.code)


class AcceptReferralTermsCommandTests(TestCase):
    def test_is_idempotent(self):
        user = UserFactory(email="terms-user@example.com")
        first = accept_referral_terms(user=user)
        second = accept_referral_terms(user=user)
        self.assertEqual(first.id, second.id)
        self.assertEqual(ReferralTermsAcceptance.objects.filter(user=user).count(), 1)


class MyReferralLinkApiTests(TestCase):
    def setUp(self):
        self.user = UserFactory(email="link-user@example.com")
        self.token = Token.objects.create(user=self.user)

    def _auth_headers(self):
        return {"HTTP_AUTHORIZATION": f"Token {self.token.key}"}

    def _make_premium(self):
        Subscription.objects.create(
            user=self.user,
            amount=300000,
            payment_reference="SUB-LINK-USER",
            status=SubscriptionStatus.ACTIVE,
        )

    def test_requires_authentication(self):
        response = self.client.get(reverse("referral-my-link"))
        self.assertEqual(response.status_code, 401)

    def test_rejects_session_authentication(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("referral-my-link"))
        self.assertEqual(response.status_code, 401)

    def test_returns_403_when_not_premium(self):
        response = self.client.get(reverse("referral-my-link"), **self._auth_headers())
        self.assertEqual(response.status_code, 403)

    def test_returns_terms_not_accepted_and_no_code_when_premium_but_terms_unaccepted(self):
        self._make_premium()
        response = self.client.get(reverse("referral-my-link"), **self._auth_headers())
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["terms_accepted"])
        self.assertIsNone(payload["code"])
        self.assertFalse(ReferralCode.objects.filter(user=self.user).exists())

    def test_lazily_generates_a_code_once_terms_are_accepted(self):
        self._make_premium()
        accept_referral_terms(user=self.user)
        response = self.client.get(reverse("referral-my-link"), **self._auth_headers())
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["terms_accepted"])
        self.assertIsNotNone(payload["code"])
        self.assertEqual(ReferralCode.objects.get(user=self.user).code, payload["code"])

    def test_repeat_calls_return_the_same_code(self):
        self._make_premium()
        accept_referral_terms(user=self.user)
        first = self.client.get(reverse("referral-my-link"), **self._auth_headers()).json()
        second = self.client.get(reverse("referral-my-link"), **self._auth_headers()).json()
        self.assertEqual(first["code"], second["code"])


class AcceptReferralTermsApiTests(TestCase):
    def setUp(self):
        self.user = UserFactory(email="accept-terms-user@example.com")
        self.token = Token.objects.create(user=self.user)

    def _auth_headers(self):
        return {"HTTP_AUTHORIZATION": f"Token {self.token.key}"}

    def test_requires_authentication(self):
        response = self.client.post(reverse("referral-accept-terms"))
        self.assertEqual(response.status_code, 401)

    def test_accepts_and_persists(self):
        response = self.client.post(reverse("referral-accept-terms"), **self._auth_headers())
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["terms_accepted"])
        self.assertIsNotNone(payload["accepted_at"])
        self.assertTrue(ReferralTermsAcceptance.objects.filter(user=self.user).exists())

    def test_a_repeat_accept_does_not_error_or_duplicate(self):
        first = self.client.post(reverse("referral-accept-terms"), **self._auth_headers())
        second = self.client.post(reverse("referral-accept-terms"), **self._auth_headers())
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json()["accepted_at"], second.json()["accepted_at"])
        self.assertEqual(ReferralTermsAcceptance.objects.filter(user=self.user).count(), 1)
