from django.test import TestCase
from django.urls import reverse
from rest_framework.authtoken.models import Token

from apps.notifications.models import DeviceToken
from apps.users.tests.factories import UserFactory


class DeviceTokenApiTests(TestCase):
    def setUp(self):
        self.user = UserFactory(email="device-owner@example.com")
        self.token = Token.objects.create(user=self.user)

    def _auth(self):
        return {"HTTP_AUTHORIZATION": f"Token {self.token.key}"}

    def test_requires_authentication(self):
        post_response = self.client.post(
            reverse("notification-device-token"),
            {"token": "fcm-token-1", "platform": "android"},
            content_type="application/json",
        )
        self.assertEqual(post_response.status_code, 401)

        delete_response = self.client.delete(
            reverse("notification-device-token"),
            {"token": "fcm-token-1"},
            content_type="application/json",
        )
        self.assertEqual(delete_response.status_code, 401)

    def test_registers_a_new_device_token(self):
        response = self.client.post(
            reverse("notification-device-token"),
            {"token": "fcm-token-new", "platform": "android"},
            content_type="application/json",
            **self._auth(),
        )
        self.assertEqual(response.status_code, 200)

        device = DeviceToken.objects.get(token="fcm-token-new")
        self.assertEqual(device.user, self.user)
        self.assertEqual(device.platform, "android")

    def test_reregistering_the_same_token_for_the_same_user_does_not_duplicate(self):
        for platform in ("android", "android"):
            response = self.client.post(
                reverse("notification-device-token"),
                {"token": "fcm-token-repeat", "platform": platform},
                content_type="application/json",
                **self._auth(),
            )
            self.assertEqual(response.status_code, 200)

        self.assertEqual(DeviceToken.objects.filter(token="fcm-token-repeat").count(), 1)

    def test_registering_a_token_already_owned_by_another_user_reassigns_it(self):
        # The classic shared-device scenario: user A logs out, user B logs
        # into the same physical device, and the OS hands the app the same
        # FCM token. Registering it for B must reassign ownership so A never
        # keeps receiving B's pushes.
        other_user = UserFactory(email="previous-owner@example.com")
        DeviceToken.objects.create(user=other_user, token="fcm-token-shared", platform="ios")

        response = self.client.post(
            reverse("notification-device-token"),
            {"token": "fcm-token-shared", "platform": "ios"},
            content_type="application/json",
            **self._auth(),
        )
        self.assertEqual(response.status_code, 200)

        self.assertEqual(DeviceToken.objects.filter(token="fcm-token-shared").count(), 1)
        device = DeviceToken.objects.get(token="fcm-token-shared")
        self.assertEqual(device.user, self.user)
        self.assertFalse(DeviceToken.objects.filter(token="fcm-token-shared", user=other_user).exists())

    def test_rejects_invalid_platform(self):
        response = self.client.post(
            reverse("notification-device-token"),
            {"token": "fcm-token-bad-platform", "platform": "windows-phone"},
            content_type="application/json",
            **self._auth(),
        )
        self.assertEqual(response.status_code, 400)

    def test_deregisters_own_device_token(self):
        DeviceToken.objects.create(user=self.user, token="fcm-token-remove", platform="android")

        response = self.client.delete(
            reverse("notification-device-token"),
            {"token": "fcm-token-remove"},
            content_type="application/json",
            **self._auth(),
        )
        self.assertEqual(response.status_code, 204)
        self.assertFalse(DeviceToken.objects.filter(token="fcm-token-remove").exists())

    def test_cannot_deregister_another_users_device_token(self):
        other_user = UserFactory(email="other-owner@example.com")
        DeviceToken.objects.create(user=other_user, token="fcm-token-protected", platform="ios")

        response = self.client.delete(
            reverse("notification-device-token"),
            {"token": "fcm-token-protected"},
            content_type="application/json",
            **self._auth(),
        )
        self.assertEqual(response.status_code, 204)
        # Silently a no-op for tokens you don't own, rather than leaking
        # whether the token exists at all.
        self.assertTrue(DeviceToken.objects.filter(token="fcm-token-protected", user=other_user).exists())

    def test_deregister_of_unknown_token_is_a_harmless_no_op(self):
        response = self.client.delete(
            reverse("notification-device-token"),
            {"token": "fcm-token-never-existed"},
            content_type="application/json",
            **self._auth(),
        )
        self.assertEqual(response.status_code, 204)
