from django.test import TestCase
from django.urls import reverse
from rest_framework.authtoken.models import Token

from apps.creators.models import CreatorProfile
from apps.creators.services.commands import create_creator_profile, follow_creator
from apps.subscriptions.models import Subscription, SubscriptionStatus
from apps.users.tests.factories import ProfileFactory, UserFactory


def _premium_user(email="premium@example.com"):
    user = UserFactory(email=email)
    ProfileFactory(user=user, full_name="Premium User")
    Subscription.objects.create(
        user=user, amount=300000, payment_reference=f"SUB-{email}", status=SubscriptionStatus.ACTIVE
    )
    return user


def _free_user(email="free@example.com"):
    user = UserFactory(email=email)
    ProfileFactory(user=user, full_name="Free User")
    return user


def _auth_headers(user):
    token = Token.objects.create(user=user)
    return {"HTTP_AUTHORIZATION": f"Token {token.key}"}


class CreatorProfileMeApiTests(TestCase):
    def test_requires_authentication(self):
        response = self.client.post(reverse("creator-profile-me"), {"display_name": "X"}, content_type="application/json")
        self.assertEqual(response.status_code, 401)

    def test_a_free_user_is_rejected_with_403_not_a_generic_error(self):
        user = _free_user()
        response = self.client.post(
            reverse("creator-profile-me"),
            {"display_name": "Grace Restoration Ministries"},
            content_type="application/json",
            **_auth_headers(user),
        )
        self.assertEqual(response.status_code, 403)

    def test_a_premium_user_creates_a_profile(self):
        user = _premium_user()
        response = self.client.post(
            reverse("creator-profile-me"),
            {"display_name": "Grace Restoration Ministries", "bio": "Healing testimonies from Lagos."},
            content_type="application/json",
            **_auth_headers(user),
        )
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["display_name"], "Grace Restoration Ministries")
        self.assertFalse(body["is_verified"])

    def test_creating_a_second_profile_returns_400(self):
        user = _premium_user()
        headers = _auth_headers(user)
        self.client.post(reverse("creator-profile-me"), {"display_name": "First"}, content_type="application/json", **headers)
        response = self.client.post(reverse("creator-profile-me"), {"display_name": "Second"}, content_type="application/json", **headers)
        self.assertEqual(response.status_code, 400)

    def test_get_returns_404_when_no_profile_exists(self):
        user = _premium_user()
        response = self.client.get(reverse("creator-profile-me"), **_auth_headers(user))
        self.assertEqual(response.status_code, 404)

    def test_get_returns_the_profile_once_created(self):
        user = _premium_user()
        headers = _auth_headers(user)
        self.client.post(reverse("creator-profile-me"), {"display_name": "Grace Restoration Ministries"}, content_type="application/json", **headers)
        response = self.client.get(reverse("creator-profile-me"), **headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["display_name"], "Grace Restoration Ministries")

    def test_patch_updates_the_profile(self):
        user = _premium_user()
        headers = _auth_headers(user)
        self.client.post(reverse("creator-profile-me"), {"display_name": "Old Name"}, content_type="application/json", **headers)
        response = self.client.patch(
            reverse("creator-profile-me"), {"bio": "New bio."}, content_type="application/json", **headers
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["display_name"], "Old Name")
        self.assertEqual(body["bio"], "New bio.")

    def test_patch_is_rejected_once_premium_lapses(self):
        user = _premium_user()
        headers = _auth_headers(user)
        self.client.post(reverse("creator-profile-me"), {"display_name": "Grace Restoration Ministries"}, content_type="application/json", **headers)
        Subscription.objects.filter(user=user).update(status=SubscriptionStatus.EXPIRED)

        response = self.client.patch(
            reverse("creator-profile-me"), {"bio": "New bio."}, content_type="application/json", **headers
        )
        self.assertEqual(response.status_code, 403)


