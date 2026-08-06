from datetime import datetime, timezone as dt_timezone

from django.test import TestCase

from apps.subscriptions.services.commands import _add_one_month


class AddOneMonthTests(TestCase):
    def test_mid_month_date_rolls_to_the_same_day_next_month(self):
        start = datetime(2026, 8, 15, 10, 30, tzinfo=dt_timezone.utc)
        self.assertEqual(_add_one_month(start), datetime(2026, 9, 15, 10, 30, tzinfo=dt_timezone.utc))

    def test_january_31st_clamps_to_february_28th_in_a_non_leap_year(self):
        start = datetime(2026, 1, 31, tzinfo=dt_timezone.utc)
        self.assertEqual(_add_one_month(start), datetime(2026, 2, 28, tzinfo=dt_timezone.utc))

    def test_january_31st_clamps_to_february_29th_in_a_leap_year(self):
        start = datetime(2028, 1, 31, tzinfo=dt_timezone.utc)
        self.assertEqual(_add_one_month(start), datetime(2028, 2, 29, tzinfo=dt_timezone.utc))

    def test_december_rolls_over_into_january_of_the_next_year(self):
        start = datetime(2026, 12, 10, tzinfo=dt_timezone.utc)
        self.assertEqual(_add_one_month(start), datetime(2027, 1, 10, tzinfo=dt_timezone.utc))

    def test_preserves_the_time_of_day(self):
        start = datetime(2026, 3, 5, 23, 59, 59, tzinfo=dt_timezone.utc)
        self.assertEqual(_add_one_month(start).time(), start.time())
