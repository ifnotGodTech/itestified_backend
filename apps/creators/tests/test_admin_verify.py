"""Phase 23 Slice 5 (admin) -- verify/unverify a creator/ministry."""

from django.test import TestCase
from django.urls import reverse

from apps.creators.models import CreatorProfile
from apps.creators.services.commands import create_creator_profile, verify_creator_profile
from apps.subscriptions.models import Subscription, SubscriptionStatus
from apps.testimonies.models import Testimony, TestimonyCategory, TestimonyStatus, TestimonyType
from apps.users.choices import AdminRoleCode
from apps.users.tests.factories import AdminAssignmentFactory, AdminRoleFactory, ProfileFactory, UserFactory


def _premium_user(email="premium@example.com"):
    user = UserFactory(email=email)
    ProfileFactory(user=user, full_name="Premium User")
    Subscription.objects.create(user=user, amount=300000, payment_reference=f"SUB-{email}", status=SubscriptionStatus.ACTIVE)
    return user


class VerifyCreatorProfileServiceTests(TestCase):
    def test_verifying_sets_verified_at_and_verified_by(self):
        creator = _premium_user()
        profile = create_creator_profile(user=creator, display_name="Grace Restoration Ministries")
        admin = UserFactory(email="admin@example.com")
        ProfileFactory(user=admin, full_name="Admin")

        updated = verify_creator_profile(creator_profile=profile, admin_user=admin, is_verified=True)

        self.assertTrue(updated.is_verified)
        self.assertIsNotNone(updated.verified_at)
        self.assertEqual(updated.verified_by, admin)

    def test_unverifying_clears_verified_at_and_verified_by(self):
        creator = _premium_user()
        profile = create_creator_profile(user=creator, display_name="Grace Restoration Ministries")
        admin = UserFactory(email="admin@example.com")
        ProfileFactory(user=admin, full_name="Admin")
        verify_creator_profile(creator_profile=profile, admin_user=admin, is_verified=True)

        updated = verify_creator_profile(creator_profile=profile, admin_user=admin, is_verified=False)

        self.assertFalse(updated.is_verified)
        self.assertIsNone(updated.verified_at)
        self.assertIsNone(updated.verified_by)

    def test_verification_never_touches_the_creators_testimonies(self):
        creator = _premium_user()
        profile = create_creator_profile(user=creator, display_name="Grace Restoration Ministries")
        category = TestimonyCategory.objects.create(name="Healing", slug="healing")
        testimony = Testimony.objects.create(
            author=creator, category=category, title="Restoration", body="Body.",
            testimony_type=TestimonyType.WRITTEN, status=TestimonyStatus.PENDING_REVIEW,
        )
        admin = UserFactory(email="admin@example.com")
        ProfileFactory(user=admin, full_name="Admin")

        verify_creator_profile(creator_profile=profile, admin_user=admin, is_verified=True)

        testimony.refresh_from_db()
        self.assertEqual(testimony.status, TestimonyStatus.PENDING_REVIEW)


class AdminCreatorProfileApiTestsBase(TestCase):
    def setUp(self) -> None:
        self.admin = UserFactory(email="creator-admin@example.com")
        ProfileFactory(user=self.admin, full_name="Creator Admin")
        role = AdminRoleFactory(code=AdminRoleCode.SUPER_ADMIN)
        AdminAssignmentFactory(user=self.admin, role=role)


class AdminCreatorProfileListApiTests(AdminCreatorProfileApiTestsBase):
    def test_requires_admin_session(self):
        response = self.client.get(reverse("admin-creator-profile-list"))
        self.assertEqual(response.status_code, 403)

    def test_lists_profiles_and_filters_by_verified_status(self):
        creator_a = _premium_user(email="a@example.com")
        create_creator_profile(user=creator_a, display_name="Ministry A")
        creator_b = _premium_user(email="b@example.com")
        profile_b = create_creator_profile(user=creator_b, display_name="Ministry B")
        verify_creator_profile(creator_profile=profile_b, admin_user=self.admin, is_verified=True)

        self.client.force_login(self.admin)
        response = self.client.get(reverse("admin-creator-profile-list"), {"is_verified": "true"})

        self.assertEqual(response.status_code, 200)
        results = response.json()["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["display_name"], "Ministry B")


class AdminCreatorProfileVerifyApiTests(AdminCreatorProfileApiTestsBase):
    def test_requires_admin_session(self):
        creator = _premium_user()
        create_creator_profile(user=creator, display_name="Grace Restoration Ministries")
        response = self.client.post(reverse("admin-creator-profile-verify", kwargs={"user_id": creator.id}))
        self.assertEqual(response.status_code, 403)

    def test_verifies_a_creator(self):
        creator = _premium_user()
        create_creator_profile(user=creator, display_name="Grace Restoration Ministries")
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("admin-creator-profile-verify", kwargs={"user_id": creator.id}),
            {"is_verified": True},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["is_verified"])
        self.assertEqual(body["verified_by_email"], self.admin.email)

    def test_404_for_a_user_with_no_ministry_profile(self):
        no_profile_user = UserFactory(email="no-profile@example.com")
        ProfileFactory(user=no_profile_user, full_name="No Profile")
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("admin-creator-profile-verify", kwargs={"user_id": no_profile_user.id}),
            {"is_verified": True},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)

    def test_unverifies_a_creator(self):
        creator = _premium_user()
        profile = create_creator_profile(user=creator, display_name="Grace Restoration Ministries")
        verify_creator_profile(creator_profile=profile, admin_user=self.admin, is_verified=True)
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("admin-creator-profile-verify", kwargs={"user_id": creator.id}),
            {"is_verified": False},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["is_verified"])
