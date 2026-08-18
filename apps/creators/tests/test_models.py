from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.creators.models import CreatorFollow, CreatorProfile
from apps.users.tests.factories import ProfileFactory, UserFactory


class CreatorProfileConstraintTests(TestCase):
    def test_a_user_can_only_have_one_creator_profile(self):
        user = UserFactory(email="creator@example.com")
        ProfileFactory(user=user, full_name="Creator")
        CreatorProfile.objects.create(user=user, display_name="Grace Restoration Ministries")

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CreatorProfile.objects.create(user=user, display_name="Second Profile")


class CreatorFollowConstraintTests(TestCase):
    def setUp(self):
        self.creator = UserFactory(email="creator@example.com")
        ProfileFactory(user=self.creator, full_name="Creator")
        CreatorProfile.objects.create(user=self.creator, display_name="Grace Restoration Ministries")
        self.follower = UserFactory(email="follower@example.com")
        ProfileFactory(user=self.follower, full_name="Follower")

    def test_a_follower_cannot_follow_the_same_creator_twice_at_the_db_level(self):
        CreatorFollow.objects.create(follower=self.follower, creator=self.creator)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CreatorFollow.objects.create(follower=self.follower, creator=self.creator)

    def test_a_user_cannot_follow_themselves_at_the_db_level(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CreatorFollow.objects.create(follower=self.creator, creator=self.creator)
