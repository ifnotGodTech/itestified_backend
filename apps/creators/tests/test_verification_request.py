"""Phase 23 Slice 14 -- owner-initiated verification request, and the
admin list's resulting queue ordering (oldest requested first)."""

from django.test import TestCase
from django.urls import reverse

from apps.creators.exceptions import CreatorProfileNotFoundError
from apps.creators.services.commands import create_creator_profile, request_creator_verification, verify_creator_profile
from apps.subscriptions.models import Subscription, SubscriptionStatus
from apps.users.choices import AdminRoleCode
from apps.users.tests.factories import AdminAssignmentFactory, AdminRoleFactory, ProfileFactory, UserFactory


def _premium_user(email="premium@example.com"):
    user = UserFactory(email=email)
    ProfileFactory(user=user, full_name="Premium User")
    Subscription.objects.create(user=user, amount=300000, payment_reference=f"SUB-{email}", status=SubscriptionStatus.ACTIVE)
    return user


class RequestCreatorVerificationServiceTests(TestCase):
    def test_sets_verification_requested_at(self):
        creator = _premium_user()
        create_creator_profile(user=creator, display_name="Grace Restoration Ministries")

        updated = request_creator_verification(user=creator)

        self.assertIsNotNone(updated.verification_requested_at)

    def test_a_second_request_does_not_move_the_original_timestamp(self):
        creator = _premium_user()
        create_creator_profile(user=creator, display_name="Grace Restoration Ministries")

        first = request_creator_verification(user=creator)
        second = request_creator_verification(user=creator)

        self.assertEqual(first.verification_requested_at, second.verification_requested_at)

    def test_requesting_after_already_verified_is_a_no_op(self):
        creator = _premium_user()
        profile = create_creator_profile(user=creator, display_name="Grace Restoration Ministries")
        admin = UserFactory(email="admin@example.com")
        ProfileFactory(user=admin, full_name="Admin")
        verify_creator_profile(creator_profile=profile, admin_user=admin, is_verified=True)

        updated = request_creator_verification(user=creator)

        self.assertIsNone(updated.verification_requested_at)
        self.assertTrue(updated.is_verified)

    def test_raises_when_no_profile_exists(self):
        no_profile_user = UserFactory(email="no-profile@example.com")
        ProfileFactory(user=no_profile_user, full_name="No Profile")

        with self.assertRaises(CreatorProfileNotFoundError):
            request_creator_verification(user=no_profile_user)


class RequestCreatorVerificationApiTests(TestCase):
    def test_requires_authentication(self):
        response = self.client.post(reverse("creator-request-verification"))
        self.assertEqual(response.status_code, 401)

    def test_requests_verification_for_the_authenticated_users_profile(self):
        from rest_framework.authtoken.models import Token

        creator = _premium_user()
        create_creator_profile(user=creator, display_name="Grace Restoration Ministries")
        token = Token.objects.create(user=creator)

        response = self.client.post(
            reverse("creator-request-verification"), HTTP_AUTHORIZATION=f"Token {token.key}"
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.json()["verification_requested_at"])

    def test_404_when_no_profile_exists(self):
        from rest_framework.authtoken.models import Token

        user = UserFactory(email="no-profile@example.com")
        ProfileFactory(user=user, full_name="No Profile")
        token = Token.objects.create(user=user)

        response = self.client.post(
            reverse("creator-request-verification"), HTTP_AUTHORIZATION=f"Token {token.key}"
        )

        self.assertEqual(response.status_code, 404)


class AdminCreatorProfileQueueOrderingTests(TestCase):
    """The admin list (Slice 5) doubles as Slice 14's queue: requested,
    unverified profiles surface first, oldest request first."""

    def setUp(self) -> None:
        self.admin = UserFactory(email="creator-admin@example.com")
        ProfileFactory(user=self.admin, full_name="Creator Admin")
        role = AdminRoleFactory(code=AdminRoleCode.SUPER_ADMIN)
        AdminAssignmentFactory(user=self.admin, role=role)

    def test_requested_profiles_surface_before_never_requested_ones(self):
        never_requested = _premium_user(email="never@example.com")
        create_creator_profile(user=never_requested, display_name="Never Requested Ministry")

        requested_first = _premium_user(email="first@example.com")
        create_creator_profile(user=requested_first, display_name="First Requester")
        request_creator_verification(user=requested_first)

        requested_second = _premium_user(email="second@example.com")
        create_creator_profile(user=requested_second, display_name="Second Requester")
        request_creator_verification(user=requested_second)

        self.client.force_login(self.admin)
        response = self.client.get(reverse("admin-creator-profile-list"))

        names = [row["display_name"] for row in response.json()["results"]]
        self.assertEqual(
            names,
            ["First Requester", "Second Requester", "Never Requested Ministry"],
        )
