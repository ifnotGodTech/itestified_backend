"""Phase 23 follow-up -- Ministry avatar photo, deliberately separate from
Profile.avatar (the personal account photo). Mirrors
apps.users.api.views.ProfileAvatarUploadSignatureView's own tests."""

from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from rest_framework.authtoken.models import Token

from apps.common.services.media_uploads import CloudinaryUploadError, CloudinaryUploadSignature
from apps.creators.models import CreatorProfile
from apps.creators.services.commands import create_creator_profile, update_creator_profile
from apps.subscriptions.models import Subscription, SubscriptionStatus
from apps.users.tests.factories import ProfileFactory, UserFactory


def _premium_user(email="premium@example.com"):
    user = UserFactory(email=email)
    ProfileFactory(user=user, full_name="Premium User")
    Subscription.objects.create(user=user, amount=300000, payment_reference=f"SUB-{email}", status=SubscriptionStatus.ACTIVE)
    return user


def _free_user(email="free@example.com"):
    user = UserFactory(email=email)
    ProfileFactory(user=user, full_name="Free User")
    return user


class CreatorProfileAvatarServiceTests(TestCase):
    def test_create_stores_the_avatar_url(self):
        user = _premium_user()
        profile = create_creator_profile(
            user=user, display_name="Grace Restoration Ministries", avatar_url="https://cloudinary.example/a.jpg"
        )
        self.assertEqual(profile.avatar_url, "https://cloudinary.example/a.jpg")

    def test_update_changes_the_avatar_url(self):
        user = _premium_user()
        create_creator_profile(user=user, display_name="Grace Restoration Ministries")
        updated = update_creator_profile(user=user, avatar_url="https://cloudinary.example/new.jpg")
        self.assertEqual(updated.avatar_url, "https://cloudinary.example/new.jpg")

    def test_update_without_avatar_url_leaves_it_untouched(self):
        user = _premium_user()
        create_creator_profile(user=user, display_name="X", avatar_url="https://cloudinary.example/a.jpg")
        updated = update_creator_profile(user=user, display_name="Y")
        self.assertEqual(updated.avatar_url, "https://cloudinary.example/a.jpg")


class CreatorAvatarUploadSignatureApiTests(TestCase):
    def _auth_headers(self, user):
        token = Token.objects.create(user=user)
        return {"HTTP_AUTHORIZATION": f"Token {token.key}"}

    def test_requires_authentication(self):
        response = self.client.post(reverse("creator-avatar-upload-signature"))
        self.assertEqual(response.status_code, 401)

    def test_a_free_user_is_rejected_with_403(self):
        user = _free_user()
        response = self.client.post(reverse("creator-avatar-upload-signature"), **self._auth_headers(user))
        self.assertEqual(response.status_code, 403)
        self.assertIn("Premium", response.json()["message"])

    @patch("apps.creators.api.views.create_direct_upload_signature")
    def test_a_premium_user_gets_a_signed_payload_for_the_creator_avatar_folder(self, signature_mock):
        user = _premium_user()
        signature_mock.return_value = CloudinaryUploadSignature(
            cloud_name="demo",
            api_key="12345",
            timestamp=1784720000,
            folder="itestified/creators/avatars",
            signature="signed-payload",
        )

        response = self.client.post(reverse("creator-avatar-upload-signature"), **self._auth_headers(user))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "cloud_name": "demo",
                "api_key": "12345",
                "timestamp": 1784720000,
                "folder": "itestified/creators/avatars",
                "signature": "signed-payload",
                "resource_type": "image",
            },
        )
        signature_mock.assert_called_once_with(resource_type="creator_avatar")

    @patch("apps.creators.api.views.create_direct_upload_signature")
    def test_surfaces_a_cloudinary_configuration_error(self, signature_mock):
        user = _premium_user()
        signature_mock.side_effect = CloudinaryUploadError("Cloudinary direct upload credentials are incomplete.")

        response = self.client.post(reverse("creator-avatar-upload-signature"), **self._auth_headers(user))

        self.assertEqual(response.status_code, 400)
        self.assertIn("Cloudinary", response.json()["message"])


class CreatorProfileAvatarApiTests(TestCase):
    def _auth_headers(self, user):
        token = Token.objects.create(user=user)
        return {"HTTP_AUTHORIZATION": f"Token {token.key}"}

    def test_creating_a_profile_with_an_avatar_url_persists_it(self):
        user = _premium_user()
        response = self.client.post(
            reverse("creator-profile-me"),
            {"display_name": "Grace Restoration Ministries", "avatar_url": "https://cloudinary.example/a.jpg"},
            content_type="application/json",
            **self._auth_headers(user),
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["avatar_url"], "https://cloudinary.example/a.jpg")
        self.assertEqual(CreatorProfile.objects.get(user=user).avatar_url, "https://cloudinary.example/a.jpg")

    def test_public_profile_exposes_the_avatar_url(self):
        creator = _premium_user(email="creator@example.com")
        create_creator_profile(user=creator, display_name="Grace Restoration Ministries", avatar_url="https://cloudinary.example/a.jpg")
        viewer = _free_user(email="viewer@example.com")

        response = self.client.get(
            reverse("creator-profile-detail", kwargs={"user_id": creator.id}), **self._auth_headers(viewer)
        )

        self.assertEqual(response.json()["avatar_url"], "https://cloudinary.example/a.jpg")
