"""Phase 23 Slices 1-3 -- Ministry profile creation/management, follow, and
creator analytics. Reaction/moderation domain reused as-is from Phase 3/15,
never duplicated (see Phase 23's Background note)."""

from django.test import TestCase

from apps.creators.exceptions import (
    CannotFollowSelfError,
    CreatorProfileAlreadyExistsError,
    CreatorProfileNotEligibleError,
    CreatorProfileNotFoundError,
)
from apps.creators.models import CreatorFollow, CreatorProfile
from apps.creators.selectors import get_creator_analytics
from apps.creators.services.commands import (
    create_creator_profile,
    follow_creator,
    unfollow_creator,
    update_creator_profile,
)
from apps.subscriptions.models import Subscription, SubscriptionStatus
from apps.testimonies.models import (
    Testimony,
    TestimonyCategory,
    TestimonyReaction,
    TestimonyReactionType,
    TestimonyStatus,
    TestimonyType,
)
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


class CreateCreatorProfileTests(TestCase):
    def test_a_free_user_cannot_create_a_ministry_profile(self):
        user = _free_user()
        with self.assertRaises(CreatorProfileNotEligibleError):
            create_creator_profile(user=user, display_name="Grace Restoration Ministries")
        self.assertFalse(CreatorProfile.objects.filter(user=user).exists())

    def test_a_premium_user_can_create_a_ministry_profile(self):
        user = _premium_user()
        profile = create_creator_profile(
            user=user, display_name="Grace Restoration Ministries", bio="Healing testimonies from Lagos."
        )
        self.assertEqual(profile.display_name, "Grace Restoration Ministries")
        self.assertEqual(profile.bio, "Healing testimonies from Lagos.")
        self.assertFalse(profile.is_verified)

    def test_a_second_profile_for_the_same_user_is_rejected(self):
        user = _premium_user()
        create_creator_profile(user=user, display_name="Grace Restoration Ministries")
        with self.assertRaises(CreatorProfileAlreadyExistsError):
            create_creator_profile(user=user, display_name="Second Name")
        self.assertEqual(CreatorProfile.objects.filter(user=user).count(), 1)


class UpdateCreatorProfileTests(TestCase):
    def test_updates_display_name_and_bio(self):
        user = _premium_user()
        create_creator_profile(user=user, display_name="Grace Restoration Ministries", bio="Old bio.")
        updated = update_creator_profile(user=user, display_name="Grace Restoration Ministry", bio="New bio.")
        self.assertEqual(updated.display_name, "Grace Restoration Ministry")
        self.assertEqual(updated.bio, "New bio.")

    def test_a_lapsed_premium_user_cannot_edit_their_existing_profile(self):
        user = _premium_user()
        profile = create_creator_profile(user=user, display_name="Grace Restoration Ministries")
        Subscription.objects.filter(user=user).update(status=SubscriptionStatus.EXPIRED)

        with self.assertRaises(CreatorProfileNotEligibleError):
            update_creator_profile(user=user, display_name="New Name")

        # Never clawed back -- the existing profile is untouched.
        profile.refresh_from_db()
        self.assertEqual(profile.display_name, "Grace Restoration Ministries")

    def test_raises_when_no_profile_exists(self):
        user = _premium_user()
        with self.assertRaises(CreatorProfileNotFoundError):
            update_creator_profile(user=user, display_name="Anything")


