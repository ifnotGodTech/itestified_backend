from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from apps.testimonies.models import (
    Testimony,
    TestimonyCategory,
    TestimonyReactionType,
    TestimonyStatus,
    TestimonyType,
)
from apps.testimonies.services.commands import (
    create_testimony_comment,
    recount_testimony_counters,
    set_testimony_reaction,
)
from apps.users.tests.factories import ProfileFactory, UserFactory


class TestimonyCounterRecountTests(TestCase):
    def setUp(self) -> None:
        category = TestimonyCategory.objects.create(name="Healing", slug="healing")
        self.author = UserFactory(email="author@example.com")
        ProfileFactory(user=self.author, full_name="Author")
        self.leaver = UserFactory(email="leaver@example.com")
        ProfileFactory(user=self.leaver, full_name="Leaver")
        self.stayer = UserFactory(email="stayer@example.com")
        ProfileFactory(user=self.stayer, full_name="Stayer")
        self.testimony = Testimony.objects.create(
            author=self.author,
            category=category,
            title="God healed me",
            body="...",
            testimony_type=TestimonyType.WRITTEN,
            status=TestimonyStatus.APPROVED,
        )

    def test_deleting_a_user_outright_takes_their_reactions_and_comments_off_the_counts(self) -> None:
        set_testimony_reaction(testimony=self.testimony, user=self.leaver, reaction_type=TestimonyReactionType.AMEN)
        set_testimony_reaction(testimony=self.testimony, user=self.stayer, reaction_type=TestimonyReactionType.AMEN)
        comment = create_testimony_comment(testimony_id=self.testimony.id, author=self.leaver, body="Praise God")
        # The stayer's reply goes too: it hangs off the leaver's comment.
        create_testimony_comment(
            testimony_id=self.testimony.id, author=self.stayer, body="Amen", parent_comment_id=comment.id
        )
        create_testimony_comment(testimony_id=self.testimony.id, author=self.stayer, body="Encouraging")

        with self.captureOnCommitCallbacks(execute=True):
            self.leaver.delete()

        self.testimony.refresh_from_db()
        self.assertEqual(self.testimony.amen_count, 1)
        self.assertEqual(self.testimony.comment_count, 1)

    def test_recount_repairs_drifted_counters_and_leaves_correct_ones(self) -> None:
        set_testimony_reaction(
            testimony=self.testimony, user=self.stayer, reaction_type=TestimonyReactionType.GIVES_ME_HOPE
        )
        Testimony.objects.filter(id=self.testimony.id).update(comment_count=4, amen_count=2)

        self.assertEqual(recount_testimony_counters(), 1)
        self.testimony.refresh_from_db()
        self.assertEqual(
            (self.testimony.comment_count, self.testimony.amen_count, self.testimony.gives_me_hope_count),
            (0, 0, 1),
        )
        self.assertEqual(recount_testimony_counters(), 0)

    def test_management_command_reports_what_it_corrected(self) -> None:
        Testimony.objects.filter(id=self.testimony.id).update(praying_for_you_count=3)
        out = StringIO()

        call_command("recount_testimony_counters", stdout=out)

        self.assertIn("corrected 1 testimonies", out.getvalue())
        self.testimony.refresh_from_db()
        self.assertEqual(self.testimony.praying_for_you_count, 0)
