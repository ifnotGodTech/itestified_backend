from django.test import TestCase
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from django.core.management import call_command
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.authtoken.models import Token
from unittest.mock import patch

from apps.notifications.models import NotificationType, UserNotification
from apps.testimonies.models import (
    TestimonyComment,
    Testimony,
    TestimonyCategory,
    TestimonyFavorite,
    TestimonyStatus,
    TestimonyType,
)
from apps.users.tests.factories import ProfileFactory, UserFactory
from apps.users.tests.factories import AdminAssignmentFactory, AdminRoleFactory
from apps.users.choices import AdminRoleCode


class TestimonyApiTests(TestCase):
    def setUp(self) -> None:
        self.category_faith = TestimonyCategory.objects.create(
            name="Faith",
            slug="faith",
            description="Faith stories",
            is_active=True,
        )
        self.category_healing = TestimonyCategory.objects.create(
            name="Healing",
            slug="healing",
            description="Healing stories",
            is_active=True,
        )
        self.category_inactive = TestimonyCategory.objects.create(
            name="Archived",
            slug="archived",
            is_active=False,
        )

        author = UserFactory(email="approved@author.com")
        ProfileFactory(user=author, full_name="Approved Author")
        Testimony.objects.create(
            author=author,
            category=self.category_faith,
            title="God healed me",
            body="I was healed after prayer.",
            testimony_type=TestimonyType.WRITTEN,
            status=TestimonyStatus.APPROVED,
            view_count=100,
            comment_count=4,
        )
        Testimony.objects.create(
            author=author,
            category=self.category_healing,
            title="Breakthrough after fasting",
            body="A powerful breakthrough came.",
            testimony_type=TestimonyType.WRITTEN,
            status=TestimonyStatus.APPROVED,
            view_count=22,
            comment_count=1,
        )
        Testimony.objects.create(
            author=author,
            category=self.category_faith,
            title="Pending testimony",
            body="This should not be listed publicly.",
            testimony_type=TestimonyType.WRITTEN,
            status=TestimonyStatus.PENDING_REVIEW,
        )
        Testimony.objects.create(
            author=author,
            category=self.category_inactive,
            title="Hidden by inactive category",
            body="Should not be listed publicly.",
            testimony_type=TestimonyType.WRITTEN,
            status=TestimonyStatus.APPROVED,
        )

    def test_slice1_browse_testimonies_lists_only_approved_with_filters(self) -> None:
        response = self.client.get(reverse("testimony-list"))
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["count"], 2)
        self.assertEqual(len(body["results"]), 2)

        filtered = self.client.get(f'{reverse("testimony-list")}?category=faith')
        self.assertEqual(filtered.status_code, 200)
        self.assertEqual(filtered.json()["count"], 1)
        self.assertEqual(filtered.json()["results"][0]["category_slug"], "faith")

        searched = self.client.get(f'{reverse("testimony-list")}?search=breakthrough')
        self.assertEqual(searched.status_code, 200)
        self.assertEqual(searched.json()["count"], 1)
        self.assertIn("Breakthrough", searched.json()["results"][0]["title"])

    def test_public_video_list_returns_generated_cloudinary_thumbnail_when_missing(self) -> None:
        author = UserFactory(email="video@author.com")
        video = Testimony.objects.create(
            author=author,
            category=self.category_healing,
            title="Cloudinary video",
            body="A video testimony.",
            testimony_type=TestimonyType.VIDEO,
            status=TestimonyStatus.APPROVED,
            video_url="https://res.cloudinary.com/itestified/video/upload/v1784671784/amtlhus0uyr7wovwvb6v.mp4",
            thumbnail_url="",
        )

        response = self.client.get(reverse("testimony-list"))

        self.assertEqual(response.status_code, 200)
        payload = next(item for item in response.json()["results"] if item["id"] == video.id)
        self.assertEqual(
            payload["thumbnail_url"],
            "https://res.cloudinary.com/itestified/video/upload/so_2,w_1280,h_720,c_fill,g_auto/v1784671784/amtlhus0uyr7wovwvb6v.jpg",
        )

    def test_category_slug_auto_generates_when_missing(self) -> None:
        category = TestimonyCategory.objects.create(name="My New Category")
        self.assertEqual(category.slug, "my-new-category")

    def test_slice2_view_testimony_detail_returns_full_fields(self) -> None:
        testimony = Testimony.objects.get(title="God healed me")
        response = self.client.get(reverse("testimony-detail", kwargs={"pk": testimony.pk}))

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["title"], testimony.title)
        self.assertEqual(body["body"], testimony.body)
        self.assertEqual(body["author_name"], "Approved Author")
        self.assertEqual(body["category"], testimony.category.name)
        self.assertEqual(body["view_count"], testimony.view_count)
        self.assertEqual(body["comment_count"], testimony.comment_count)

    def test_view_increment_increases_view_count(self) -> None:
        testimony = Testimony.objects.get(title="God healed me")
        before = testimony.view_count
        response = self.client.post(
            reverse("testimony-view-increment", kwargs={"testimony_id": testimony.id}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        testimony.refresh_from_db()
        self.assertEqual(testimony.view_count, before + 1)
        self.assertEqual(response.json()["view_count"], before + 1)

    def test_view_increment_returns_404_for_non_public_testimony(self) -> None:
        pending = Testimony.objects.get(title="Pending testimony")
        response = self.client.post(
            reverse("testimony-view-increment", kwargs={"testimony_id": pending.id}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)

    def test_slice3_submit_written_testimony_requires_auth_and_sets_pending(self) -> None:
        unauth_response = self.client.post(
            reverse("testimony-submit-written"),
            {
                "title": "Fresh testimony",
                "body": "God did it for me again.",
                "category_id": self.category_faith.id,
            },
            content_type="application/json",
        )
        self.assertEqual(unauth_response.status_code, 401)

        user = UserFactory(email="writer@example.com")
        ProfileFactory(user=user, full_name="Writer User")
        token = Token.objects.create(user=user)
        auth_response = self.client.post(
            reverse("testimony-submit-written"),
            {
                "title": "Fresh testimony",
                "body": "God did it for me again.",
                "category_id": self.category_faith.id,
            },
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Token {token.key}",
        )

        self.assertEqual(auth_response.status_code, 201)
        created = Testimony.objects.get(title="Fresh testimony")
        self.assertEqual(created.author, user)
        self.assertEqual(created.status, TestimonyStatus.PENDING_REVIEW)
        self.assertEqual(created.testimony_type, TestimonyType.WRITTEN)

    def test_mobile_video_testimony_submission_route_is_not_exposed(self) -> None:
        with self.assertRaises(NoReverseMatch):
            reverse("testimony-submit-video")

    def test_slice5_my_testimonies_lists_all_statuses_for_user(self) -> None:
        owner = UserFactory(email="mine@example.com")
        ProfileFactory(user=owner, full_name="Mine User")
        other = UserFactory(email="other@example.com")
        ProfileFactory(user=other, full_name="Other User")
        token = Token.objects.create(user=owner)

        Testimony.objects.create(
            author=owner,
            category=self.category_faith,
            title="Mine approved",
            body="Approved one",
            testimony_type=TestimonyType.WRITTEN,
            status=TestimonyStatus.APPROVED,
        )
        Testimony.objects.create(
            author=owner,
            category=self.category_faith,
            title="Mine rejected",
            body="Rejected one",
            testimony_type=TestimonyType.WRITTEN,
            status=TestimonyStatus.REJECTED,
            rejection_reason="Needs more detail.",
        )
        Testimony.objects.create(
            author=other,
            category=self.category_faith,
            title="Not mine",
            body="Not mine",
            testimony_type=TestimonyType.WRITTEN,
            status=TestimonyStatus.APPROVED,
        )

        response = self.client.get(
            reverse("testimony-mine-list"),
            HTTP_AUTHORIZATION=f"Token {token.key}",
        )
        self.assertEqual(response.status_code, 200)
        titles = {item["title"] for item in response.json()["results"]}
        self.assertIn("Mine approved", titles)
        self.assertIn("Mine rejected", titles)
        self.assertNotIn("Not mine", titles)
        rejected = next(item for item in response.json()["results"] if item["title"] == "Mine rejected")
        self.assertEqual(rejected["rejection_reason"], "Needs more detail.")

    def test_my_testimonies_orders_newest_first_so_fresh_pending_is_visible(self) -> None:
        owner = UserFactory(email="fresh-mine@example.com")
        ProfileFactory(user=owner, full_name="Fresh Mine")
        token = Token.objects.create(user=owner)
        older = Testimony.objects.create(
            author=owner,
            category=self.category_faith,
            title="Older approved",
            body="Older approved body",
            testimony_type=TestimonyType.WRITTEN,
            status=TestimonyStatus.APPROVED,
        )
        fresh_pending = Testimony.objects.create(
            author=owner,
            category=self.category_faith,
            title="Fresh pending",
            body="Fresh pending body",
            testimony_type=TestimonyType.WRITTEN,
            status=TestimonyStatus.PENDING_REVIEW,
        )

        response = self.client.get(
            reverse("testimony-mine-list"),
            HTTP_AUTHORIZATION=f"Token {token.key}",
        )

        self.assertEqual(response.status_code, 200)
        results = response.json()["results"]
        self.assertEqual(results[0]["id"], fresh_pending.id)
        self.assertEqual(results[0]["status"], TestimonyStatus.PENDING_REVIEW)
        self.assertEqual(results[1]["id"], older.id)

    def test_rejected_written_testimony_resubmit_transitions_to_pending_and_notifies_admin(self) -> None:
        owner = UserFactory(email="resubmit-owner@example.com")
        ProfileFactory(user=owner, full_name="Resubmit Owner")
        owner_token = Token.objects.create(user=owner)
        rejected = Testimony.objects.create(
            author=owner,
            category=self.category_faith,
            title="Rejected Title",
            body="Rejected body",
            testimony_type=TestimonyType.WRITTEN,
            status=TestimonyStatus.REJECTED,
            rejection_reason="Needs details.",
        )

        admin_user = UserFactory(email="resubmit-admin@example.com")
        ProfileFactory(user=admin_user, full_name="Resubmit Admin")
        admin_role = AdminRoleFactory(code=AdminRoleCode.MODERATOR)
        AdminAssignmentFactory(user=admin_user, role=admin_role)

        response = self.client.post(
            reverse("testimony-mine-resubmit", kwargs={"testimony_id": rejected.id}),
            {
                "title": "Updated Rejected Title",
                "body": "Updated testimony body with enough details.",
                "category_id": self.category_healing.id,
            },
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Token {owner_token.key}",
        )
        self.assertEqual(response.status_code, 200)
        rejected.refresh_from_db()
        self.assertEqual(rejected.status, TestimonyStatus.PENDING_REVIEW)
        self.assertEqual(rejected.rejection_reason, "")
        self.assertEqual(rejected.category_id, self.category_healing.id)
        self.assertEqual(rejected.title, "Updated Rejected Title")

        admin_notification = UserNotification.objects.filter(
            recipient=admin_user,
            actor=owner,
            notification_type=NotificationType.TESTIMONY_SUBMITTED,
        ).first()
        self.assertIsNotNone(admin_notification)
        self.assertIn("Updated Rejected Title", admin_notification.message)  # type: ignore[union-attr]

    def test_rejected_testimony_resubmit_returns_404_for_non_owner(self) -> None:
        owner = UserFactory(email="resubmit-owner-2@example.com")
        other = UserFactory(email="resubmit-other@example.com")
        other_token = Token.objects.create(user=other)
        rejected = Testimony.objects.create(
            author=owner,
            category=self.category_faith,
            title="Owner Rejected",
            body="Original body",
            testimony_type=TestimonyType.WRITTEN,
            status=TestimonyStatus.REJECTED,
            rejection_reason="Needs edit",
        )

        response = self.client.post(
            reverse("testimony-mine-resubmit", kwargs={"testimony_id": rejected.id}),
            {
                "title": "Attempted edit",
                "body": "Not allowed",
                "category_id": self.category_faith.id,
            },
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Token {other_token.key}",
        )
        self.assertEqual(response.status_code, 404)
        rejected.refresh_from_db()
        self.assertEqual(rejected.status, TestimonyStatus.REJECTED)
        self.assertEqual(rejected.title, "Owner Rejected")

    def test_rejected_testimony_resubmit_rejects_non_rejected_status(self) -> None:
        owner = UserFactory(email="resubmit-owner-3@example.com")
        owner_token = Token.objects.create(user=owner)
        pending = Testimony.objects.create(
            author=owner,
            category=self.category_faith,
            title="Pending testimony",
            body="Pending body",
            testimony_type=TestimonyType.WRITTEN,
            status=TestimonyStatus.PENDING_REVIEW,
        )

        response = self.client.post(
            reverse("testimony-mine-resubmit", kwargs={"testimony_id": pending.id}),
            {
                "title": "Pending testimony updated",
                "body": "Still pending",
                "category_id": self.category_healing.id,
            },
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Token {owner_token.key}",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["message"], "Only rejected testimonies can be resubmitted.")

    def test_my_testimony_delete_allows_owner_for_rejected(self) -> None:
        owner = UserFactory(email="delete-owner@example.com")
        owner_token = Token.objects.create(user=owner)
        rejected = Testimony.objects.create(
            author=owner,
            category=self.category_faith,
            title="Delete me rejected",
            body="Rejected content",
            testimony_type=TestimonyType.WRITTEN,
            status=TestimonyStatus.REJECTED,
            rejection_reason="Needs edit",
        )

        response = self.client.delete(
            reverse("testimony-mine-delete", kwargs={"testimony_id": rejected.id}),
            HTTP_AUTHORIZATION=f"Token {owner_token.key}",
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Testimony.objects.filter(id=rejected.id).exists())

    def test_my_testimony_delete_rejects_non_owner(self) -> None:
        owner = UserFactory(email="delete-owner-2@example.com")
        other = UserFactory(email="delete-other@example.com")
        other_token = Token.objects.create(user=other)
        rejected = Testimony.objects.create(
            author=owner,
            category=self.category_faith,
            title="Cannot delete",
            body="Rejected content",
            testimony_type=TestimonyType.WRITTEN,
            status=TestimonyStatus.REJECTED,
            rejection_reason="Needs edit",
        )

        response = self.client.delete(
            reverse("testimony-mine-delete", kwargs={"testimony_id": rejected.id}),
            HTTP_AUTHORIZATION=f"Token {other_token.key}",
        )
        self.assertEqual(response.status_code, 404)
        self.assertTrue(Testimony.objects.filter(id=rejected.id).exists())

    def test_my_testimony_delete_rejects_approved_status(self) -> None:
        owner = UserFactory(email="delete-owner-3@example.com")
        owner_token = Token.objects.create(user=owner)
        approved = Testimony.objects.create(
            author=owner,
            category=self.category_faith,
            title="Approved cannot delete",
            body="Approved content",
            testimony_type=TestimonyType.WRITTEN,
            status=TestimonyStatus.APPROVED,
        )

        response = self.client.delete(
            reverse("testimony-mine-delete", kwargs={"testimony_id": approved.id}),
            HTTP_AUTHORIZATION=f"Token {owner_token.key}",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["message"], "Only pending or rejected testimonies can be deleted.")
        self.assertTrue(Testimony.objects.filter(id=approved.id).exists())

    def test_slice6_and_slice7_add_and_remove_favorite(self) -> None:
        user = UserFactory(email="favorite@example.com")
        ProfileFactory(user=user, full_name="Favorite User")
        token = Token.objects.create(user=user)
        testimony = Testimony.objects.get(title="God healed me")
        assert testimony is not None

        add_response = self.client.post(
            reverse("testimony-favorite-toggle", kwargs={"testimony_id": testimony.id}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Token {token.key}",
        )
        self.assertEqual(add_response.status_code, 201)
        self.assertTrue(
            TestimonyFavorite.objects.filter(user=user, testimony=testimony).exists()
        )

        list_response = self.client.get(
            reverse("testimony-favorite-list"),
            HTTP_AUTHORIZATION=f"Token {token.key}",
        )
        self.assertEqual(list_response.status_code, 200)
        favorite_ids = [item["testimony_id"] for item in list_response.json()]
        self.assertIn(testimony.id, favorite_ids)

        remove_response = self.client.delete(
            reverse("testimony-favorite-toggle", kwargs={"testimony_id": testimony.id}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Token {token.key}",
        )
        self.assertEqual(remove_response.status_code, 200)
        self.assertFalse(
            TestimonyFavorite.objects.filter(user=user, testimony=testimony).exists()
        )

    def test_slice8_view_favorites_feed_returns_paginated_testimonies(self) -> None:
        user = UserFactory(email="favorite-feed@example.com")
        ProfileFactory(user=user, full_name="Favorite Feed User")
        token = Token.objects.create(user=user)
        testimony = Testimony.objects.get(title="God healed me")
        TestimonyFavorite.objects.create(user=user, testimony=testimony)

        response = self.client.get(
            reverse("testimony-favorite-feed"),
            HTTP_AUTHORIZATION=f"Token {token.key}",
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["results"][0]["title"], "God healed me")

    def test_slice9_comment_on_approved_testimony(self) -> None:
        user = UserFactory(email="commenter@example.com")
        ProfileFactory(user=user, full_name="Comment User")
        token = Token.objects.create(user=user)
        testimony = Testimony.objects.get(title="God healed me")
        initial_comment_count = testimony.comment_count

        response = self.client.post(
            reverse("testimony-comment-list-create", kwargs={"testimony_id": testimony.id}),
            {"body": "This blessed me so much."},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Token {token.key}",
        )
        self.assertEqual(response.status_code, 201)
        self.assertTrue(
            TestimonyComment.objects.filter(testimony=testimony, author=user).exists()
        )
        testimony.refresh_from_db()
        self.assertEqual(testimony.comment_count, initial_comment_count + 1)

    def test_comment_reply_allows_depth_one_only(self) -> None:
        user = UserFactory(email="reply-user@example.com")
        ProfileFactory(user=user, full_name="Reply User")
        token = Token.objects.create(user=user)
        testimony = Testimony.objects.get(title="God healed me")
        top_level = TestimonyComment.objects.create(
            testimony=testimony,
            author=user,
            body="Top level comment.",
        )

        reply_response = self.client.post(
            reverse("testimony-comment-list-create", kwargs={"testimony_id": testimony.id}),
            {"body": "First level reply", "parent_comment_id": top_level.id},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Token {token.key}",
        )
        self.assertEqual(reply_response.status_code, 201)
        reply = TestimonyComment.objects.filter(
            testimony=testimony,
            author=user,
            body="First level reply",
            parent_comment=top_level,
        ).first()
        self.assertIsNotNone(reply)
        reply_id = reply.id  # type: ignore[union-attr]

        nested_response = self.client.post(
            reverse("testimony-comment-list-create", kwargs={"testimony_id": testimony.id}),
            {"body": "Second level reply", "parent_comment_id": reply_id},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Token {token.key}",
        )
        self.assertEqual(nested_response.status_code, 400)
        self.assertEqual(nested_response.json()["message"], "Only one reply level is allowed.")

    def test_comment_list_returns_top_level_only_with_replies_count(self) -> None:
        testimony = Testimony.objects.get(title="God healed me")
        user = UserFactory(email="reply-reader@example.com")
        ProfileFactory(user=user, full_name="Reply Reader")
        top = TestimonyComment.objects.create(
            testimony=testimony,
            author=user,
            body="Parent comment.",
        )
        TestimonyComment.objects.create(
            testimony=testimony,
            author=user,
            body="Child reply.",
            parent_comment=top,
        )

        response = self.client.get(
            reverse("testimony-comment-list-create", kwargs={"testimony_id": testimony.id}),
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        ids = [item["id"] for item in payload["results"]]
        self.assertIn(top.id, ids)
        top_row = next(item for item in payload["results"] if item["id"] == top.id)
        self.assertEqual(top_row["replies_count"], 1)
        self.assertEqual(len(top_row["replies"]), 1)
        self.assertEqual(top_row["replies"][0]["body"], "Child reply.")
        self.assertEqual(top_row["replies"][0]["parent_comment_id"], top.id)

    def test_comment_list_is_public_for_approved_testimony(self) -> None:
        testimony = Testimony.objects.get(title="God healed me")
        commenter = UserFactory(email="public-comment-reader@example.com")
        ProfileFactory(user=commenter, full_name="Public Comment Reader")
        TestimonyComment.objects.create(
            testimony=testimony,
            author=commenter,
            body="Public visible comment.",
        )

        response = self.client.get(
            reverse("testimony-comment-list-create", kwargs={"testimony_id": testimony.id}),
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertGreaterEqual(payload["count"], 1)

    def test_comment_list_sets_is_owner_for_authenticated_user(self) -> None:
        testimony = Testimony.objects.get(title="God healed me")
        owner = UserFactory(email="owner-visible@example.com")
        ProfileFactory(user=owner, full_name="Owner Visible")
        token = Token.objects.create(user=owner)
        comment = TestimonyComment.objects.create(
            testimony=testimony,
            author=owner,
            body="Owner comment visible.",
        )

        response = self.client.get(
            reverse("testimony-comment-list-create", kwargs={"testimony_id": testimony.id}),
            HTTP_AUTHORIZATION=f"Token {token.key}",
        )
        self.assertEqual(response.status_code, 200)
        rows = response.json()["results"]
        row = next(item for item in rows if item["id"] == comment.id)
        self.assertEqual(row["is_owner"], True)

    def test_comment_list_sets_is_owner_false_for_other_users_comment(self) -> None:
        testimony = Testimony.objects.get(title="God healed me")
        owner = UserFactory(email="comment-owner-visible@example.com")
        ProfileFactory(user=owner, full_name="Comment Owner")
        reader = UserFactory(email="comment-reader-visible@example.com")
        ProfileFactory(user=reader, full_name="Comment Reader")
        token = Token.objects.create(user=reader)
        comment = TestimonyComment.objects.create(
            testimony=testimony,
            author=owner,
            body="Someone else's comment.",
        )

        response = self.client.get(
            reverse("testimony-comment-list-create", kwargs={"testimony_id": testimony.id}),
            HTTP_AUTHORIZATION=f"Token {token.key}",
        )
        self.assertEqual(response.status_code, 200)
        rows = response.json()["results"]
        row = next(item for item in rows if item["id"] == comment.id)
        self.assertEqual(row["is_owner"], False)

    def test_slice10_delete_only_own_comment(self) -> None:
        owner = UserFactory(email="owner@example.com")
        ProfileFactory(user=owner, full_name="Owner")
        other = UserFactory(email="other-commenter@example.com")
        ProfileFactory(user=other, full_name="Other")
        owner_token = Token.objects.create(user=owner)
        other_token = Token.objects.create(user=other)
        testimony = Testimony.objects.get(title="God healed me")
        comment = TestimonyComment.objects.create(
            testimony=testimony,
            author=owner,
            body="Owner comment.",
        )
        Testimony.objects.filter(id=testimony.id).update(comment_count=1)

        forbidden = self.client.delete(
            reverse("testimony-comment-delete", kwargs={"comment_id": comment.id}),
            HTTP_AUTHORIZATION=f"Token {other_token.key}",
        )
        self.assertEqual(forbidden.status_code, 403)
        self.assertTrue(TestimonyComment.objects.filter(id=comment.id).exists())

        success = self.client.delete(
            reverse("testimony-comment-delete", kwargs={"comment_id": comment.id}),
            HTTP_AUTHORIZATION=f"Token {owner_token.key}",
        )
        self.assertEqual(success.status_code, 200)
        self.assertFalse(TestimonyComment.objects.filter(id=comment.id).exists())

    def test_slice10_delete_comment_never_sets_negative_comment_count(self) -> None:
        owner = UserFactory(email="owner-negative@example.com")
        ProfileFactory(user=owner, full_name="Owner Negative")
        owner_token = Token.objects.create(user=owner)
        testimony = Testimony.objects.get(title="God healed me")
        comment = TestimonyComment.objects.create(
            testimony=testimony,
            author=owner,
            body="Owner comment.",
        )
        Testimony.objects.filter(id=testimony.id).update(comment_count=0)

        success = self.client.delete(
            reverse("testimony-comment-delete", kwargs={"comment_id": comment.id}),
            HTTP_AUTHORIZATION=f"Token {owner_token.key}",
        )
        self.assertEqual(success.status_code, 200)
        testimony.refresh_from_db()
        self.assertEqual(testimony.comment_count, 0)


class AdminTestimonyApiTests(TestCase):
    def setUp(self) -> None:
        self.category = TestimonyCategory.objects.create(
            name="Deliverance",
            slug="deliverance",
            description="Deliverance stories",
            is_active=True,
        )
        self.author = UserFactory(email="member@example.com")
        ProfileFactory(user=self.author, full_name="Member User")
        self.pending = Testimony.objects.create(
            author=self.author,
            category=self.category,
            title="Pending testimony",
            body="Pending body",
            testimony_type=TestimonyType.WRITTEN,
            status=TestimonyStatus.PENDING_REVIEW,
        )
        self.approved = Testimony.objects.create(
            author=self.author,
            category=self.category,
            title="Approved testimony",
            body="Approved body\nSource: Youtube",
            testimony_type=TestimonyType.VIDEO,
            status=TestimonyStatus.APPROVED,
            video_url="https://example.com/video.mp4",
        )
        self.admin = UserFactory(email="admin@example.com")
        ProfileFactory(user=self.admin, full_name="Admin User")
        role = AdminRoleFactory(code=AdminRoleCode.SUPER_ADMIN)
        AdminAssignmentFactory(user=self.admin, role=role)
        self.client.force_login(self.admin)

    def test_slice11_admin_manage_categories(self) -> None:
        list_response = self.client.get(reverse("admin-testimony-category-list-create"))
        self.assertEqual(list_response.status_code, 200)
        self.assertGreaterEqual(len(list_response.json()), 1)

        create_response = self.client.post(
            reverse("admin-testimony-category-list-create"),
            {"name": "faith", "description": "Faith stories"},
            content_type="application/json",
        )
        self.assertEqual(create_response.status_code, 201)
        self.assertEqual(create_response.json()["name"], "Faith")
        created_id = create_response.json()["id"]

        duplicate_response = self.client.post(
            reverse("admin-testimony-category-list-create"),
            {"name": "FAITH", "description": "Duplicate faith stories"},
            content_type="application/json",
        )
        self.assertEqual(duplicate_response.status_code, 400)
        self.assertEqual(duplicate_response.json()["name"], ["Category name already exists."])

        edit_response = self.client.patch(
            reverse("admin-testimony-category-detail", kwargs={"pk": created_id}),
            {"description": "Updated faith stories"},
            content_type="application/json",
        )
        self.assertEqual(edit_response.status_code, 200)
        self.assertEqual(edit_response.json()["description"], "Updated faith stories")

        deactivate_response = self.client.delete(
            reverse("admin-testimony-category-activation", kwargs={"category_id": created_id})
        )
        self.assertEqual(deactivate_response.status_code, 200)
        self.assertEqual(deactivate_response.json()["is_active"], False)

        reactivate_response = self.client.post(
            reverse("admin-testimony-category-activation", kwargs={"category_id": created_id})
        )
        self.assertEqual(reactivate_response.status_code, 200)
        self.assertEqual(reactivate_response.json()["is_active"], True)

    def test_slice12_admin_view_all_testimonies_with_filters_and_detail(self) -> None:
        list_response = self.client.get(reverse("admin-testimony-list"))
        self.assertEqual(list_response.status_code, 200)
        payload = list_response.json()
        self.assertEqual(payload["count"], 2)
        self.assertEqual([row["id"] for row in payload["results"]], [self.approved.id, self.pending.id])

        pending_only = self.client.get(f'{reverse("admin-testimony-list")}?status=pending_review')
        self.assertEqual(pending_only.status_code, 200)
        self.assertEqual(pending_only.json()["count"], 1)
        self.assertEqual(pending_only.json()["results"][0]["title"], self.pending.title)

        category_only = self.client.get(f'{reverse("admin-testimony-list")}?category=deliverance')
        self.assertEqual(category_only.status_code, 200)
        self.assertEqual(category_only.json()["count"], 2)

        written_only = self.client.get(f'{reverse("admin-testimony-list")}?testimony_type=written')
        self.assertEqual(written_only.status_code, 200)
        self.assertEqual(written_only.json()["count"], 1)
        self.assertEqual(written_only.json()["results"][0]["title"], self.pending.title)

        video_only = self.client.get(f'{reverse("admin-testimony-list")}?testimony_type=video')
        self.assertEqual(video_only.status_code, 200)
        self.assertEqual(video_only.json()["count"], 1)
        self.assertEqual(video_only.json()["results"][0]["title"], self.approved.title)

        source_only = self.client.get(f'{reverse("admin-testimony-list")}?testimony_type=video&source=YouTube')
        self.assertEqual(source_only.status_code, 200)
        self.assertEqual(source_only.json()["count"], 1)
        self.assertEqual(source_only.json()["results"][0]["title"], self.approved.title)
        self.assertEqual(source_only.json()["results"][0]["source"], "YouTube")

        lower_source = self.client.get(f'{reverse("admin-testimony-list")}?testimony_type=video&source=youtube')
        self.assertEqual(lower_source.status_code, 200)
        self.assertEqual(lower_source.json()["count"], 1)
        self.assertEqual(lower_source.json()["results"][0]["source"], "YouTube")

        missing_source = self.client.get(f'{reverse("admin-testimony-list")}?testimony_type=video&source=TikTok')
        self.assertEqual(missing_source.status_code, 200)
        self.assertEqual(missing_source.json()["count"], 0)

        date_only = self.client.get(f'{reverse("admin-testimony-list")}?date_from=01/01/2020&date_to=31/12/2099')
        self.assertEqual(date_only.status_code, 200)
        self.assertEqual(date_only.json()["count"], 2)

        detail_response = self.client.get(reverse("admin-testimony-detail", kwargs={"pk": self.approved.id}))
        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(detail_response.json()["title"], self.approved.title)
        self.assertEqual(detail_response.json()["status"], TestimonyStatus.APPROVED)

    @patch("apps.testimonies.api.serializers.upload_testimony_media")
    def test_slice13_admin_upload_video_testimony_uses_cloudinary_urls(self, upload_mock) -> None:
        from apps.testimonies.services.media_uploads import CloudinaryUploadResult

        upload_mock.return_value = CloudinaryUploadResult(
            video_url="https://res.cloudinary.com/demo/video/upload/v1/testimony.mp4",
            thumbnail_url="https://res.cloudinary.com/demo/image/upload/v1/thumb.jpg",
        )

        video = SimpleUploadedFile("testimony.mp4", b"fake-video-content", content_type="video/mp4")
        thumbnail = SimpleUploadedFile("thumb.jpg", b"fake-image-content", content_type="image/jpeg")

        response = self.client.post(
            reverse("admin-testimony-upload-video"),
            {
                "title": "Admin uploaded testimony",
                "category_id": self.category.id,
                "body": "Uploaded by admin.",
                "video_file": video,
                "thumbnail_file": thumbnail,
            },
        )
        self.assertEqual(response.status_code, 201)
        created = Testimony.objects.get(title="Admin uploaded testimony")
        self.assertEqual(created.testimony_type, TestimonyType.VIDEO)
        self.assertEqual(created.status, TestimonyStatus.APPROVED)
        self.assertEqual(created.video_url, "https://res.cloudinary.com/demo/video/upload/v1/testimony.mp4")
        self.assertEqual(created.thumbnail_url, "https://res.cloudinary.com/demo/image/upload/v1/thumb.jpg")
        submitted_notifications = UserNotification.objects.filter(
            notification_type=NotificationType.TESTIMONY_SUBMITTED
        ).count()
        self.assertEqual(submitted_notifications, 0)
        published_notifications = UserNotification.objects.filter(
            notification_type=NotificationType.NEW_VIDEO_TESTIMONY,
            recipient=self.author,
        )
        self.assertEqual(published_notifications.count(), 1)
        self.assertIn("Admin uploaded testimony", published_notifications.get().message)

    @patch("apps.testimonies.api.views.create_direct_upload_signature")
    def test_admin_upload_signature_returns_signed_cloudinary_payload(self, signature_mock) -> None:
        from apps.testimonies.services.media_uploads import CloudinaryUploadSignature

        signature_mock.return_value = CloudinaryUploadSignature(
            cloud_name="demo",
            api_key="12345",
            timestamp=1784720000,
            folder="itestified/testimonies/videos",
            signature="signed-payload",
        )

        response = self.client.post(
            reverse("admin-testimony-upload-signature"),
            {"resource_type": "video"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "cloud_name": "demo",
                "api_key": "12345",
                "timestamp": 1784720000,
                "folder": "itestified/testimonies/videos",
                "signature": "signed-payload",
                "resource_type": "video",
            },
        )
        signature_mock.assert_called_once_with(resource_type="video")

    def test_admin_create_video_from_url_normalizes_source_in_body(self) -> None:
        response = self.client.post(
            reverse("admin-testimony-create-video-from-url"),
            {
                "title": "Video from URL",
                "category_id": self.category.id,
                "body": "Uploaded by admin.\nSource: youtube\nSource: YouTube",
                "video_url": "https://res.cloudinary.com/demo/video/upload/v1/testimony-url.mp4",
                "thumbnail_url": "",
                "upload_status": "draft",
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201)
        created = Testimony.objects.get(title="Video from URL")
        self.assertEqual(created.body, "Uploaded by admin.\nSource: YouTube")
        self.assertEqual(response.json()["source"], "YouTube")

    @patch("apps.testimonies.api.serializers.upload_testimony_media")
    def test_admin_upload_video_with_draft_status_persists_draft(self, upload_mock) -> None:
        from apps.testimonies.services.media_uploads import CloudinaryUploadResult

        upload_mock.return_value = CloudinaryUploadResult(
            video_url="https://res.cloudinary.com/demo/video/upload/v1/testimony-draft.mp4",
            thumbnail_url="",
        )
        video = SimpleUploadedFile("testimony.mp4", b"fake-video-content", content_type="video/mp4")
        response = self.client.post(
            reverse("admin-testimony-upload-video"),
            {
                "title": "Draft upload testimony",
                "category_id": self.category.id,
                "upload_status": "draft",
                "video_file": video,
            },
        )
        self.assertEqual(response.status_code, 201)
        created = Testimony.objects.get(title="Draft upload testimony")
        self.assertEqual(created.status, TestimonyStatus.DRAFT)
        self.assertIsNone(created.publish_at)
        self.assertFalse(
            UserNotification.objects.filter(
                notification_type=NotificationType.NEW_VIDEO_TESTIMONY,
                message__icontains="Draft upload testimony",
            ).exists()
        )

    @patch("apps.testimonies.api.serializers.upload_testimony_media")
    def test_admin_upload_video_with_schedule_status_requires_future_datetime(self, upload_mock) -> None:
        from apps.testimonies.services.media_uploads import CloudinaryUploadResult

        upload_mock.return_value = CloudinaryUploadResult(
            video_url="https://res.cloudinary.com/demo/video/upload/v1/testimony-scheduled.mp4",
            thumbnail_url="",
        )
        video = SimpleUploadedFile("testimony.mp4", b"fake-video-content", content_type="video/mp4")
        missing_schedule = self.client.post(
            reverse("admin-testimony-upload-video"),
            {
                "title": "Scheduled upload testimony",
                "category_id": self.category.id,
                "upload_status": "schedule_for_later",
                "video_file": video,
            },
        )
        self.assertEqual(missing_schedule.status_code, 400)
        self.assertIn("scheduled_publish_at", missing_schedule.json())

        valid_video = SimpleUploadedFile("testimony2.mp4", b"fake-video-content", content_type="video/mp4")
        publish_at = (timezone.now() + timezone.timedelta(hours=1)).isoformat()
        valid_schedule = self.client.post(
            reverse("admin-testimony-upload-video"),
            {
                "title": "Scheduled upload testimony",
                "category_id": self.category.id,
                "upload_status": "schedule_for_later",
                "scheduled_publish_at": publish_at,
                "video_file": valid_video,
            },
        )
        self.assertEqual(valid_schedule.status_code, 201)
        created = Testimony.objects.get(title="Scheduled upload testimony")
        self.assertEqual(created.status, TestimonyStatus.SCHEDULED)
        self.assertIsNotNone(created.publish_at)
        self.assertFalse(
            UserNotification.objects.filter(
                notification_type=NotificationType.NEW_VIDEO_TESTIMONY,
                message__icontains="Scheduled upload testimony",
            ).exists()
        )

    @patch("apps.testimonies.api.serializers.upload_testimony_media")
    def test_admin_upload_video_upload_now_status_persists_approved(self, upload_mock) -> None:
        from apps.testimonies.services.media_uploads import CloudinaryUploadResult

        upload_mock.return_value = CloudinaryUploadResult(
            video_url="https://res.cloudinary.com/demo/video/upload/v1/testimony-upload-now.mp4",
            thumbnail_url="",
        )
        video = SimpleUploadedFile("testimony.mp4", b"fake-video-content", content_type="video/mp4")
        response = self.client.post(
            reverse("admin-testimony-upload-video"),
            {
                "title": "Upload now testimony",
                "category_id": self.category.id,
                "upload_status": "upload_now",
                "video_file": video,
            },
        )
        self.assertEqual(response.status_code, 201)
        created = Testimony.objects.get(title="Upload now testimony")
        self.assertEqual(created.status, TestimonyStatus.APPROVED)
        self.assertIsNone(created.publish_at)
        self.assertTrue(
            UserNotification.objects.filter(
                recipient=self.author,
                notification_type=NotificationType.NEW_VIDEO_TESTIMONY,
                message__icontains="Upload now testimony",
            ).exists()
        )

    def test_admin_upload_video_rejects_non_mp4_file(self) -> None:
        video = SimpleUploadedFile("testimony.mov", b"fake-video-content", content_type="video/quicktime")
        response = self.client.post(
            reverse("admin-testimony-upload-video"),
            {
                "title": "Invalid format upload",
                "category_id": self.category.id,
                "video_file": video,
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("video_file", response.json())

    def test_admin_upload_video_rejects_excessive_batch_size(self) -> None:
        video = SimpleUploadedFile("testimony.mp4", b"fake-video-content", content_type="video/mp4")
        response = self.client.post(
            reverse("admin-testimony-upload-video"),
            {
                "title": "Too many in batch",
                "category_id": self.category.id,
                "total_videos_in_batch": 11,
                "video_file": video,
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("total_videos_in_batch", response.json())

    def test_admin_delete_video_testimony(self) -> None:
        response = self.client.delete(
            reverse("admin-testimony-delete-video", kwargs={"testimony_id": self.approved.id})
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Testimony.objects.filter(id=self.approved.id).exists())

    def test_admin_delete_text_testimony(self) -> None:
        response = self.client.delete(
            reverse("admin-testimony-delete-video", kwargs={"testimony_id": self.pending.id})
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Testimony.objects.filter(id=self.pending.id).exists())

    def test_admin_delete_testimony_requires_admin(self) -> None:
        self.client.logout()
        non_admin = UserFactory(email="nonadmin-delete@example.com")
        self.client.force_login(non_admin)
        response = self.client.delete(
            reverse("admin-testimony-delete-video", kwargs={"testimony_id": self.approved.id})
        )
        self.assertEqual(response.status_code, 403)

    def test_admin_edit_video_testimony_updates_title_and_category(self) -> None:
        faith = TestimonyCategory.objects.create(
            name="Faith",
            slug="faith",
            description="Faith stories",
            is_active=True,
        )
        response = self.client.patch(
            reverse("admin-testimony-edit-video", kwargs={"testimony_id": self.approved.id}),
            {"title": "Updated video title", "category_id": faith.id},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.approved.refresh_from_db()
        self.assertEqual(self.approved.title, "Updated video title")
        self.assertEqual(self.approved.category_id, faith.id)

    def test_admin_edit_video_testimony_schedule_requires_future_datetime(self) -> None:
        scheduled_video = Testimony.objects.create(
            author=self.author,
            category=self.category,
            title="Scheduled video",
            body="",
            testimony_type=TestimonyType.VIDEO,
            status=TestimonyStatus.SCHEDULED,
            video_url="https://example.com/scheduled.mp4",
            publish_at=timezone.now() + timezone.timedelta(days=1),
        )
        invalid = self.client.patch(
            reverse("admin-testimony-edit-video", kwargs={"testimony_id": scheduled_video.id}),
            {"scheduled_publish_at": (timezone.now() - timezone.timedelta(hours=1)).isoformat()},
            content_type="application/json",
        )
        self.assertEqual(invalid.status_code, 400)
        self.assertIn("scheduled_publish_at", invalid.json())

        valid = self.client.patch(
            reverse("admin-testimony-edit-video", kwargs={"testimony_id": scheduled_video.id}),
            {"scheduled_publish_at": (timezone.now() + timezone.timedelta(days=2)).isoformat()},
            content_type="application/json",
        )
        self.assertEqual(valid.status_code, 200)
        scheduled_video.refresh_from_db()
        self.assertEqual(scheduled_video.status, TestimonyStatus.SCHEDULED)
        self.assertGreater(scheduled_video.publish_at, timezone.now())

    def test_admin_edit_video_testimony_rejects_non_video(self) -> None:
        response = self.client.patch(
            reverse("admin-testimony-edit-video", kwargs={"testimony_id": self.pending.id}),
            {"title": "Should fail"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_admin_upload_now_video_promotes_draft_to_approved(self) -> None:
        draft_video = Testimony.objects.create(
            author=self.author,
            category=self.category,
            title="Draft video",
            body="",
            testimony_type=TestimonyType.VIDEO,
            status=TestimonyStatus.DRAFT,
            video_url="https://example.com/draft.mp4",
        )
        response = self.client.post(
            reverse("admin-testimony-upload-now-video", kwargs={"testimony_id": draft_video.id}),
            {},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        draft_video.refresh_from_db()
        self.assertEqual(draft_video.status, TestimonyStatus.APPROVED)
        self.assertTrue(
            UserNotification.objects.filter(
                recipient=self.author,
                notification_type=NotificationType.NEW_VIDEO_TESTIMONY,
                message__icontains="Draft video",
            ).exists()
        )

    def test_scheduled_video_auto_publish_notifies_regular_users(self) -> None:
        scheduled_video = Testimony.objects.create(
            author=self.admin,
            category=self.category,
            title="Scheduled public video",
            body="",
            testimony_type=TestimonyType.VIDEO,
            status=TestimonyStatus.SCHEDULED,
            video_url="https://example.com/scheduled-public.mp4",
            publish_at=timezone.now() - timezone.timedelta(minutes=1),
        )

        call_command("publish_scheduled_testimonies")

        scheduled_video.refresh_from_db()
        self.assertEqual(scheduled_video.status, TestimonyStatus.APPROVED)
        self.assertTrue(
            UserNotification.objects.filter(
                recipient=self.author,
                notification_type=NotificationType.NEW_VIDEO_TESTIMONY,
                message__icontains="Scheduled public video",
            ).exists()
        )
        self.assertFalse(
            UserNotification.objects.filter(
                recipient=self.admin,
                notification_type=NotificationType.NEW_VIDEO_TESTIMONY,
                message__icontains="Scheduled public video",
            ).exists()
        )

    def test_admin_upload_now_video_rejects_non_draft_or_scheduled(self) -> None:
        response = self.client.post(
            reverse("admin-testimony-upload-now-video", kwargs={"testimony_id": self.approved.id}),
            {},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_admin_upload_video_requires_admin_session(self) -> None:
        self.client.logout()
        non_admin = UserFactory(email="nonadmin@example.com")
        self.client.force_login(non_admin)
        video = SimpleUploadedFile("testimony.mp4", b"fake-video-content", content_type="video/mp4")
        response = self.client.post(
            reverse("admin-testimony-upload-video"),
            {
                "title": "Unauthorized upload",
                "category_id": self.category.id,
                "video_file": video,
            },
        )
        self.assertEqual(response.status_code, 403)

    def test_phase4_slice1_pending_queue_orders_oldest_first(self) -> None:
        oldest = Testimony.objects.create(
            author=self.author,
            category=self.category,
            title="Oldest pending",
            body="Old pending",
            testimony_type=TestimonyType.WRITTEN,
            status=TestimonyStatus.PENDING_REVIEW,
        )
        newest = Testimony.objects.create(
            author=self.author,
            category=self.category,
            title="Newest pending",
            body="New pending",
            testimony_type=TestimonyType.WRITTEN,
            status=TestimonyStatus.PENDING_REVIEW,
        )
        response = self.client.get(reverse("admin-testimony-pending-queue"))
        self.assertEqual(response.status_code, 200)
        titles = [item["title"] for item in response.json()["results"]]
        self.assertLess(titles.index(oldest.title), titles.index(newest.title))

    def test_phase4_slice2_approve_pending_testimony(self) -> None:
        response = self.client.post(reverse("admin-testimony-approve", kwargs={"testimony_id": self.pending.id}))
        self.assertEqual(response.status_code, 200)
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.status, TestimonyStatus.APPROVED)
        public_detail = self.client.get(reverse("testimony-detail", kwargs={"pk": self.pending.id}))
        self.assertEqual(public_detail.status_code, 200)

    def test_phase4_slice3_reject_pending_testimony_requires_reason_and_exposes_it_to_author(self) -> None:
        missing_reason = self.client.post(
            reverse("admin-testimony-reject", kwargs={"testimony_id": self.pending.id}),
            {},
            content_type="application/json",
        )
        self.assertEqual(missing_reason.status_code, 400)

        response = self.client.post(
            reverse("admin-testimony-reject", kwargs={"testimony_id": self.pending.id}),
            {"reason": "Insufficient context in submission."},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.status, TestimonyStatus.REJECTED)
        self.assertEqual(self.pending.rejection_reason, "Insufficient context in submission.")

        author_token = Token.objects.create(user=self.author)
        mine = self.client.get(reverse("testimony-mine-list"), HTTP_AUTHORIZATION=f"Token {author_token.key}")
        self.assertEqual(mine.status_code, 200)
        pending_item = next(item for item in mine.json()["results"] if item["id"] == self.pending.id)
        self.assertEqual(pending_item["rejection_reason"], "Insufficient context in submission.")

    def test_phase4_slice4_schedule_testimony_future_publish_and_auto_publish_to_public_feed(self) -> None:
        publish_at = (timezone.now() + timezone.timedelta(hours=2)).isoformat()
        response = self.client.post(
            reverse("admin-testimony-schedule", kwargs={"testimony_id": self.pending.id}),
            {"publish_at": publish_at},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.status, TestimonyStatus.SCHEDULED)
        self.assertIsNotNone(self.pending.publish_at)

        not_yet_public = self.client.get(reverse("testimony-detail", kwargs={"pk": self.pending.id}))
        self.assertEqual(not_yet_public.status_code, 404)

        from apps.testimonies.models import TestimonyModerationHistory

        Testimony.objects.filter(id=self.pending.id).update(publish_at=timezone.now() - timezone.timedelta(minutes=1))
        call_command("publish_scheduled_testimonies")
        list_response = self.client.get(reverse("testimony-list"))
        self.assertEqual(list_response.status_code, 200)
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.status, TestimonyStatus.APPROVED)
        auto_history_exists = TestimonyModerationHistory.objects.filter(
            testimony=self.pending,
            action="auto_published",
        ).exists()
        self.assertTrue(auto_history_exists)

    def test_phase4_slice5_archive_approved_testimony_removes_from_public_feed(self) -> None:
        response = self.client.post(
            reverse("admin-testimony-archive", kwargs={"testimony_id": self.approved.id}),
            {"reason": "Seasonal curation update."},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.approved.refresh_from_db()
        self.assertEqual(self.approved.status, TestimonyStatus.ARCHIVED)
        self.assertIsNotNone(self.approved.archived_at)

        public_detail = self.client.get(reverse("testimony-detail", kwargs={"pk": self.approved.id}))
        self.assertEqual(public_detail.status_code, 404)

    def test_phase4_slice6_view_moderation_history(self) -> None:
        self.client.post(reverse("admin-testimony-approve", kwargs={"testimony_id": self.pending.id}))
        self.client.post(
            reverse("admin-testimony-archive", kwargs={"testimony_id": self.pending.id}),
            {"reason": "Archive for policy clean-up"},
            content_type="application/json",
        )
        response = self.client.get(
            reverse("admin-testimony-moderation-history", kwargs={"testimony_id": self.pending.id})
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        actions = [item["action"] for item in payload]
        self.assertIn("approved", actions)
        self.assertIn("archived", actions)
        archived_row = next(item for item in payload if item["action"] == "archived")
        self.assertEqual(archived_row["reason"], "Archive for policy clean-up")
        self.assertIn("actor_name", archived_row)

    def test_phase4_slice7_author_my_testimonies_reflects_approved_and_rejected_with_reason(self) -> None:
        author_token = Token.objects.create(user=self.author)
        approve_response = self.client.post(
            reverse("admin-testimony-approve", kwargs={"testimony_id": self.pending.id})
        )
        self.assertEqual(approve_response.status_code, 200)
        mine_after_approve = self.client.get(
            reverse("testimony-mine-list"),
            HTTP_AUTHORIZATION=f"Token {author_token.key}",
        )
        self.assertEqual(mine_after_approve.status_code, 200)
        approved_item = next(item for item in mine_after_approve.json()["results"] if item["id"] == self.pending.id)
        self.assertEqual(approved_item["status"], TestimonyStatus.APPROVED)

        self.pending.status = TestimonyStatus.PENDING_REVIEW
        self.pending.rejection_reason = ""
        self.pending.save(update_fields=["status", "rejection_reason", "updated_at"])
        reject_response = self.client.post(
            reverse("admin-testimony-reject", kwargs={"testimony_id": self.pending.id}),
            {"reason": "Please include specific details."},
            content_type="application/json",
        )
        self.assertEqual(reject_response.status_code, 200)
        mine_after_reject = self.client.get(
            reverse("testimony-mine-list"),
            HTTP_AUTHORIZATION=f"Token {author_token.key}",
        )
        self.assertEqual(mine_after_reject.status_code, 200)
        rejected_item = next(item for item in mine_after_reject.json()["results"] if item["id"] == self.pending.id)
        self.assertEqual(rejected_item["status"], TestimonyStatus.REJECTED)
        self.assertEqual(rejected_item["rejection_reason"], "Please include specific details.")

    def test_phase4_slice8_approved_testimony_appears_in_public_browse_feed(self) -> None:
        response = self.client.post(reverse("admin-testimony-approve", kwargs={"testimony_id": self.pending.id}))
        self.assertEqual(response.status_code, 200)
        list_response = self.client.get(reverse("testimony-list"))
        self.assertEqual(list_response.status_code, 200)
        titles = [item["title"] for item in list_response.json()["results"]]
        self.assertIn(self.pending.title, titles)

    def test_phase4_slice9_scheduled_testimony_auto_publishes_into_public_browse_feed(self) -> None:
        future_publish = (timezone.now() + timezone.timedelta(hours=1)).isoformat()
        schedule_response = self.client.post(
            reverse("admin-testimony-schedule", kwargs={"testimony_id": self.pending.id}),
            {"publish_at": future_publish},
            content_type="application/json",
        )
        self.assertEqual(schedule_response.status_code, 200)
        before_due = self.client.get(reverse("testimony-list"))
        self.assertEqual(before_due.status_code, 200)
        before_titles = [item["title"] for item in before_due.json()["results"]]
        self.assertNotIn(self.pending.title, before_titles)

        Testimony.objects.filter(id=self.pending.id).update(
            publish_at=timezone.now() - timezone.timedelta(minutes=1)
        )
        call_command("publish_scheduled_testimonies")
        after_due = self.client.get(reverse("testimony-list"))
        self.assertEqual(after_due.status_code, 200)
        after_titles = [item["title"] for item in after_due.json()["results"]]
        self.assertIn(self.pending.title, after_titles)