class FollowCreatorTests(TestCase):
    def test_follows_a_creator(self):
        creator = _premium_user(email="creator@example.com")
        create_creator_profile(user=creator, display_name="Grace Restoration Ministries")
        follower = _free_user(email="follower@example.com")

        follow_creator(follower=follower, creator_user_id=creator.id)

        self.assertTrue(CreatorFollow.objects.filter(follower=follower, creator=creator).exists())

    def test_cannot_follow_yourself(self):
        creator = _premium_user(email="creator@example.com")
        create_creator_profile(user=creator, display_name="Grace Restoration Ministries")

        with self.assertRaises(CannotFollowSelfError):
            follow_creator(follower=creator, creator_user_id=creator.id)

    def test_cannot_follow_a_user_with_no_ministry_profile(self):
        follower = _free_user(email="follower@example.com")
        not_a_creator = _free_user(email="not-a-creator@example.com")

        with self.assertRaises(CreatorProfileNotFoundError):
            follow_creator(follower=follower, creator_user_id=not_a_creator.id)

    def test_following_twice_is_idempotent(self):
        creator = _premium_user(email="creator@example.com")
        create_creator_profile(user=creator, display_name="Grace Restoration Ministries")
        follower = _free_user(email="follower@example.com")

        follow_creator(follower=follower, creator_user_id=creator.id)
        follow_creator(follower=follower, creator_user_id=creator.id)

        self.assertEqual(CreatorFollow.objects.filter(follower=follower, creator=creator).count(), 1)

    def test_unfollowing_removes_the_row(self):
        creator = _premium_user(email="creator@example.com")
        create_creator_profile(user=creator, display_name="Grace Restoration Ministries")
        follower = _free_user(email="follower@example.com")
        follow_creator(follower=follower, creator_user_id=creator.id)

        unfollow_creator(follower=follower, creator_user_id=creator.id)

        self.assertFalse(CreatorFollow.objects.filter(follower=follower, creator=creator).exists())

    def test_unfollowing_someone_you_never_followed_is_a_safe_no_op(self):
        creator = _premium_user(email="creator@example.com")
        create_creator_profile(user=creator, display_name="Grace Restoration Ministries")
        follower = _free_user(email="follower@example.com")

        unfollow_creator(follower=follower, creator_user_id=creator.id)  # should not raise

        self.assertFalse(CreatorFollow.objects.filter(follower=follower, creator=creator).exists())


class CreatorAnalyticsTests(TestCase):
    def _approved_testimony(self, author, category, title, view_count=0):
        return Testimony.objects.create(
            author=author,
            category=category,
            title=title,
            body="Body.",
            testimony_type=TestimonyType.WRITTEN,
            status=TestimonyStatus.APPROVED,
            view_count=view_count,
        )

    def test_aggregates_views_reactions_and_followers_across_approved_testimonies_only(self):
        creator = _premium_user(email="creator@example.com")
        create_creator_profile(user=creator, display_name="Grace Restoration Ministries")
        category = TestimonyCategory.objects.create(name="Healing", slug="healing")

        approved_one = self._approved_testimony(creator, category, "Testimony One", view_count=100)
        approved_two = self._approved_testimony(creator, category, "Testimony Two", view_count=50)
        pending = Testimony.objects.create(
            author=creator,
            category=category,
            title="Still pending",
            body="Body.",
            testimony_type=TestimonyType.WRITTEN,
            status=TestimonyStatus.PENDING_REVIEW,
            view_count=999,
        )

        reactor_a = _free_user(email="reactor-a@example.com")
        reactor_b = _free_user(email="reactor-b@example.com")
        reactor_c = _free_user(email="reactor-c@example.com")
        TestimonyReaction.objects.create(user=reactor_a, testimony=approved_one, reaction_type=TestimonyReactionType.PRAYING_FOR_YOU)
        TestimonyReaction.objects.create(user=reactor_b, testimony=approved_one, reaction_type=TestimonyReactionType.AMEN)
        TestimonyReaction.objects.create(user=reactor_c, testimony=approved_two, reaction_type=TestimonyReactionType.PRAYING_FOR_YOU)
        # A reaction on the still-pending testimony must never count.
        TestimonyReaction.objects.create(user=reactor_a, testimony=pending, reaction_type=TestimonyReactionType.GIVES_ME_HOPE)

        follower = _free_user(email="follower@example.com")
        follow_creator(follower=follower, creator_user_id=creator.id)

        analytics = get_creator_analytics(creator_user_id=creator.id)

        self.assertEqual(analytics["follower_count"], 1)
        self.assertEqual(analytics["testimony_count"], 2)
        self.assertEqual(analytics["total_views"], 150)
        self.assertEqual(analytics["total_reactions"], 3)
        self.assertEqual(
            analytics["reaction_counts"],
            {"praying_for_you": 2, "amen": 1, "gives_me_hope": 0},
        )

    def test_a_creator_with_no_approved_testimonies_gets_zeroed_analytics_not_an_error(self):
        creator = _premium_user(email="creator@example.com")
        create_creator_profile(user=creator, display_name="Grace Restoration Ministries")

        analytics = get_creator_analytics(creator_user_id=creator.id)

        self.assertEqual(analytics["follower_count"], 0)
        self.assertEqual(analytics["testimony_count"], 0)
        self.assertEqual(analytics["total_views"], 0)
        self.assertEqual(analytics["total_reactions"], 0)
