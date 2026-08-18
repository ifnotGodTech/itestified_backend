"""Phase 23 Slice 4 -- prayer reaction inbox + respond."""

from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from rest_framework.authtoken.models import Token

from apps.creators.exceptions import (
    CreatorProfileNotFoundError,
    PrayerReactionAlreadyRespondedError,
    PrayerReactionNotFoundError,
    PrayerReactionNotOwnedByCreatorError,
    PrayerReactionWrongTypeError,
)
from apps.creators.models import PrayerResponse
from apps.creators.selectors import list_prayer_reactions_for_creator
from apps.creators.services.commands import create_creator_profile, respond_to_prayer_reaction
from apps.notifications.models import NotificationType, UserNotification
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
    Subscription.objects.create(user=user, amount=300000, payment_reference=f"SUB-{email}", status=SubscriptionStatus.ACTIVE)
    return user


def _free_user(email="free@example.com", full_name="Free User"):
    user = UserFactory(email=email)
    ProfileFactory(user=user, full_name=full_name)
    return user


def _auth_headers(user):
    token = Token.objects.create(user=user)
    return {"HTTP_AUTHORIZATION": f"Token {token.key}"}


class RespondToPrayerReactionServiceTests(TestCase):
    def setUp(self):
        self.category = TestimonyCategory.objects.create(name="Healing", slug="healing")
        self.creator = _premium_user(email="creator@example.com")
        create_creator_profile(user=self.creator, display_name="Grace Restoration Ministries")
        self.testimony = Testimony.objects.create(
            author=self.creator,
            category=self.category,
            title="God healed my knee",
            body="Body.",
            testimony_type=TestimonyType.WRITTEN,
            status=TestimonyStatus.APPROVED,
        )
        self.reactor = _free_user(email="reactor@example.com", full_name="Chidinma O.")

    def test_responding_creates_a_response_and_notifies_the_reactor(self):
        reaction = TestimonyReaction.objects.create(
            user=self.reactor, testimony=self.testimony, reaction_type=TestimonyReactionType.PRAYING_FOR_YOU
        )

        with patch("apps.notifications.services.send_push_to_tokens", return_value=[]):
            with self.captureOnCommitCallbacks(execute=True):
                response = respond_to_prayer_reaction(
                    creator=self.creator, reaction_id=reaction.id, response_text="Praying with you too!"
                )

        self.assertEqual(response.reaction, reaction)
        self.assertEqual(response.response_text, "Praying with you too!")
        notification = UserNotification.objects.get(recipient=self.reactor, notification_type=NotificationType.PRAYER_RESPONSE)
        self.assertIn("Grace Restoration Ministries", notification.title)
        self.assertIn("Praying with you too!", notification.message)

    def test_cannot_respond_to_a_missing_reaction(self):
        with self.assertRaises(PrayerReactionNotFoundError):
            respond_to_prayer_reaction(creator=self.creator, reaction_id=999999, response_text="Hi")

    def test_cannot_respond_to_a_reaction_on_someone_elses_testimony(self):
        other_creator = _premium_user(email="other-creator@example.com")
        create_creator_profile(user=other_creator, display_name="Other Ministry")
        other_testimony = Testimony.objects.create(
            author=other_creator,
            category=self.category,
            title="Someone else's testimony",
            body="Body.",
            testimony_type=TestimonyType.WRITTEN,
            status=TestimonyStatus.APPROVED,
        )
        reaction = TestimonyReaction.objects.create(
            user=self.reactor, testimony=other_testimony, reaction_type=TestimonyReactionType.PRAYING_FOR_YOU
        )

        with self.assertRaises(PrayerReactionNotOwnedByCreatorError):
            respond_to_prayer_reaction(creator=self.creator, reaction_id=reaction.id, response_text="Hi")

    def test_cannot_respond_to_a_non_praying_for_you_reaction(self):
        reaction = TestimonyReaction.objects.create(
            user=self.reactor, testimony=self.testimony, reaction_type=TestimonyReactionType.AMEN
        )
        with self.assertRaises(PrayerReactionWrongTypeError):
            respond_to_prayer_reaction(creator=self.creator, reaction_id=reaction.id, response_text="Hi")

    def test_cannot_respond_twice_to_the_same_reaction(self):
        reaction = TestimonyReaction.objects.create(
            user=self.reactor, testimony=self.testimony, reaction_type=TestimonyReactionType.PRAYING_FOR_YOU
        )
        with self.captureOnCommitCallbacks(execute=True):
            respond_to_prayer_reaction(creator=self.creator, reaction_id=reaction.id, response_text="First response.")

        with self.assertRaises(PrayerReactionAlreadyRespondedError):
            respond_to_prayer_reaction(creator=self.creator, reaction_id=reaction.id, response_text="Second response.")

        self.assertEqual(PrayerResponse.objects.filter(reaction=reaction).count(), 1)

    def test_an_ordinary_author_with_no_ministry_profile_cannot_respond(self):
        ordinary_author = _free_user(email="ordinary@example.com")
        written = Testimony.objects.create(
            author=ordinary_author,
            category=self.category,
            title="An ordinary testimony",
            body="Body.",
            testimony_type=TestimonyType.WRITTEN,
            status=TestimonyStatus.APPROVED,
        )
        reaction = TestimonyReaction.objects.create(
            user=self.reactor, testimony=written, reaction_type=TestimonyReactionType.PRAYING_FOR_YOU
        )
        with self.assertRaises(CreatorProfileNotFoundError):
            respond_to_prayer_reaction(creator=ordinary_author, reaction_id=reaction.id, response_text="Hi")


