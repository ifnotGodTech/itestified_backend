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

    def test_filters_by_search_on_display_name_or_email(self):
        creator_a = _premium_user(email="grace@example.com")
        create_creator_profile(user=creator_a, display_name="Grace Restoration Ministries")
        creator_b = _premium_user(email="rivers@example.com")
        create_creator_profile(user=creator_b, display_name="Rivers of Mercy")

        self.client.force_login(self.admin)

        by_name = self.client.get(reverse("admin-creator-profile-list"), {"search": "grace"})
        self.assertEqual([row["display_name"] for row in by_name.json()["results"]], ["Grace Restoration Ministries"])

        by_email = self.client.get(reverse("admin-creator-profile-list"), {"search": "rivers@example.com"})
        self.assertEqual([row["display_name"] for row in by_email.json()["results"]], ["Rivers of Mercy"])

    def test_filters_by_verification_requested(self):
        from apps.creators.services.commands import request_creator_verification

        requested_creator = _premium_user(email="requested@example.com")
        create_creator_profile(user=requested_creator, display_name="Requested Ministry")
        request_creator_verification(user=requested_creator)
        never_requested_creator = _premium_user(email="never@example.com")
        create_creator_profile(user=never_requested_creator, display_name="Never Requested Ministry")

        self.client.force_login(self.admin)

        response = self.client.get(reverse("admin-creator-profile-list"), {"verification_requested": "true"})
        self.assertEqual([row["display_name"] for row in response.json()["results"]], ["Requested Ministry"])

    def test_includes_follower_count(self):
        from apps.creators.services.commands import follow_creator

        creator = _premium_user(email="followed@example.com")
        create_creator_profile(user=creator, display_name="Followed Ministry")
        follower_one = UserFactory(email="fan-one@example.com")
        ProfileFactory(user=follower_one, full_name="Fan One")
        follower_two = UserFactory(email="fan-two@example.com")
        ProfileFactory(user=follower_two, full_name="Fan Two")
        follow_creator(follower=follower_one, creator_user_id=creator.id)
        follow_creator(follower=follower_two, creator_user_id=creator.id)

        self.client.force_login(self.admin)
        response = self.client.get(reverse("admin-creator-profile-list"))

        row = next(r for r in response.json()["results"] if r["display_name"] == "Followed Ministry")
        self.assertEqual(row["follower_count"], 2)


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
