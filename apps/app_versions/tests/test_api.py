from django.test import TestCase
from django.urls import reverse

from apps.app_versions.choices import AppPlatform
from apps.app_versions.models import AppVersionConfig
from apps.users.choices import AdminRoleCode
from apps.users.tests.factories import AdminAssignmentFactory, AdminRoleFactory, UserFactory


class AppVersionAdminApiTests(TestCase):
    def _super_admin(self, email: str):
        admin = UserFactory(email=email)
        AdminAssignmentFactory(user=admin, role=AdminRoleFactory(code=AdminRoleCode.SUPER_ADMIN))
        return admin

    def test_list_requires_authentication(self) -> None:
        response = self.client.get(reverse("admin-app-version-list"))
        self.assertEqual(response.status_code, 403)

    def test_list_denies_non_admin_user(self) -> None:
        user = UserFactory(email="regular@example.com")
        self.client.force_login(user)

        response = self.client.get(reverse("admin-app-version-list"))
        self.assertEqual(response.status_code, 403)

    def test_list_denies_active_admin_who_is_not_super_admin(self) -> None:
        moderator = UserFactory(email="moderator@example.com")
        AdminAssignmentFactory(user=moderator, role=AdminRoleFactory(code=AdminRoleCode.MODERATOR))
        self.client.force_login(moderator)

        response = self.client.get(reverse("admin-app-version-list"))
        self.assertEqual(response.status_code, 403)

    def test_list_returns_both_platforms_with_empty_defaults_when_unset(self) -> None:
        admin = self._super_admin("super-list@example.com")
        self.client.force_login(admin)

        response = self.client.get(reverse("admin-app-version-list"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        platforms = {row["platform"]: row for row in payload}
        self.assertEqual(set(platforms.keys()), {AppPlatform.ANDROID, AppPlatform.IOS})
        self.assertEqual(platforms[AppPlatform.ANDROID]["minimum_version"], "")
        self.assertIsNone(platforms[AppPlatform.ANDROID]["updated_at"])

    def test_update_creates_a_new_requirement_and_records_who_set_it(self) -> None:
        admin = self._super_admin("super-update@example.com")
        self.client.force_login(admin)

        response = self.client.put(
            reverse("admin-app-version-update", kwargs={"platform": AppPlatform.ANDROID}),
            {"minimum_version": "1.2.0"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["minimum_version"], "1.2.0")
        instance = AppVersionConfig.objects.get(platform=AppPlatform.ANDROID)
        self.assertEqual(instance.minimum_version, "1.2.0")
        self.assertEqual(instance.updated_by, admin)

    def test_update_overwrites_an_existing_requirement(self) -> None:
        admin = self._super_admin("super-overwrite@example.com")
        self.client.force_login(admin)
        AppVersionConfig.objects.create(platform=AppPlatform.IOS, minimum_version="1.0.0")

        response = self.client.put(
            reverse("admin-app-version-update", kwargs={"platform": AppPlatform.IOS}),
            {"minimum_version": "2.0.0"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            AppVersionConfig.objects.get(platform=AppPlatform.IOS).minimum_version, "2.0.0"
        )
        self.assertEqual(AppVersionConfig.objects.filter(platform=AppPlatform.IOS).count(), 1)

    def test_update_rejects_malformed_version(self) -> None:
        admin = self._super_admin("super-malformed@example.com")
        self.client.force_login(admin)

        response = self.client.put(
            reverse("admin-app-version-update", kwargs={"platform": AppPlatform.ANDROID}),
            {"minimum_version": "not-a-version"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(AppVersionConfig.objects.filter(platform=AppPlatform.ANDROID).exists())

    def test_update_rejects_unknown_platform(self) -> None:
        admin = self._super_admin("super-platform@example.com")
        self.client.force_login(admin)

        response = self.client.put(
            reverse("admin-app-version-update", kwargs={"platform": "windows"}),
            {"minimum_version": "1.0.0"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)

    def test_update_denies_active_admin_who_is_not_super_admin(self) -> None:
        moderator = UserFactory(email="moderator-update@example.com")
        AdminAssignmentFactory(user=moderator, role=AdminRoleFactory(code=AdminRoleCode.MODERATOR))
        self.client.force_login(moderator)

        response = self.client.put(
            reverse("admin-app-version-update", kwargs={"platform": AppPlatform.ANDROID}),
            {"minimum_version": "1.0.0"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)
