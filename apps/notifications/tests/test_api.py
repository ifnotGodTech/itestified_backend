from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.authtoken.models import Token

from apps.notifications.models import UserNotification
from apps.testimonies.models import Testimony, TestimonyCategory, TestimonyStatus
from apps.users.choices import AdminRoleCode
from apps.users.tests.factories import AdminAssignmentFactory, AdminRoleFactory, UserFactory


class NotificationApiTests(TestCase):
    def setUp(self):
        self.author = UserFactory(email="author@example.com")
        self.author_token = Token.objects.create(user=self.author)
        self.category = TestimonyCategory.objects.create(
            name="Faith Stories",
            slug="faith-stories",
            is_active=True,
        )
        self.pending = Testimony.objects.create(
            author=self.author,
            category=self.category,
            title="God showed up for me",
            body="I got healed.",
            status=TestimonyStatus.PENDING_REVIEW,
        )
        self.approved = Testimony.objects.create(
            author=self.author,
            category=self.category,
            title="Approved public story",
            body="Encouraging story.",
            status=TestimonyStatus.APPROVED,
        )
        self.admin = UserFactory(email="admin@example.com")
        AdminAssignmentFactory(
            user=self.admin,
            role=AdminRoleFactory(code=AdminRoleCode.MODERATOR),
        )
        self.client.force_login(self.admin)

    def test_phase6_slice1_notification_created_on_approval(self):
        response = self.client.post(
            reverse("admin-testimony-approve", kwargs={"testimony_id": self.pending.id}),
        )
        self.assertEqual(response.status_code, 200)

        notification_response = self.client.get(
            reverse("notification-mine-list"),
            HTTP_AUTHORIZATION=f"Token {self.author_token.key}",
        )
        self.assertEqual(notification_response.status_code, 200)
        payload = notification_response.json()
        self.assertEqual(payload["unread_count"], 1)
        self.assertEqual(payload["results"][0]["notification_type"], "testimony_approved")

    def test_phase6_slice2_notification_created_on_rejection_with_reason(self):
        response = self.client.post(
            reverse("admin-testimony-reject", kwargs={"testimony_id": self.pending.id}),
            {"reason": "Please add more detail."},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)

        notification_response = self.client.get(
            reverse("notification-mine-list"),
            HTTP_AUTHORIZATION=f"Token {self.author_token.key}",
        )
        self.assertEqual(notification_response.status_code, 200)
        payload = notification_response.json()
        self.assertEqual(payload["results"][0]["notification_type"], "testimony_rejected")
        self.assertIn("Please add more detail.", payload["results"][0]["message"])

    def test_phase6_slice3_notification_created_on_new_comment_not_for_self_comment(self):
        commenter = UserFactory(email="commenter@example.com")
        commenter_token = Token.objects.create(user=commenter)

        comment_response = self.client.post(
            reverse("testimony-comment-list-create", kwargs={"testimony_id": self.approved.id}),
            {"body": "So powerful!"},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Token {commenter_token.key}",
        )
        self.assertEqual(comment_response.status_code, 201)

        author_notifications = self.client.get(
            reverse("notification-mine-list"),
            HTTP_AUTHORIZATION=f"Token {self.author_token.key}",
        )
        self.assertEqual(author_notifications.status_code, 200)
        payload = author_notifications.json()
        self.assertEqual(payload["results"][0]["notification_type"], "testimony_comment")

        self_comment_response = self.client.post(
            reverse("testimony-comment-list-create", kwargs={"testimony_id": self.approved.id}),
            {"body": "Thanks all!"},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Token {self.author_token.key}",
        )
        self.assertEqual(self_comment_response.status_code, 201)

        author_notifications_again = self.client.get(
            reverse("notification-mine-list"),
            HTTP_AUTHORIZATION=f"Token {self.author_token.key}",
        )
        self.assertEqual(author_notifications_again.status_code, 200)
        payload_again = author_notifications_again.json()
        self.assertEqual(payload_again["count"], 1)

    def test_phase6_slice4_notification_list_returns_paginated_items_and_unread_count(self):
        self.client.post(
            reverse("admin-testimony-approve", kwargs={"testimony_id": self.pending.id}),
        )
        other_pending = Testimony.objects.create(
            author=self.author,
            category=self.category,
            title="Another pending story",
            body="Waiting review",
            status=TestimonyStatus.PENDING_REVIEW,
        )
        self.client.post(
            reverse("admin-testimony-reject", kwargs={"testimony_id": other_pending.id}),
            {"reason": "Not enough details."},
            content_type="application/json",
        )

        response = self.client.get(
            reverse("notification-mine-list"),
            {"page_size": 1},
            HTTP_AUTHORIZATION=f"Token {self.author_token.key}",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["count"], 2)
        self.assertEqual(len(payload["results"]), 1)
        self.assertEqual(payload["unread_count"], 2)

    def test_phase6_slice5_mark_single_notification_as_read(self):
        self.client.post(
            reverse("admin-testimony-approve", kwargs={"testimony_id": self.pending.id}),
        )
        first_notification = UserNotification.objects.filter(recipient=self.author).first()
        self.assertIsNotNone(first_notification)
        response = self.client.post(
            reverse("notification-mark-read", kwargs={"notification_id": first_notification.id}),
            HTTP_AUTHORIZATION=f"Token {self.author_token.key}",
        )
        self.assertEqual(response.status_code, 200)
        first_notification.refresh_from_db()
        self.assertTrue(first_notification.is_read)
        self.assertIsNotNone(first_notification.read_at)
        self.assertEqual(response.json()["unread_count"], 0)

    def test_phase6_slice6_mark_all_notifications_as_read(self):
        self.client.post(
            reverse("admin-testimony-approve", kwargs={"testimony_id": self.pending.id}),
        )
        second_pending = Testimony.objects.create(
            author=self.author,
            category=self.category,
            title="Pending two",
            body="body",
            status=TestimonyStatus.PENDING_REVIEW,
        )
        self.client.post(
            reverse("admin-testimony-reject", kwargs={"testimony_id": second_pending.id}),
            {"reason": "Reason needed."},
            content_type="application/json",
        )
        response = self.client.post(
            reverse("notification-mark-all-read"),
            HTTP_AUTHORIZATION=f"Token {self.author_token.key}",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["unread_count"], 0)
        self.assertEqual(
            UserNotification.objects.filter(recipient=self.author, is_read=False).count(),
            0,
        )

    def test_phase6_slice7_admin_notification_history_with_filters(self):
        # Create diverse notifications directly for deterministic filter checks.
        UserNotification.objects.create(
            recipient=self.author,
            actor=self.admin,
            notification_type="testimony_approved",
            title="Approved One",
            message="Approved message",
            is_read=False,
        )
        read_notification = UserNotification.objects.create(
            recipient=self.author,
            actor=self.admin,
            notification_type="testimony_comment",
            title="Comment One",
            message="Comment message",
            is_read=True,
            read_at=timezone.now(),
        )
        UserNotification.objects.create(
            recipient=self.author,
            actor=self.admin,
            notification_type="testimony_rejected",
            title="Rejected One",
            message="Rejected message",
            is_read=False,
        )

        history_all = self.client.get(reverse("admin-notification-history"))
        self.assertEqual(history_all.status_code, 200)
        self.assertGreaterEqual(history_all.json()["count"], 3)

        history_read = self.client.get(
            reverse("admin-notification-history"),
            {"status": "read"},
        )
        self.assertEqual(history_read.status_code, 200)
        self.assertEqual(history_read.json()["count"], 1)
        self.assertEqual(history_read.json()["results"][0]["id"], read_notification.id)

        history_type = self.client.get(
            reverse("admin-notification-history"),
            {"type": "testimony_rejected"},
        )
        self.assertEqual(history_type.status_code, 200)
        self.assertEqual(history_type.json()["count"], 1)
        self.assertEqual(history_type.json()["results"][0]["notification_type"], "testimony_rejected")

        history_search = self.client.get(
            reverse("admin-notification-history"),
            {"q": "author@example.com"},
        )
        self.assertEqual(history_search.status_code, 200)
        self.assertGreaterEqual(history_search.json()["count"], 3)

    def test_notification_endpoints_require_authentication(self):
        self.client.logout()

        list_response = self.client.get(reverse("notification-mine-list"))
        self.assertEqual(list_response.status_code, 401)

        mark_all_response = self.client.post(reverse("notification-mark-all-read"))
        self.assertEqual(mark_all_response.status_code, 401)

        preferences_response = self.client.patch(
            reverse("notification-preferences-me"),
            {"allow_email_notifications": False},
            content_type="application/json",
        )
        self.assertEqual(preferences_response.status_code, 403)

    def test_admin_notification_history_requires_admin_session(self):
        self.client.logout()
        plain_user = UserFactory(email="plain-user@example.com")
        self.client.force_login(plain_user)
        response = self.client.get(reverse("admin-notification-history"))
        self.assertEqual(response.status_code, 403)

    def test_notification_preferences_available_for_token_authenticated_user(self):
        response = self.client.get(
            reverse("notification-preferences-me"),
            HTTP_AUTHORIZATION=f"Token {self.author_token.key}",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["allow_email_notifications"], True)
        self.assertEqual(payload["notify_new_donation_received"], True)
        self.assertEqual(payload["send_donation_thank_you_email"], False)

    def test_notification_preferences_patch_updates_fields(self):
        response = self.client.patch(
            reverse("notification-preferences-me"),
            {
                "allow_email_notifications": False,
                "notify_new_donation_received": False,
                "send_donation_thank_you_email": True,
            },
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Token {self.author_token.key}",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["allow_email_notifications"], False)
        self.assertEqual(payload["notify_new_donation_received"], False)
        self.assertEqual(payload["send_donation_thank_you_email"], True)
