from unittest import mock

from django.core.cache import cache
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


class HomeFeedSeededShuffleTests(TestCase):
    """The seeded, bounded-window shuffle added after discussing what
    "randomized, not itemized" should mean at scale -- a genuine per-
    session permutation of the ranked catalog, not just a different
    rotation of the same fixed order."""

    def setUp(self) -> None:
        # _cached_base_ids caches by (user, seed) in the process-level
        # LocMemCache, which isn't tied to the DB transaction rollback
        # TestCase gives each test -- without clearing it, a cached id
        # list from one test could leak into another if they ever reuse
        # a seed against different underlying testimonies.
        cache.clear()
        category = TestimonyCategory.objects.create(name="Faith", slug="faith")
        author = UserFactory(email="seeded-home-feed-author@example.com")
        ProfileFactory(user=author, full_name="Seeded Feed Author")
        # 10 items: enough that two different seeds producing the exact
        # same permutation by chance is effectively impossible (1 in 10!),
        # while still cheap to create per test.
        self.testimonies = [
            Testimony.objects.create(
                author=author,
                category=category,
                title=f"Testimony {index}",
                body="...",
                testimony_type=TestimonyType.WRITTEN,
                status=TestimonyStatus.APPROVED,
            )
            for index in range(10)
        ]

    def test_same_seed_produces_the_same_order_on_repeated_calls(self) -> None:
        first = home_feed_page(user=None, page=1, page_size=10, seed="abc")
        second = home_feed_page(user=None, page=1, page_size=10, seed="abc")

        self.assertEqual(
            [row.id for row in first["results"]],
            [row.id for row in second["results"]],
        )

    def test_different_seeds_produce_different_orders(self) -> None:
        first = home_feed_page(user=None, page=1, page_size=10, seed="abc")
        second = home_feed_page(user=None, page=1, page_size=10, seed="xyz")

        self.assertNotEqual(
            [row.id for row in first["results"]],
            [row.id for row in second["results"]],
        )

    def test_seeded_order_is_a_genuine_shuffle_not_just_a_rotation(self) -> None:
        # A rotation preserves every item's neighbor (whoever's next in
        # rank order is still next after rotating); a real shuffle breaks
        # that for at least some items. Comparing the seeded order against
        # every possible rotation of the plain recency order rules out
        # "this is secretly still just a rotation."
        plain_ids = [
            row.id
            for row in home_feed_page(user=None, page=1, page_size=10)["results"]
        ]
        seeded_ids = [
            row.id
            for row in home_feed_page(
                user=None, page=1, page_size=10, seed="rotation-check"
            )["results"]
        ]

        possible_rotations = {
            tuple(plain_ids[i:] + plain_ids[:i]) for i in range(len(plain_ids))
        }
        self.assertNotIn(tuple(seeded_ids), possible_rotations)

    def test_seeded_pagination_has_no_duplicates_or_gaps_within_one_loop(self) -> None:
        seen_ids = []
        for page_number in range(1, 6):
            page = home_feed_page(
                user=None, page=page_number, page_size=2, seed="pagination-check"
            )
            seen_ids.extend(row.id for row in page["results"])

        # 5 pages of 2 = exactly one full loop through 10 real items --
        # every id appears exactly once, none missing, none duplicated.
        self.assertEqual(sorted(seen_ids), sorted(t.id for t in self.testimonies))

    def test_only_the_shuffle_window_is_shuffled_the_rest_stays_ranked(self) -> None:
        with mock.patch(
            "apps.testimonies.services.queries.HOME_FEED_SHUFFLE_WINDOW", 3
        ):
            plain_ids = [
                row.id
                for row in home_feed_page(user=None, page=1, page_size=10)["results"]
            ]
            seeded_ids = [
                row.id
                for row in home_feed_page(
                    user=None, page=1, page_size=10, seed="window-check"
                )["results"]
            ]

        # Items past the (patched) 3-item window are untouched by the
        # shuffle, so they still read in plain rank order.
        self.assertEqual(seeded_ids[3:], plain_ids[3:])
        # The window itself (first 3) is some permutation of the same ids,
        # not necessarily identical to the plain order.
        self.assertEqual(sorted(seeded_ids[:3]), sorted(plain_ids[:3]))

    def test_no_seed_behaves_exactly_as_before_seeding_existed(self) -> None:
        with_none = home_feed_page(user=None, page=1, page_size=10, seed=None)
        without_param = home_feed_page(user=None, page=1, page_size=10)

        self.assertEqual(
            [row.id for row in with_none["results"]],
            [row.id for row in without_param["results"]],
        )

    def test_no_seed_fast_path_costs_exactly_a_count_and_a_slice(self) -> None:
        # Guest/signal-less path: no extra queries computing category_ids
        # (see _home_feed_base_queryset), so this should be exactly
        # count() + the select_related slice -- nothing more, regardless
        # of catalog size, as the docstring claims.
        with self.assertNumQueries(2):
            home_feed_page(user=None, page=1, page_size=10)

    def test_seeded_first_call_costs_exactly_an_id_fetch_and_a_testimony_fetch(
        self,
    ) -> None:
        with self.assertNumQueries(2):
            home_feed_page(user=None, page=1, page_size=10, seed="query-count-a")

    def test_seeded_repeat_call_with_same_seed_skips_the_id_query(self) -> None:
        # First call warms the (user, seed) cache entry.
        home_feed_page(user=None, page=1, page_size=2, seed="query-count-b")

        # A later page within the same session reuses the cached id list
        # -- only the final testimony fetch should hit the database.
        with self.assertNumQueries(1):
            home_feed_page(user=None, page=2, page_size=2, seed="query-count-b")

    def test_seeded_call_with_a_different_seed_does_not_reuse_the_cache(self) -> None:
        home_feed_page(user=None, page=1, page_size=2, seed="query-count-c1")

        # A different seed is a different session -- it must not silently
        # reuse another session's cached id list, so it pays the full cost
        # again.
        with self.assertNumQueries(2):
            home_feed_page(user=None, page=1, page_size=2, seed="query-count-c2")