class PublicCreatorProfileApiTests(TestCase):
    def test_404_for_a_user_with_no_ministry_profile(self):
        viewer = _free_user(email="viewer@example.com")
        other = _free_user(email="other@example.com")
        response = self.client.get(reverse("creator-profile-detail", kwargs={"user_id": other.id}), **_auth_headers(viewer))
        self.assertEqual(response.status_code, 404)

    def test_returns_follower_count_and_is_following(self):
        creator = _premium_user(email="creator@example.com")
        create_creator_profile(user=creator, display_name="Grace Restoration Ministries", bio="Bio.")
        viewer = _free_user(email="viewer@example.com")
        follow_creator(follower=viewer, creator_user_id=creator.id)

        response = self.client.get(reverse("creator-profile-detail", kwargs={"user_id": creator.id}), **_auth_headers(viewer))

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["display_name"], "Grace Restoration Ministries")
        self.assertEqual(body["follower_count"], 1)
        self.assertTrue(body["is_following"])

    def test_is_following_is_false_for_a_non_follower(self):
        creator = _premium_user(email="creator@example.com")
        create_creator_profile(user=creator, display_name="Grace Restoration Ministries")
        viewer = _free_user(email="viewer@example.com")

        response = self.client.get(reverse("creator-profile-detail", kwargs={"user_id": creator.id}), **_auth_headers(viewer))

        self.assertFalse(response.json()["is_following"])


class CreatorFollowToggleApiTests(TestCase):
    def test_requires_authentication(self):
        creator = _premium_user(email="creator@example.com")
        create_creator_profile(user=creator, display_name="Grace Restoration Ministries")
        response = self.client.post(reverse("creator-follow-toggle", kwargs={"user_id": creator.id}))
        self.assertEqual(response.status_code, 401)

    def test_follow_then_unfollow(self):
        creator = _premium_user(email="creator@example.com")
        create_creator_profile(user=creator, display_name="Grace Restoration Ministries")
        follower = _free_user(email="follower@example.com")
        headers = _auth_headers(follower)

        follow_response = self.client.post(reverse("creator-follow-toggle", kwargs={"user_id": creator.id}), **headers)
        self.assertEqual(follow_response.status_code, 201)

        detail = self.client.get(reverse("creator-profile-detail", kwargs={"user_id": creator.id}), **headers)
        self.assertTrue(detail.json()["is_following"])

        unfollow_response = self.client.delete(reverse("creator-follow-toggle", kwargs={"user_id": creator.id}), **headers)
        self.assertEqual(unfollow_response.status_code, 200)

        detail_again = self.client.get(reverse("creator-profile-detail", kwargs={"user_id": creator.id}), **headers)
        self.assertFalse(detail_again.json()["is_following"])

    def test_cannot_follow_yourself(self):
        creator = _premium_user(email="creator@example.com")
        create_creator_profile(user=creator, display_name="Grace Restoration Ministries")
        response = self.client.post(reverse("creator-follow-toggle", kwargs={"user_id": creator.id}), **_auth_headers(creator))
        self.assertEqual(response.status_code, 400)

    def test_404_when_target_has_no_ministry_profile(self):
        follower = _free_user(email="follower@example.com")
        not_a_creator = _free_user(email="not-a-creator@example.com")
        response = self.client.post(
            reverse("creator-follow-toggle", kwargs={"user_id": not_a_creator.id}), **_auth_headers(follower)
        )
        self.assertEqual(response.status_code, 404)

    def test_unfollowing_someone_never_followed_is_still_200(self):
        creator = _premium_user(email="creator@example.com")
        create_creator_profile(user=creator, display_name="Grace Restoration Ministries")
        follower = _free_user(email="follower@example.com")
        response = self.client.delete(reverse("creator-follow-toggle", kwargs={"user_id": creator.id}), **_auth_headers(follower))
        self.assertEqual(response.status_code, 200)


class CreatorAnalyticsApiTests(TestCase):
    def test_requires_authentication(self):
        response = self.client.get(reverse("creator-analytics"))
        self.assertEqual(response.status_code, 401)

    def test_404_when_the_requesting_user_has_no_ministry_profile(self):
        user = _premium_user()
        response = self.client.get(reverse("creator-analytics"), **_auth_headers(user))
        self.assertEqual(response.status_code, 404)

    def test_returns_zeroed_analytics_for_a_new_profile(self):
        user = _premium_user()
        create_creator_profile(user=user, display_name="Grace Restoration Ministries")
        response = self.client.get(reverse("creator-analytics"), **_auth_headers(user))
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["follower_count"], 0)
        self.assertEqual(body["total_views"], 0)
        self.assertEqual(
            body["reaction_counts"], {"praying_for_you": 0, "amen": 0, "gives_me_hope": 0}
        )
