from __future__ import annotations

import gzip
import shutil
import sqlite3
import tempfile
import zipfile
from pathlib import Path

from django.test import SimpleTestCase

from apps.bible.canon import USFM_CODES
from apps.bible.exceptions import BibleSourceFormatError
from apps.bible.services.pack_builds import write_version_pack
from apps.bible.services.usfm_text import clean_usfm_text, parse_usfm_zip
from apps.bible.sources import VERSIONS

# Real eBible eng-kjv2006 markup, trimmed: Psalm 23 opens with a title, Psalm
# 119 with a Hebrew-letter heading; John 3:16 is fully Strong's-tagged.
PSALMS = r"""\id PSA - King James Version
\h Psalms
\mt1 The Psalms
\c 23
\d A \w Psalm|strong="H4210"\w* of \w David|strong="H1732"\w*.
\q1
\v 1 The \nd \+w LORD|strong="H3068"\+w*\nd* \add is\add* my \w shepherd|strong="H7462"\w*; I shall not \w want|strong="H2637"\w*.
\q1
\v 2 He \w maketh|strong="H7257"\w* me to lie down
\q2 in \w green|strong="H1877"\w* \w pastures|strong="H4999"\w*.\f + \fr 23.2 \ft green…: Heb. pastures of tender grass\f*
\c 119
\s1 \tl א ALEPH.\tl*
\q1
\v 1 \w Blessed|strong="H0835"\w* \add are\add* the \w undefiled|strong="H8549"\w* in the \w way|strong="H1870"\w* .
\v 2
"""

ROMANS = r"""\id ROM
\c 16
\v 27 To God only wise, \add be\add* glory through Jesus Christ for ever. Amen.
\s1 Written to the Romans from Corinthus, \add and sent\add* by Phebe.
"""

JOHN = r"""\id JHN
\c 3
\p
\v 16 \wj ¶ \+w For|strong="G1063"\+w* \+w God|strong="G2316"\+w* \+w so|strong="G3779"\+w* \+w loved|strong="G0025"\+w* \+w the world|strong="G2889"\+w*, \+w that|strong="G5620"\+w* \+w he gave|strong="G1325"\+w* \+w his|strong="G0846"\+w* \+w only begotten|strong="G3439"\+w* \+w Son|strong="G5207"\+w*.\wj*
"""


def _write_zip(directory: Path, *, skip: str | None = None, extra: dict[str, str] | None = None) -> Path:
    path = directory / "kjv_usfm.zip"
    with zipfile.ZipFile(path, "w") as archive:
        for index, code in enumerate(USFM_CODES, start=2):
            if code == skip:
                continue
            body = {"PSA": PSALMS, "JHN": JOHN, "ROM": ROMANS}.get(code, f"\\id {code}\n\\c 1\n\\p\n\\v 1 Text of {code}.\n")
            archive.writestr(f"{index:02d}-{code}eng-kjv2006.usfm", body)
        for name, body in (extra or {}).items():
            archive.writestr(name, body)
        archive.writestr("copr.htm", "<p>Public Domain</p>")  # not a book: ignored
    return path


class CleanUsfmTextTests(SimpleTestCase):
    def test_keeps_the_words_and_drops_tagging_notes_and_markers(self):
        raw = r'\wj ¶ \+w For|strong="G1063"\+w* \+w God|strong="G2316"\+w*, he \add is\add* \nd LORD\nd*.\f + \fr 1.1 \ft note\f*\wj*'
        self.assertEqual(clean_usfm_text(raw), "For God, he is LORD.")

    def test_tidies_a_space_left_before_punctuation(self):
        self.assertEqual(clean_usfm_text(r'\w way|strong="H1870"\w* .'), "way.")


