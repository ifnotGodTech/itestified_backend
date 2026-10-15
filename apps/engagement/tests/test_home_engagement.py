"""Phase 35 Slice 5: what viewers do on the Home feed, and the dashboard's
"Home engagement" card built from it."""

from datetime import datetime, timedelta, timezone as dt_timezone

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.engagement.choices import HomeEventType
from apps.engagement.models import HomeEngagementDay, HomeEvent
from apps.engagement.services.queries import HOME_EVENT_RETENTION_DAYS, home_engagement_summary
from apps.users.choices import AdminRoleCode
from apps.users.tests.factories import AdminAssignmentFactory, AdminRoleFactory, ProfileFactory, UserFactory


def _event(event_type, *, when, session="s1", duration_ms=None, testimony_id=None):
    return HomeEvent.objects.create(
        session_id=session,
        event_type=event_type,
        duration_ms=duration_ms,
        testimony_id=testimony_id,
        occurred_at=when,
    )


class HomeEventBatchApiTests(TestCase):
    def _post(self, events, **extra):
        return APIClient().post(
            reverse("engagement-home-events"),
            {"device_id": "install-1", "session_id": "session-1", "events": events},
            format="json",
            **extra,
        )

    def test_a_guest_batch_is_stored_compactly(self):
        now = timezone.now()
        response = self._post(
            [
                {"type": "item_viewed", "testimony_id": 7, "duration_ms": 41000, "at": now.isoformat()},
                {"type": "swiped", "at": now.isoformat()},
            ]
        )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json(), {"accepted": 2})
        viewed = HomeEvent.objects.get(event_type=HomeEventType.ITEM_VIEWED)
        self.assertEqual(
            (viewed.user, viewed.device_id, viewed.session_id, viewed.testimony_id, viewed.duration_ms),
            (None, "install-1", "session-1", 7, 41000),
        )

    def test_a_signed_in_viewer_is_recorded_as_themselves(self):
        user = UserFactory(email="viewer@example.com")
        client = APIClient()
        client.force_authenticate(user)

        client.post(
            reverse("engagement-home-events"),
            {"session_id": "s", "events": [{"type": "search_run", "at": timezone.now().isoformat()}]},
            format="json",
        )

        self.assertEqual(HomeEvent.objects.get().user, user)

    def test_events_from_the_future_or_too_long_ago_are_dropped(self):
        now = timezone.now()
        response = self._post(
            [
                {"type": "swiped", "at": (now + timedelta(hours=1)).isoformat()},
                {"type": "swiped", "at": (now - timedelta(days=5)).isoformat()},
                {"type": "swiped", "at": now.isoformat()},
            ]
        )

        self.assertEqual(response.json(), {"accepted": 1})

    def test_rejects_unknown_types_oversized_batches_and_absurd_durations(self):
        now = timezone.now().isoformat()
        self.assertEqual(self._post([{"type": "liked", "at": now}]).status_code, 400)
        self.assertEqual(self._post([{"type": "swiped", "at": now}] * 51).status_code, 400)
        self.assertEqual(
            self._post([{"type": "item_viewed", "duration_ms": 5 * 60 * 60 * 1000, "at": now}]).status_code,
            400,
        )
        self.assertFalse(HomeEvent.objects.exists())


class HomeEngagementSummaryTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.yesterday_noon = datetime.combine(
            self.today - timedelta(days=1), datetime.min.time(), tzinfo=dt_timezone.utc
        ) + timedelta(hours=12)

    def test_worked_example_numbers(self):
        # Yesterday: 3 items viewed (20s, 40s, 90s) across 2 sessions, 4
        # swipes, 2 searches, 1 result opened, 1 response.
        for session, duration in (("a", 20000), ("a", 40000), ("b", 90000)):
            _event(HomeEventType.ITEM_VIEWED, when=self.yesterday_noon, session=session, duration_ms=duration)
        for _ in range(4):
            _event(HomeEventType.SWIPED, when=self.yesterday_noon, session="a")
        _event(HomeEventType.SEARCH_RUN, when=self.yesterday_noon, session="b")
        _event(HomeEventType.SEARCH_RUN, when=self.yesterday_noon, session="b")
        _event(HomeEventType.RESULT_OPENED, when=self.yesterday_noon, session="b")
        _event(HomeEventType.RESPONDED, when=self.yesterday_noon, session="a")

        summary = home_engagement_summary(days=7, today=self.today)

        self.assertEqual(summary["median_view_ms"], 40000)
        self.assertEqual(summary["swipes_per_session"], 2.0)
        self.assertEqual(summary["searches_per_day"], 0.3)
        self.assertEqual(summary["search_play_rate"], 0.5)
        self.assertEqual(summary["response_rate"], 0.333)
        self.assertEqual(summary["items_viewed"], 3)
        self.assertEqual(len(summary["series"]), 7)
        yesterday = summary["series"][-2]
        self.assertEqual((yesterday["items_viewed"], yesterday["sessions"]), (3, 2))

    def test_finished_days_are_rolled_up_once_and_old_raw_events_pruned(self):
        _event(HomeEventType.SWIPED, when=self.yesterday_noon)
        ancient = self.yesterday_noon - timedelta(days=HOME_EVENT_RETENTION_DAYS + 5)
        _event(HomeEventType.SWIPED, when=ancient)

        home_engagement_summary(days=7, today=self.today)
        home_engagement_summary(days=7, today=self.today)

        self.assertEqual(
            HomeEngagementDay.objects.get(day=self.today - timedelta(days=1)).swipes, 1
        )
        # The ancient day was rolled up before its raw events were dropped.
        self.assertTrue(HomeEngagementDay.objects.filter(day=ancient.date()).exists())
        self.assertFalse(HomeEvent.objects.filter(occurred_at=ancient).exists())

    def test_today_is_live_not_rolled_up(self):
        _event(HomeEventType.SEARCH_RUN, when=timezone.now())

        summary = home_engagement_summary(days=7, today=self.today)

        self.assertEqual(summary["series"][-1]["searches"], 1)
        self.assertFalse(HomeEngagementDay.objects.filter(day=self.today).exists())

    def test_no_activity_gives_zeros_not_errors(self):
        summary = home_engagement_summary(days=30, today=self.today)

        self.assertEqual(summary["median_view_ms"], 0)
        self.assertIsNone(summary["swipes_per_session"])
        self.assertIsNone(summary["response_rate"])
        self.assertEqual(len(summary["series"]), 30)


class AdminHomeEngagementApiTests(TestCase):
    def test_admins_only(self):
        self.assertEqual(APIClient().get(reverse("engagement-admin-home")).status_code, 403)

        admin = UserFactory(email="engagement-admin@example.com")
        ProfileFactory(user=admin, full_name="Admin")
        AdminAssignmentFactory(user=admin, role=AdminRoleFactory(code=AdminRoleCode.SUPER_ADMIN))
        client = APIClient()
        client.force_authenticate(admin)

        response = client.get(reverse("engagement-admin-home"), {"days": 30})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["days"], 30)
        # An unsupported period falls back to 7 days.
        self.assertEqual(client.get(reverse("engagement-admin-home"), {"days": 12}).json()["days"], 7)
