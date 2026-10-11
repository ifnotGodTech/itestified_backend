import gzip
import shutil
import sqlite3
import tempfile
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase

from apps.bible.exceptions import BibleSourceChecksumError, BibleSourceFormatError
from apps.bible.services.pack_builds import fetch_source, parse_verse_text, sha256_of_file
from apps.bible.sources import SourceDataset

from .helpers import JOHN_3_16, build_test_pack, write_source


class ParseVerseTextTests(SimpleTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_parses_every_book_in_canonical_order_skipping_header_lines(self):
        verses = parse_verse_text(write_source(self.dir)).verses

        self.assertEqual(len(verses), 66)
        self.assertEqual([verse.book_id for verse in verses], list(range(1, 67)))
        john = next(verse for verse in verses if verse.book_id == 43)
        self.assertEqual((john.chapter, john.verse, john.text), (3, 16, JOHN_3_16))

    def test_maps_the_sources_psalm_spelling_to_psalms(self):
        verses = parse_verse_text(write_source(self.dir)).verses
        self.assertTrue(any(verse.book_id == 19 for verse in verses))

    def test_missing_book_is_refused(self):
        with self.assertRaisesMessage(BibleSourceFormatError, "Missing books: Jude"):
            parse_verse_text(write_source(self.dir, skip_book="Jude"))

    def test_unknown_book_is_refused(self):
        with self.assertRaisesMessage(BibleSourceFormatError, "Unknown book name 'Hezekiah'"):
            parse_verse_text(write_source(self.dir, extra_lines=["Hezekiah 1:1\tNot a book."]))

    def test_duplicate_verse_is_refused(self):
        with self.assertRaisesMessage(BibleSourceFormatError, "Duplicate verse John 3:16"):
            parse_verse_text(write_source(self.dir, extra_lines=["John 3:16\tAgain."]))

    def test_a_verse_left_empty_by_the_translation_is_skipped_and_reported(self):
        # The BSB lists e.g. Matthew 17:21 with no text: a deliberate omission.
        parsed = parse_verse_text(write_source(self.dir, extra_lines=["Matthew 17:21\t "]))

        self.assertEqual(parsed.omitted, ["Matthew 17:21"])
        self.assertFalse(any(verse.book_id == 40 and verse.chapter == 17 for verse in parsed.verses))

    def test_more_omissions_than_any_translation_makes_is_refused(self):
        empties = [f"John 4:{verse}\t" for verse in range(1, 50)]
        with self.assertRaisesMessage(BibleSourceFormatError, "the source looks broken"):
            parse_verse_text(write_source(self.dir, extra_lines=empties))


class WriteVersionPackTests(SimpleTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _open(self, pack_path: Path) -> sqlite3.Connection:
        database = self.dir / "unpacked.sqlite"
        with gzip.open(pack_path, "rb") as source, database.open("wb") as target:
            shutil.copyfileobj(source, target)
        return sqlite3.connect(database)

    def test_pack_holds_books_verses_and_metadata(self):
        connection = self._open(build_test_pack(self.dir / "out"))
        try:
            meta = dict(connection.execute("SELECT key, value FROM meta"))
            book = connection.execute("SELECT osis, name, testament, chapter_count FROM books WHERE id = 43").fetchone()
            verse = connection.execute(
                "SELECT text FROM verses WHERE book_id = 43 AND chapter = 3 AND verse = 16"
            ).fetchone()
            book_count = connection.execute("SELECT COUNT(*) FROM books").fetchone()[0]
        finally:
            connection.close()

        self.assertEqual(meta["code"], "bsb")
        self.assertEqual(meta["kind"], "version")
        self.assertEqual(meta["format_version"], "1")
        self.assertEqual(meta["has_word_links"], "0")
        self.assertEqual(meta["verse_count"], "66")
        self.assertEqual(book, ("John", "John", "NT", 3))
        self.assertEqual(verse, (JOHN_3_16,))
        self.assertEqual(book_count, 66)

    def test_builds_are_byte_for_byte_reproducible(self):
        first = build_test_pack(self.dir / "first")
        second = build_test_pack(self.dir / "second")
        self.assertEqual(sha256_of_file(first), sha256_of_file(second))

    def test_a_content_change_changes_the_checksum(self):
        first = build_test_pack(self.dir / "first")
        changed = build_test_pack(self.dir / "changed", attribution="Different attribution")
        self.assertNotEqual(sha256_of_file(first), sha256_of_file(changed))


class FetchSourceTests(SimpleTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _response(self, body: bytes):
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.iter_content.return_value = [body]
        return response

    @mock.patch("apps.bible.services.pack_builds.requests.get")
    def test_downloads_and_caches_a_file_matching_its_pin(self, get):
        body = b"Genesis 1:1\tIn the beginning.\n"
        get.return_value = self._response(body)
        reference = self.dir / "reference.txt"
        reference.write_bytes(body)
        dataset = SourceDataset("demo", "https://example.com/demo.txt", sha256_of_file(reference), "test")

        path = fetch_source(dataset, self.dir / "cache")
        self.assertEqual(path.read_bytes(), body)

        fetch_source(dataset, self.dir / "cache")
        get.assert_called_once()  # second call reused the verified cached copy

    @mock.patch("apps.bible.services.pack_builds.requests.get")
    def test_a_changed_upstream_file_is_refused_and_not_cached(self, get):
        get.return_value = self._response(b"tampered")
        dataset = SourceDataset("demo", "https://example.com/demo.txt", "a" * 64, "test")

        with self.assertRaises(BibleSourceChecksumError):
            fetch_source(dataset, self.dir / "cache")
        self.assertEqual(list((self.dir / "cache").iterdir()), [])
