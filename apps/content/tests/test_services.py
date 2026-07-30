from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.content.exceptions import ContentError
from apps.content.models import ScriptureReadReceipt
from apps.content.services.commands import mark_scripture_read, scripture_streak_freezes_remaining
from apps.users.tests.factories import ProfileFactory, UserFactory


class MarkScriptureReadTests(TestCase):
    def setUp(self) -> None:
        self.user = UserFactory(email="streak-reader@example.com")
        self.profile = ProfileFactory(user=self.user, full_name="Streak Reader")
        # Real "today" -- mark_scripture_read validates read_date against
        # timezone.localdate() at call time, so the *submission* in each
        # test must stay within a day of this. Prior streak history is set
        # up directly on the profile below rather than via repeated calls
        # with historical dates, since those would (correctly) be rejected
        # by that same guard.
        self.today = timezone.localdate()

    def _seed_prior_state(self, *, last_read_date, streak_count, freezes_used=0, freeze_month=None):
        self.profile.scripture_last_read_date = last_read_date
        self.profile.scripture_streak_count = streak_count
        self.profile.scripture_streak_freezes_used = freezes_used
        self.profile.scripture_streak_freeze_month = freeze_month
        self.profile.save()

    def test_first_ever_read_starts_a_streak_of_one(self) -> None:
        profile = mark_scripture_read(user=self.user, read_date=self.today)

        self.assertEqual(profile.scripture_streak_count, 1)
        self.assertEqual(profile.scripture_last_read_date, self.today)
        self.assertTrue(
            ScriptureReadReceipt.objects.filter(user=self.user, read_date=self.today).exists()
        )

    def test_consecutive_day_read_extends_the_streak(self) -> None:
        self._seed_prior_state(last_read_date=self.today - timedelta(days=1), streak_count=2)

        profile = mark_scripture_read(user=self.user, read_date=self.today)

        self.assertEqual(profile.scripture_streak_count, 3)

    def test_reading_twice_the_same_day_does_not_double_count(self) -> None:
        mark_scripture_read(user=self.user, read_date=self.today)
        profile = mark_scripture_read(user=self.user, read_date=self.today)

        self.assertEqual(profile.scripture_streak_count, 1)
        self.assertEqual(
            ScriptureReadReceipt.objects.filter(user=self.user, read_date=self.today).count(), 1
        )

    def test_a_single_missed_day_consumes_a_freeze_and_continues(self) -> None:
        self._seed_prior_state(last_read_date=self.today - timedelta(days=2), streak_count=5)

        profile = mark_scripture_read(user=self.user, read_date=self.today)

        self.assertEqual(profile.scripture_streak_count, 6)
        self.assertEqual(scripture_streak_freezes_remaining(profile), 1)

    def test_second_freeze_in_the_same_month_still_works(self) -> None:
        month_start = self.today.replace(day=1)
        self._seed_prior_state(
            last_read_date=self.today - timedelta(days=2),
            streak_count=5,
            freezes_used=1,
            freeze_month=month_start,
        )

        profile = mark_scripture_read(user=self.user, read_date=self.today)

        self.assertEqual(profile.scripture_streak_count, 6)
        self.assertEqual(scripture_streak_freezes_remaining(profile), 0)

    def test_missed_day_with_no_freezes_left_this_month_resets_to_one(self) -> None:
        month_start = self.today.replace(day=1)
        self._seed_prior_state(
            last_read_date=self.today - timedelta(days=2),
            streak_count=10,
            freezes_used=2,
            freeze_month=month_start,
        )

        profile = mark_scripture_read(user=self.user, read_date=self.today)

        self.assertEqual(profile.scripture_streak_count, 1)

    def test_freeze_allowance_resets_each_calendar_month(self) -> None:
        first_of_this_month = self.today.replace(day=1)
        first_of_last_month = (first_of_this_month - timedelta(days=1)).replace(day=1)
        # Both freezes already used *last* month -- should not carry over.
        self._seed_prior_state(
            last_read_date=self.today - timedelta(days=2),
            streak_count=4,
            freezes_used=2,
            freeze_month=first_of_last_month,
        )

        profile = mark_scripture_read(user=self.user, read_date=self.today)

        self.assertEqual(profile.scripture_streak_count, 5)
        self.assertEqual(scripture_streak_freezes_remaining(profile), 1)

    def test_a_two_plus_day_gap_resets_to_one_even_with_freezes_available(self) -> None:
        self._seed_prior_state(last_read_date=self.today - timedelta(days=3), streak_count=8, freezes_used=0)

        profile = mark_scripture_read(user=self.user, read_date=self.today)

        # Freezes only ever cover exactly one missed day, never a longer gap.
        self.assertEqual(profile.scripture_streak_count, 1)

    def test_rejects_a_submission_date_too_far_from_the_servers_today(self) -> None:
        with self.assertRaises(ContentError):
            mark_scripture_read(user=self.user, read_date=self.today - timedelta(days=10))
