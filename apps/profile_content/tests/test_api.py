from django.test import TestCase
from django.urls import reverse

from apps.profile_content.choices import ProfileContentKey
from apps.profile_content.models import ProfileContentBlock
from apps.users.choices import AdminRoleCode
from apps.users.tests.factories import AdminAssignmentFactory, AdminRoleFactory, UserFactory


class ProfileContentBlockAdminApiTests(TestCase):
    def _admin(self, email: str):
        admin = UserFactory(email=email)
        AdminAssignmentFactory(user=admin, role=AdminRoleFactory(code=AdminRoleCode.CONTENT_ADMIN))
        return admin

    def test_list_requires_authentication(self) -> None:
        response = self.client.get(reverse("admin-profile-content-block-list"))
        self.assertEqual(response.status_code, 403)

    def test_list_denies_non_admin_user(self) -> None:
        user = UserFactory(email="regular-content@example.com")
        self.client.force_login(user)

        response = self.client.get(reverse("admin-profile-content-block-list"))
        self.assertEqual(response.status_code, 403)

    def test_list_returns_every_known_key_with_empty_default_when_unset(self) -> None:
        # A data migration seeds real starting copy for every key (so making
        # this dashboard-editable doesn't blank out already-shipped app
        # content) -- clear it here to test the genuinely-never-configured path.
        ProfileContentBlock.objects.all().delete()
        admin = self._admin("content-list@example.com")
        self.client.force_login(admin)

        response = self.client.get(reverse("admin-profile-content-block-list"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        keys = {row["key"]: row for row in payload}
        self.assertEqual(set(keys.keys()), set(ProfileContentKey.values))
        self.assertEqual(keys[ProfileContentKey.ABOUT_US]["body"], "")
        self.assertIsNone(keys[ProfileContentKey.ABOUT_US]["updated_at"])

    def test_update_creates_a_new_block_and_records_who_set_it(self) -> None:
        ProfileContentBlock.objects.all().delete()
        admin = self._admin("content-update@example.com")
        self.client.force_login(admin)

        response = self.client.put(
            reverse("admin-profile-content-block-update", kwargs={"key": ProfileContentKey.ABOUT_US}),
            {"body": "Welcome to iTestified, updated."},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        instance = ProfileContentBlock.objects.get(key=ProfileContentKey.ABOUT_US)
        self.assertEqual(instance.body, "Welcome to iTestified, updated.")
        self.assertEqual(instance.updated_by, admin)

    def test_update_overwrites_an_existing_block(self) -> None:
        admin = self._admin("content-overwrite@example.com")
        self.client.force_login(admin)
        ProfileContentBlock.objects.filter(key=ProfileContentKey.TERMS_OF_USE).update(body="Old terms.")

        response = self.client.put(
            reverse("admin-profile-content-block-update", kwargs={"key": ProfileContentKey.TERMS_OF_USE}),
            {"body": "New terms."},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            ProfileContentBlock.objects.get(key=ProfileContentKey.TERMS_OF_USE).body, "New terms."
        )
        self.assertEqual(ProfileContentBlock.objects.filter(key=ProfileContentKey.TERMS_OF_USE).count(), 1)

    def test_update_rejects_unknown_key(self) -> None:
        admin = self._admin("content-unknown@example.com")
        self.client.force_login(admin)

        response = self.client.put(
            reverse("admin-profile-content-block-update", kwargs={"key": "refund_policy"}),
            {"body": "Not a real key."},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)

    def test_update_denies_non_admin_user(self) -> None:
        user = UserFactory(email="regular-content-update@example.com")
        self.client.force_login(user)

        response = self.client.put(
            reverse("admin-profile-content-block-update", kwargs={"key": ProfileContentKey.PRIVACY_POLICY}),
            {"body": "Attempted edit."},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)

    def test_update_accepts_a_well_formed_support_email(self) -> None:
        admin = self._admin("content-email-valid@example.com")
        self.client.force_login(admin)

        response = self.client.put(
            reverse("admin-profile-content-block-update", kwargs={"key": ProfileContentKey.SUPPORT_EMAIL}),
            {"body": "help@itestified.app"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            ProfileContentBlock.objects.get(key=ProfileContentKey.SUPPORT_EMAIL).body, "help@itestified.app"
        )

    def test_update_rejects_a_malformed_support_email(self) -> None:
        admin = self._admin("content-email-invalid@example.com")
        self.client.force_login(admin)
        ProfileContentBlock.objects.filter(key=ProfileContentKey.SUPPORT_EMAIL).update(body="original@example.com")

        response = self.client.put(
            reverse("admin-profile-content-block-update", kwargs={"key": ProfileContentKey.SUPPORT_EMAIL}),
            {"body": "not-an-email"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            ProfileContentBlock.objects.get(key=ProfileContentKey.SUPPORT_EMAIL).body, "original@example.com"
        )

    def test_update_accepts_a_well_formed_support_phone(self) -> None:
        admin = self._admin("content-phone-valid@example.com")
        self.client.force_login(admin)

        response = self.client.put(
            reverse("admin-profile-content-block-update", kwargs={"key": ProfileContentKey.SUPPORT_PHONE}),
            {"body": "+234 806 146 4092"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)

    def test_update_rejects_a_malformed_support_phone(self) -> None:
        admin = self._admin("content-phone-invalid@example.com")
        self.client.force_login(admin)

        response = self.client.put(
            reverse("admin-profile-content-block-update", kwargs={"key": ProfileContentKey.SUPPORT_PHONE}),
            {"body": "call us maybe"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)

    def test_update_does_not_apply_email_validation_to_other_keys(self) -> None:
        # Regression guard: the key-specific validation in validate_body must
        # only fire for its own key, not leak onto About Us/Terms/Privacy.
        admin = self._admin("content-no-leak@example.com")
        self.client.force_login(admin)

        response = self.client.put(
            reverse("admin-profile-content-block-update", kwargs={"key": ProfileContentKey.ABOUT_US}),
            {"body": "not an email and not a phone number, just About Us text."},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)


class MobileProfileContentBlocksApiTests(TestCase):
    def test_returns_every_key_without_authentication(self) -> None:
        ProfileContentBlock.objects.filter(key=ProfileContentKey.ABOUT_US).update(body="About text.")
        ProfileContentBlock.objects.filter(
            key__in=[ProfileContentKey.TERMS_OF_USE, ProfileContentKey.PRIVACY_POLICY]
        ).delete()

        response = self.client.get(reverse("mobile-profile-content-blocks"))

        self.assertEqual(response.status_code, 200)
        result = response.json()["result"]
        self.assertEqual(result["about_us"], "About text.")
        # Never-configured keys are blank, not missing -- mobile always gets
        # a value for every key it expects.
        self.assertEqual(result["terms_of_use"], "")
        self.assertEqual(result["privacy_policy"], "")
        # Seeded by the Slice 5 data migration -- confirms support contact
        # info is served through this same endpoint.
        self.assertEqual(result["support_email"], "ifnotgodtech@gmail.com")
        self.assertEqual(result["support_phone"], "+2348061464092")
