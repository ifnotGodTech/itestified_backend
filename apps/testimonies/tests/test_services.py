from django.test import TestCase

from apps.testimonies.models import (
    Testimony,
    TestimonyCategory,
    TestimonyStatus,
    TestimonyType,
    UserFollowedCategory,
)
from apps.testimonies.services.queries import home_feed_page
from apps.users.tests.factories import ProfileFactory, UserFactory


class HomeFeedPageTests(TestCase):
    """Phase 20 Slice 3 -- the immersive Home feed's ranking and
    loop-back pagination, tested directly against the selector (not just
    the HTTP contract) since the interesting behavior is the ordering and
    windowing arithmetic, not the transport."""

    def setUp(self) -> None:
        self.category_faith = TestimonyCategory.objects.create(name="Faith", slug="faith")
        self.category_healing = TestimonyCategory.objects.create(name="Healing", slug="healing")
        author = UserFactory(email="home-feed-author@example.com")
        ProfileFactory(user=author, full_name="Home Feed Author")
        # Created in this order, so plain recency puts "Newer in Healing"
        # first -- used to prove signal-first ordering actually overrides
        # recency, not just happens to agree with it.
        self.older_faith = Testimony.objects.create(
            author=author,
            category=self.category_faith,
            title="Older in Faith",
            body="...",
            testimony_type=TestimonyType.WRITTEN,
            status=TestimonyStatus.APPROVED,
        )
        self.newer_healing = Testimony.objects.create(
            author=author,
            category=self.category_healing,
            title="Newer in Healing",
            body="...",
            testimony_type=TestimonyType.WRITTEN,
            status=TestimonyStatus.APPROVED,
        )

    def test_orders_by_recency_for_a_guest(self) -> None:
        # page_size matches the real total here on purpose -- a larger
        # page_size would legitimately loop within page 1 itself to fill
        # the page (see the loop-back test below), which would make a
        # plain ordering assertion meaningless.
        page = home_feed_page(user=None, page=1, page_size=2)

        titles = [row.title for row in page["results"]]
        self.assertEqual(titles, ["Newer in Healing", "Older in Faith"])
        self.assertEqual(page["next_page"], 2)

    def test_orders_by_recency_for_a_signal_less_registered_user(self) -> None:
        user = UserFactory(email="no-signal-home-feed@example.com")
        ProfileFactory(user=user, full_name="No Signal")

        page = home_feed_page(user=user, page=1, page_size=2)

        titles = [row.title for row in page["results"]]
        self.assertEqual(titles, ["Newer in Healing", "Older in Faith"])

    def test_signal_category_testimonies_come_first_even_when_older(self) -> None:
        user = UserFactory(email="signal-home-feed@example.com")
        ProfileFactory(user=user, full_name="Has Signal")
        UserFollowedCategory.objects.create(user=user, category=self.category_faith)

        page = home_feed_page(user=user, page=1, page_size=2)

        titles = [row.title for row in page["results"]]
        self.assertEqual(titles, ["Older in Faith", "Newer in Healing"])

    def test_a_small_catalog_still_fills_a_full_page(self) -> None:
        # Only 2 real testimonies exist, but a full 10-item page is asked
        # for -- the page should still come back full (looping within
        # page 1 itself) rather than returning just the 2 real items.
        page = home_feed_page(user=None, page=1, page_size=10)

        self.assertEqual(len(page["results"]), 10)

    def test_returns_empty_results_with_no_approved_content(self) -> None:
        Testimony.objects.all().delete()

        page = home_feed_page(user=None, page=1, page_size=10)

        self.assertEqual(page["results"], [])
        self.assertEqual(page["next_page"], 2)

    def test_loops_back_instead_of_dead_ending_once_content_is_exhausted(self) -> None:
        known_ids = {self.older_faith.id, self.newer_healing.id}

        seen_across_pages = []
        for page_number in range(1, 6):
            page = home_feed_page(user=None, page=page_number, page_size=2)
            self.assertEqual(len(page["results"]), 2)
            for row in page["results"]:
                self.assertIn(row.id, known_ids)
            seen_across_pages.extend(row.id for row in page["results"])

        # With only 2 real testimonies and 5 pages of 2, some id must repeat
        # -- the feed keeps serving full pages instead of ever emptying out.
        self.assertGreater(len(seen_across_pages), len(known_ids))
