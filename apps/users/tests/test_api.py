from django.test import TestCase
from django.urls import reverse
from rest_framework.authtoken.models import Token

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
