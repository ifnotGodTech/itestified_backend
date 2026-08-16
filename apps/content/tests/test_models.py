from datetime import timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.content.models import HomePromoCard, HomePromoCardStatus, HomePromoCtaDestination


class HomePromoCardCleanTests(TestCase):
    """Phase 20 Slice 6 -- model-level invariants, independent of whether
    they're reached through the admin API's serializer validation."""

    def test_ends_at_before_starts_at_is_invalid(self):
        now = timezone.now()
        card = HomePromoCard(
            title="T", body="B", starts_at=now, ends_at=now - timedelta(days=1)
        )
        with self.assertRaises(ValidationError):
            card.clean()

    def test_ends_at_equal_to_starts_at_is_invalid(self):
        now = timezone.now()
        card = HomePromoCard(title="T", body="B", starts_at=now, ends_at=now)
        with self.assertRaises(ValidationError):
            card.clean()

    def test_no_cta_at_all_is_valid(self):
        card = HomePromoCard(title="T", body="B")
        card.clean()  # must not raise

    def test_cta_label_without_destination_is_invalid(self):
        card = HomePromoCard(title="T", body="B", cta_label="Give Today")
        with self.assertRaises(ValidationError):
            card.clean()

    def test_cta_destination_without_label_is_invalid(self):
        card = HomePromoCard(title="T", body="B", cta_destination=HomePromoCtaDestination.GIVING)
        with self.assertRaises(ValidationError):
            card.clean()

    def test_external_url_destination_without_cta_url_is_invalid(self):
        card = HomePromoCard(
            title="T",
            body="B",
            cta_label="Learn More",
            cta_destination=HomePromoCtaDestination.EXTERNAL_URL,
        )
        with self.assertRaises(ValidationError):
            card.clean()

    def test_external_url_destination_with_cta_url_is_valid(self):
        card = HomePromoCard(
            title="T",
            body="B",
            cta_label="Learn More",
            cta_destination=HomePromoCtaDestination.EXTERNAL_URL,
            cta_url="https://itestified.app/events",
        )
        card.clean()  # must not raise


class HomePromoCardComputedStatusTests(TestCase):
    def setUp(self):
        self.now = timezone.now()

    def test_inactive_wins_over_the_date_window(self):
        card = HomePromoCard(
            title="T", body="B", is_active=False, starts_at=self.now - timedelta(days=1)
        )
        self.assertEqual(card.computed_status(now=self.now), HomePromoCardStatus.INACTIVE)

    def test_future_start_is_scheduled(self):
        card = HomePromoCard(title="T", body="B", starts_at=self.now + timedelta(days=1))
        self.assertEqual(card.computed_status(now=self.now), HomePromoCardStatus.SCHEDULED)

    def test_past_end_is_ended(self):
        card = HomePromoCard(
            title="T",
            body="B",
            starts_at=self.now - timedelta(days=10),
            ends_at=self.now - timedelta(days=1),
        )
        self.assertEqual(card.computed_status(now=self.now), HomePromoCardStatus.ENDED)

    def test_within_window_with_no_end_date_is_active(self):
        card = HomePromoCard(title="T", body="B", starts_at=self.now - timedelta(days=1))
        self.assertEqual(card.computed_status(now=self.now), HomePromoCardStatus.ACTIVE)
        self.assertTrue(card.is_eligible_for_feed(now=self.now))

    def test_within_window_with_a_future_end_date_is_active(self):
        card = HomePromoCard(
            title="T",
            body="B",
            starts_at=self.now - timedelta(days=1),
            ends_at=self.now + timedelta(days=1),
        )
        self.assertEqual(card.computed_status(now=self.now), HomePromoCardStatus.ACTIVE)
        self.assertTrue(card.is_eligible_for_feed(now=self.now))

    def test_scheduled_and_ended_are_not_eligible_for_the_feed(self):
        scheduled = HomePromoCard(title="T", body="B", starts_at=self.now + timedelta(days=1))
        ended = HomePromoCard(
            title="T", body="B", starts_at=self.now - timedelta(days=10), ends_at=self.now - timedelta(days=1)
        )
        self.assertFalse(scheduled.is_eligible_for_feed(now=self.now))
        self.assertFalse(ended.is_eligible_for_feed(now=self.now))
