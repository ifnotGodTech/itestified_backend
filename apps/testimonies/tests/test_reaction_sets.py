"""Phase 35 Slice 6: admin-managed reactions per category.

The worked example from the plan: Healing gets "Pray with me", "This
encouraged me" and "Believing for the same"; Faith keeps the default set
(Phase 15's three)."""

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework.authtoken.models import Token

from apps.testimonies.exceptions import ReactionAdminError, ReactionNotOfferedError
from apps.testimonies.models import (
    Reaction,
    ReactionChangeLog,
    Testimony,
    TestimonyCategory,
    TestimonyReaction,
    TestimonyReactionCount,
    TestimonyStatus,
    TestimonyType,
)
from apps.testimonies.services.commands import (
    create_reaction,
    remove_testimony_reaction,
    restore_reaction,
    retire_reaction,
    set_category_reactions,
    set_default_reactions,
    set_testimony_reaction,
    update_reaction,
)
from apps.users.choices import AdminRoleCode
from apps.users.tests.factories import AdminAssignmentFactory, AdminRoleFactory, ProfileFactory, UserFactory


class _ReactionSetsBase(TestCase):
    def setUp(self) -> None:
        self.admin = UserFactory(email="reactions-admin@example.com")
        ProfileFactory(user=self.admin, full_name="Reactions Admin")
        AdminAssignmentFactory(user=self.admin, role=AdminRoleFactory(code=AdminRoleCode.SUPER_ADMIN))
        self.author = UserFactory(email="author@example.com")
        ProfileFactory(user=self.author, full_name="Grace Chapel")
        self.viewer = UserFactory(email="viewer@example.com")
        ProfileFactory(user=self.viewer, full_name="Viewer")

        self.healing = TestimonyCategory.objects.create(name="Healing", slug="healing")
        self.faith = TestimonyCategory.objects.create(name="Faith", slug="faith")
        self.pray_with_me = create_reaction(actor=self.admin, label="Pray with me", icon="handshake")
        self.encouraged = create_reaction(actor=self.admin, label="This encouraged me", icon="heart")
        self.believing = create_reaction(actor=self.admin, label="Believing for the same", icon="fire")
        set_category_reactions(
            actor=self.admin,
            category_id=self.healing.id,
            reaction_ids=[self.pray_with_me.id, self.encouraged.id, self.believing.id],
        )
        self.in_healing = self._testimony("Healed after eleven years", self.healing)
        self.in_faith = self._testimony("Faith that held", self.faith)

    def _testimony(self, title: str, category: TestimonyCategory) -> Testimony:
        return Testimony.objects.create(
            author=self.author,
            category=category,
            title=title,
            body="...",
            testimony_type=TestimonyType.WRITTEN,
            status=TestimonyStatus.APPROVED,
        )

    def _count(self, testimony: Testimony, reaction: Reaction) -> int:
        row = TestimonyReactionCount.objects.filter(testimony=testimony, reaction=reaction).first()
        return row.count if row else 0

    def _listed(self, testimony: Testimony) -> dict:
        results = self.client.get(reverse("testimony-list")).json()["results"]
        return next(row for row in results if row["id"] == testimony.id)


