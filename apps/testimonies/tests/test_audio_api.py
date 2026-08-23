from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework.authtoken.models import Token

from apps.users.tests.factories import UserFactory


class AudioTestimonyApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_audio_policy_exposes_phase_28_defaults(self):
        response = self.client.get(reverse("audio-upload-policy"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["max_file_size_bytes"], 50 * 1024 * 1024)
        self.assertEqual(response.json()["max_duration_ms"], 15 * 60 * 1000)
        self.assertIn("audio/mp3", response.json()["allowed_content_types"])

    def test_free_user_gets_stable_premium_required_response(self):
        user = UserFactory()
        token, _ = Token.objects.get_or_create(user=user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

        response = self.client.post(reverse("testimony-submit-audio-signature"), {}, format="json")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "premium_required")