class ListPrayerReactionsForCreatorTests(TestCase):
    def test_only_lists_praying_for_you_reactions_and_shows_response_state(self):
        category = TestimonyCategory.objects.create(name="Faith", slug="faith")
        creator = _premium_user(email="creator@example.com")
        create_creator_profile(user=creator, display_name="Grace Restoration Ministries")
        testimony = Testimony.objects.create(
            author=creator, category=category, title="Restoration", body="Body.",
            testimony_type=TestimonyType.WRITTEN, status=TestimonyStatus.APPROVED,
        )
        reactor_a = _free_user(email="a@example.com", full_name="Reactor A")
        reactor_b = _free_user(email="b@example.com", full_name="Reactor B")

        prayer_reaction = TestimonyReaction.objects.create(user=reactor_a, testimony=testimony, reaction_type=TestimonyReactionType.PRAYING_FOR_YOU)
        TestimonyReaction.objects.create(user=reactor_b, testimony=testimony, reaction_type=TestimonyReactionType.AMEN)

        with self.captureOnCommitCallbacks(execute=True):
            respond_to_prayer_reaction(creator=creator, reaction_id=prayer_reaction.id, response_text="Thank you!")

        rows = list(list_prayer_reactions_for_creator(creator_user_id=creator.id))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].id, prayer_reaction.id)
        self.assertEqual(rows[0].prayer_response.response_text, "Thank you!")


class PrayerInboxApiTests(TestCase):
    def setUp(self):
        self.category = TestimonyCategory.objects.create(name="Healing", slug="healing")
        self.creator = _premium_user(email="creator@example.com")
        create_creator_profile(user=self.creator, display_name="Grace Restoration Ministries")
        self.testimony = Testimony.objects.create(
            author=self.creator, category=self.category, title="God healed my knee", body="Body.",
            testimony_type=TestimonyType.WRITTEN, status=TestimonyStatus.APPROVED,
        )
        self.reactor = _free_user(email="reactor@example.com", full_name="Chidinma O.")

    def test_requires_authentication(self):
        response = self.client.get(reverse("creator-prayer-inbox"))
        self.assertEqual(response.status_code, 401)

    def test_lists_the_creators_prayer_reactions(self):
        TestimonyReaction.objects.create(user=self.reactor, testimony=self.testimony, reaction_type=TestimonyReactionType.PRAYING_FOR_YOU)

        response = self.client.get(reverse("creator-prayer-inbox"), **_auth_headers(self.creator))

        self.assertEqual(response.status_code, 200)
        results = response.json()["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["reactor_name"], "Chidinma O.")
        self.assertEqual(results[0]["testimony_title"], "God healed my knee")
        self.assertIsNone(results[0]["response"])

    def test_respond_endpoint_creates_a_response(self):
        reaction = TestimonyReaction.objects.create(
            user=self.reactor, testimony=self.testimony, reaction_type=TestimonyReactionType.PRAYING_FOR_YOU
        )
        headers = _auth_headers(self.creator)

        with patch("apps.notifications.services.send_push_to_tokens", return_value=[]):
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(
                    reverse("creator-prayer-reaction-respond", kwargs={"reaction_id": reaction.id}),
                    {"response_text": "Praying with you!"},
                    content_type="application/json",
                    **headers,
                )
        self.assertEqual(response.status_code, 201)

        inbox_response = self.client.get(reverse("creator-prayer-inbox"), **headers)
        row = inbox_response.json()["results"][0]
        self.assertEqual(row["response"]["response_text"], "Praying with you!")

    def test_respond_with_blank_text_is_a_400(self):
        reaction = TestimonyReaction.objects.create(
            user=self.reactor, testimony=self.testimony, reaction_type=TestimonyReactionType.PRAYING_FOR_YOU
        )
        response = self.client.post(
            reverse("creator-prayer-reaction-respond", kwargs={"reaction_id": reaction.id}),
            {"response_text": "   "},
            content_type="application/json",
            **_auth_headers(self.creator),
        )
        self.assertEqual(response.status_code, 400)

    def test_responding_twice_returns_400(self):
        reaction = TestimonyReaction.objects.create(
            user=self.reactor, testimony=self.testimony, reaction_type=TestimonyReactionType.PRAYING_FOR_YOU
        )
        headers = _auth_headers(self.creator)
        with patch("apps.notifications.services.send_push_to_tokens", return_value=[]):
            with self.captureOnCommitCallbacks(execute=True):
                self.client.post(
                    reverse("creator-prayer-reaction-respond", kwargs={"reaction_id": reaction.id}),
                    {"response_text": "First."},
                    content_type="application/json",
                    **headers,
                )
            second = self.client.post(
                reverse("creator-prayer-reaction-respond", kwargs={"reaction_id": reaction.id}),
                {"response_text": "Second."},
                content_type="application/json",
                **headers,
            )
        self.assertEqual(second.status_code, 400)