class OfferedReactionsTests(_ReactionSetsBase):
    def test_each_category_shows_its_own_set_and_others_the_default(self) -> None:
        self.assertEqual(
            [option["label"] for option in self._listed(self.in_healing)["reactions"]],
            ["Pray with me", "This encouraged me", "Believing for the same"],
        )
        self.assertEqual(
            [option["key"] for option in self._listed(self.in_faith)["reactions"]],
            ["praying_for_you", "amen", "gives_me_hope"],
        )
        self.assertEqual(self._listed(self.in_healing)["reactions"][0]["icon"], "handshake")

    def test_reacting_counts_on_the_categorys_reaction(self) -> None:
        set_testimony_reaction(testimony=self.in_healing, user=self.viewer, reaction_key=self.pray_with_me.key)

        self.assertEqual(self._count(self.in_healing, self.pray_with_me), 1)
        self.assertEqual(self._listed(self.in_healing)["reactions"][0]["count"], 1)

    def test_a_reaction_outside_the_categorys_set_is_refused(self) -> None:
        with self.assertRaises(ReactionNotOfferedError):
            set_testimony_reaction(testimony=self.in_healing, user=self.viewer, reaction_key="amen")
        with self.assertRaises(ReactionNotOfferedError):
            set_testimony_reaction(testimony=self.in_faith, user=self.viewer, reaction_key=self.pray_with_me.key)

        token = Token.objects.create(user=self.viewer)
        response = self.client.post(
            reverse("testimony-react", kwargs={"testimony_id": self.in_healing.id}),
            {"reaction_type": "amen"},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Token {token.key}",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(TestimonyReaction.objects.filter(user=self.viewer).exists())

    def test_moving_a_testimony_keeps_its_responses_but_offers_the_new_set(self) -> None:
        set_testimony_reaction(testimony=self.in_healing, user=self.viewer, reaction_key=self.pray_with_me.key)
        Testimony.objects.filter(id=self.in_healing.id).update(category=self.faith)

        listed = self._listed(self.in_healing)
        self.assertEqual([option["key"] for option in listed["reactions"]], ["praying_for_you", "amen", "gives_me_hope"])
        self.assertEqual(self._count(self.in_healing, self.pray_with_me), 1)
        # Taking the old reaction back still works and settles the count.
        self.in_healing.refresh_from_db()
        remove_testimony_reaction(testimony=self.in_healing, user=self.viewer)
        self.assertEqual(self._count(self.in_healing, self.pray_with_me), 0)

    def test_a_list_loads_reactions_in_a_fixed_number_of_queries(self) -> None:
        def queries_for_list() -> int:
            with CaptureQueriesContext(connection) as captured:
                self.client.get(reverse("testimony-list"))
            return len(captured.captured_queries)

        before = queries_for_list()
        for index in range(5):
            testimony = self._testimony(f"Another {index}", self.healing if index % 2 else self.faith)
            set_testimony_reaction(
                testimony=testimony,
                user=self.viewer,
                reaction_key=self.encouraged.key if index % 2 else "amen",
            )
        self.assertEqual(queries_for_list(), before)


class ReactionCatalogueTests(_ReactionSetsBase):
    def test_a_new_reaction_gets_a_key_from_its_label_and_a_unique_one_if_taken(self) -> None:
        self.assertEqual(self.pray_with_me.key, "pray_with_me")
        Reaction.objects.filter(id=self.pray_with_me.id).update(label="Old label")
        again = create_reaction(actor=self.admin, label="Pray with me", icon="pray")
        self.assertEqual(again.key, "pray_with_me_2")

    def test_labels_must_be_unique_short_and_icons_from_the_list(self) -> None:
        with self.assertRaisesMessage(ReactionAdminError, "already a reaction called"):
            create_reaction(actor=self.admin, label="  amen ", icon="pray")
        with self.assertRaisesMessage(ReactionAdminError, "24 characters"):
            create_reaction(actor=self.admin, label="A label that is far too long to fit", icon="pray")
        with self.assertRaisesMessage(ReactionAdminError, "Choose one of the icons"):
            create_reaction(actor=self.admin, label="Peace be with you", icon="unicorn")

    def test_renaming_keeps_the_key_and_the_responses(self) -> None:
        set_testimony_reaction(testimony=self.in_healing, user=self.viewer, reaction_key=self.pray_with_me.key)

        update_reaction(actor=self.admin, reaction_id=self.pray_with_me.id, label="Praying with you", icon="pray")

        option = self._listed(self.in_healing)["reactions"][0]
        self.assertEqual((option["key"], option["label"], option["icon"], option["count"]), ("pray_with_me", "Praying with you", "pray", 1))

    def test_retiring_takes_it_off_every_set_but_keeps_its_responses(self) -> None:
        set_testimony_reaction(testimony=self.in_healing, user=self.viewer, reaction_key=self.pray_with_me.key)

        retire_reaction(actor=self.admin, reaction_id=self.pray_with_me.id)

        self.assertEqual(
            [option["label"] for option in self._listed(self.in_healing)["reactions"]],
            ["This encouraged me", "Believing for the same"],
        )
        self.assertEqual(self._count(self.in_healing, self.pray_with_me), 1)
        self.assertTrue(TestimonyReaction.objects.filter(user=self.viewer, reaction=self.pray_with_me).exists())
        log = ReactionChangeLog.objects.first()
        self.assertEqual((log.actor, log.action), (self.admin, "retired"))
        self.assertIn("taken off Healing", log.summary)

        # Brought back, it's in the catalogue again but in no set until placed.
        restore_reaction(actor=self.admin, reaction_id=self.pray_with_me.id)
        self.assertEqual(len(self._listed(self.in_healing)["reactions"]), 2)

    def test_a_category_whose_whole_set_is_retired_falls_back_to_the_default(self) -> None:
        set_category_reactions(actor=self.admin, category_id=self.healing.id, reaction_ids=[self.believing.id])
        retire_reaction(actor=self.admin, reaction_id=self.believing.id)

        self.assertEqual(
            [option["key"] for option in self._listed(self.in_healing)["reactions"]],
            ["praying_for_you", "amen", "gives_me_hope"],
        )

    def test_the_default_set_can_never_be_left_empty(self) -> None:
        set_default_reactions(actor=self.admin, reaction_ids=[Reaction.objects.get(key="amen").id])

        with self.assertRaisesMessage(ReactionAdminError, "only reaction in the default set"):
            retire_reaction(actor=self.admin, reaction_id=Reaction.objects.get(key="amen").id)
        with self.assertRaisesMessage(ReactionAdminError, "at least one"):
            set_default_reactions(actor=self.admin, reaction_ids=[])


class ReactionSetRulesTests(_ReactionSetsBase):
    def test_a_set_holds_at_most_four_distinct_active_reactions(self) -> None:
        extra = [create_reaction(actor=self.admin, label=f"Extra {n}", icon="star").id for n in range(2)]
        too_many = [self.pray_with_me.id, self.encouraged.id, self.believing.id, *extra]

        with self.assertRaisesMessage(ReactionAdminError, "at most 4"):
            set_category_reactions(actor=self.admin, category_id=self.faith.id, reaction_ids=too_many)
        with self.assertRaisesMessage(ReactionAdminError, "only appear once"):
            set_category_reactions(
                actor=self.admin, category_id=self.faith.id, reaction_ids=[self.encouraged.id, self.encouraged.id]
            )
        retire_reaction(actor=self.admin, reaction_id=extra[0])
        with self.assertRaisesMessage(ReactionAdminError, "retired reaction"):
            set_category_reactions(actor=self.admin, category_id=self.faith.id, reaction_ids=[extra[0]])

    def test_an_empty_set_puts_the_category_back_on_the_default(self) -> None:
        set_category_reactions(actor=self.admin, category_id=self.healing.id, reaction_ids=[])

        self.assertEqual(
            [option["key"] for option in self._listed(self.in_healing)["reactions"]],
            ["praying_for_you", "amen", "gives_me_hope"],
        )
        self.assertEqual(ReactionChangeLog.objects.first().summary, "Healing: back to the default set")

    def test_order_is_kept(self) -> None:
        set_category_reactions(
            actor=self.admin,
            category_id=self.healing.id,
            reaction_ids=[self.believing.id, self.pray_with_me.id],
        )
        self.assertEqual(
            [option["label"] for option in self._listed(self.in_healing)["reactions"]],
            ["Believing for the same", "Pray with me"],
        )


class AdminReactionApiTests(_ReactionSetsBase):
    def test_requires_an_admin_session(self) -> None:
        self.assertEqual(self.client.get(reverse("admin-reaction-overview")).status_code, 403)
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(reverse("admin-reaction-overview")).status_code, 403)

    def test_overview_lists_the_catalogue_default_set_and_category_sets(self) -> None:
        set_testimony_reaction(testimony=self.in_healing, user=self.viewer, reaction_key=self.pray_with_me.key)
        self.client.force_login(self.admin)

        body = self.client.get(reverse("admin-reaction-overview")).json()

        self.assertEqual(body["max_per_set"], 4)
        self.assertEqual(len(body["icons"]), 12)
        pray = next(r for r in body["reactions"] if r["key"] == "pray_with_me")
        self.assertEqual(
            (pray["label"], pray["emoji"], pray["categories"], pray["response_count"], pray["in_default_set"]),
            ("Pray with me", "🤝", ["Healing"], 1, False),
        )
        default_keys = [next(r["key"] for r in body["reactions"] if r["id"] == rid) for rid in body["default_set"]]
        self.assertEqual(default_keys, ["praying_for_you", "amen", "gives_me_hope"])
        healing = next(c for c in body["categories"] if c["name"] == "Healing")
        self.assertEqual(healing["reaction_ids"], [self.pray_with_me.id, self.encouraged.id, self.believing.id])
        self.assertEqual(next(c for c in body["categories"] if c["name"] == "Faith")["reaction_ids"], [])

    def test_create_edit_retire_restore_and_set_through_the_api(self) -> None:
        self.client.force_login(self.admin)

        created = self.client.post(
            reverse("admin-reaction-overview"), {"label": "Peace be with you", "icon": "dove"}, content_type="application/json"
        )
        self.assertEqual(created.status_code, 201)
        peace = next(r for r in created.json()["reactions"] if r["label"] == "Peace be with you")

        clash = self.client.post(
            reverse("admin-reaction-overview"), {"label": "Amen", "icon": "dove"}, content_type="application/json"
        )
        self.assertEqual(clash.status_code, 400)
        self.assertIn("already a reaction", clash.json()["message"])

        renamed = self.client.patch(
            reverse("admin-reaction-detail", kwargs={"reaction_id": peace["id"]}),
            {"label": "Peace to you"},
            content_type="application/json",
        )
        self.assertEqual(renamed.status_code, 200)
        self.assertIn("Peace to you", [r["label"] for r in renamed.json()["reactions"]])

        placed = self.client.put(
            reverse("admin-reaction-set", kwargs={"target": self.faith.id}),
            {"reaction_ids": [peace["id"]]},
            content_type="application/json",
        )
        self.assertEqual(next(c for c in placed.json()["categories"] if c["name"] == "Faith")["reaction_ids"], [peace["id"]])

        retired = self.client.post(reverse("admin-reaction-retire", kwargs={"reaction_id": peace["id"]}))
        self.assertFalse(next(r for r in retired.json()["reactions"] if r["id"] == peace["id"])["is_active"])
        restored = self.client.post(reverse("admin-reaction-restore", kwargs={"reaction_id": peace["id"]}))
        self.assertTrue(next(r for r in restored.json()["reactions"] if r["id"] == peace["id"])["is_active"])

        default = self.client.put(
            reverse("admin-reaction-set", kwargs={"target": "default"}),
            {"reaction_ids": [peace["id"], self.encouraged.id]},
            content_type="application/json",
        )
        self.assertEqual(default.json()["default_set"], [peace["id"], self.encouraged.id])
        self.assertEqual(
            self.client.put(
                reverse("admin-reaction-set", kwargs={"target": "default"}), {"reaction_ids": []}, content_type="application/json"
            ).status_code,
            400,
        )
        self.assertEqual(ReactionChangeLog.objects.filter(actor=self.admin).count(), 10)
