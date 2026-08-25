from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from rest_framework.authtoken.models import Token

from apps.creators.models import CreatorProfile
from apps.live_broadcasts.models import (
    LiveBroadcast,
    LiveBroadcastApprovalRequest,
    LiveBroadcastStatus,
    MinistryStreamingAllowance,
)
from apps.live_broadcasts.services.agora import PublisherCredential
from apps.testimonies.models import TestimonyCategory
from apps.users.choices import AdminRoleCode
from apps.users.tests.factories import AdminAssignmentFactory, AdminRoleFactory, UserFactory
from django.utils import timezone


def _verified_ministry(email="ministry@example.com"):
    user = UserFactory(email=email)
    CreatorProfile.objects.create(user=user, display_name="Grace Chapel", is_verified=True)
    token = Token.objects.create(user=user)
    return user, token


class LiveBroadcastApiTests(TestCase):
    def test_endpoints_require_authentication(self):
        response = self.client.post(reverse("live-broadcast-list-create"), {"title": "x"}, content_type="application/json")
        self.assertEqual(response.status_code, 401)

    def test_non_ministry_gets_403_on_create(self):
        user = UserFactory()
        token = Token.objects.create(user=user)
        category = TestimonyCategory.objects.create(name="Faith", slug="faith")
        response = self.client.post(
            reverse("live-broadcast-list-create"),
            {"title": "Sunday Service", "category_id": category.id},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Token {token.key}",
        )
        self.assertEqual(response.status_code, 403)

    def test_verified_ministry_can_schedule(self):
        ministry, token = _verified_ministry()
        category = TestimonyCategory.objects.create(name="Faith", slug="faith")
        response = self.client.post(
            reverse("live-broadcast-list-create"),
            {"title": "Sunday Service", "category_id": category.id},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Token {token.key}",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["status"], LiveBroadcastStatus.SCHEDULED)

    @patch("apps.live_broadcasts.services.commands.agora.issue_publisher_credential")
    def test_go_live_returns_publisher_credential(self, issue_mock):
        ministry, token = _verified_ministry()
        broadcast = LiveBroadcast.objects.create(creator=ministry, title="Sunday Service")
        now = timezone.now()
        MinistryStreamingAllowance.objects.create(
            creator=ministry, year=now.year, month=now.month, base_allowance_minutes=200, purchased_minutes=1300
        )
        issue_mock.return_value = PublisherCredential(
            app_id="app-id", channel_name="itestified-live-1-abcd", uid=ministry.id, token="signed", expires_at_unix=1
        )

        response = self.client.post(
            reverse("live-broadcast-go-live", kwargs={"broadcast_id": broadcast.id}),
            HTTP_AUTHORIZATION=f"Token {token.key}",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["channel_name"], "itestified-live-1-abcd")

    def test_go_live_without_enough_allowance_returns_402_with_shortfall(self):
        ministry, token = _verified_ministry()
        broadcast = LiveBroadcast.objects.create(creator=ministry, title="Sunday Service")

        response = self.client.post(
            reverse("live-broadcast-go-live", kwargs={"broadcast_id": broadcast.id}),
            HTTP_AUTHORIZATION=f"Token {token.key}",
        )
        self.assertEqual(response.status_code, 402)
        body = response.json()
        self.assertEqual(body["code"], "insufficient_allowance")
        self.assertIn("shortfall_minutes", body)

    def test_allowance_endpoint_reports_remaining_minutes(self):
        ministry, token = _verified_ministry()
        response = self.client.get(reverse("live-broadcast-allowance"), HTTP_AUTHORIZATION=f"Token {token.key}")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["total_allowance_minutes"], 200)
        self.assertEqual(body["remaining_minutes"], 200)

    def test_end_broadcast_requires_it_to_be_live(self):
        ministry, token = _verified_ministry()
        category = TestimonyCategory.objects.create(name="Faith", slug="faith")
        broadcast = LiveBroadcast.objects.create(creator=ministry, title="Sunday Service", category=category)

        response = self.client.post(
            reverse("live-broadcast-end", kwargs={"broadcast_id": broadcast.id}),
            HTTP_AUTHORIZATION=f"Token {token.key}",
        )
        self.assertEqual(response.status_code, 400)

    def test_creator_can_end_a_live_broadcast(self):
        ministry, token = _verified_ministry()
        category = TestimonyCategory.objects.create(name="Faith", slug="faith")
        broadcast = LiveBroadcast.objects.create(creator=ministry, title="Sunday Service", category=category)
        broadcast.status = LiveBroadcastStatus.LIVE
        broadcast.save()

        response = self.client.post(
            reverse("live-broadcast-end", kwargs={"broadcast_id": broadcast.id}),
            HTTP_AUTHORIZATION=f"Token {token.key}",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ended")
        self.assertEqual(response.json()["ended_reason"], "creator_ended")

    def test_request_approval_creates_pending_request(self):
        ministry, token = _verified_ministry()
        broadcast = LiveBroadcast.objects.create(creator=ministry, title="Sunday Service")
        response = self.client.post(
            reverse("live-broadcast-request-approval", kwargs={"broadcast_id": broadcast.id}),
            {"requested_minutes": 500},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Token {token.key}",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["status"], "pending")


class AdminApprovalApiTests(TestCase):
    def _admin(self):
        admin = UserFactory(email="admin@example.com")
        role = AdminRoleFactory(code=AdminRoleCode.SUPER_ADMIN)
        AdminAssignmentFactory(user=admin, role=role)
        return admin

    def test_non_admin_cannot_list_requests(self):
        ministry, _token = _verified_ministry()
        self.client.force_login(ministry)
        response = self.client.get(reverse("admin-live-broadcast-approval-request-list"))
        self.assertEqual(response.status_code, 403)

    def test_admin_can_list_and_approve_a_request(self):
        ministry, _token = _verified_ministry()
        broadcast = LiveBroadcast.objects.create(creator=ministry, title="Sunday Service")
        approval_request = LiveBroadcastApprovalRequest.objects.create(
            broadcast=broadcast, creator=ministry, requested_minutes=500
        )
        admin = self._admin()
        self.client.force_login(admin)

        list_response = self.client.get(reverse("admin-live-broadcast-approval-request-list"))
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(len(list_response.json()), 1)

        decide_response = self.client.post(
            reverse("admin-live-broadcast-approval-decide", kwargs={"approval_request_id": approval_request.id}),
            {"approve": True},
            content_type="application/json",
        )
        self.assertEqual(decide_response.status_code, 200)
        self.assertEqual(decide_response.json()["status"], "approved")


class ViewerBrowseApiTests(TestCase):
    def test_guest_can_list_live_broadcasts(self):
        ministry, _token = _verified_ministry()
        category = TestimonyCategory.objects.create(name="Faith", slug="faith")
        live = LiveBroadcast.objects.create(creator=ministry, title="Sunday Service", category=category)
        live.status = LiveBroadcastStatus.LIVE
        live.save()

        response = self.client.get(reverse("live-broadcast-live-now"))
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body), 1)
        self.assertEqual(body[0]["ministry_name"], "Grace Chapel")
        self.assertEqual(body[0]["title"], "Sunday Service")

    def test_guest_can_list_upcoming_broadcasts(self):
        ministry, _token = _verified_ministry()
        category = TestimonyCategory.objects.create(name="Faith", slug="faith")
        LiveBroadcast.objects.create(
            creator=ministry,
            title="Next Week",
            category=category,
            scheduled_at=timezone.now() + timezone.timedelta(days=7),
        )

        response = self.client.get(reverse("live-broadcast-upcoming"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 1)

    def test_guest_gets_404_joining_a_missing_broadcast(self):
        response = self.client.post(reverse("live-broadcast-join", kwargs={"broadcast_id": 999999}))
        self.assertEqual(response.status_code, 404)

    def test_guest_cannot_join_a_non_live_broadcast(self):
        ministry, _token = _verified_ministry()
        category = TestimonyCategory.objects.create(name="Faith", slug="faith")
        broadcast = LiveBroadcast.objects.create(creator=ministry, title="Sunday Service", category=category)

        response = self.client.post(reverse("live-broadcast-join", kwargs={"broadcast_id": broadcast.id}))
        self.assertEqual(response.status_code, 400)

    @patch("apps.live_broadcasts.services.commands.agora.issue_viewer_credential")
    def test_guest_can_join_a_live_broadcast(self, issue_mock):
        ministry, _token = _verified_ministry()
        category = TestimonyCategory.objects.create(name="Faith", slug="faith")
        broadcast = LiveBroadcast.objects.create(creator=ministry, title="Sunday Service", category=category)
        broadcast.status = LiveBroadcastStatus.LIVE
        broadcast.agora_channel_name = "itestified-live-1-abcd"
        broadcast.save()
        issue_mock.return_value = PublisherCredential(
            app_id="app", channel_name="itestified-live-1-abcd", uid=1_000_000_001, token="t", expires_at_unix=1
        )

        response = self.client.post(reverse("live-broadcast-join", kwargs={"broadcast_id": broadcast.id}))
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["channel_name"], "itestified-live-1-abcd")
        self.assertEqual(body["ministry_name"], "Grace Chapel")
        self.assertEqual(body["title"], "Sunday Service")
