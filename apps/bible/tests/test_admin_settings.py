"""Phase 34 Slice 8: the admin's Bible settings (which packs readers can
download, and which Bible new readers get first)."""

from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.bible.choices import BiblePackChangeAction, BiblePackKind
from apps.bible.exceptions import BiblePackChangeRefused
from apps.bible.models import BiblePack, BiblePackChange
from apps.bible.services.commands import make_bible_pack_default, set_bible_pack_enabled
from apps.users.choices import AdminRoleCode
from apps.users.tests.factories import AdminAssignmentFactory, AdminRoleFactory, ProfileFactory, UserFactory


def _pack(code: str, **overrides) -> BiblePack:
    fields = dict(
        code=code,
        kind=BiblePackKind.VERSION,
        name=code.upper(),
        abbreviation=code.upper(),
        attribution="Public domain",
        file_url=f"https://cdn.example.com/{code}.sqlite.gz",
        size_bytes=1234,
        sha256="f" * 64,
        is_enabled=True,
        supports_word_study=True,
    )
    fields.update(overrides)
    return BiblePack.objects.create(**fields)


def _admin(email: str = "bible-admin@example.com", name: str = "Bible Admin"):
    user = UserFactory(email=email)
    ProfileFactory(user=user, full_name=name)
    AdminAssignmentFactory(user=user, role=AdminRoleFactory(code=AdminRoleCode.SUPER_ADMIN))
    return user


class BiblePackSettingsServiceTests(TestCase):
    def setUp(self):
        self.admin = _admin()
        self.bsb = _pack("bsb", is_default=True, sort_order=10)
        self.kjv = _pack("kjv", sort_order=20)
        self.study = _pack("study", kind=BiblePackKind.STUDY, supports_word_study=False, sort_order=100)

    def _refused(self, code: str, call):
        with self.assertRaises(BiblePackChangeRefused) as raised:
            call()
        self.assertEqual(raised.exception.code, code)
        return str(raised.exception)

    def test_hiding_a_version_is_recorded_and_hides_it_from_readers(self):
        set_bible_pack_enabled(actor=self.admin, code="kjv", enabled=False)

        self.kjv.refresh_from_db()
        self.assertFalse(self.kjv.is_enabled)
        change = BiblePackChange.objects.get()
        self.assertEqual((change.pack, change.action, change.actor), (self.kjv, BiblePackChangeAction.DISABLED, self.admin))
        public = self.client.get(reverse("bible-pack-list")).json()
        self.assertNotIn("kjv", [item["code"] for item in public["results"]])

    def test_showing_it_again_is_recorded_too(self):
        set_bible_pack_enabled(actor=self.admin, code="kjv", enabled=False)
        set_bible_pack_enabled(actor=self.admin, code="kjv", enabled=True)

        self.assertEqual(
            list(BiblePackChange.objects.values_list("action", flat=True)),
            [BiblePackChangeAction.ENABLED, BiblePackChangeAction.DISABLED],
        )

    def test_a_change_to_the_same_state_records_nothing(self):
        set_bible_pack_enabled(actor=self.admin, code="kjv", enabled=True)
        make_bible_pack_default(actor=self.admin, code="bsb")
        self.assertFalse(BiblePackChange.objects.exists())

    def test_the_default_bible_cannot_be_hidden(self):
        message = self._refused("is_default", lambda: set_bible_pack_enabled(actor=self.admin, code="bsb", enabled=False))
        self.assertIn("Make another version the default", message)

    def test_the_last_bible_readers_can_download_cannot_be_hidden(self):
        set_bible_pack_enabled(actor=self.admin, code="kjv", enabled=False)
        # BSB is the default too; take that out of the picture.
        BiblePack.objects.filter(code="bsb").update(is_default=False)
        self._refused("last_version", lambda: set_bible_pack_enabled(actor=self.admin, code="bsb", enabled=False))

    def test_word_study_cannot_be_hidden_while_word_study_bibles_are_shown(self):
        message = self._refused("study_in_use", lambda: set_bible_pack_enabled(actor=self.admin, code="study", enabled=False))
        self.assertIn("BSB, KJV", message)

    def test_word_study_can_be_hidden_once_no_shown_bible_needs_it(self):
        BiblePack.objects.filter(kind=BiblePackKind.VERSION).update(supports_word_study=False)
        set_bible_pack_enabled(actor=self.admin, code="study", enabled=False)
        self.study.refresh_from_db()
        self.assertFalse(self.study.is_enabled)

    def test_making_another_version_the_default_moves_it_and_is_recorded(self):
        make_bible_pack_default(actor=self.admin, code="kjv")

        self.assertEqual(list(BiblePack.objects.filter(is_default=True).values_list("code", flat=True)), ["kjv"])
        self.assertTrue(BiblePack.objects.get(code="bsb").is_enabled)  # the old default stays available
        self.assertEqual(BiblePackChange.objects.get().action, BiblePackChangeAction.MADE_DEFAULT)

    def test_only_a_shown_bible_version_can_be_the_default(self):
        self._refused("not_a_version", lambda: make_bible_pack_default(actor=self.admin, code="study"))
        set_bible_pack_enabled(actor=self.admin, code="kjv", enabled=False)
        self._refused("disabled", lambda: make_bible_pack_default(actor=self.admin, code="kjv"))

    def test_an_unknown_pack_is_refused(self):
        self._refused("not_found", lambda: make_bible_pack_default(actor=self.admin, code="niv"))


class BiblePackSettingsApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = _admin()
        _pack("bsb", is_default=True, sort_order=10, data_version=2)
        _pack("kjv", sort_order=20, is_enabled=False)
        _pack("study", kind=BiblePackKind.STUDY, supports_word_study=False, sort_order=100)

    def test_lists_every_pack_hidden_ones_included_with_their_details(self):
        self.client.force_login(self.admin)
        body = self.client.get(reverse("bible-admin-pack-list")).json()

        self.assertEqual([item["code"] for item in body["results"]], ["bsb", "kjv", "study"])
        bsb = body["results"][0]
        self.assertEqual(
            {key: bsb[key] for key in ("is_enabled", "is_default", "data_version", "size_bytes", "attribution")},
            {"is_enabled": True, "is_default": True, "data_version": 2, "size_bytes": 1234, "attribution": "Public domain"},
        )
        self.assertFalse(body["results"][1]["is_enabled"])

    def test_actions_return_the_updated_pack_and_show_in_the_history(self):
        self.client.force_login(self.admin)

        enabled = self.client.post(reverse("bible-admin-pack-enable", args=["kjv"]))
        self.assertEqual(enabled.status_code, 200)
        self.assertTrue(enabled.json()["is_enabled"])
        made_default = self.client.post(reverse("bible-admin-pack-make-default", args=["kjv"]))
        self.assertTrue(made_default.json()["is_default"])

        history = self.client.get(reverse("bible-admin-pack-changes")).json()
        self.assertEqual(history["count"], 2)
        self.assertEqual(
            history["results"][0],
            {
                "pack_code": "kjv",
                "pack_name": "KJV",
                "action": "made_default",
                "actor_name": "Bible Admin",
                "created_at": history["results"][0]["created_at"],
            },
        )

    def test_a_refused_change_explains_why_with_a_stable_code(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("bible-admin-pack-disable", args=["bsb"]))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "is_default")
        self.assertEqual(self.client.post(reverse("bible-admin-pack-enable", args=["niv"])).status_code, 404)

    def test_only_an_active_admin_can_see_or_change_the_settings(self):
        urls = [
            ("get", reverse("bible-admin-pack-list")),
            ("get", reverse("bible-admin-pack-changes")),
            ("post", reverse("bible-admin-pack-enable", args=["kjv"])),
            ("post", reverse("bible-admin-pack-disable", args=["kjv"])),
            ("post", reverse("bible-admin-pack-make-default", args=["bsb"])),
        ]
        for method, url in urls:
            with self.subTest(url=url, who="guest"):
                self.assertIn(getattr(self.client, method)(url).status_code, (401, 403))
        self.client.force_login(UserFactory(email="reader@example.com"))
        for method, url in urls:
            with self.subTest(url=url, who="reader"):
                self.assertEqual(getattr(self.client, method)(url).status_code, 403)
        self.assertFalse(BiblePack.objects.get(code="kjv").is_enabled)
