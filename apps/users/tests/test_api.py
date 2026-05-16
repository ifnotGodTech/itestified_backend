from django.test import TestCase
from django.urls import reverse
from rest_framework.authtoken.models import Token

from apps.users.models import Profile
from apps.users.tests.factories import UserFactory


class UsersApiTests(TestCase):
    def test_profile_me_creates_missing_profile(self) -> None:
        user = UserFactory(email="admin@example.com")
        Profile.objects.filter(user=user).delete()
        token = Token.objects.create(user=user)

        response = self.client.get(
            reverse("profile-me"),
            HTTP_AUTHORIZATION=f"Token {token.key}",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["email"], user.email)
        self.assertTrue(Profile.objects.filter(user=user).exists())
