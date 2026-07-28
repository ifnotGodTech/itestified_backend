from django.test import TestCase
from django.urls import reverse

from apps.social_links.choices import SocialPlatform
from apps.social_links.models import SocialLink
from apps.users.choices import AdminRoleCode
from apps.users.tests.factories import AdminAssignmentFactory, AdminRoleFactory, UserFactory


class SocialLinkAdminApiTests(TestCase):
    def _admin(self, email: str):
        admin = UserFactory(email=email)
        AdminAssignmentFactory(user=admin, role=AdminRoleFactory(code=AdminRoleCode.CONTENT_ADMIN))
        return admin

    def test_list_requires_authentication(self) -> None:
        response = self.client.get(reverse("admin-social-link-list"))
        self.assertEqual(response.status_code, 403)

    def test_list_denies_non_admin_user(self) -> None:
        user = UserFactory(email="regular-social@example.com")
        self.client.force_login(user)

        response = self.client.get(reverse("admin-social-link-list"))
        self.assertEqual(response.status_code, 403)

    def test_list_returns_every_known_platform_with_empty_defaults_when_unset(self) -> None:
        admin = self._admin("social-list@example.com")
        self.client.force_login(admin)

        response = self.client.get(reverse("admin-social-link-list"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        platforms = {row["platform"]: row for row in payload}
        self.assertEqual(set(platforms.keys()), set(SocialPlatform.values))
        self.assertEqual(platforms[SocialPlatform.INSTAGRAM]["url"], "")
        self.assertFalse(platforms[SocialPlatform.INSTAGRAM]["is_active"])
        self.assertIsNone(platforms[SocialPlatform.INSTAGRAM]["updated_at"])

    def test_update_creates_a_new_link_and_records_who_set_it(self) -> None:
        admin = self._admin("social-update@example.com")
        self.client.force_login(admin)

        response = self.client.put(
            reverse("admin-social-link-update", kwargs={"platform": SocialPlatform.INSTAGRAM}),
            {"url": "https://instagram.com/itestified", "is_active": True, "display_order": 1},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        instance = SocialLink.objects.get(platform=SocialPlatform.INSTAGRAM)
        self.assertEqual(instance.url, "https://instagram.com/itestified")
        self.assertTrue(instance.is_active)
        self.assertEqual(instance.updated_by, admin)

    def test_update_overwrites_an_existing_link(self) -> None:
        admin = self._admin("social-overwrite@example.com")
        self.client.force_login(admin)
        SocialLink.objects.create(platform=SocialPlatform.FACEBOOK, url="https://facebook.com/old")

        response = self.client.put(
            reverse("admin-social-link-update", kwargs={"platform": SocialPlatform.FACEBOOK}),
            {"url": "https://facebook.com/itestified"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            SocialLink.objects.get(platform=SocialPlatform.FACEBOOK).url,
            "https://facebook.com/itestified",
        )
        self.assertEqual(SocialLink.objects.filter(platform=SocialPlatform.FACEBOOK).count(), 1)

    def test_update_can_deactivate_without_clearing_the_url(self) -> None:
        admin = self._admin("social-deactivate@example.com")
        self.client.force_login(admin)
        SocialLink.objects.create(
            platform=SocialPlatform.TIKTOK, url="https://tiktok.com/@itestified", is_active=True
        )

        response = self.client.put(
            reverse("admin-social-link-update", kwargs={"platform": SocialPlatform.TIKTOK}),
            {"is_active": False},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        instance = SocialLink.objects.get(platform=SocialPlatform.TIKTOK)
        self.assertFalse(instance.is_active)
        self.assertEqual(instance.url, "https://tiktok.com/@itestified")

    def test_update_rejects_malformed_url(self) -> None:
        admin = self._admin("social-malformed@example.com")
        self.client.force_login(admin)

        response = self.client.put(
            reverse("admin-social-link-update", kwargs={"platform": SocialPlatform.YOUTUBE}),
            {"url": "not-a-url"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(SocialLink.objects.filter(platform=SocialPlatform.YOUTUBE).exists())

    def test_update_rejects_unknown_platform(self) -> None:
        admin = self._admin("social-platform@example.com")
        self.client.force_login(admin)

        response = self.client.put(
            reverse("admin-social-link-update", kwargs={"platform": "myspace"}),
            {"url": "https://myspace.com/itestified"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)

    def test_update_denies_non_admin_user(self) -> None:
        user = UserFactory(email="regular-social-update@example.com")
        self.client.force_login(user)

        response = self.client.put(
            reverse("admin-social-link-update", kwargs={"platform": SocialPlatform.WHATSAPP}),
            {"url": "https://wa.me/2348000000000"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)


class MobileSocialLinksApiTests(TestCase):
    def test_returns_only_active_links_with_a_url_without_authentication(self) -> None:
        SocialLink.objects.create(
            platform=SocialPlatform.INSTAGRAM,
            url="https://instagram.com/itestified",
            is_active=True,
            display_order=2,
        )
        SocialLink.objects.create(
            platform=SocialPlatform.FACEBOOK,
            url="https://facebook.com/itestified",
            is_active=True,
            display_order=1,
        )
        SocialLink.objects.create(platform=SocialPlatform.X, url="", is_active=True)
        SocialLink.objects.create(
            platform=SocialPlatform.TIKTOK, url="https://tiktok.com/@itestified", is_active=False
        )

        response = self.client.get(reverse("mobile-social-links"))

        self.assertEqual(response.status_code, 200)
        result = response.json()["result"]
        self.assertEqual([row["platform"] for row in result], [SocialPlatform.FACEBOOK, SocialPlatform.INSTAGRAM])

    def test_returns_an_empty_list_when_nothing_is_configured(self) -> None:
        response = self.client.get(reverse("mobile-social-links"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["result"], [])
