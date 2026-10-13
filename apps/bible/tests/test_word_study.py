"""Phase 34 Slice 5: building word study (original text, word links,
lexicon, the study pack) from synthetic sources shaped like the real ones."""

from __future__ import annotations

import gzip
import shutil
import sqlite3
import tempfile
from pathlib import Path
from unittest import mock

import requests
from django.test import SimpleTestCase

from apps.bible.exceptions import BibleSourceFormatError
from apps.bible.services.lexicon import clean_definition, parse_lexicon, part_of_speech
from apps.bible.services.original_text import parse_bsb_tables, readable_parsing, strongs_key
from apps.bible.services.pack_builds import fetch_source, parse_verse_text, sha256_of_file, write_version_pack
from apps.bible.services.study_pack import write_study_pack
from apps.bible.services.usfm_text import strong_tags
from apps.bible.services.word_links import (
    LinkReport,
    link_bsb,
    link_tagged,
    renderings,
    require_coverage,
)
from apps.bible.sources import STUDY, VERSIONS, SourceDataset
from apps.bible.tests.helpers import JOHN_3_16, write_source
from apps.bible.tests.word_study_helpers import GREEK_LEXICON, HEBREW_LEXICON, write_lexicon, write_tables

GENESIS_1_1 = "In the beginning God created the heavens and the earth."
JOHN = (43, 3, 16)
GENESIS = (1, 1, 1)


