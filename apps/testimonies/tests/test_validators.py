from django.test import TestCase
from django.utils import timezone

from apps.testimonies.validators import parse_future_publish_at


class ParseFuturePublishAtTests(TestCase):
    """Moved out of `AdminScheduleTestimonyView` (2026-08-15 audit fix) --
    this logic previously lived directly in the view, contrary to
    `backend/AGENTS.md`'s "views must stay thin" rule."""

    def test_blank_value_is_rejected(self) -> None:
        with self.assertRaisesMessage(ValueError, "publish_at is required."):
            parse_future_publish_at("")

    def test_invalid_iso_datetime_is_rejected(self) -> None:
        with self.assertRaisesMessage(ValueError, "publish_at must be a valid ISO datetime."):
            parse_future_publish_at("not-a-date")

    def test_past_datetime_is_rejected(self) -> None:
        past = (timezone.now() - timezone.timedelta(hours=1)).isoformat()
        with self.assertRaisesMessage(ValueError, "publish_at must be in the future."):
            parse_future_publish_at(past)

    def test_naive_future_datetime_is_made_aware_and_accepted(self) -> None:
        naive_future = (timezone.now() + timezone.timedelta(hours=2)).replace(tzinfo=None).isoformat()
        result = parse_future_publish_at(naive_future)
        self.assertTrue(timezone.is_aware(result))
        self.assertGreater(result, timezone.now())

    def test_zulu_suffix_future_datetime_is_accepted(self) -> None:
        future = (timezone.now() + timezone.timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S") + "Z"
        result = parse_future_publish_at(future)
        self.assertTrue(timezone.is_aware(result))
