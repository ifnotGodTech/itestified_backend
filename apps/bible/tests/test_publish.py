from __future__ import annotations

import tempfile
from io import StringIO
from pathlib import Path
from unittest import mock

import requests
from django.core.management import CommandError, call_command
from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.bible.choices import BiblePackKind
from apps.bible.models import BiblePack
from apps.bible.services.pack_builds import sha256_of_file

from .helpers import build_test_pack

PACK_URL = "https://cdn.example.com/bible-packs/bsb.sqlite.gz"


def _serving(body: bytes):
    response = mock.MagicMock()
    response.__enter__.return_value = response
    response.iter_content.return_value = [body]
    return response


class PublishBiblePackCommandTests(TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.pack = build_test_pack(self.dir / "v1")

    def tearDown(self):
        self._tmp.cleanup()

    def _publish(self, pack: Path, *flags: str, served: bytes | None = None) -> str:
        out = StringIO()
        body = pack.read_bytes() if served is None else served
        with mock.patch("apps.bible.services.pack_files.requests.get", return_value=_serving(body)):
            call_command("publish_bible_pack", str(pack), "--url", PACK_URL, *flags, stdout=out)
        return out.getvalue()

    def test_registers_a_verified_pack_from_its_own_metadata(self):
        output = self._publish(self.pack, "--default")

        pack = BiblePack.objects.get(code="bsb")
        self.assertIn("Registered BSB", output)
        self.assertEqual(pack.kind, BiblePackKind.VERSION)
        self.assertEqual(pack.name, "Berean Standard Bible")
        self.assertEqual(pack.description, "Modern English")
        self.assertEqual(pack.file_url, PACK_URL)
        self.assertEqual(pack.sha256, sha256_of_file(self.pack))
        self.assertEqual(pack.size_bytes, self.pack.stat().st_size)
        self.assertEqual(pack.data_version, 1)
        self.assertEqual(pack.sort_order, 10)
        self.assertFalse(pack.supports_word_study)
        self.assertTrue(pack.is_enabled)
        self.assertTrue(pack.is_default)

    def test_a_mismatched_upload_is_never_registered(self):
        with self.assertRaisesMessage(CommandError, "Re-upload the file"):
            self._publish(self.pack, "--enable", served=self.pack.read_bytes()[:-10])
        self.assertFalse(BiblePack.objects.exists())

    def test_an_unreachable_upload_is_never_registered(self):
        with mock.patch(
            "apps.bible.services.pack_files.requests.get", side_effect=requests.ConnectionError("refused")
        ), self.assertRaisesMessage(CommandError, "Couldn't download"):
            call_command("publish_bible_pack", str(self.pack), "--url", PACK_URL, stdout=StringIO())
        self.assertFalse(BiblePack.objects.exists())

    def test_a_file_that_is_not_a_pack_is_refused(self):
        bogus = self.dir / "bogus.sqlite.gz"
        bogus.write_bytes(b"not a pack")
        with self.assertRaisesMessage(CommandError, "not a readable Bible pack"):
            self._publish(bogus)

    def test_republishing_the_same_file_keeps_its_data_version(self):
        self._publish(self.pack, "--enable")
        output = self._publish(self.pack)

        self.assertIn("Unchanged BSB", output)
        self.assertEqual(BiblePack.objects.get(code="bsb").data_version, 1)

    def test_publishing_a_rebuilt_file_bumps_the_data_version(self):
        self._publish(self.pack, "--enable")
        rebuilt = build_test_pack(self.dir / "v2", attribution="Corrected attribution")
        output = self._publish(rebuilt)

        pack = BiblePack.objects.get(code="bsb")
        self.assertIn("Updated BSB", output)
        self.assertEqual(pack.data_version, 2)
        self.assertEqual(pack.sha256, sha256_of_file(rebuilt))
        self.assertTrue(pack.is_enabled)  # publishing never switches a pack off

    def test_publishing_without_flags_leaves_a_new_pack_hidden(self):
        self._publish(self.pack)
        self.assertFalse(BiblePack.objects.get(code="bsb").is_enabled)

    def test_making_a_version_default_moves_the_default_off_the_old_one(self):
        BiblePack.objects.create(
            code="kjv", kind=BiblePackKind.VERSION, name="King James Version", abbreviation="KJV",
            attribution="Public domain", file_url="https://cdn.example.com/kjv.sqlite.gz",
            is_enabled=True, is_default=True,
        )
        self._publish(self.pack, "--default")

        self.assertTrue(BiblePack.objects.get(code="bsb").is_default)
        self.assertFalse(BiblePack.objects.get(code="kjv").is_default)


class BiblePackConstraintTests(TestCase):
    def _pack(self, code: str, **overrides) -> BiblePack:
        fields = dict(
            code=code, kind=BiblePackKind.VERSION, name=code.upper(), abbreviation=code.upper(),
            attribution="Public domain", file_url=f"https://cdn.example.com/{code}.sqlite.gz", is_enabled=True,
        )
        fields.update(overrides)
        return BiblePack.objects.create(**fields)

    def test_only_one_pack_can_be_the_default(self):
        self._pack("bsb", is_default=True)
        with transaction.atomic(), self.assertRaises(IntegrityError):
            self._pack("kjv", is_default=True)

    def test_a_disabled_pack_cannot_be_the_default(self):
        with transaction.atomic(), self.assertRaises(IntegrityError):
            self._pack("bsb", is_enabled=False, is_default=True)

    def test_the_study_pack_cannot_be_the_default(self):
        with transaction.atomic(), self.assertRaises(IntegrityError):
            self._pack("study", kind=BiblePackKind.STUDY, is_default=True)

    def test_a_downloadable_pack_needs_a_file_url(self):
        with transaction.atomic(), self.assertRaises(IntegrityError):
            self._pack("bsb", file_url="")
