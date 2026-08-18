"""Phase 23 Slice 2 -- the daily digest batching task. Calls the task
function directly (not via .delay()) since CELERY_TASK_ALWAYS_EAGER already
makes real dispatch synchronous elsewhere in this codebase's tests, and this
task isn't wired into a beat schedule yet (see the task's own docstring)."""

from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps.creators.services.commands import create_creator_profile, follow_creator
from apps.creators.tasks import send_creator_follower_digests
from apps.subscriptions.models import Subscription, SubscriptionStatus
from apps.testimonies.models import Testimony, TestimonyCategory, TestimonyStatus, TestimonyType
from apps.users.tests.factories import ProfileFactory, UserFactory


def _premium_user(email="premium@example.com"):
    user = UserFactory(email=email)
    ProfileFactory(user=user, full_name="Premium User")
    Subscription.objects.create(user=user, amount=300000, payment_reference=f"SUB-{email}", status=SubscriptionStatus.ACTIVE)
    return user


def _free_user(email="free@example.com"):
    user = UserFactory(email=email)
    ProfileFactory(user=user, full_name="Free User")
    return user


def _approved_testimony(author, category, title):
    return Testimony.objects.create(
        author=author,
        category=category,
        title=title,
        body="Body.",
        testimony_type=TestimonyType.WRITTEN,
        status=TestimonyStatus.APPROVED,
        publish_at=timezone.now(),
    )


class SendCreatorFollowerDigestsTests(TestCase):
    def setUp(self):
        self.category = TestimonyCategory.objects.create(name="Healing", slug="healing")

    def test_sends_one_digest_per_follower_regardless_of_testimony_count(self):
        creator = _premium_user(email="creator@example.com")
        create_creator_profile(user=creator, display_name="Grace Restoration Ministries")
        follower_a = _free_user(email="follower-a@example.com")
        follower_b = _free_user(email="follower-b@example.com")
        follow_creator(follower=follower_a, creator_user_id=creator.id)
        follow_creator(follower=follower_b, creator_user_id=creator.id)

        _approved_testimony(creator, self.category, "Testimony One")
        _approved_testimony(creator, self.category, "Testimony Two")
        _approved_testimony(creator, self.category, "Testimony Three")

        with patch("apps.creators.tasks.notify_creator_digest") as notify_mock:
            sent = send_creator_follower_digests()

        notify_mock.assert_called_once()
        kwargs = notify_mock.call_args.kwargs
        self.assertCountEqual(kwargs["follower_ids"], [follower_a.id, follower_b.id])
        self.assertEqual(kwargs["new_testimony_count"], 3)
        self.assertEqual(sent, 2)  # one per follower, not one per testimony

    def test_skips_a_creator_with_no_followers(self):
        creator = _premium_user(email="creator@example.com")
        create_creator_profile(user=creator, display_name="Grace Restoration Ministries")
        _approved_testimony(creator, self.category, "Testimony One")

        with patch("apps.creators.tasks.notify_creator_digest") as notify_mock:
            sent = send_creator_follower_digests()

        notify_mock.assert_not_called()
        self.assertEqual(sent, 0)

    def test_skips_an_ordinary_author_with_no_ministry_profile(self):
        ordinary_author = _free_user(email="ordinary@example.com")
        _approved_testimony(ordinary_author, self.category, "A written testimony")

        with patch("apps.creators.tasks.notify_creator_digest") as notify_mock:
            sent = send_creator_follower_digests()

        notify_mock.assert_not_called()
        self.assertEqual(sent, 0)

    def test_a_creator_with_no_new_testimonies_in_the_window_is_skipped(self):
        creator = _premium_user(email="creator@example.com")
        create_creator_profile(user=creator, display_name="Grace Restoration Ministries")
        follower = _free_user(email="follower@example.com")
        follow_creator(follower=follower, creator_user_id=creator.id)
        # No approved testimonies at all.

        with patch("apps.creators.tasks.notify_creator_digest") as notify_mock:
            sent = send_creator_follower_digests()

        notify_mock.assert_not_called()
        self.assertEqual(sent, 0)
