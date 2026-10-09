from unittest import mock

from django.test import TestCase

from apps.notifications.models import NotificationType, UserNotification
from apps.testimonies.exceptions import (
    CommentNotFoundError,
    CommentNotOwnedError,
    CommentReplyDepthError,
    CommentTestimonyNotFoundError,
    ParentCommentNotFoundError,
)
from apps.testimonies.models import (
    Testimony,
    TestimonyCategory,
    TestimonyComment,
    TestimonyStatus,
    TestimonyType,
)
from apps.testimonies.services.commands import create_testimony_comment, delete_testimony_comment
from apps.users.tests.factories import ProfileFactory, UserFactory


class _CommentTestBase(TestCase):
    def setUp(self) -> None:
        self.category = TestimonyCategory.objects.create(name="Healing", slug="healing")
        self.author = UserFactory(email="testimony-author@example.com")
        ProfileFactory(user=self.author, full_name="Testimony Author")
        self.commenter = UserFactory(email="commenter@example.com")
        ProfileFactory(user=self.commenter, full_name="Comment User")
        self.testimony = self._testimony(status=TestimonyStatus.APPROVED)

    def _testimony(self, *, status: str) -> Testimony:
        return Testimony.objects.create(
            author=self.author,
            category=self.category,
            title="God healed me",
            body="...",
            testimony_type=TestimonyType.WRITTEN,
            status=status,
        )

    def _comment_notifications(self):
        return UserNotification.objects.filter(
            recipient=self.author, notification_type=NotificationType.TESTIMONY_COMMENT
        )


class CreateTestimonyCommentTests(_CommentTestBase):
    def test_comment_increments_count_and_notifies_author_after_commit(self) -> None:
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            comment = create_testimony_comment(
                testimony_id=self.testimony.id, author=self.commenter, body="This blessed me."
            )
            self.assertEqual(self._comment_notifications().count(), 0)

        self.assertEqual(len(callbacks), 1)
        self.assertEqual(comment.body, "This blessed me.")
        self.testimony.refresh_from_db()
        self.assertEqual(self.testimony.comment_count, 1)
        self.assertEqual(self._comment_notifications().count(), 1)

    def test_commenting_on_own_testimony_does_not_notify(self) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            create_testimony_comment(testimony_id=self.testimony.id, author=self.author, body="Thank you all.")

        self.assertEqual(self._comment_notifications().count(), 0)

    def test_cannot_comment_on_unapproved_testimony(self) -> None:
        pending = self._testimony(status=TestimonyStatus.PENDING_REVIEW)

        with self.assertRaises(CommentTestimonyNotFoundError):
            create_testimony_comment(testimony_id=pending.id, author=self.commenter, body="Hello")
        self.assertFalse(TestimonyComment.objects.exists())

    def test_reply_to_a_reply_is_rejected(self) -> None:
        top = create_testimony_comment(testimony_id=self.testimony.id, author=self.commenter, body="Top")
        reply = create_testimony_comment(
            testimony_id=self.testimony.id, author=self.commenter, body="Reply", parent_comment_id=top.id
        )

        with self.assertRaises(CommentReplyDepthError):
            create_testimony_comment(
                testimony_id=self.testimony.id, author=self.commenter, body="Too deep", parent_comment_id=reply.id
            )

    def test_parent_comment_from_another_testimony_is_not_found(self) -> None:
        other = self._testimony(status=TestimonyStatus.APPROVED)
        foreign_parent = create_testimony_comment(testimony_id=other.id, author=self.commenter, body="Elsewhere")

        with self.assertRaises(ParentCommentNotFoundError):
            create_testimony_comment(
                testimony_id=self.testimony.id,
                author=self.commenter,
                body="Reply",
                parent_comment_id=foreign_parent.id,
            )

    def test_comment_is_not_saved_if_the_count_update_fails(self) -> None:
        # Regression (2026-10-09): the view used to save the comment and bump
        # the counter as separate, non-atomic writes.
        with mock.patch(
            "apps.testimonies.services.commands._adjust_comment_count", side_effect=RuntimeError("db hiccup")
        ):
            with self.assertRaises(RuntimeError):
                create_testimony_comment(testimony_id=self.testimony.id, author=self.commenter, body="Hello")

        self.assertFalse(TestimonyComment.objects.exists())

    def test_notification_failure_does_not_fail_the_comment(self) -> None:
        with mock.patch(
            "apps.testimonies.services.commands.notify_testimony_comment", side_effect=RuntimeError("push down")
        ):
            with self.captureOnCommitCallbacks(execute=True):
                comment = create_testimony_comment(
                    testimony_id=self.testimony.id, author=self.commenter, body="Still saved"
                )

        self.assertTrue(TestimonyComment.objects.filter(id=comment.id).exists())
        self.testimony.refresh_from_db()
        self.assertEqual(self.testimony.comment_count, 1)


class DeleteTestimonyCommentTests(_CommentTestBase):
    def test_deleting_a_comment_removes_its_replies_and_decrements_by_all_of_them(self) -> None:
        top = create_testimony_comment(testimony_id=self.testimony.id, author=self.commenter, body="Top")
        for body in ("Reply 1", "Reply 2"):
            create_testimony_comment(
                testimony_id=self.testimony.id, author=self.author, body=body, parent_comment_id=top.id
            )
        create_testimony_comment(testimony_id=self.testimony.id, author=self.author, body="Unrelated")
        self.testimony.refresh_from_db()
        self.assertEqual(self.testimony.comment_count, 4)

        delete_testimony_comment(comment_id=top.id, actor=self.commenter)

        self.testimony.refresh_from_db()
        self.assertEqual(self.testimony.comment_count, 1)
        self.assertEqual(TestimonyComment.objects.count(), 1)

    def test_cannot_delete_someone_elses_comment(self) -> None:
        comment = create_testimony_comment(testimony_id=self.testimony.id, author=self.commenter, body="Mine")

        with self.assertRaises(CommentNotOwnedError):
            delete_testimony_comment(comment_id=comment.id, actor=self.author)
        self.assertTrue(TestimonyComment.objects.filter(id=comment.id).exists())

    def test_deleting_a_missing_comment_raises_not_found(self) -> None:
        with self.assertRaises(CommentNotFoundError):
            delete_testimony_comment(comment_id=999999, actor=self.commenter)

    def test_count_never_goes_negative(self) -> None:
        comment = create_testimony_comment(testimony_id=self.testimony.id, author=self.commenter, body="Hi")
        Testimony.objects.filter(id=self.testimony.id).update(comment_count=0)

        delete_testimony_comment(comment_id=comment.id, actor=self.commenter)

        self.testimony.refresh_from_db()
        self.assertEqual(self.testimony.comment_count, 0)