class _TempDirTestCase(SimpleTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()


class OriginalTextTests(_TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.verses = parse_bsb_tables(write_tables(self.dir))

    def test_reads_each_verse_in_bsb_order_skipping_blank_padding_rows(self):
        self.assertEqual(sorted(self.verses), [GENESIS, JOHN])
        self.assertEqual([word.english for word in self.verses[JOHN]][:3], ["For", "-", "God"])

    def test_positions_follow_the_original_languages_word_order(self):
        positions = {word.word: word.position for word in self.verses[JOHN]}
        self.assertEqual(positions["Οὕτως"], 0)  # Greek opens "Οὕτως γὰρ ἠγάπησεν"
        self.assertEqual(positions["ἠγάπησεν"], 2)
        self.assertEqual(sorted(positions.values()), list(range(9)))

    def test_hebrew_cantillation_is_stripped_but_vowels_stay(self):
        first = self.verses[GENESIS][0]
        self.assertEqual(first.word, "בְּרֵאשִׁית")
        self.assertEqual(first.strongs, "H7225")

    def test_parsing_reads_in_plain_words(self):
        self.assertEqual(
            readable_parsing("Verb - Aorist Indicative Active - 3rd Person Singular"),
            "Verb · aorist indicative active · 3rd person singular",
        )
        self.assertEqual(
            readable_parsing("Verb - Qal - Perfect - third person masculine singular"),
            "Verb · Qal · perfect · third person masculine singular",
        )
        self.assertEqual(
            readable_parsing("Conjunctive waw | Noun - masculine plural"), "Conjunctive waw + Noun · masculine plural"
        )

    def test_strongs_numbers_use_the_lexicons_key_format(self):
        self.assertEqual(strongs_key("25", greek=True), "G0025")
        self.assertEqual(strongs_key("430", greek=False), "H0430")
        self.assertEqual(strongs_key("", greek=False), "")

    def test_a_file_that_is_not_the_tables_is_refused(self):
        other = self.dir / "other.tsv"
        other.write_text("a\tb\n1\t2\n", encoding="utf-8")
        with self.assertRaises(BibleSourceFormatError):
            parse_bsb_tables(other)


class BsbWordLinkTests(_TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.originals = parse_bsb_tables(write_tables(self.dir))
        self.texts = {JOHN: JOHN_3_16, GENESIS: GENESIS_1_1}
        self.report = link_bsb(self.texts, self.originals)

    def _spans(self, key):
        text = self.texts[key]
        return [(text[link.start : link.end], link.strongs, link.position) for link in self.report.links if link[:3] == key]

    def test_each_translated_phrase_links_its_words_to_the_original(self):
        spans = self._spans(JOHN)
        self.assertIn(("loved", "G0025", 2), spans)
        self.assertIn(("God", "G2316", 4), spans)
        self.assertEqual(self.report.placed, self.report.expected)

    def test_untranslated_words_get_no_link(self):
        # "ὁ" (the article before Θεὸς) is "-" in the tables.
        self.assertNotIn("G3588", [strongs for _, strongs, _ in self._spans(JOHN)])

    def test_a_vvv_word_shares_the_next_phrases_span(self):
        spans = self._spans(JOHN)
        self.assertIn(("shall not perish", "G3361", 5), spans)  # μὴ, "not"
        self.assertIn(("shall not perish", "G0622", 6), spans)

    def test_supplied_word_brackets_are_matched_without_the_brackets(self):
        self.assertIn(("the heavens", "H8064", 4), self._spans(GENESIS))

    def test_offsets_point_into_the_verse_text_exactly(self):
        john = [link for link in self.report.links if link[:3] == JOHN]
        self.assertEqual([JOHN_3_16[link.start : link.end] for link in john][-2:], ["eternal", "life"])

    def test_spacing_differences_around_punctuation_still_match(self):
        texts = {JOHN: "Nevertheless, the people refused."}
        originals = {JOHN: [self.originals[JOHN][0]._replace(english="Nevertheless , the people")]}
        report = link_bsb(texts, originals)
        self.assertEqual(report.placed, 1)
        self.assertEqual(texts[JOHN][report.links[0].start : report.links[0].end], "Nevertheless, the people")

    def test_too_little_coverage_fails_the_build_with_examples(self):
        report = LinkReport(links=[], placed=90, expected=100, problems=["(43, 3, 16): 'x' after 'y'"])
        with self.assertRaisesMessage(BibleSourceFormatError, "only 90/100 words linked"):
            require_coverage(report, minimum=0.999, label="BSB word links")

    def test_renderings_count_how_each_word_is_translated_case_insensitively(self):
        texts = {(1, 1, 1): "Love one another.", (1, 1, 2): "We love, for He loved us.", (1, 1, 3): "love"}
        links = [
            link._replace(book_id=1, chapter=1, verse=verse, start=start, end=end, strongs="G0025")
            for link, (verse, start, end) in zip(
                [self.report.links[0]] * 4, [(1, 0, 4), (2, 3, 7), (2, 16, 21), (3, 0, 4)]
            )
        ]
        self.assertEqual(renderings(texts, links), [("G0025", "love", 3), ("G0025", "loved", 1)])


class TaggedWordLinkTests(_TempDirTestCase):
    KJV_JOHN = "For God so loved the world, that he gave his only begotten Son."

    def test_tagged_words_are_found_in_order_and_matched_to_the_original_word(self):
        originals = parse_bsb_tables(write_tables(self.dir))
        tags = {JOHN: [("For", "G1063"), ("God", "G2316"), ("so", "G3779"), ("loved", "G0025"), ("Son", "G5207")]}
        report = link_tagged({JOHN: self.KJV_JOHN}, tags, originals)

        spans = [(self.KJV_JOHN[link.start : link.end], link.strongs, link.position) for link in report.links]
        self.assertEqual(spans[:4], [("For", "G1063", 1), ("God", "G2316", 4), ("so", "G3779", 0), ("loved", "G0025", 2)])
        # Υἱὸν isn't among the test tables' words: linked by number only.
        self.assertEqual(spans[4], ("Son", "G5207", None))
        self.assertEqual((report.placed, report.expected), (4, 5))

    def test_usfm_tags_are_read_with_their_strongs_numbers(self):
        raw = (
            r'\wj \+w For|strong="G1063"\+w* \+w God|strong="G2316"\+w* \+w the world|strong="G2889"\+w*,'
            r'\f + \fr 3:16 \ft note \w word|strong="G9999"\w*\f* \w Son|strong="H5207a"\w*\wj*'
        )
        self.assertEqual(
            strong_tags(raw), [("For", "G1063"), ("God", "G2316"), ("the world", "G2889"), ("Son", "H5207")]
        )


class LexiconTests(_TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.entries = {
            **parse_lexicon(write_lexicon(self.dir, "tbesh.txt", HEBREW_LEXICON)),
            **parse_lexicon(write_lexicon(self.dir, "tbesg.txt", GREEK_LEXICON)),
        }

    def test_one_entry_per_plain_strongs_number(self):
        self.assertEqual(sorted(self.entries), ["G0025", "G2316", "H0430", "H1121", "H3068"])

    def test_a_split_number_uses_its_a_entry_and_the_main_meaning(self):
        entry = self.entries["H1121"]
        self.assertEqual((entry.lemma, entry.gloss), ("בֵּן", "son: child"))
        self.assertEqual(entry.definition, "child/son")

    def test_with_only_sub_meanings_the_first_is_used(self):
        self.assertEqual(self.entries["H0430"].gloss, "God")

    def test_definitions_are_plain_text(self):
        # The headword repeated with its endings ("ἀγαπάω, -ῶ,") is dropped.
        self.assertEqual(self.entries["G0025"].definition, "to love, Mat.5:43; 1. of God & men")
        self.assertEqual(clean_definition("a<br>b <i>c</i>"), "a\nb c")

    def test_headword_forms_and_septuagint_notes_are_dropped_from_the_start(self):
        lines = [["G0622", "G0622 =", "G0622", "ἀπολλύω", "apolluō", "G:V", "to destroy",
                  "ἀπ-όλλυμι and ἀπολλύω<BR>[in LXX for אָבַד, etc.]<BR>to destroy utterly"]]
        entry = parse_lexicon(write_lexicon(self.dir, "g.txt", lines))["G0622"]
        self.assertEqual(entry.definition, "to destroy utterly")

    def test_parts_of_speech_read_in_plain_words(self):
        self.assertEqual(part_of_speech("G:V"), "verb")
        self.assertEqual(part_of_speech("H:N-M"), "noun · masculine")
        self.assertEqual(part_of_speech("N:N--T"), "proper name")
        self.assertEqual(part_of_speech("X:Unknown"), "")


class StudyPackTests(_TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.originals = parse_bsb_tables(write_tables(self.dir))
        lexicon = {
            **parse_lexicon(write_lexicon(self.dir, "tbesh.txt", HEBREW_LEXICON)),
            **parse_lexicon(write_lexicon(self.dir, "tbesg.txt", GREEK_LEXICON)),
        }
        # Every number in the test tables gets an entry, as in the real data.
        for verse_words in self.originals.values():
            for word in verse_words:
                if word.strongs and word.strongs not in lexicon:
                    lexicon[word.strongs] = lexicon["G0025"]._replace(strongs=word.strongs)
        self.lexicon = lexicon

    def _build(self, out: str, lexicon=None) -> Path:
        path, _ = write_study_pack(
            definition=STUDY,
            originals=self.originals,
            lexicon=self.lexicon if lexicon is None else lexicon,
            source_sha256s={"bsb_tables": "0" * 64},
            out_dir=self.dir / out,
        )
        return path

    def _open(self, pack: Path) -> sqlite3.Connection:
        database = pack.with_suffix("")
        with gzip.open(pack, "rb") as source, database.open("wb") as target:
            shutil.copyfileobj(source, target)
        connection = sqlite3.connect(database)
        self.addCleanup(connection.close)
        return connection

    def test_holds_original_words_parsing_lexicon_and_counts(self):
        db = self._open(self._build("a"))
        meta = dict(db.execute("SELECT key, value FROM meta"))
        self.assertEqual((meta["kind"], meta["code"], meta["format_version"]), ("study", "study", "1"))
        row = db.execute(
            "SELECT word, translit, w.strongs, description FROM original_words w "
            "JOIN morphology m ON m.id = w.morphology_id WHERE book_id = 43 AND chapter = 3 AND verse = 16 "
            "AND position = 2"
        ).fetchone()
        self.assertEqual(row, ("ἠγάπησεν", "ēgapēsen", "G0025", "Verb · aorist indicative active · 3rd person singular"))
        self.assertEqual(db.execute("SELECT lemma, gloss FROM lexicon WHERE strongs = 'G0025'").fetchone(), ("ἀγαπάω", "to love"))
        self.assertEqual(db.execute("SELECT total FROM strongs_counts WHERE strongs = 'G2316'").fetchone(), (1,))

    def test_the_concordance_finds_every_verse_with_a_word(self):
        db = self._open(self._build("a"))
        rows = db.execute(
            "SELECT book_id, chapter, verse FROM original_words WHERE strongs = 'H0430' ORDER BY book_id, chapter, verse"
        ).fetchall()
        self.assertEqual(rows, [GENESIS])

    def test_builds_are_reproducible(self):
        self.assertEqual(sha256_of_file(self._build("a")), sha256_of_file(self._build("b")))

    def test_a_lexicon_missing_many_entries_fails_the_build(self):
        with self.assertRaisesMessage(BibleSourceFormatError, "have no lexicon entry"):
            with mock.patch("apps.bible.services.study_pack.MAX_MISSING_LEXICON_ENTRIES", 0):
                self._build("c", lexicon={})


class VersionPackWordLinkTests(_TempDirTestCase):
    def test_a_version_pack_with_links_stores_them_by_verse_and_says_so(self):
        parsed = parse_verse_text(write_source(self.dir))
        texts = {(verse.book_id, verse.chapter, verse.verse): verse.text for verse in parsed.verses}
        report = link_bsb(texts, parse_bsb_tables(write_tables(self.dir)))
        pack = write_version_pack(
            definition=VERSIONS["bsb"],
            parsed=parsed,
            source_sha256="0" * 64,
            out_dir=self.dir / "out",
            word_links=report.links,
            renderings=renderings(texts, report.links),
        )
        database = self.dir / "pack.sqlite"
        with gzip.open(pack, "rb") as source, database.open("wb") as target:
            shutil.copyfileobj(source, target)
        db = sqlite3.connect(database)
        self.addCleanup(db.close)

        self.assertEqual(dict(db.execute("SELECT key, value FROM meta"))["has_word_links"], "1")
        rows = db.execute(
            "SELECT seq, start_offset, end_offset, strongs, position FROM word_links "
            "WHERE book_id = 43 AND chapter = 3 AND verse = 16 ORDER BY seq"
        ).fetchall()
        self.assertEqual(rows[0], (0, 0, 3, "G1063", 1))  # "For"
        self.assertEqual([row[0] for row in rows], list(range(len(rows))))
        self.assertEqual(
            db.execute("SELECT rendering, count FROM renderings WHERE strongs = 'G0025'").fetchall(), [("loved", 1)]
        )


class ResumingDownloadTests(_TempDirTestCase):
    @mock.patch("apps.bible.services.pack_builds.requests.get")
    def test_a_dropped_connection_resumes_where_it_stopped(self, get):
        body = b"0123456789" * 10
        reference = self.dir / "reference.txt"
        reference.write_bytes(body)

        def dropped(*args, **kwargs):
            response = mock.MagicMock(status_code=200)
            response.__enter__.return_value = response

            def chunks(chunk_size):
                yield body[:40]
                raise requests.exceptions.ChunkedEncodingError("Connection reset by peer")

            response.iter_content.side_effect = chunks
            return response

        def rest(*args, **kwargs):
            self.assertEqual(kwargs["headers"], {"Range": "bytes=40-"})
            response = mock.MagicMock(status_code=206)
            response.__enter__.return_value = response
            response.iter_content.return_value = [body[40:]]
            return response

        calls = iter([dropped, rest])
        get.side_effect = lambda *args, **kwargs: next(calls)(*args, **kwargs)

        dataset = SourceDataset("tables", "https://example.com/tables.tsv", sha256_of_file(reference), "test")
        self.assertEqual(fetch_source(dataset, self.dir / "cache").read_bytes(), body)
