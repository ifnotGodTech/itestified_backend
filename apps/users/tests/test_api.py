from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from rest_framework.authtoken.models import Token

from apps.common.services.media_uploads import CloudinaryUploadError, CloudinaryUploadSignature
from apps.testimonies.models import (
    Testimony,
    TestimonyCategory,
    TestimonyFavorite,
    TestimonyReaction,
    TestimonyReactionType,
    TestimonyStatus,
    TestimonyType,
    TestimonyWatch,
)
from apps.users.choices import AdminRoleCode, UserAccountStatus
from apps.users.models import Profile
from apps.users.tests.factories import AdminAssignmentFactory, AdminRoleFactory, ProfileFactory, UserFactory


class UsersApiTests(TestCase):
    def test_profile_me_requires_authentication(self) -> None:
        response = self.client.get(reverse("profile-me"))
        self.assertEqual(response.status_code, 403)

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

    def test_profile_me_patch_requires_authentication(self) -> None:
        response = self.client.patch(
            reverse("profile-me"),
            {"full_name": "New Name"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_profile_me_patch_updates_full_name_and_avatar(self) -> None:
        user = UserFactory(email="patch-profile@example.com")
        ProfileFactory(user=user, full_name="Old Name", avatar="")
        token = Token.objects.create(user=user)

        response = self.client.patch(
            reverse("profile-me"),
            {"full_name": "New Name", "avatar": "https://res.cloudinary.com/demo/image/upload/avatar.jpg"},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Token {token.key}",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["full_name"], "New Name")
        self.assertEqual(response.json()["avatar"], "https://res.cloudinary.com/demo/image/upload/avatar.jpg")
        profile = Profile.objects.get(user=user)
        self.assertEqual(profile.full_name, "New Name")
        self.assertEqual(profile.avatar, "https://res.cloudinary.com/demo/image/upload/avatar.jpg")

    def test_profile_me_patch_normalizes_full_name_casing(self) -> None:
        user = UserFactory(email="caps-name@example.com")
        ProfileFactory(user=user, full_name="Old Name")
        token = Token.objects.create(user=user)

        response = self.client.patch(
            reverse("profile-me"),
            {"full_name": "AIGUOSATILE AISOSA"},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Token {token.key}",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["full_name"], "Aiguosatile Aisosa")
        self.assertEqual(Profile.objects.get(user=user).full_name, "Aiguosatile Aisosa")

    def test_profile_me_patch_supports_partial_update(self) -> None:
        user = UserFactory(email="partial-patch@example.com")
        ProfileFactory(user=user, full_name="Keep Me", avatar="https://res.cloudinary.com/demo/image/upload/old.jpg")
        token = Token.objects.create(user=user)

        response = self.client.patch(
            reverse("profile-me"),
            {"avatar": "https://res.cloudinary.com/demo/image/upload/new.jpg"},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Token {token.key}",
        )

        self.assertEqual(response.status_code, 200)
        profile = Profile.objects.get(user=user)
        self.assertEqual(profile.full_name, "Keep Me")
        self.assertEqual(profile.avatar, "https://res.cloudinary.com/demo/image/upload/new.jpg")

    def test_profile_me_patch_rejects_empty_full_name(self) -> None:
        user = UserFactory(email="empty-name@example.com")
        ProfileFactory(user=user, full_name="Has A Name")
        token = Token.objects.create(user=user)

        response = self.client.patch(
            reverse("profile-me"),
            {"full_name": ""},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Token {token.key}",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Profile.objects.get(user=user).full_name, "Has A Name")

    def test_profile_me_patch_rejects_non_url_avatar(self) -> None:
        user = UserFactory(email="bad-avatar@example.com")
        ProfileFactory(user=user)
        token = Token.objects.create(user=user)

        response = self.client.patch(
            reverse("profile-me"),
            {"avatar": "not-a-url"},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Token {token.key}",
        )

        self.assertEqual(response.status_code, 400)

    def test_avatar_upload_signature_requires_authentication(self) -> None:
        response = self.client.post(reverse("profile-avatar-upload-signature"))
        self.assertEqual(response.status_code, 403)

    @patch("apps.users.api.views.create_direct_upload_signature")
    def test_avatar_upload_signature_returns_signed_cloudinary_payload(self, signature_mock) -> None:
        user = UserFactory(email="avatar-signature@example.com")
        token = Token.objects.create(user=user)
        signature_mock.return_value = CloudinaryUploadSignature(
            cloud_name="demo",
            api_key="12345",
            timestamp=1784720000,
            folder="itestified/profile/avatars",
            signature="signed-payload",
        )

        response = self.client.post(
            reverse("profile-avatar-upload-signature"),
            HTTP_AUTHORIZATION=f"Token {token.key}",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "cloud_name": "demo",
                "api_key": "12345",
                "timestamp": 1784720000,
                "folder": "itestified/profile/avatars",
                "signature": "signed-payload",
                "resource_type": "image",
            },
        )
        signature_mock.assert_called_once_with(resource_type="avatar")

    @patch("apps.users.api.views.create_direct_upload_signature")
    def test_avatar_upload_signature_surfaces_configuration_error(self, signature_mock) -> None:
        user = UserFactory(email="avatar-signature-error@example.com")
        token = Token.objects.create(user=user)
        signature_mock.side_effect = CloudinaryUploadError("Cloudinary direct upload credentials are incomplete.")

        response = self.client.post(
            reverse("profile-avatar-upload-signature"),
            HTTP_AUTHORIZATION=f"Token {token.key}",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Cloudinary", response.json()["message"])

    def test_admin_can_list_filter_and_deactivate_reactivate_users(self) -> None:
        admin = UserFactory(email="admin-users@example.com")
        AdminAssignmentFactory(user=admin, role=AdminRoleFactory(code=AdminRoleCode.SUPER_ADMIN))
        self.client.force_login(admin)

        active_user = UserFactory(email="active@example.com")
        ProfileFactory(user=active_user, full_name="Active User")
        deactivated_user = UserFactory(
            email="deactivated@example.com",
            account_status=UserAccountStatus.DEACTIVATED,
        )
        ProfileFactory(user=deactivated_user, full_name="Deactivated User")

        list_response = self.client.get(reverse("admin-user-list"))
        self.assertEqual(list_response.status_code, 200)
        self.assertGreaterEqual(list_response.json()["count"], 2)

        filtered = self.client.get(f'{reverse("admin-user-list")}?status=deactivated&q=deactivated')
        self.assertEqual(filtered.status_code, 200)
        self.assertEqual(filtered.json()["count"], 1)
        self.assertEqual(filtered.json()["results"][0]["email"], "deactivated@example.com")

        name_filtered = self.client.get(f'{reverse("admin-user-list")}?q=Active User')
        self.assertEqual(name_filtered.status_code, 200)
        self.assertEqual(name_filtered.json()["count"], 1)
        self.assertEqual(name_filtered.json()["results"][0]["email"], "active@example.com")

        user_id_filtered = self.client.get(f'{reverse("admin-user-list")}?q=U{str(active_user.id).zfill(5)}')
        self.assertEqual(user_id_filtered.status_code, 200)
        self.assertEqual(user_id_filtered.json()["count"], 1)
        self.assertEqual(user_id_filtered.json()["results"][0]["email"], "active@example.com")

        deactivate_response = self.client.post(
            reverse("admin-user-deactivate", kwargs={"user_id": active_user.id}),
            {},
            content_type="application/json",
        )
        self.assertEqual(deactivate_response.status_code, 200)
        active_user.refresh_from_db()
        self.assertEqual(active_user.account_status, UserAccountStatus.DEACTIVATED)

        reactivate_response = self.client.post(
            reverse("admin-user-reactivate", kwargs={"user_id": active_user.id}),
            {},
            content_type="application/json",
        )
        self.assertEqual(reactivate_response.status_code, 200)
        active_user.refresh_from_db()
        self.assertEqual(active_user.account_status, UserAccountStatus.ACTIVE)


class ProfileJourneyApiTests(TestCase):
    """Phase 18 Slice 3: the private "Your Journey" card's real numbers."""

    def setUp(self) -> None:
        self.user = UserFactory(email="journey-user@example.com")
        ProfileFactory(user=self.user, full_name="Journey User")
        self.token = Token.objects.create(user=self.user)

        self.category_healing = TestimonyCategory.objects.create(
            name="Healing", slug="healing", is_active=True
        )
        self.category_faith = TestimonyCategory.objects.create(
            name="Faith", slug="faith", is_active=True
        )
        author = UserFactory(email="journey-author@example.com")
        ProfileFactory(user=author, full_name="Journey Author")

        def make_testimony(title: str, category: TestimonyCategory) -> Testimony:
            return Testimony.objects.create(
                author=author,
                category=category,
                title=title,
                body="Body text.",
                testimony_type=TestimonyType.WRITTEN,
                status=TestimonyStatus.APPROVED,
            )

        self.healing_a = make_testimony("Healing A", self.category_healing)
        self.healing_b = make_testimony("Healing B", self.category_healing)
        self.faith_a = make_testimony("Faith A", self.category_faith)

    def test_requires_authentication(self) -> None:
        response = self.client.get(reverse("profile-journey"))
        self.assertEqual(response.status_code, 403)

    def test_returns_zero_counts_and_no_theme_for_a_user_with_no_signal(self) -> None:
        response = self.client.get(
            reverse("profile-journey"),
            HTTP_AUTHORIZATION=f"Token {self.token.key}",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "watched_count": 0,
                "favorited_count": 0,
                "most_visited_theme": None,
                "theme_distribution": [],
            },
        )

    def test_watched_count_matches_distinct_testimonies_watched(self) -> None:
        TestimonyWatch.objects.create(user=self.user, testimony=self.healing_a)
        TestimonyWatch.objects.create(user=self.user, testimony=self.faith_a)

        response = self.client.get(
            reverse("profile-journey"),
            HTTP_AUTHORIZATION=f"Token {self.token.key}",
        )

        self.assertEqual(response.json()["watched_count"], 2)

    def test_favorited_count_matches_the_favorites_table(self) -> None:
        TestimonyFavorite.objects.create(user=self.user, testimony=self.healing_a)

        response = self.client.get(
            reverse("profile-journey"),
            HTTP_AUTHORIZATION=f"Token {self.token.key}",
        )

        self.assertEqual(response.json()["favorited_count"], 1)

    def test_most_visited_theme_picks_the_actual_top_category_across_all_three_signals(
        self,
    ) -> None:
        # Healing gets 3 signals (2 watches + 1 favorite), Faith gets 1
        # (a reaction) -- Healing should win even though no single table
        # alone would show it as the clear favorite.
        TestimonyWatch.objects.create(user=self.user, testimony=self.healing_a)
        TestimonyWatch.objects.create(user=self.user, testimony=self.healing_b)
        TestimonyFavorite.objects.create(user=self.user, testimony=self.healing_a)
        TestimonyReaction.objects.create(
            user=self.user,
            testimony=self.faith_a,
            reaction_type=TestimonyReactionType.AMEN,
        )

        response = self.client.get(
            reverse("profile-journey"),
            HTTP_AUTHORIZATION=f"Token {self.token.key}",
        )

        self.assertEqual(response.json()["most_visited_theme"], "Healing")

    def test_theme_distribution_ranks_categories_by_combined_signal_count(
        self,
    ) -> None:
        TestimonyWatch.objects.create(user=self.user, testimony=self.healing_a)
        TestimonyWatch.objects.create(user=self.user, testimony=self.healing_b)
        TestimonyFavorite.objects.create(user=self.user, testimony=self.healing_a)
        TestimonyReaction.objects.create(
            user=self.user,
            testimony=self.faith_a,
            reaction_type=TestimonyReactionType.AMEN,
        )

        response = self.client.get(
            reverse("profile-journey"),
            HTTP_AUTHORIZATION=f"Token {self.token.key}",
        )

        self.assertEqual(
            response.json()["theme_distribution"],
            [{"theme": "Healing", "count": 3}, {"theme": "Faith", "count": 1}],
        )

    def test_theme_distribution_caps_at_the_top_four_categories(self) -> None:
        extra_categories = [
            TestimonyCategory.objects.create(name=name, slug=name.lower(), is_active=True)
            for name in ("Deliverance", "Salvation", "Provision")
        ]
        author = Testimony.objects.filter(pk=self.healing_a.pk).get().author
        for category in extra_categories:
            testimony = Testimony.objects.create(
                author=author,
                category=category,
                title=f"{category.name} testimony",
                body="Body text.",
                testimony_type=TestimonyType.WRITTEN,
                status=TestimonyStatus.APPROVED,
            )
            TestimonyWatch.objects.create(user=self.user, testimony=testimony)
        TestimonyWatch.objects.create(user=self.user, testimony=self.healing_a)
        TestimonyWatch.objects.create(user=self.user, testimony=self.faith_a)

        response = self.client.get(
            reverse("profile-journey"),
            HTTP_AUTHORIZATION=f"Token {self.token.key}",
        )

        self.assertEqual(len(response.json()["theme_distribution"]), 4)