class ParseUsfmZipTests(SimpleTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _verse(self, parsed, book_id, chapter, verse):
        return next(v.text for v in parsed.verses if (v.book_id, v.chapter, v.verse) == (book_id, chapter, verse))

    def test_reads_every_book_with_clean_verse_text(self):
        parsed = parse_usfm_zip(_write_zip(self.dir))

        self.assertEqual({v.book_id for v in parsed.verses}, set(range(1, 67)))
        self.assertEqual(
            self._verse(parsed, 43, 3, 16),
            "For God so loved the world, that he gave his only begotten Son.",
        )
        self.assertEqual(self._verse(parsed, 19, 23, 1), "The LORD is my shepherd; I shall not want.")

    def test_a_poetry_line_continues_its_verse_and_footnotes_are_dropped(self):
        parsed = parse_usfm_zip(_write_zip(self.dir))
        self.assertEqual(self._verse(parsed, 19, 23, 2), "He maketh me to lie down in green pastures.")

    def test_psalm_titles_and_section_headings_sit_above_the_verse_not_in_it(self):
        parsed = parse_usfm_zip(_write_zip(self.dir))

        self.assertEqual(
            [(h.book_id, h.chapter, h.before_verse, h.text) for h in parsed.headings if h.book_id == 19],
            [(19, 23, 1, "A Psalm of David."), (19, 119, 1, "א ALEPH.")],
        )
        self.assertNotIn("Psalm of David", self._verse(parsed, 19, 23, 1))

    def test_a_closing_subscription_is_kept_after_the_last_verse(self):
        parsed = parse_usfm_zip(_write_zip(self.dir))
        romans = [(h.chapter, h.before_verse, h.text) for h in parsed.headings if h.book_id == 45]
        self.assertEqual(romans, [(16, 28, "Written to the Romans from Corinthus, and sent by Phebe.")])

    def test_an_empty_verse_is_reported_as_omitted(self):
        parsed = parse_usfm_zip(_write_zip(self.dir))
        self.assertEqual(parsed.omitted, ["Psalms 119:2"])

    def test_a_missing_book_is_refused(self):
        with self.assertRaisesMessage(BibleSourceFormatError, "Missing books: Jude"):
            parse_usfm_zip(_write_zip(self.dir, skip="JUD"))

    def test_an_unknown_book_code_is_refused(self):
        with self.assertRaisesMessage(BibleSourceFormatError, "unknown USFM book code 'XYZ'"):
            parse_usfm_zip(_write_zip(self.dir, extra={"99-XYZ.usfm": "\\id XYZ\n\\c 1\n\\v 1 Text.\n"}))

    def test_a_duplicate_verse_is_refused(self):
        with self.assertRaisesMessage(BibleSourceFormatError, "Duplicate verse Genesis 1:1"):
            parse_usfm_zip(_write_zip(self.dir, extra={"99-GEN2.usfm": "\\id GEN\n\\c 1\n\\v 1 Again.\n"}))

    def test_not_a_zip_is_refused(self):
        bogus = self.dir / "bogus.zip"
        bogus.write_text("nope")
        with self.assertRaisesMessage(BibleSourceFormatError, "not a valid zip"):
            parse_usfm_zip(bogus)

    def test_headings_are_written_into_the_pack_in_order(self):
        parsed = parse_usfm_zip(_write_zip(self.dir))
        pack = write_version_pack(
            definition=VERSIONS["kjv"], parsed=parsed, source_sha256="0" * 64, out_dir=self.dir / "out"
        )
        database = self.dir / "kjv.sqlite"
        with gzip.open(pack, "rb") as source, database.open("wb") as target:
            shutil.copyfileobj(source, target)
        connection = sqlite3.connect(database)
        try:
            rows = connection.execute(
                "SELECT chapter, before_verse, position, text FROM headings WHERE book_id = 19 ORDER BY chapter"
            ).fetchall()
            meta = dict(connection.execute("SELECT key, value FROM meta"))
        finally:
            connection.close()

        self.assertEqual(rows, [(23, 1, 0, "A Psalm of David."), (119, 1, 0, "א ALEPH.")])
        self.assertEqual(meta["code"], "kjv")
        self.assertEqual(meta["abbreviation"], "KJV")
        self.assertIn("CrossWire", meta["attribution"])
